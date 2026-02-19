"""
Dynamic navigation explorer.

Explores menu by clicking buttons, captures state at each step.
Stores all states for later LLM processing.
"""

import asyncio
import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent / 'config' / '.env')

from playwright.async_api import async_playwright, Page

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scraper.navigation.llm_popup_dismiss import dismiss_popups_with_llm
from scraper.navigation.output.tree import NavTree, build_tree_from_results
from scraper.llm_handler import LLMHandler, LLMUsageTracker
from utils.page_wait import wait_for_page_ready


# =============================================================================
# Menu Context: Tracks menu state for interactions
# =============================================================================

@dataclass
class MenuContext:
    """
    Holds menu state to verify menu stays open after interactions.

    Only created when a menu was successfully opened. Pass to click/hover
    functions to automatically check and restore menu state after interaction.
    """
    before_aria: str          # ARIA snapshot before menu was opened
    base_url: str             # URL to return to if we navigate away
    menu_start_line: str      # First new line when menu opened (for quick check)
    boundary_marker: str = None  # First landmark after menu (e.g., "- banner:") to truncate ARIA

    @classmethod
    def from_menu_result(cls, result: dict, base_url: str) -> Optional['MenuContext']:
        """Create MenuContext from open_menu_and_capture() result."""
        if not result.get('opened'):
            return None

        menu_start = result.get('menu_start')
        menu_start_line = menu_start[1] if menu_start else None
        boundary_marker = result.get('boundary_marker')

        return cls(
            before_aria=result['before_aria'],
            base_url=base_url,
            menu_start_line=menu_start_line,
            boundary_marker=boundary_marker
        )


# Module-level LLM usage tracking (reset at start of explore())
_llm_usage = {"input_tokens": 0, "output_tokens": 0}

# Shared LLMHandler instance for this module
_llm_handler = None

# Cached menu button info - avoids re-detecting on every reset
# Format: {'selector': str, 'method': 'click'|'hover'}
_cached_menu_button = None

# Hover behavior tracking for current site
# If hover repeatedly fails to reveal content, stop trying and only click
_hover_stats = {"attempts": 0, "successes": 0}
_hover_disabled = False  # Set True after too many failures
_HOVER_DISABLE_THRESHOLD = 3  # Disable after N failed attempts with 0 successes

# Popup dismissal tracking - only dismiss once at start and once after menu opens
_popups_dismissed = False  # Set True after initial dismissal, reset per-site


def _reset_site_state():
    """Reset all per-site tracking for new site."""
    global _hover_stats, _hover_disabled, _popups_dismissed
    _hover_stats = {"attempts": 0, "successes": 0}
    _hover_disabled = False
    _popups_dismissed = False


def _reset_hover_stats():
    """Reset hover tracking for new site (alias for backwards compat)."""
    _reset_site_state()


def _track_hover(success: bool):
    """Track hover attempt result."""
    global _hover_stats, _hover_disabled
    _hover_stats["attempts"] += 1
    if success:
        _hover_stats["successes"] += 1
    else:
        # Check if we should disable hover
        if (_hover_stats["attempts"] >= _HOVER_DISABLE_THRESHOLD and
            _hover_stats["successes"] == 0):
            _hover_disabled = True
            print(f"    [HOVER] Disabled for this site ({_hover_stats['attempts']} failures, 0 successes)")


def _should_try_hover() -> bool:
    """Check if we should attempt hover."""
    return not _hover_disabled

def _get_llm_handler():
    """Get or create the module-level LLMHandler."""
    global _llm_handler
    if _llm_handler is None:
        _llm_handler = LLMHandler()
    return _llm_handler

def _track_llm_result(result: dict):
    """Track LLM usage from a call result."""
    global _llm_usage
    if result.get("usage"):
        _llm_usage["input_tokens"] += result["usage"].get("input_tokens", 0)
        _llm_usage["output_tokens"] += result["usage"].get("output_tokens", 0)

def _cache_menu_button(selector: str, method: str = 'click', controls_id: str = None):
    """Cache the menu button selector and what it controls for fast reopening."""
    global _cached_menu_button
    _cached_menu_button = {'selector': selector, 'method': method, 'controls': controls_id}
    print(f"    [NAV] Cached menu button: {selector} ({method})")
    if controls_id:
        print(f"    [NAV] Controls: #{controls_id}")

def _clear_menu_cache():
    """Clear the menu button cache."""
    global _cached_menu_button
    _cached_menu_button = None


# =============================================================================
# ARIA Boundary Detection: Identify where menu ends in page ARIA
# =============================================================================

# ARIA landmarks that indicate we've left the menu area
ARIA_LANDMARKS = ['banner:', 'main:', 'contentinfo:', 'footer:', 'region:', 'complementary:']


def find_menu_boundary(aria: str, menu_start_line: str = None) -> str | None:
    """
    Find the first ARIA landmark at root level that indicates main content.

    This boundary marker is used to truncate ARIA snapshots so we only
    process menu content, not footer/main page elements.

    Args:
        aria: Full ARIA snapshot after menu opened
        menu_start_line: First line of menu content (optional, for context)

    Returns:
        The boundary line (e.g., "- main:") or None if not found
    """
    lines = aria.split('\n')

    # Priority landmarks that clearly indicate end of menu
    priority_landmarks = ['main:', 'contentinfo:', 'footer:']

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Root level elements have indent 0-2 spaces
        if indent <= 2 and stripped.startswith('- '):
            # Check priority landmarks first (main content area)
            for landmark in priority_landmarks:
                if landmark in stripped.lower():
                    print(f"    [BOUNDARY] Found menu boundary: {stripped[:50]}")
                    return stripped

    # Fallback: look for any landmark after navigation section
    found_navigation = False
    for line in lines:
        if '- navigation:' in line and not found_navigation:
            found_navigation = True
            continue

        if found_navigation:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            if indent <= 2 and stripped.startswith('- '):
                for landmark in ARIA_LANDMARKS:
                    if landmark in stripped.lower():
                        print(f"    [BOUNDARY] Found menu boundary (fallback): {stripped[:50]}")
                        return stripped

    return None


def truncate_aria_at_boundary(aria: str, boundary_marker: str) -> str:
    """
    Truncate ARIA snapshot at the boundary marker.

    This removes all content after the menu section (footer, main content, etc.)
    so that find_expandable_elements only finds menu buttons.

    Args:
        aria: Full ARIA snapshot
        boundary_marker: Line that marks end of menu (e.g., "- banner:")

    Returns:
        Truncated ARIA containing only menu content
    """
    if not boundary_marker:
        return aria

    lines = aria.split('\n')
    truncated_lines = []

    # Normalize the boundary marker for comparison
    boundary_normalized = boundary_marker.strip().lower()

    for line in lines:
        # Check if this line matches the boundary
        if line.strip().lower() == boundary_normalized:
            break
        # Also check for partial match (in case of slight variations)
        if boundary_normalized in line.lower() and line.lstrip().startswith('- '):
            indent = len(line) - len(line.lstrip())
            if indent <= 2:  # Root level
                break
        truncated_lines.append(line)

    return '\n'.join(truncated_lines)


async def reopen_menu_fast(page: Page) -> bool:
    """
    Reopen menu using cached button info (no LLM detection).
    Returns True if successful, False if cache miss or failure.
    """
    global _cached_menu_button
    if not _cached_menu_button:
        return False

    selector = _cached_menu_button['selector']
    method = _cached_menu_button['method']

    try:
        el = page.locator(selector).first
        if not await el.is_visible():
            print(f"    [NAV] Cached menu button not visible: {selector}")
            return False

        if method == 'hover':
            await el.hover()
        else:
            await el.click()

        await page.wait_for_timeout(400)
        print(f"    [NAV] Reopened menu via cache: {selector}")
        return True
    except Exception as e:
        print(f"    [NAV] Cache reopen failed: {e}")
        _clear_menu_cache()
        return False


# =============================================================================
# LLM: Find top-level nav items
# =============================================================================

def prompt_top_level(header_aria: str, body_aria: str = None) -> str:
    # Use header ARIA (focused, no popup/cookie/country junk) as primary source.
    # Fall back to body ARIA only if header ARIA is empty.
    aria = header_aria.strip() if header_aria and header_aria.strip() else (body_aria or "")[:15000]
    return f"""Look at this ARIA snapshot of a fashion website's navigation.

List ALL top-level navigation categories (the main menu items).

ARIA:
{aria[:15000]}

RESPOND EXACTLY LIKE THIS:

ITEMS:
- BUTTON: Category Name
- TAB: Category Name
- GROUP: Category Name
- LINK: Category Name | /url/path

RULES:
- BUTTON = expandable button (will reveal subcategories)
- TAB = tab element (switches content panel)
- GROUP = group element (often hoverable nav items)
- LINK = direct page (has URL)
- Include product categories (Women, Men, Kids, Shoes, Bags, Shop, etc.)
- Include hamburger/toggle menu buttons (Menu, MENU, Navigation, ☰) - these reveal the nav
- IGNORE: Search, Cart, Login, Account, Language, Country
- IGNORE: About, Contact, FAQ, Careers, Legal, Newsletter
- IGNORE: Support, Help, Customer Service, Returns, Shipping - these are NOT product navigation
- IGNORE: Archive, Blog, News, Journal, Stories - these are content, not shopping navigation
"""


def prompt_menu_structure(aria: str) -> str:
    """Prompt to analyze menu structure after opening a toggle/hamburger menu."""
    return f"""Look at this ARIA snapshot of an OPEN navigation menu.

Identify the menu structure - what are the TOP-LEVEL categories vs SUBCATEGORIES.

ARIA:
{aria[:8000]}

RESPOND EXACTLY LIKE THIS:

TOP_LEVEL:
- TAB: Women
- TAB: Men

SUBCATEGORIES:
- TAB: Handbags
- TAB: Shoes
- TAB: Ready-to-Wear

LINKS:
- LINK: New in | /url/path
- LINK: Sale | /url/path

RULES:
- TOP_LEVEL = main category selectors (Women, Men, Kids, etc.) - usually in a "Categories" tablist
- SUBCATEGORIES = product type selectors that SWITCH content (Handbags, Shoes, Clothing, etc.) - tabs that don't navigate
- LINKS = items that have a /url: and will NAVIGATE to a new page - DO NOT put these in SUBCATEGORIES
- IMPORTANT: If an item has "/url:" in the ARIA, it's a LINK not a TAB - put it in LINKS section
- Use TAB if ARIA shows "tab" without URL, BUTTON if "button" without URL
- IGNORE: Search, Cart, Login, Account, Country selectors, Close buttons
- IGNORE: Social links, FAQ, About, Legal, Newsletter
"""


def prompt_subcategories(aria: str, current_path: list, extracted_links: dict = None) -> str:
    """Prompt to identify subcategories at the current navigation path."""
    path_str = " > ".join(current_path)

    # Format extracted links for the prompt
    links_section = ""
    if extracted_links:
        links_list = [f"  - {name} → {url}" for name, url in list(extracted_links.items())[:30]]
        links_section = f"""
EXTRACTED LINKS ON THIS PAGE:
{chr(10).join(links_list)}
"""

    return f"""PURPOSE: We're building a navigation tree for a fashion site. We need to find all category paths.

CURRENT PATH: {path_str}
{links_section}
TASK: First determine if this is a PRODUCT LISTING page or a NAVIGATION page.

HOW TO IDENTIFY A PRODUCT LISTING PAGE (LEAF):
Look at the EXTRACTED LINKS above. If you see ANY of these patterns, it's a LEAF page:

1. Filter/sort controls: "Filter", "Filter and sort", "Filters", "Refine", "Sort", "Sort by", "Clear"

2. Individual PRODUCT links - these have specific patterns:
   - Long descriptive names with color/size: "Tokyo Dad Jeans | Baggy, Wide-Leg Metal Black"
   - Names with color in parentheses: "STITCH WINGS ZIP HOODIE BLACK (DETACHABLE WINGS)"
   - Names with material/variant: "Oversized Cotton Hoodie - Washed Black"
   - Multiple similar items (same product, different colors): seeing 3+ links that are variants of same item
   - Product names are usually 4+ words describing a specific item

3. Category links look DIFFERENT - they are short, generic names:
   - "Hoodies", "Tops", "Jackets", "Shoes", "Bags" (1-2 words)
   - "New Arrivals", "Best Sellers", "Sale" (collection names)

CRITICAL RULE: If EXTRACTED LINKS contains MOSTLY long product names (4+ words with colors/sizes/variants), this is a LEAF page. Don't be fooled by a few category buttons in the header - look at the LINKS.

RESPOND WITH THIS FORMAT:

First line MUST be one of:
PAGE_TYPE: LEAF
PAGE_TYPE: HAS_CATEGORIES

If PAGE_TYPE: LEAF, stop there. Don't list any items.

If PAGE_TYPE: HAS_CATEGORIES, find EXPANDABLE elements and LINKS to category pages:

CLASSIFICATION - Based on ARIA ROLE, not the name:
- EXPANDABLE: role=button, role=tab, role=menuitem → we click these to explore
- LINK: role=link → we record the URL but don't click

IMPORTANT - INDENTATION SHOWS HIERARCHY:
- In ARIA, indentation indicates parent/child nesting.
- Only list items that are CHILDREN of the current path.
- If current path is "Men", only list items INDENTED UNDER Men's expanded region.
- Do NOT list sibling items at the same level (e.g., "Women" is a sibling of "Men", not a child).
- Example: If you see:
    - button "Men" [expanded]:
      - button "Shoes"      ← CHILD of Men (indented under)
      - button "Clothing"   ← CHILD of Men (indented under)
    - button "Women":       ← SIBLING of Men (same level, not indented under)
  Then Shoes and Clothing are children of Men, but Women is NOT.

IMPORTANT:
- Look at the actual ARIA role, not what the name suggests.
- "Ready-to-wear" with role=menuitem is EXPANDABLE, not a LINK.
- Include ALL buttons, tabs, and menuitems that are CHILDREN of current path.
- Menus often have one item already selected (usually the first) - include it too.

EXPANDABLE:
- BUTTON: ExactName
- TAB: ExactName
- MENUITEM: ExactName

LINKS:
- LINK: ExactName

EXCLUDE from both sections:
- Individual product links (specific items like "Blue Cotton Dress $89", "Nike Air Max")
- Utility links (Cart, Login, Search, About Us, Contact, FAQ)
- Filter/facet options (color names, size names, price ranges)
- Sort options
- Pagination controls

CONSTRAINTS:
- Classify by ARIA role, not by name
- Only include CHILDREN of the current path, not siblings or parent items
- Ignore utility controls: Back, Close, Search, Cart, Menu, Login, Account
- Use exact names from the ARIA
- If you see filters/sort controls, respond with PAGE_TYPE: LEAF

ARIA SNAPSHOT:
{aria[:6000]}
"""


def prompt_identify_menu_button(menu_candidates: list[dict], all_buttons: list[dict]) -> str:
    """
    Prompt to ask LLM which element (if any) is the menu toggle.
    Combines menu candidates (elements with menu-related attributes) and all buttons.
    """
    # Format menu candidates (high confidence - have menu keywords in attributes)
    candidates_list = []
    for i, c in enumerate(menu_candidates):
        text = c.get('text', '').strip()[:30]
        selector = c.get('selector', '')
        score = c.get('menuScore', 0)
        candidates_list.append(f"  [C{i}] selector=\"{selector}\" text=\"{text}\" score={score}")

    candidates_str = "\n".join(candidates_list) if candidates_list else "  (none found)"

    # Format all buttons
    buttons_list = []
    for i, btn in enumerate(all_buttons):
        text = btn.get('text', '').strip()[:30]
        aria = btn.get('aria_label', '')
        tag = btn.get('tag', 'button')
        buttons_list.append(f"  [B{i}] <{tag}> text=\"{text}\" aria-label=\"{aria}\"")

    buttons_str = "\n".join(buttons_list) if buttons_list else "  (none found)"

    return f"""Find the MAIN NAVIGATION MENU toggle on this fashion website.

MENU CANDIDATES (elements with menu-related attributes):
{candidates_str}

ALL BUTTONS:
{buttons_str}

RULES:
- We want the button that opens the main product navigation (Women, Men, Shop, etc.)
- Common labels: "Menu", "Shop", "Browse", "Navigation", hamburger icon (☰)
- Prefer MENU CANDIDATES if they look right (they have menu keywords in HTML)
- IGNORE: Search, Cart, Account, Login, Language, Currency, Country, Close, Wishlist

RESPOND WITH EXACTLY ONE LINE:
- Menu candidate: MENU: C[number]
- Button: MENU: B[number]
- No menu found: MENU: NONE

Examples:
MENU: C0
MENU: B2
MENU: NONE
"""


async def extract_header_buttons(page: Page) -> list[dict]:
    """
    Extract all visible buttons on the page.
    Returns list of dicts with text, aria_label, tag, and index for LLM identification.
    """
    script = """
    () => {
        const results = [];
        const seen = new Set();

        // All buttons and short links on the page
        const elements = document.querySelectorAll('button, [role="button"], a');

        for (const el of elements) {
            const text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
            const ariaLabel = el.getAttribute('aria-label') || '';
            const tag = el.tagName.toLowerCase();

            // Skip invisible elements
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            if (el.offsetParent === null) continue;

            // Skip elements with very long text (likely content, not buttons)
            if (text.length > 50) continue;

            // Create unique key to avoid duplicates
            const key = `${tag}:${text}:${ariaLabel}`;
            if (seen.has(key)) continue;
            seen.add(key);

            results.push({
                text: text,
                aria_label: ariaLabel,
                tag: tag,
                width: rect.width,
                height: rect.height,
                has_svg: el.querySelector('svg') !== null,
                has_img: el.querySelector('img') !== null
            });
        }

        // Add index for LLM reference
        return results.slice(0, 20).map((r, i) => ({...r, index: i}));
    }
    """
    try:
        return await page.evaluate(script)
    except:
        return []


def parse_menu_button_response(response: str) -> tuple[str, int] | None:
    """
    Parse LLM response for menu button identification.
    Returns (type, index) where type is 'C' for candidate or 'B' for button.
    Returns None if no menu found.
    """
    import re
    for line in response.strip().split('\n'):
        if 'MENU:' in line.upper() or 'MENU_INDEX' in line.upper():
            if 'NONE' in line.upper():
                return None
            # Look for C[number] or B[number]
            match = re.search(r'([CB])(\d+)', line.upper())
            if match:
                return (match.group(1), int(match.group(2)))
            # Fallback: just a number (assume button)
            match = re.search(r'(\d+)', line)
            if match:
                return ('B', int(match.group(1)))
    return None


def parse_subcategories(response: str) -> tuple[list, list, bool]:
    """
    Parse LLM response for subcategories.
    Returns (clickable_items, links, is_product_listing)
    - clickable items will be explored
    - is_product_listing: True if page is a product listing (not a nav menu)
    """
    import re
    clickable = []
    links = []
    is_product_listing = False
    current_section = None  # 'clickable' or 'links'

    for line in response.split('\n'):
        line = line.strip()

        # Check for leaf page indicator (no more navigation depth)
        if 'PAGE_TYPE' in line.upper() and ('LEAF' in line.upper() or 'PRODUCT_LISTING' in line.upper()):
            is_product_listing = True
            continue

        if 'CLICKABLE' in line.upper() or 'EXPANDABLE' in line.upper():
            current_section = 'clickable'
            continue
        elif 'LINKS' in line.upper() and ':' in line:
            current_section = 'links'
            continue
        # Backwards compatibility
        elif 'SUBCATEGORIES:' in line.upper() or 'ITEMS:' in line.upper():
            current_section = 'clickable'
            continue

        if current_section:
            if line.upper() == 'NONE':
                continue
            # Parse any type: "- TYPE: Name"
            match = re.match(r'-\s*(\w+):\s*(.+)', line)
            if match:
                item_type = match.group(1).lower()
                name = match.group(2).strip()
                if name:
                    item = {'type': item_type, 'name': name}
                    if current_section == 'clickable':
                        clickable.append(item)
                    else:
                        links.append(item)

    return clickable, links, is_product_listing


def parse_menu_structure(response: str) -> dict:
    """Parse LLM response for menu structure into top_level, subcategories, and links."""
    result = {'top_level': [], 'subcategories': [], 'links': []}
    current_section = None

    for line in response.split('\n'):
        line = line.strip()

        if 'TOP_LEVEL:' in line.upper():
            current_section = 'top_level'
            continue
        elif 'SUBCATEGORIES:' in line.upper() or 'SUB_CATEGORIES:' in line.upper():
            current_section = 'subcategories'
            continue
        elif 'LINKS:' in line.upper():
            current_section = 'links'
            continue

        if current_section and line.startswith('- '):
            # Parse: - TAB: Name or - BUTTON: Name or - LINK: Name | url
            if line.startswith('- TAB:'):
                name = line[6:].strip()
                if name and name.lower() not in ['none', '']:
                    result[current_section].append({'type': 'tab', 'name': name})
            elif line.startswith('- BUTTON:'):
                name = line[9:].strip()
                if name and name.lower() not in ['none', '']:
                    result[current_section].append({'type': 'button', 'name': name})
            elif line.startswith('- LINK:'):
                parts = line[7:].strip().split('|')
                name = parts[0].strip()
                url = parts[1].strip() if len(parts) > 1 else None
                if name and name.lower() not in ['none', '']:
                    result[current_section].append({'type': 'link', 'name': name, 'url': url})

    return result


def parse_items(response: str) -> list:
    """Parse LLM response into list of items."""
    items = []
    in_section = False

    for line in response.split('\n'):
        line = line.strip()

        if 'ITEMS:' in line.upper():
            in_section = True
            continue

        if in_section:
            if line.startswith('- BUTTON:'):
                name = line[9:].strip()
                if name.lower() not in ['none', '']:
                    items.append({'type': 'button', 'name': name})
            elif line.startswith('- TAB:'):
                name = line[6:].strip()
                if name.lower() not in ['none', '']:
                    items.append({'type': 'tab', 'name': name})
            elif line.startswith('- GROUP:'):
                name = line[8:].strip()
                if name.lower() not in ['none', '']:
                    items.append({'type': 'group', 'name': name})
            elif line.startswith('- LINK:'):
                parts = line[7:].strip().split('|')
                name = parts[0].strip()
                url = parts[1].strip() if len(parts) > 1 else None
                if name.lower() not in ['none', '']:
                    items.append({'type': 'link', 'name': name, 'url': url})

    return items


# =============================================================================
# Button extraction from ARIA
# =============================================================================

def extract_buttons_from_aria(aria: str, with_types: bool = False) -> set | dict:
    """
    Extract all button and tab names from ARIA.

    Args:
        aria: ARIA snapshot string
        with_types: If True, return dict {name: type}, else return set of names

    Returns:
        set of names (default) or dict {name: 'button'|'tab'} if with_types=True
    """
    import re

    if with_types:
        items = {}  # {name: type}
    else:
        items = set()

    for line in aria.split('\n'):
        # Match buttons: - button "Name"
        btn_match = re.search(r'- button "([^"]+)"', line)
        if btn_match:
            name = btn_match.group(1)
            # Clean duplicated names like "Sweaters Sweaters"
            words = name.split()
            if len(words) >= 2 and len(words) % 2 == 0:
                half = len(words) // 2
                if words[:half] == words[half:]:
                    name = ' '.join(words[:half])
            if with_types:
                items[name] = 'button'
            else:
                items.add(name)

        # Match tabs: - tab "Name" (with optional [selected])
        tab_match = re.search(r'- tab "([^"]+)"', line)
        if tab_match:
            name = tab_match.group(1)
            if with_types:
                items[name] = 'tab'
            else:
                items.add(name)

    return items


def extract_links_with_hierarchy_from_aria(aria: str) -> dict:
    """
    Extract links from ARIA grouped by their parent region/heading.

    Parses ARIA structure to find regions like:
        - region "New In":
            - list:
              - link "Highlights"

    Returns: {region_name: {link_name: url}}
    """
    import re

    groups = {}
    current_region = '_root'
    lines = aria.split('\n')

    for i, line in enumerate(lines):
        # Detect region start: - region "Name":
        region_match = re.search(r'- region "([^"]+)"', line)
        if region_match:
            current_region = region_match.group(1).strip()
            if current_region not in groups:
                groups[current_region] = {}
            continue

        # Detect heading (alternative grouping): - heading "Name"
        heading_match = re.search(r'- heading "([^"]+)"', line)
        if heading_match:
            # Headings often precede regions, but can also be standalone groups
            potential_region = heading_match.group(1).strip()
            # Only switch if we see links after it (will be handled naturally)
            continue

        # Detect link: - link "Name":
        link_match = re.search(r'- link "([^"]+)"', line)
        if link_match:
            link_name = link_match.group(1).strip()

            # Look for URL on same line or next lines
            url = None
            url_match = re.search(r'/url:\s*([^\s]+)', line)
            if url_match:
                url = url_match.group(1).strip()
            else:
                # Check next few lines for URL
                for j in range(i + 1, min(i + 4, len(lines))):
                    url_match = re.search(r'/url:\s*([^\s]+)', lines[j])
                    if url_match:
                        url = url_match.group(1).strip()
                        break
                    # Stop if we hit another element
                    if re.match(r'\s*- (link|button|heading|region)', lines[j]):
                        break

            if url and link_name:
                if current_region not in groups:
                    groups[current_region] = {}
                groups[current_region][link_name] = url

    return groups


async def extract_links_with_hierarchy(page: Page, container_selector: str = None) -> dict:
    """
    Extract links with hierarchy by parsing ARIA snapshot.

    Gets ARIA from container (or body) and parses region structure.
    Returns: {region_name: {link_name: url}}
    """
    try:
        if container_selector:
            locator = page.locator(container_selector).first
            if await locator.count() > 0:
                aria = await locator.aria_snapshot()
                print(f"    [HIERARCHY] Parsing ARIA from container ({len(aria)} chars)")
            else:
                aria = await page.locator('body').aria_snapshot()
                print(f"    [HIERARCHY] Container not found, using body ({len(aria)} chars)")
        else:
            aria = await page.locator('body').aria_snapshot()
            print(f"    [HIERARCHY] Using body ({len(aria)} chars)")

        result = extract_links_with_hierarchy_from_aria(aria)
        regions = list(result.keys())
        total_links = sum(len(links) for links in result.values())
        print(f"    [HIERARCHY] Found {len(regions)} regions with {total_links} links: {regions[:5]}...")
        return result
    except Exception as e:
        print(f"    [HIERARCHY] Error: {e}")
        return {}


def extract_links_from_aria(aria: str) -> dict:
    """Extract all links from ARIA. Returns {name: url}."""
    import re
    links = {}
    lines = aria.split('\n')
    for i, line in enumerate(lines):
        # Match: - link "Text" OR - link: (nameless)
        named_match = re.search(r'- link "([^"]+)"', line)
        nameless_match = re.search(r'- link:\s*$', line)

        if named_match or nameless_match:
            name = named_match.group(1).strip() if named_match else None

            # Look for URL on same line
            url_match = re.search(r'/url:\s*([^\s]+)', line)
            if url_match:
                url = url_match.group(1)
            else:
                # URL might be on next line(s) - check next few lines
                url = None
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j]
                    url_match = re.search(r'/url:\s*([^\s]+)', next_line)
                    if url_match:
                        url = url_match.group(1)
                        break
                    # Stop if we hit another element (but not /url line)
                    if re.match(r'\s*-\s+(link|button|tab|img|text|listitem|menu)', next_line):
                        break

            if url:
                # If no name, derive from URL path
                if not name or name == 'null':
                    # /en_us/scarves-women → scarves-women
                    path_parts = url.rstrip('/').split('/')
                    name = path_parts[-1] if path_parts else url
                    # Clean up: scarves-women → Scarves Women
                    name = name.replace('-', ' ').replace('_', ' ').title()

                if name and len(name) < 100:
                    links[name] = url
    return links


def filter_utility_links(links: dict) -> dict:
    """Filter out utility/non-product links."""
    skip_url_patterns = [
        'login', 'cart', 'wishlist', 'account', 'saved',
        'faq', 'contact', 'careers', 'legal', 'privacy', 'cookie', 'terms',
        'facebook', 'instagram', 'tiktok', 'pinterest', 'linkedin', 'twitter',
        'tel:', 'mailto:', 'javascript:',
        'track-order', 'returns', 'shipping', 'payment', 'newsletter',
        'store-locator', 'find-store', 'appointments',
        # Filter/vendor URLs - these are product filters, not categories
        '/vendors?', 'vendors?q=', '?q=', '?filter=', '?color=', '?size=',
        # External utility domains
        'calendly.com', 'shopify.com', 'klaviyo.com',
        # Return/exchange policy
        'return-exchange', 'refund-policy',
    ]

    # Skip anchor-only links (just "#" or "#something" with no path)
    skip_anchor_only = lambda url: url.startswith('#') or url == '#'

    skip_names = [
        'login', 'cart', 'search', 'close', 'back', 'menu',
        'saved items', 'wishlist', 'account', 'sign in',
        # Utility links
        'skip to content', 'skip to main', 'powered by',
        'book appointment', 'book a call', 'schedule',
        # Color/size names (common filter values - these aren't categories)
        'explore',  # Generic non-category link
    ]

    filtered = {}
    for name, url in links.items():
        name_lower = name.lower()
        url_lower = url.lower() if url else ''

        # Skip by name
        if any(skip in name_lower for skip in skip_names):
            continue
        # Skip by URL pattern
        if any(skip in url_lower for skip in skip_url_patterns):
            continue
        # Skip anchor-only links
        if skip_anchor_only(url):
            continue

        filtered[name] = url

    return filtered


def filter_utility_buttons(buttons: set | dict) -> set | dict:
    """
    Filter out utility/non-product buttons.

    Args:
        buttons: Either a set of names or dict {name: type}

    Returns:
        Same type as input, with utility buttons removed
    """
    skip_buttons = {
        'back', 'close', 'search', 'login', 'cart', 'menu',
        'shipping to the us', 'change language', 'subscribe',
        'play', 'pause', 'mute', 'unmute',
        'chat support', 'cookie settings', 'link', 'chat', 'support',
        'cookies', 'settings', 'help', 'navigation'
    }

    def should_skip(name: str) -> bool:
        name_lower = name.lower()
        if name_lower in skip_buttons:
            return True
        if any(skip in name_lower for skip in skip_buttons):
            return True
        return False

    if isinstance(buttons, dict):
        return {name: typ for name, typ in buttons.items() if not should_skip(name)}
    else:
        return {b for b in buttons if not should_skip(b)}


# =============================================================================
# Menu ARIA detection and extraction
# =============================================================================

def diff_aria_states(before: str, after: str) -> tuple[int, list[str]] | None:
    """
    Compare ARIA before and after menu opens.
    Returns (first_new_line_index, new_lines) or None if no diff.

    The menu content is the new/changed content that appeared after opening.
    """
    before_lines = before.split('\n')
    after_lines = after.split('\n')

    before_set = set(before_lines)

    # Find first line in 'after' that wasn't in 'before'
    first_new_idx = None
    new_lines = []

    for i, line in enumerate(after_lines):
        if line not in before_set:
            if first_new_idx is None:
                first_new_idx = i
            new_lines.append(line)

    if first_new_idx is None:
        return None

    return (first_new_idx, new_lines)


def find_menu_start(before: str, after: str) -> tuple[int, str] | None:
    """
    Find where the menu content starts by comparing before/after ARIA states.
    Returns (line_index, first_new_line) or None if no change detected.
    """
    result = diff_aria_states(before, after)
    if result is None:
        return None

    first_idx, new_lines = result
    first_line = new_lines[0] if new_lines else ""
    return (first_idx, first_line.strip()[:100])


def extract_menu_aria(before: str, after: str, context_lines: int = 3) -> str:
    """
    Extract just the menu portion of ARIA by comparing before/after states.
    Keeps a few lines before the first new content for context.

    Args:
        before: ARIA snapshot before opening menu
        after: ARIA snapshot after opening menu
        context_lines: Number of lines to keep before new content

    Returns:
        Truncated ARIA with just menu content, or full 'after' if no diff found
    """
    result = find_menu_start(before, after)

    if result is None:
        return after

    menu_start, _ = result
    lines = after.split('\n')
    start_line = max(0, menu_start - context_lines)

    return '\n'.join(lines[start_line:])


async def find_menu_container(page: Page) -> tuple[str | None, str | None]:
    """
    Find the menu element and return its ARIA snapshot and selector.

    Priority:
    1. Use aria-controls from cached menu button (semantic)
    2. Find visible nav element (the menu IS a nav)

    Returns:
        (aria_snapshot, selector) or (None, None) if not found
    """
    global _cached_menu_button

    # PRIORITY 1: Use aria-controls from the menu button we clicked
    if _cached_menu_button and _cached_menu_button.get('controls'):
        controls_id = _cached_menu_button['controls']
        # Use attribute selector to handle special characters in ID
        selector = f'[id="{controls_id}"]'
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                aria = await el.aria_snapshot()
                if aria and 'link' in aria.lower():
                    print(f"    [MENU] Using aria-controls: {controls_id}")
                    return aria, selector
        except Exception as e:
            print(f"    [MENU] aria-controls failed: {e}")

    return None, None


def compute_aria_diff(before_aria: str, after_aria: str) -> list[str]:
    """
    Compute ARIA diff - lines that are in after but not in before.
    This represents what became visible (e.g., the menu content).
    """
    before_lines = set(before_aria.split('\n'))
    new_lines = [l for l in after_aria.split('\n') if l not in before_lines]
    return new_lines


def is_duplicate_block(block_aria: str, before_aria: str, threshold: float = 0.8) -> bool:
    """
    Check if block content exists in BEFORE with different indentation.

    This detects cases where mobile menu drawers duplicate footer content -
    the same links appear but at different nesting levels (different indentation).

    Args:
        block_aria: ARIA content of the candidate block
        before_aria: ARIA content from before menu opened
        threshold: Fraction of block lines that must match to be considered duplicate

    Returns:
        True if block is a duplicate (should be filtered out)
    """
    # Strip indentation from block
    stripped_block = [line.lstrip() for line in block_aria.split('\n') if line.strip()]
    if not stripped_block:
        return False

    # Strip indentation from before and build a set for fast lookup
    stripped_before = {line.lstrip() for line in before_aria.split('\n') if line.strip()}

    # Count how many block lines exist in before (ignoring indentation)
    matches = sum(1 for line in stripped_block if line in stripped_before)
    match_ratio = matches / len(stripped_block)

    return match_ratio >= threshold


async def _discover_menu_container(page: Page, diff_text: str, before_aria: str) -> str | None:
    """
    Discover menu container by finding element whose ARIA matches the diff content.

    Used as fallback when no standard ARIA roles (dialog, navigation, etc.) are found.

    Args:
        page: Playwright page
        diff_text: The ARIA diff content (new lines that appeared)
        before_aria: ARIA before menu opened (to filter out pre-existing content)

    Returns:
        CSS selector for the menu container, or None if not found
    """
    print(f"    [DISCOVER] Diff content ({len(diff_text)} chars):")
    print(diff_text)
    print(f"    [DISCOVER] --- end diff ---")

    # Strip leading whitespace for comparison (indentation differs between full-page and element ARIA)
    diff_lines = set(line.lstrip() for line in diff_text.split('\n') if line.strip())
    before_lines = set(line.lstrip() for line in before_aria.split('\n') if line.strip())

    print(f"    [DISCOVER] Diff has {len(diff_lines)} unique lines")

    # Find visible overlay elements via JS (fixed/absolute positioned, large, visible)
    # Track per-tag index for accurate Playwright locator
    overlay_info = await page.evaluate("""() => {
        const results = [];
        const tagCounts = {};  // Track index per tag

        document.querySelectorAll('div, aside, section, header').forEach((el) => {
            const tag = el.tagName.toLowerCase();
            tagCounts[tag] = (tagCounts[tag] || 0);
            const tagIdx = tagCounts[tag];
            tagCounts[tag]++;

            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();

            // Must be visible
            if (style.display === 'none' || style.visibility === 'hidden') return;
            if (parseFloat(style.opacity) === 0) return;
            if (rect.width < 200 || rect.height < 200) return;

            // Prefer fixed/absolute (overlays) but also check static elements
            const isOverlay = style.position === 'fixed' || style.position === 'absolute';

            results.push({
                tag: tag,
                tagIdx: tagIdx,  // Index within this tag type
                isOverlay: isOverlay,
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            });
        });
        return results;
    }""")

    # Sort: overlays first, then by size (larger first)
    overlay_info.sort(key=lambda x: (not x['isOverlay'], -(x['width'] * x['height'])))

    print(f"    [DISCOVER] Found {len(overlay_info)} visible large elements ({sum(1 for x in overlay_info if x['isOverlay'])} overlays)")

    # Debug: show first few overlays
    for i, info in enumerate(overlay_info[:10]):
        overlay_tag = "OVERLAY" if info['isOverlay'] else "static"
        print(f"    [DISCOVER] #{i}: {info['tag']}[{info['tagIdx']}] ({overlay_tag}, {info['width']}x{info['height']})")

    candidates = []

    for info in overlay_info[:30]:  # Check top 30
        try:
            # Get element by tag and index within that tag
            el = page.locator(f"{info['tag']}").nth(info['tagIdx'])

            el_aria = await el.aria_snapshot()
            if not el_aria or len(el_aria) < 100:
                print(f"    [DISCOVER] {info['tag']}[{info['tagIdx']}]: skipped (aria={len(el_aria) if el_aria else 0} chars)")
                continue

            # Strip whitespace to match diff_lines format
            el_lines = set(line.lstrip() for line in el_aria.split('\n') if line.strip())

            # Check how much of diff is in this element
            diff_in_el = diff_lines & el_lines
            if len(diff_lines) == 0:
                continue

            coverage = len(diff_in_el) / len(diff_lines)

            # Check how much is NEW (not from before)
            new_in_el = el_lines - before_lines
            if len(el_lines) == 0:
                continue

            new_ratio = len(new_in_el) / len(el_lines)

            # Log all overlays and elements with any coverage
            overlay_tag = "[OVERLAY]" if info['isOverlay'] else ""
            if info['isOverlay'] or coverage > 0.1:
                print(f"    [DISCOVER] {info['tag']}[{info['tagIdx']}]{overlay_tag}: coverage={coverage:.0%}, new={new_ratio:.0%}, size={len(el_aria)}")

            # Good candidate: contains most of diff AND mostly new content
            if coverage > 0.5 and new_ratio > 0.5:
                selector = await _build_selector_for_element(page, el)
                if selector:
                    candidates.append({
                        'selector': selector,
                        'coverage': coverage,
                        'new_ratio': new_ratio,
                        'size': len(el_aria),
                        'is_overlay': info['isOverlay']
                    })
                    print(f"    [DISCOVER] Candidate: {selector}")

        except Exception as e:
            continue

    if not candidates:
        print(f"    [DISCOVER] No container found matching diff content")
        return None

    # Pick best candidate: prefer overlays, then highest new_ratio (menu should be mostly new content)
    candidates.sort(key=lambda c: (not c['is_overlay'], -c['new_ratio'], c['size']))
    best = candidates[0]
    print(f"    [DISCOVER] Selected: {best['selector']} (overlay={best['is_overlay']}, coverage={best['coverage']:.0%}, new={best['new_ratio']:.0%})")

    # Debug: print first 500 chars of selected element
    try:
        el = page.locator(best['selector']).first
        el_aria = await el.aria_snapshot()
        preview = el_aria[:500] if el_aria else "N/A"
        print(f"    [DISCOVER] Preview:\n{preview}")
    except:
        pass

    return best['selector']


async def _build_selector_for_element(page: Page, el) -> str | None:
    """Build a CSS selector for an element."""
    try:
        # Try to get a unique selector via JS
        selector = await el.evaluate("""el => {
            // Try ID first
            if (el.id) return '#' + el.id;

            // Try unique class combination
            if (el.className) {
                const classes = el.className.toString().split(' ')
                    .filter(c => c && !c.includes(':') && c.length < 30)
                    .slice(0, 3);
                if (classes.length) {
                    const selector = el.tagName.toLowerCase() + '.' + classes.join('.');
                    if (document.querySelectorAll(selector).length === 1) {
                        return selector;
                    }
                }
            }

            // Try aria-label
            const label = el.getAttribute('aria-label');
            if (label) {
                const selector = el.tagName.toLowerCase() + '[aria-label="' + label + '"]';
                if (document.querySelectorAll(selector).length === 1) {
                    return selector;
                }
            }

            return null;
        }""")
        return selector
    except:
        return None


def find_root_role_in_diff(new_lines: list[str]) -> list[str]:
    """
    Find container roles in the ARIA diff.
    Returns a prioritized list of roles found (dialog first since menus are usually dialogs).
    """
    # Priority order - dialog first since menus are typically dialogs
    container_roles = ['dialog', 'navigation', 'menu', 'region', 'list', 'complementary', 'generic']

    found_roles = set()

    for line in new_lines:
        stripped = line.lstrip()
        if not stripped.startswith('- '):
            continue

        # Parse role from line like "- navigation" or "- dialog:"
        for role in container_roles:
            if stripped.startswith(f'- {role}'):
                found_roles.add(role)
                break

    # Return in priority order
    return [r for r in container_roles if r in found_roles]


async def find_menu_from_aria_diff(page: Page, before_aria: str, after_aria: str) -> tuple[str | None, str | None]:
    """
    Find the menu element by using ARIA diff to map back to DOM.

    Strategy:
    1. Compute ARIA diff (what became visible after clicking menu)
    2. Find visible containers that have mostly new content
    3. Use LLM to identify which container is the navigation menu

    Returns:
        (menu_aria, selector, additional_branches) or (None, None, []) if not found
    """
    # 1. Compute diff - what became visible
    new_lines = compute_aria_diff(before_aria, after_aria)

    print(f"    [ARIA-DIFF] {len(new_lines)} new lines appeared")

    if not new_lines:
        print(f"    [ARIA-DIFF] No new content detected")
        return None, None, []

    diff_text = '\n'.join(new_lines)

    # 2. Find all container roles in diff
    candidate_roles = find_root_role_in_diff(new_lines)

    if not candidate_roles:
        # Fallback: discover menu container by matching ARIA content
        print(f"    [ARIA-DIFF] No standard roles, discovering container by content...")
        selector = await _discover_menu_container(page, diff_text, before_aria)
        return diff_text, selector, []

    print(f"    [ARIA-DIFF] Container roles found: {candidate_roles}")

    # 3. Collect candidate containers (new content, reasonable size)
    before_lines = set(before_aria.split('\n'))
    candidates = []

    for role in candidate_roles:
        try:
            elements = await page.get_by_role(role).all()
        except Exception:
            continue

        for i, el in enumerate(elements[:10]):  # Limit per role
            try:
                if not await el.is_visible():
                    continue

                el_aria = await el.aria_snapshot()
                if not el_aria or len(el_aria) < 100:
                    continue

                # Check if content is mostly new
                el_lines = set(el_aria.split('\n'))
                new_in_el = el_lines - before_lines

                if len(el_lines) == 0:
                    continue

                new_ratio = len(new_in_el) / len(el_lines)
                if new_ratio < 0.5:
                    continue

                # Check if this block is duplicate content (e.g., footer in menu drawer)
                if is_duplicate_block(el_aria, before_aria):
                    print(f"    [ARIA-DIFF] Skipping duplicate block: {role}[{i}]")
                    continue

                candidates.append({
                    'el': el,
                    'aria': el_aria,
                    'role': role,
                    'idx': i,
                    'size': len(el_aria)
                })

            except Exception:
                continue

    if not candidates:
        print(f"    [ARIA-DIFF] No candidates found, using raw diff")
        return diff_text, None, []

    print(f"    [ARIA-DIFF] Found {len(candidates)} candidate containers")

    # 4. If only one candidate, use it
    if len(candidates) == 1:
        c = candidates[0]
        selector = await _get_element_selector(page, c['el'], c['role'], c['idx'])
        print(f"    [ARIA-DIFF] Single candidate: {c['role']}[{c['idx']}] ({c['size']} chars)")
        return c['aria'], selector, []

    # 5. Multiple candidates - ask LLM which to EXCLUDE (be inclusive by default)
    print(f"    [ARIA-DIFF] Using LLM to filter {len(candidates)} containers")

    # Build prompt with truncated ARIA for each candidate
    candidate_summaries = []
    for i, c in enumerate(candidates):
        # Truncate to first 1500 chars for LLM
        truncated = c['aria'][:1500] + ('...' if len(c['aria']) > 1500 else '')
        candidate_summaries.append(f"[{i}] {c['role']} ({c['size']} chars):\n{truncated}")

    prompt = f"""A menu was opened on a fashion website. Multiple containers appeared.

{chr(10).join(candidate_summaries)}

Which containers should be EXCLUDED from the navigation menu?
Only exclude containers that are clearly NOT product/collection navigation (e.g., account settings, language selector, admin panels).
Include everything that could contain clothing categories, collections, or product links.

Reply: EXCLUDE: 0, 2 (or EXCLUDE: NONE if all should be included)"""

    try:
        llm = _get_llm_handler()
        result = llm.call_text(prompt, max_tokens=50, operation="filter_menu_containers")
        _track_llm_result(result)
        response = result.get('response', '').strip()

        print(f"    [LLM] {response}")

        # Parse excluded indices
        excluded = set()
        match = re.search(r'EXCLUDE:\s*([^\n]+)', response, re.IGNORECASE)
        if match:
            text = match.group(1)
            if 'NONE' not in text.upper():
                for m in re.finditer(r'\d+', text):
                    excluded.add(int(m.group()))

        # Include all non-excluded containers
        included = [c for i, c in enumerate(candidates) if i not in excluded]

        if not included:
            # All excluded? Use all as fallback
            included = candidates

        # Combine ARIA from all included containers
        combined_aria = '\n'.join(c['aria'] for c in included)
        # Use first included container's selector
        first = included[0]
        selector = await _get_element_selector(page, first['el'], first['role'], first['idx'])

        print(f"    [ARIA-DIFF] Included {len(included)}/{len(candidates)} containers ({len(combined_aria)} chars)")
        return combined_aria, selector, []

    except Exception as e:
        print(f"    [ARIA-DIFF] LLM error: {e}")

    except Exception as e:
        print(f"    [ARIA-DIFF] LLM error: {e}")

    # Fallback: use largest candidate
    largest = max(candidates, key=lambda c: c['size'])
    selector = await _get_element_selector(page, largest['el'], largest['role'], largest['idx'])
    print(f"    [ARIA-DIFF] Fallback to largest: {largest['role']}[{largest['idx']}] ({largest['size']} chars)")
    return largest['aria'], selector, []


async def _get_element_selector(page: Page, el, role: str, idx: int) -> str | None:
    """Get a CSS selector for an element."""
    try:
        selector = await page.evaluate('''(el) => {
            if (el.id) return '[id="' + el.id + '"]';
            if (el.getAttribute('aria-label')) return '[aria-label="' + el.getAttribute('aria-label') + '"]';
            return null;
        }''', await el.element_handle())

        if not selector:
            selector = f'role={role} >> nth={idx}'

        return selector
    except:
        return f'role={role} >> nth={idx}'


async def open_menu_and_capture(page: Page) -> dict:
    """
    Open menu and capture before/after ARIA states.

    Returns dict with:
        - opened: bool - whether menu was opened
        - before_aria: str - ARIA before opening
        - after_aria: str - ARIA after opening
        - menu_aria: str - extracted menu content only (from container if found)
        - menu_start: tuple - (line_idx, first_new_line) or None
        - menu_container_found: bool - whether we found the specific menu element
        - menu_container_selector: str - CSS selector for menu element (if found)
    """
    # Capture BEFORE state
    before_aria = await page.locator('body').aria_snapshot()

    # Try cached menu button first (fast path)
    opened = await reopen_menu_fast(page)

    # Fall back to full menu detection
    if not opened:
        opened = await open_menu(page)

    if not opened:
        return {
            'opened': False,
            'before_aria': before_aria,
            'after_aria': before_aria,
            'menu_aria': before_aria,
            'menu_start': None,
            'menu_container_found': False
        }

    await page.wait_for_timeout(300)

    # Capture AFTER state (full body)
    after_aria = await page.locator('body').aria_snapshot()

    # Try to find the menu element
    # 1. First try aria-controls (semantic link from button)
    container_aria, container_selector = await find_menu_container(page)

    if container_aria:
        print(f"    [MENU] Using aria-controls container ({len(container_aria)} chars)")
        return {
            'opened': True,
            'before_aria': before_aria,
            'after_aria': after_aria,
            'menu_aria': container_aria,
            'menu_start': None,
            'menu_container_found': True,
            'menu_container_selector': container_selector
        }

    # 2. Find menu by ARIA diff - what became visible after clicking
    menu_aria, menu_selector, additional_branches = await find_menu_from_aria_diff(page, before_aria, after_aria)

    if menu_aria:
        print(f"    [MENU] Using ARIA diff menu ({len(menu_aria)} chars)")
        result = {
            'opened': True,
            'before_aria': before_aria,
            'after_aria': after_aria,
            'menu_aria': menu_aria,
            'menu_start': None,
            'menu_container_found': menu_selector is not None,
            'menu_container_selector': menu_selector
        }
        # Add additional branches if multiple menu parts were found
        # These should be treated like tabs in DFS exploration
        if additional_branches:
            result['menu_branches'] = additional_branches
            print(f"    [MENU] {len(additional_branches)} additional branches to explore")
        return result

    # 3. Fallback: use raw diff extraction (shouldn't reach here normally)
    print(f"    [MENU] Fallback: using raw diff extraction")
    menu_start = find_menu_start(before_aria, after_aria)
    menu_aria = extract_menu_aria(before_aria, after_aria)

    return {
        'opened': True,
        'before_aria': before_aria,
        'after_aria': after_aria,
        'menu_aria': menu_aria,
        'menu_start': menu_start,
        'menu_container_found': False
    }


# =============================================================================
# Tab Detection: Find top-level category tabs using geometric layout
# =============================================================================

def extract_elements_from_aria(menu_aria: str) -> set[str]:
    """
    Extract element names (buttons, tabs, links) from menu ARIA snapshot.

    Returns set of element text/names that appear in the menu.
    """
    import re
    elements = set()

    # Match patterns like: button "Text", tab "Text", link "Text"
    # Also match: link "Text /url"
    pattern = r'(?:button|tab|link|menuitem)\s+"([^"]+)"'

    for match in re.finditer(pattern, menu_aria, re.IGNORECASE):
        text = match.group(1)
        # Remove URL part if present (e.g., "Shop All /en/shop")
        if ' /' in text:
            text = text.split(' /')[0].strip()
        if text and len(text) < 30:
            elements.add(text)

    return elements


async def detect_top_level_tabs(
    page: Page,
    menu_aria: str = None,
    y_tolerance: int = 10,
    min_tabs: int = 2
) -> dict:
    """
    Detect top-level category tabs by finding horizontally-aligned elements.

    If menu_aria is provided, only considers elements that appear in the menu.

    Args:
        page: Playwright page with menu open
        menu_aria: ARIA snapshot of menu content (from open_menu_and_capture)
        y_tolerance: Pixels tolerance for "same row" detection
        min_tabs: Minimum number of elements to consider it a tab row

    Returns:
        dict with:
            - found: bool - whether candidate rows were detected
            - candidate_rows: list of rows, each with y position and elements
            - menu_aria: the menu ARIA used (for debugging)
    """
    # Extract allowed element names from menu ARIA
    allowed_names = None
    if menu_aria:
        allowed_names = extract_elements_from_aria(menu_aria)

    # Get all clickable elements with their bounding boxes
    elements = await page.evaluate('''
        () => {
            // Get ALL elements - we'll filter by text match to ARIA later
            const items = document.querySelectorAll('*');
            return Array.from(items)
                .filter(el => {
                    // Must be visible
                    if (el.offsetParent === null) return false;
                    const rect = el.getBoundingClientRect();
                    // Must have size
                    if (rect.width === 0 || rect.height === 0) return false;
                    // Must be in viewport
                    if (rect.y < 0 || rect.y > window.innerHeight) return false;
                    // Must have direct text (not just child text)
                    const text = el.textContent.trim();
                    if (!text || text.length === 0 || text.length > 30) return false;
                    return true;
                })
                .map(el => {
                    const rect = el.getBoundingClientRect();
                    return {
                        text: el.textContent.trim().replace(/\\s+/g, ' '),
                        y: Math.round(rect.y),
                        x: Math.round(rect.x),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        tag: el.tagName.toLowerCase(),
                        role: el.getAttribute('role') || ''
                    };
                });
        }
    ''')

    if not elements:
        return {'found': False, 'candidate_rows': [], 'menu_aria': menu_aria}

    # Filter to only elements that appear in menu_aria (if provided)
    if allowed_names:
        elements = [el for el in elements if el['text'] in allowed_names]

    if not elements:
        return {'found': False, 'candidate_rows': [], 'menu_aria': menu_aria,
                'note': f'No elements matched menu_aria. Allowed: {allowed_names}'}

    # Group elements by Y position (within tolerance = same row)
    rows = {}
    for el in elements:
        matched_row = None
        for row_y in rows.keys():
            if abs(el['y'] - row_y) <= y_tolerance:
                matched_row = row_y
                break

        if matched_row is not None:
            rows[matched_row].append(el)
        else:
            rows[el['y']] = [el]

    # Sort rows by Y position (topmost first)
    sorted_rows = sorted(rows.items(), key=lambda x: x[0])

    # Collect ALL candidate rows (rows with 2+ elements)
    candidate_rows = []
    for row_y, row_elements in sorted_rows:
        row_elements.sort(key=lambda x: x['x'])  # Sort left to right

        if len(row_elements) >= min_tabs:
            candidate_rows.append({
                'y': row_y,
                'elements': row_elements,
                'texts': [el['text'] for el in row_elements]
            })

    return {
        'found': len(candidate_rows) > 0,
        'candidate_rows': candidate_rows,
        'menu_aria': menu_aria
    }


async def identify_tabs_with_llm(
    page: Page,
    menu_aria: str
) -> dict:
    """
    Use LLM to identify top-level category tab names from screenshot + ARIA.

    Args:
        page: Playwright page with menu open
        menu_aria: Menu ARIA snapshot

    Returns:
        dict with:
            - tab_names: list of tab names identified by LLM
            - response: raw LLM response
            - usage: token usage
    """
    # Build prompt
    prompt = f"""This is a fashion website's mobile navigation menu.

TASK: Identify the TOP-LEVEL CATEGORY TABS.

Top-level category tabs are:
- The main shopping divisions (like Men, Women, Kids, New Arrivals, Sale)
- They appear as a row of options, often at the top of the menu
- They switch/filter the menu content when clicked
- They are NOT subcategories (like "Toddler Girls 1-3 years" or "Dresses")
- They are NOT utility buttons (like Search, Cart, Close, Back)

MENU ARIA:
{menu_aria[:6000]}

RESPOND IN THIS EXACT FORMAT:
TABS: Name1, Name2, Name3
REASON: <brief explanation>

If there are no top-level tabs (menu is just a list of links), respond:
TABS: NONE
REASON: <explanation>

Example responses:
TABS: Women, Men, Kids, Baby
REASON: These are the main category divisions at the top of the menu

TABS: NONE
REASON: This menu has no top-level tabs, just direct category links"""

    # Take screenshot and call LLM
    screenshot_bytes = await page.screenshot()
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')

    llm = _get_llm_handler()
    result = llm.call_with_image(
        prompt=prompt,
        image_b64=screenshot_b64,
        media_type="image/png",
        max_tokens=200,
        operation="identify_tabs"
    )
    _track_llm_result(result)

    response_text = result.get("response", "")

    # Parse response
    tab_names = []
    reason = ""

    for line in response_text.strip().split('\n'):
        if line.upper().startswith('TABS:'):
            tabs_part = line.replace('TABS:', '').replace('tabs:', '').strip()
            if tabs_part.upper() != 'NONE':
                # Split by comma and clean up
                tab_names = [t.strip() for t in tabs_part.split(',') if t.strip()]
        elif line.upper().startswith('REASON:'):
            reason = line.replace('REASON:', '').replace('reason:', '').strip()

    return {
        'tab_names': tab_names,
        'reason': reason,
        'response': response_text,
        'usage': result.get('usage')
    }


async def find_tabs_in_dom(
    page: Page,
    tab_names: list[str],
    menu_aria: str,
    y_tolerance: int = 15
) -> dict:
    """
    Find the tab elements in DOM that are horizontally aligned.

    Given tab names from LLM, finds elements with those texts that
    appear in a horizontal row (same Y position).

    Args:
        page: Playwright page
        tab_names: List of tab names to find
        menu_aria: Menu ARIA to find role info
        y_tolerance: Pixels tolerance for "same row"

    Returns:
        dict with:
            - found: bool
            - tabs: list of tab dicts with text, role, y, x
            - row_y: Y position of the tab row
    """
    if not tab_names:
        return {'found': False, 'tabs': [], 'row_y': None}

    # Get elements matching tab names
    tab_names_lower = {name.lower() for name in tab_names}

    elements = await page.evaluate('''
        (tabNames) => {
            const results = [];
            const tabNamesLower = tabNames.map(n => n.toLowerCase());

            // Find all elements with matching text
            const allElements = document.querySelectorAll('*');
            for (const el of allElements) {
                const text = el.textContent.trim();
                const textLower = text.toLowerCase();

                // Check if this element's text matches a tab name
                if (tabNamesLower.includes(textLower)) {
                    // Make sure it's visible and has size
                    if (el.offsetParent === null) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    if (rect.y < 0 || rect.y > window.innerHeight) continue;

                    results.push({
                        text: text,
                        y: Math.round(rect.y),
                        x: Math.round(rect.x),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        tag: el.tagName.toLowerCase()
                    });
                }
            }
            return results;
        }
    ''', tab_names)

    if not elements:
        return {'found': False, 'tabs': [], 'row_y': None, 'note': 'No elements found for tab names'}

    # Group by Y position to find the horizontal row
    rows = {}
    for el in elements:
        matched_row = None
        for row_y in rows.keys():
            if abs(el['y'] - row_y) <= y_tolerance:
                matched_row = row_y
                break

        if matched_row is not None:
            rows[matched_row].append(el)
        else:
            rows[el['y']] = [el]

    # Find the row that has the most tab names (the actual tab row)
    best_row = None
    best_row_y = None
    best_count = 0

    for row_y, row_elements in rows.items():
        # Count unique tab names in this row
        unique_texts = set(el['text'].lower() for el in row_elements)
        matching_count = len(unique_texts & tab_names_lower)

        if matching_count > best_count:
            best_count = matching_count
            best_row = row_elements
            best_row_y = row_y

    if not best_row or best_count < 2:
        return {'found': False, 'tabs': [], 'row_y': None, 'note': f'No horizontal row found with tabs'}

    # Deduplicate and sort by X position
    seen_texts = set()
    unique_tabs = []
    for el in sorted(best_row, key=lambda x: x['x']):
        text_lower = el['text'].lower()
        if text_lower not in seen_texts:
            seen_texts.add(text_lower)
            # Find role from ARIA
            role = find_role_in_aria(menu_aria, el['text'])
            unique_tabs.append({
                'text': el['text'],
                'role': role,
                'y': el['y'],
                'x': el['x']
            })

    return {
        'found': True,
        'tabs': unique_tabs,
        'row_y': best_row_y
    }


def find_role_in_aria(menu_aria: str, text: str) -> str:
    """Find the ARIA role for an element with given text."""
    import re

    # Look for patterns like: tab "Text", button "Text", link "Text /url"
    for line in menu_aria.split('\n'):
        # Check if this line contains the text
        if f'"{text}"' in line or f'"{text} /' in line:
            # Extract the role
            match = re.search(r'(button|tab|link|menuitem)\s+"', line, re.IGNORECASE)
            if match:
                return match.group(1).lower()

    return 'button'  # Default fallback


def is_menu_still_open(current_aria: str, menu_start_line: str) -> bool:
    """
    Check if menu is still open by looking for the first new line from menu opening.

    Args:
        current_aria: Current ARIA snapshot
        menu_start_line: The first new line that appeared when menu opened

    Returns True if that line is still present (menu still open).
    """
    if not menu_start_line:
        return True  # Can't verify, assume open

    return menu_start_line in current_aria


async def ensure_menu_open(page: Page, before_aria: str, base_url: str = None) -> dict:
    """
    Check if menu is still open, reopen if closed.

    Args:
        page: Playwright page
        before_aria: Original ARIA before menu was opened (to detect changes)
        base_url: URL to navigate back to if we left

    Returns same dict as open_menu_and_capture()
    """
    current_aria = await page.locator('body').aria_snapshot()
    menu_start = find_menu_start(before_aria, current_aria)

    if menu_start is not None:
        # Menu still has new content visible - probably still open
        return {
            'opened': True,
            'before_aria': before_aria,
            'after_aria': current_aria,
            'menu_aria': extract_menu_aria(before_aria, current_aria),
            'menu_start': menu_start
        }

    # Menu appears closed - reopen
    print("    [NAV] Menu appears closed, reopening...")

    # Navigate back to base URL if we left
    if base_url:
        current_url = page.url.rstrip('/')
        base_clean = base_url.rstrip('/')
        if current_url != base_clean:
            await page.goto(base_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
            # Re-capture before state
            before_aria = await page.locator('body').aria_snapshot()

    return await open_menu_and_capture(page)


async def check_and_restore_menu(page: Page, menu_ctx: Optional[MenuContext]) -> bool:
    """
    Fast check if menu is still open, restore if closed.

    This is the lightweight check to call after each interaction.
    Uses the menu_start_line string check (fast) rather than full ARIA diff.

    Args:
        page: Playwright page
        menu_ctx: Menu context from when menu was opened (None = no menu to check)

    Returns:
        True if menu is open (was open or successfully restored)
        False if menu couldn't be restored
    """
    if menu_ctx is None:
        return True  # No menu context = nothing to check

    # Fast check: look for the marker line in current ARIA
    current_aria = await page.locator('body').aria_snapshot()

    if menu_ctx.menu_start_line and menu_ctx.menu_start_line in current_aria:
        return True  # Menu still open

    # Menu might be closed - do full check and restore
    result = await ensure_menu_open(page, menu_ctx.before_aria, menu_ctx.base_url)
    return result.get('opened', False)


# =============================================================================
# Navigation helpers
# =============================================================================

async def element_exists(page: Page, name: str, element_type: str = 'button') -> bool:
    """Check if an element exists and is visible on the page."""
    roles_to_try = {
        'button': ['button', 'tab', 'link'],
        'tab': ['tab', 'button', 'link'],
        'link': ['link', 'button', 'tab'],
    }.get(element_type, ['button', 'tab', 'link'])

    for role in roles_to_try:
        try:
            locator = page.get_by_role(role, name=name, exact=True)
            if await locator.count() > 0:
                element = locator.first
                if await element.is_visible():
                    return True
        except:
            pass
    return False


async def click_button(
    page: Page,
    name: str,
    container=None,
    prefer_tab: bool = False,
    prefer_role: str = None,
    parent_menu: str = None,
    menu_ctx: Optional[MenuContext] = None
) -> bool:
    """
    Click a button by name, optionally scoped to a container or parent menu.

    Args:
        page: Playwright page
        name: Button/element name to click
        container: Optional container to search within
        prefer_tab: If True, try tab role first
        prefer_role: If set, ONLY try this role
        parent_menu: If set, search inside this menu first
        menu_ctx: If provided, check and restore menu state after click

    Returns True if element was found and clicked.
    """
    search_context = container if container else page
    clicked = False

    # If parent_menu is specified, first try to find element inside that menu
    # This handles cases like clicking "Men" inside "menu Sales" vs top-level "Men" button
    if parent_menu:
        for menu_role in ['menu', 'region', 'navigation', 'dialog']:
            try:
                menu_container = page.get_by_role(menu_role, name=parent_menu, exact=False)
                if await menu_container.count() > 0:
                    # Search for the target INSIDE this menu
                    for role in ['menuitem', 'button', 'tab', 'link']:
                        inner_locator = menu_container.get_by_role(role, name=name, exact=True)
                        if await inner_locator.count() > 0:
                            element = inner_locator.first
                            if await element.is_visible():
                                print(f"        [CLICK-DETAIL] Found '{name}' as {role} inside {menu_role} '{parent_menu}'")
                                await element.click(timeout=3000, force=True)
                                await page.wait_for_timeout(150)
                                clicked = True
                                break
                    if clicked:
                        break
            except:
                continue
        if clicked:
            if menu_ctx:
                await check_and_restore_menu(page, menu_ctx)
            return True

    # Order of roles to try
    base_roles = ['button', 'tab', 'menuitem', 'link']
    if prefer_tab:
        base_roles = ['tab', 'button', 'menuitem', 'link']

    # If a specific role is required (e.g., LLM said it's a menuitem), ONLY try that role
    # This prevents clicking button "Men" when we want menuitem "Men"
    if prefer_role:
        roles = [prefer_role]
        print(f"        [CLICK-DETAIL] Strict role search: only trying '{prefer_role}'")
    else:
        roles = base_roles

    for role in roles:
        try:
            # First try exact match, then fuzzy match if exact fails
            locator = search_context.get_by_role(role, name=name, exact=True)
            count = await locator.count()
            print(f"        [CLICK-DETAIL] {role} exact=True: {count} matches")

            # If exact match fails, try fuzzy match (handles "MENU" vs "Menu" or "Open Menu")
            if count == 0:
                locator = search_context.get_by_role(role, name=name, exact=False)
                count = await locator.count()
                print(f"        [CLICK-DETAIL] {role} exact=False: {count} matches")

            if count > 1:
                # Multiple elements with same name - potential ambiguity
                print(f"        [CLICK-DEBUG] WARNING: Found {count} elements for '{name}' as {role}")

                # For links: prefer ones with empty/no href (expandables, not navigation)
                if role == 'link':
                    try:
                        for i in range(count):
                            element = locator.nth(i)
                            href = await element.get_attribute('href')
                            # Empty href = expandable (what we want for submenu expansion)
                            if not href or href in ('', '#', 'javascript:void(0)', 'javascript:;'):
                                if await element.is_visible():
                                    print(f"        [CLICK-DETAIL] Found '{name}' as expandable link (empty href, #{i+1})")
                                    await element.click(timeout=3000, force=True)
                                    await page.wait_for_timeout(150)
                                    clicked = True
                                    break
                        if clicked:
                            break
                    except:
                        pass

            if count > 0 and not clicked:
                # Find first VISIBLE element that's NOT already expanded
                # (clicking an expanded element would close it)
                skipped_expanded = 0
                last_unexpanded = None
                for i in range(count):
                    element = locator.nth(i)
                    # Check if already expanded - skip if so
                    try:
                        aria_expanded = await element.get_attribute('aria-expanded')
                        if aria_expanded == 'true':
                            print(f"        [CLICK-DETAIL] Skipping '{name}' #{i+1} (already expanded)")
                            skipped_expanded += 1
                            continue
                    except:
                        pass
                    # Track last unexpanded element (even if not visible)
                    last_unexpanded = element
                    if await element.is_visible():
                        print(f"        [CLICK-DETAIL] Found '{name}' as {role} (#{i+1} of {count}, visible)")
                        # Short timeout - fail fast if blocked, force to bypass overlay checks
                        await element.click(timeout=3000, force=True)
                        await page.wait_for_timeout(150)
                        clicked = True
                        break
                # Fallback: if we skipped expanded elements and found an unexpanded one that's not "visible",
                # use JavaScript click (bypasses Playwright's viewport checks entirely)
                if not clicked and skipped_expanded > 0 and last_unexpanded:
                    print(f"        [CLICK-DETAIL] Trying JS click on nested element (skipped {skipped_expanded} expanded)")
                    try:
                        await last_unexpanded.evaluate("el => el.click()")
                        await page.wait_for_timeout(150)
                        clicked = True
                    except Exception as e:
                        print(f"        [CLICK-DETAIL] JS click failed: {e}")
                if clicked:
                    break
                print(f"        [CLICK-DETAIL] Found '{name}' as {role} but none visible/unexpanded")
        except Exception as e:
            print(f"        [CLICK-DETAIL] {role} failed: {e}")
            continue

    # Try <summary> elements (used by <details> pattern, appear as "group" in ARIA)
    if not clicked:
        try:
            # Prefer header summary elements to avoid footer/mobile nav duplicates
            summary = search_context.locator(f'header summary[aria-label="{name}"], header summary:has-text("{name}")')
            count = await summary.count()
            if count == 0:
                summary = search_context.locator(f'summary[aria-label="{name}"], summary:has-text("{name}")')
                count = await summary.count()

            if count > 0:
                for i in range(count):
                    element = summary.nth(i)
                    if await element.is_visible():
                        print(f"        [CLICK-DETAIL] Found '{name}' as summary (#{i+1} of {count}, visible)")
                        await element.click(timeout=2000, force=True)
                        await page.wait_for_timeout(150)
                        clicked = True
                        break
                if not clicked:
                    print(f"        [CLICK-DETAIL] Found '{name}' as summary but none visible")
        except Exception as e:
            print(f"        [CLICK-DETAIL] Error with summary: {e}")

    if not clicked:
        tried_roles = '/'.join(roles) + '/summary'
        print(f"      [CLICK] Could not find '{name}' via get_by_role - trying alternative selectors...")

        # Try finding by :has-text (finds elements containing text, even in hidden spans)
        # This handles "fallback-text" pattern where text is visually hidden
        try:
            # Look for buttons containing the text anywhere (including in child spans)
            text_locator = search_context.locator(f'button:has-text("{name}")')
            count = await text_locator.count()
            print(f"      [CLICK] button:has-text found {count} matches")
            if count > 0:
                skipped_expanded = 0
                last_unexpanded = None
                for i in range(count):
                    element = text_locator.nth(i)
                    # Check if already expanded - skip if so
                    try:
                        aria_expanded = await element.get_attribute('aria-expanded')
                        if aria_expanded == 'true':
                            print(f"      [CLICK] Skipping :has-text match #{i+1} (already expanded)")
                            skipped_expanded += 1
                            continue
                    except:
                        pass
                    last_unexpanded = element
                    if await element.is_visible():
                        print(f"      [CLICK] Found via :has-text! Clicking...")
                        await element.click(timeout=3000, force=True)
                        await page.wait_for_timeout(150)
                        if menu_ctx:
                            await check_and_restore_menu(page, menu_ctx)
                        return True
                # Fallback for nested buttons - use JS click
                if skipped_expanded > 0 and last_unexpanded:
                    print(f"      [CLICK] Trying JS click on nested :has-text element")
                    try:
                        await last_unexpanded.evaluate("el => el.click()")
                        await page.wait_for_timeout(150)
                        if menu_ctx:
                            await check_and_restore_menu(page, menu_ctx)
                        return True
                    except Exception as e:
                        print(f"      [CLICK] JS click failed: {e}")
                print(f"      [CLICK] Found {count} by :has-text but none visible/clickable")
        except Exception as e:
            print(f"      [CLICK] :has-text search failed: {e}")

        # Try finding by aria-label (ARIA name might come from aria-label attribute)
        try:
            label_locator = search_context.locator(f'[aria-label*="{name}" i]')
            count = await label_locator.count()
            print(f"      [CLICK] aria-label found {count} matches")
            if count > 0:
                for i in range(count):
                    element = label_locator.nth(i)
                    if await element.is_visible():
                        # Check if already expanded - skip if so
                        try:
                            aria_expanded = await element.get_attribute('aria-expanded')
                            if aria_expanded == 'true':
                                print(f"      [CLICK] Skipping aria-label match #{i+1} (already expanded)")
                                continue
                        except:
                            pass
                        print(f"      [CLICK] Found via aria-label! Clicking...")
                        await element.click(timeout=3000, force=True)
                        await page.wait_for_timeout(150)
                        if menu_ctx:
                            await check_and_restore_menu(page, menu_ctx)
                        return True
                print(f"      [CLICK] Found {count} by aria-label but none visible/clickable")
        except Exception as e:
            print(f"      [CLICK] aria-label search failed: {e}")

        # Try finding by title attribute
        try:
            title_locator = search_context.locator(f'[title*="{name}" i]')
            count = await title_locator.count()
            if count > 0:
                for i in range(count):
                    element = title_locator.nth(i)
                    if await element.is_visible():
                        # Check if already expanded - skip if so
                        try:
                            aria_expanded = await element.get_attribute('aria-expanded')
                            if aria_expanded == 'true':
                                print(f"      [CLICK] Skipping title match #{i+1} (already expanded)")
                                continue
                        except:
                            pass
                        print(f"      [CLICK] Found via title attribute! Clicking...")
                        await element.click(timeout=3000, force=True)
                        await page.wait_for_timeout(150)
                        if menu_ctx:
                            await check_and_restore_menu(page, menu_ctx)
                        return True
        except:
            pass

        # Print ARIA to help debug what's actually on the page
        try:
            aria = await page.locator('body').aria_snapshot()
            print(f"      [CLICK] ARIA snapshot ({len(aria)} chars):")
            # Print lines containing the name
            lines = aria.split('\n')
            matching_lines = [l for l in lines if name.lower() in l.lower()]
            if matching_lines:
                print(f"      Lines containing '{name}':")
                for line in matching_lines[:10]:
                    print(f"        {line}")
            else:
                print(f"      No lines contain '{name}'. First 30 lines:")
                for line in lines[:30]:
                    print(f"        {line}")
        except:
            pass

        # If we used strict mode and failed, try all roles as fallback
        if prefer_role and len(roles) == 1:
            print(f"      [CLICK] Retrying without strict mode...")
            for role in ['button', 'tab', 'menuitem', 'link']:
                if role == prefer_role:
                    continue  # Already tried this one
                try:
                    locator = search_context.get_by_role(role, name=name, exact=False)
                    count = await locator.count()
                    if count > 0:
                        # For links: prefer empty href (expandables) over navigation links
                        if role == 'link' and count > 1:
                            for i in range(count):
                                element = locator.nth(i)
                                href = await element.get_attribute('href')
                                if not href or href in ('', '#', 'javascript:void(0)', 'javascript:;'):
                                    if await element.is_visible():
                                        print(f"      [CLICK] Found as expandable link on retry (empty href)!")
                                        await element.click(timeout=3000, force=True)
                                        await page.wait_for_timeout(150)
                                        if menu_ctx:
                                            await check_and_restore_menu(page, menu_ctx)
                                        return True

                        for i in range(count):
                            element = locator.nth(i)
                            if await element.is_visible():
                                print(f"      [CLICK] Found as {role} on retry!")
                                await element.click(timeout=3000, force=True)
                                await page.wait_for_timeout(150)
                                if menu_ctx:
                                    await check_and_restore_menu(page, menu_ctx)
                                return True
                except:
                    continue

        return False

    # Check and restore menu state if context provided
    if menu_ctx:
        await check_and_restore_menu(page, menu_ctx)

    return True


def hover_revealed_content(aria_before: str, aria_after: str) -> tuple[bool, str]:
    """
    Check if hover revealed NEW content (links, buttons, menuitems, etc).

    Uses line-based diff to detect any new navigation content.
    Counts new lines containing interactive elements.

    Returns (revealed: bool, reason: str)
    """
    before_lines = set(aria_before.split('\n'))
    after_lines = aria_after.split('\n')

    # Find NEW lines that appeared
    new_lines = [line for line in after_lines if line not in before_lines]

    if not new_lines:
        return False, "no new content"

    # Count lines with interactive elements (links, buttons, menuitems, tabs)
    interactive_keywords = ['link', 'button', 'menuitem', 'tab']
    interactive_count = sum(
        1 for line in new_lines
        if any(kw in line.lower() for kw in interactive_keywords)
    )

    # Require at least 3 new interactive elements to count as "revealed"
    # (avoids false positives from tooltips/popups)
    if interactive_count >= 3:
        return True, f"new content (+{interactive_count} interactive elements)"

    # Also check for significant content even without interactive keywords
    # (some menus use generic elements)
    if len(new_lines) >= 10:
        return True, f"new content (+{len(new_lines)} lines)"

    return False, f"minimal change (+{len(new_lines)} lines, {interactive_count} interactive)"


async def hover_and_check(
    page: Page,
    name: str,
    item_type: str = None,
    container=None,
    menu_ctx: Optional[MenuContext] = None
) -> tuple[bool, str]:
    """
    Hover over an element and check if new content appeared.
    For sites like Eckhaus Latta where menus reveal on hover, not click.

    Args:
        page: Playwright page
        name: Element name to find
        item_type: Optional type hint ('button', 'tab', 'link', 'group') to try first
        container: Optional container to search within
        menu_ctx: If provided, check and restore menu state after hover

    Returns (revealed_content: bool, aria_after: str)
    """
    search_context = container if container else page

    # Capture ARIA before hover
    aria_before = await page.locator('body').aria_snapshot()

    # Determine role order - try the hinted type first, then others
    base_roles = ['button', 'tab', 'menuitem', 'link']
    if item_type and item_type.lower() in base_roles:
        base_roles.remove(item_type.lower())
        base_roles.insert(0, item_type.lower())
    roles = base_roles

    for role in roles:
        try:
            use_exact = (role == 'tab')
            locator = search_context.get_by_role(role, name=name, exact=use_exact)
            count = await locator.count()
            if count > 0:
                for i in range(count):
                    element = locator.nth(i)
                    if await element.is_visible():
                        print(f"        [HOVER] Hovering '{name}' as {role}")
                        await element.hover(timeout=5000, force=True)
                        await page.wait_for_timeout(500)  # Wait for menu animation

                        # Capture ARIA after hover
                        aria_after = await page.locator('body').aria_snapshot()

                        # Check if hover revealed navigation structure
                        revealed, reason = hover_revealed_content(aria_before, aria_after)
                        if revealed:
                            print(f"        [HOVER] Menu revealed! ({reason})")
                        else:
                            print(f"        [HOVER] No new content revealed")

                        # Check menu state if context provided
                        if menu_ctx:
                            await check_and_restore_menu(page, menu_ctx)

                        return revealed, aria_after
        except Exception as e:
            print(f"        [HOVER] Error with {role}: {e}")
            continue

    # Try <summary> elements as fallback (used by <details> pattern)
    # First close any open dropdowns that might be blocking
    # Try :has-text fallback (for hidden "fallback-text" patterns)
    try:
        text_locator = search_context.locator(f'button:has-text("{name}")')
        count = await text_locator.count()
        if count > 0:
            for i in range(count):
                element = text_locator.nth(i)
                if await element.is_visible():
                    print(f"        [HOVER] Hovering '{name}' via :has-text")
                    await element.hover(timeout=5000, force=True)
                    await page.wait_for_timeout(500)

                    aria_after = await page.locator('body').aria_snapshot()
                    revealed, reason = hover_revealed_content(aria_before, aria_after)
                    if revealed:
                        print(f"        [HOVER] Menu revealed! ({reason})")
                    else:
                        print(f"        [HOVER] No new content revealed")

                    if menu_ctx:
                        await check_and_restore_menu(page, menu_ctx)
                    return revealed, aria_after
    except Exception as e:
        print(f"        [HOVER] :has-text error: {e}")

    try:
        await page.keyboard.press('Escape')
        await page.wait_for_timeout(100)
    except:
        pass

    try:
        # Prefer header summary elements to avoid footer/mobile nav duplicates
        summary = search_context.locator(f'header summary[aria-label="{name}"], header summary:has-text("{name}")')
        count = await summary.count()
        if count == 0:
            summary = search_context.locator(f'summary[aria-label="{name}"], summary:has-text("{name}")')
            count = await summary.count()

        if count > 0:
            for i in range(count):
                element = summary.nth(i)
                if await element.is_visible():
                    print(f"        [HOVER] Hovering '{name}' as summary")
                    await element.hover(timeout=5000, force=True)
                    await page.wait_for_timeout(500)

                    aria_after = await page.locator('body').aria_snapshot()
                    revealed, reason = hover_revealed_content(aria_before, aria_after)
                    if revealed:
                        print(f"        [HOVER] Menu revealed! ({reason})")
                    else:
                        print(f"        [HOVER] No new content revealed")

                    # Check menu state if context provided
                    if menu_ctx:
                        await check_and_restore_menu(page, menu_ctx)

                    return revealed, aria_after
    except Exception as e:
        print(f"        [HOVER] Error with summary: {e}")

    print(f"        [HOVER] Could not find '{name}' to hover")
    return False, aria_before


async def find_expanded_region(page: Page, name: str):
    """Find the expanded menu region/container after clicking an item."""
    # Try various container patterns
    for role in ['region', 'menu', 'dialog', 'navigation']:
        try:
            locator = page.get_by_role(role, name=name, exact=False)
            if await locator.count() > 0:
                return locator.first
        except:
            continue

    # Try aria-expanded pattern
    try:
        expanded = page.locator(f'[aria-expanded="true"]').first
        if await expanded.count() > 0:
            # Look for adjacent or child content
            sibling = expanded.locator('~ *').first
            if await sibling.count() > 0:
                return sibling
    except:
        pass

    return None


async def find_menu_elements(page: Page) -> list[dict]:
    """
    Scan HTML for any elements with menu-related keywords in their attributes.
    Returns list of candidate elements with metadata.
    """
    script = """
    () => {
        const menuKeywords = ['menu', 'nav', 'drawer', 'hamburger', 'toggle'];
        const avoidKeywords = ['search', 'cart', 'account', 'wishlist', 'currency', 'language', 'country', 'ship'];
        const results = [];

        // Scan all elements in header area
        const headerEls = document.querySelectorAll('header *, nav *, [role="banner"] *');

        for (const el of headerEls) {
            // Skip non-interactive elements
            const tag = el.tagName.toLowerCase();
            if (!['a', 'button', 'div', 'span', 'label'].includes(tag)) continue;

            // Check if element has menu-related attributes
            let menuScore = 0;
            let avoidScore = 0;
            const attrs = {};

            for (const attr of el.attributes) {
                const name = attr.name.toLowerCase();
                const value = attr.value.toLowerCase();
                attrs[name] = attr.value;

                for (const kw of menuKeywords) {
                    if (name.includes(kw) || value.includes(kw)) {
                        menuScore++;
                    }
                }
                for (const kw of avoidKeywords) {
                    if (name.includes(kw) || value.includes(kw)) {
                        avoidScore++;
                    }
                }
            }

            // Also check text content
            const text = (el.textContent || '').toLowerCase().trim();
            if (text.length < 20) {  // Short text only
                for (const kw of menuKeywords) {
                    if (text.includes(kw)) menuScore++;
                }
                for (const kw of avoidKeywords) {
                    if (text.includes(kw)) avoidScore++;
                }
            }

            // Skip if it's clearly a utility element
            if (avoidScore > 0) continue;

            // Include if has menu indicators
            if (menuScore > 0) {
                const rect = el.getBoundingClientRect();
                results.push({
                    tag: tag,
                    text: text.slice(0, 30),
                    attrs: attrs,
                    menuScore: menuScore,
                    visible: el.offsetParent !== null && rect.width > 0,
                    width: rect.width,
                    height: rect.height,
                    hasSvg: el.querySelector('svg') !== null,
                    hasImg: el.querySelector('img') !== null,
                    // Build a unique selector
                    selector: el.id ? '#' + el.id
                        : attrs['data-menu-drawer'] !== undefined ? '[data-menu-drawer]'
                        : attrs['data-drawer-id'] ? `[data-drawer-id="${attrs['data-drawer-id']}"]`
                        : attrs['data-action'] && attrs['data-action'].includes('menu') ? `[data-action="${attrs['data-action']}"]`
                        : attrs['class'] ? '.' + attrs['class'].split(' ')[0]
                        : null
                });
            }
        }

        // Sort by menu score (highest first), then prefer icon-sized elements
        results.sort((a, b) => {
            if (b.menuScore !== a.menuScore) return b.menuScore - a.menuScore;
            // Prefer smaller (icon-sized) elements
            const aSize = a.width * a.height;
            const bSize = b.width * b.height;
            return aSize - bSize;
        });

        return results.slice(0, 10);  // Top 10 candidates
    }
    """
    try:
        return await page.evaluate(script)
    except:
        return []


async def open_menu(page: Page) -> bool:
    """
    Try to open the navigation menu.
    1. Extract menu candidates (elements with menu keywords) and all buttons
    2. Ask LLM to identify the menu toggle from both lists
    3. If clicking navigates away, go back and try hover instead
    4. Fall back to hardcoded selectors if LLM fails
    Returns True if menu was opened.
    """
    base_url = page.url
    avoid_patterns = ['ship', 'location', 'country', 'region', 'language', 'currency', 'search', 'cart']

    async def is_distraction(el) -> bool:
        """Check if element is a utility selector (not main nav)."""
        try:
            text = (await el.text_content() or '').lower()
            label = (await el.get_attribute('aria-label') or '').lower()
            for pattern in avoid_patterns:
                if pattern in text or pattern in label:
                    return True
        except:
            pass
        return False

    async def try_hover_then_click(el, description: str) -> bool:
        """Try hover first (non-destructive), if no substantial diff then click."""
        nonlocal base_url

        # Capture ARIA before interaction
        try:
            aria_before = await page.locator('body').aria_snapshot()
        except:
            aria_before = ""

        # FIRST: Try hover (non-destructive)
        try:
            await el.hover()
            await page.wait_for_timeout(400)

            # Check if hover revealed SUBSTANTIAL content (not just a popup)
            aria_after = await page.locator('body').aria_snapshot()
            before_lines = set(aria_before.split('\n'))
            after_lines = aria_after.split('\n')
            new_lines = [l for l in after_lines if l not in before_lines]

            # Require at least 10 new lines with links/buttons (real menu content)
            menu_indicators = sum(1 for l in new_lines if 'link' in l.lower() or 'button' in l.lower())
            if menu_indicators >= 5:
                print(f"    [NAV] Hover opened menu: {description} ({menu_indicators} nav items)")
                return True
            elif new_lines:
                print(f"    [NAV] Hover caused small diff ({len(new_lines)} lines, {menu_indicators} nav items) - not a menu")
        except Exception as e:
            print(f"    [NAV] Hover failed: {e}")

        # SECOND: Hover didn't work, try click
        try:
            await el.click()
            await page.wait_for_timeout(500)
            print(f"    [NAV] Clicked: {description}")
            return True
        except Exception as e:
            print(f"    [NAV] Click failed: {description} - {e}")
            return False

    # PHASE 1: Extract both menu candidates and all buttons
    print("    [NAV] Scanning for menu elements and buttons...")
    candidates = await find_menu_elements(page)
    buttons = await extract_header_buttons(page)

    print(f"    [NAV] Found {len(candidates)} menu candidates, {len(buttons)} buttons")

    # PHASE 2: Ask LLM to identify menu from combined list
    if candidates or buttons:
        prompt = prompt_identify_menu_button(candidates, buttons)
        llm = _get_llm_handler()
        result = llm.call_text(prompt, max_tokens=50, operation="identify_menu_button")
        _track_llm_result(result)

        response = result.get('response', '')
        parsed = parse_menu_button_response(response)

        if parsed:
            elem_type, idx = parsed

            # Get the actual name for better logging
            identified_name = f"{elem_type}{idx}"
            if elem_type == 'C' and idx < len(candidates):
                c = candidates[idx]
                identified_name = c.get('selector', f"C{idx}")
            elif elem_type == 'B' and idx < len(buttons):
                btn = buttons[idx]
                identified_name = btn.get('text') or btn.get('aria_label') or f"B{idx}"

            print(f"    [NAV] LLM identified: {identified_name}")

            try:
                if elem_type == 'C' and idx < len(candidates):
                    # Try menu candidate by selector
                    c = candidates[idx]
                    selector = c.get('selector')
                    if selector:
                        el = page.locator(selector).first
                        if await el.is_visible():
                            if await try_hover_then_click(el, f"candidate {selector}"):
                                # Get aria-controls to know what element this button controls
                                controls_id = await el.get_attribute('aria-controls')
                                _cache_menu_button(selector, 'click', controls_id)
                                return True

                elif elem_type == 'B' and idx < len(buttons):
                    # Try button by text or aria-label
                    btn = buttons[idx]
                    text = btn.get('text', '').strip()
                    aria = btn.get('aria_label', '')
                    tag = btn.get('tag', 'button')

                    if text:
                        btn_selector = f'{tag}:has-text("{text}")'
                        el = page.locator(btn_selector).first
                    elif aria:
                        btn_selector = f'[aria-label="{aria}"]'
                        el = page.locator(btn_selector).first
                    else:
                        # Icon-only button with no aria - use nth
                        btn_selector = f'{tag}:has(svg)'
                        el = page.locator(btn_selector).nth(idx)

                    if await el.is_visible():
                        if await try_hover_then_click(el, f"button \"{text or aria or '(icon)'}\""):
                            # Get aria-controls to know what element this button controls
                            controls_id = await el.get_attribute('aria-controls')
                            _cache_menu_button(btn_selector, 'click', controls_id)
                            return True

            except Exception as e:
                print(f"    [NAV] Failed to interact with LLM choice: {e}")
        else:
            print(f"    [NAV] LLM found no menu (response: {response.strip()})")

    # PHASE 3: Fallback to common hardcoded selectors
    print("    [NAV] Falling back to common selectors...")
    fallback_selectors = [
        # Explicit menu buttons
        'button:has-text("menu")',
        'button:has-text("Menu")',
        '[aria-label*="menu" i]',
        '[aria-label*="navigation" i]',
        # Common class patterns
        '.hamburger',
        '.menu-toggle',
        '[class*="hamburger"]',
        '[class*="menu-button"]',
        '[class*="nav-toggle"]',
        '[class*="menu-btn"]',
        # Header buttons/links with SVG icons (likely hamburger)
        'header a:has(svg)',
        'header button:has(svg)',
        # Generic header button (last resort)
        'header button:not([aria-label*="search" i]):not([aria-label*="cart" i])',
    ]

    for selector in fallback_selectors:
        try:
            elements = await page.locator(selector).all()
            for el in elements:
                if await el.is_visible() and not await is_distraction(el):
                    print(f"    [NAV] Opening menu with fallback: {selector}")
                    # Get aria-controls before clicking
                    controls_id = await el.get_attribute('aria-controls')
                    # Try hover first, then click if hover doesn't reveal menu
                    if await try_hover_then_click(el, selector):
                        _cache_menu_button(selector, 'click', controls_id)
                        return True
        except:
            continue

    print("    [NAV] Could not find menu trigger")
    return False


async def is_hamburger_menu_open(page: Page, hamburger_name: str, base_url: str = None) -> bool:
    """
    Check if hamburger menu is currently open.

    Uses multiple signals:
    1. URL changed from base_url → definitely navigated away (menu closed)
    2. Hamburger button aria-expanded="true" → menu open
    3. Hamburger button aria-expanded="false" → menu closed
    4. Close button visible → menu open
    5. Default: assume open if URL unchanged (accordion expansion)
    """
    # If URL changed from base, we definitely navigated away
    if base_url:
        current_url = page.url.rstrip('/')
        base_clean = base_url.rstrip('/')
        if current_url != base_clean:
            print(f"        [MENU-CHECK] URL changed: {current_url} != {base_clean} - navigated away")
            return False

    # Check hamburger button's aria-expanded state
    try:
        for role in ['button', 'tab']:
            locator = page.get_by_role(role, name=hamburger_name, exact=False)
            if await locator.count() > 0:
                element = locator.first
                if await element.is_visible():
                    expanded = await element.get_attribute('aria-expanded')
                    if expanded == 'true':
                        return True
                    elif expanded == 'false':
                        return False
    except:
        pass

    # Check for close button (common in open hamburger menus)
    close_selectors = [
        'button[aria-label*="close" i]',
        'button[aria-label*="Close" i]',
        'button:has-text("Close")',
        'button:has-text("✕")',
        'button:has-text("×")',
        '[class*="close"]',
    ]
    for selector in close_selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0 and await locator.is_visible():
                return True
        except:
            pass

    # Default: assume OPEN if URL unchanged (likely accordion expansion within menu)
    return True


def detect_back_button_in_aria(aria_content: str) -> dict | None:
    """
    Detect back button patterns in ARIA content (e.g., from a diff).

    Returns dict with {name, role, line} if found, None otherwise.
    This is faster than DOM querying and works on diff content.
    """
    # Patterns that indicate a back button in ARIA
    # Format: - role "name" or - role "name": with optional attributes
    back_patterns = [
        # Direct text matches
        r'- (button|link) "(?:back|Back|BACK|← .*|‹ .*|< .*)"',
        r'- (button|link) "(?:.*[Bb]ack.*)"',
        r'- (button|link) "(?:return|Return|RETURN)"',
        r'- (button|link) "(?:previous|Previous|PREVIOUS)"',
        # With icon/SVG - button followed by navigation text (e.g., "- button 'VALENTINE'S DAY'" with left arrow)
        r'- (button) "(.*)" \[aria-label="?(?:back|go back|return|previous)"?\]',
        # Buttons that likely have a left arrow/chevron (SVG) but show category name
        # These are tricky - we detect via context (button with same name as parent menu item)
    ]

    lines = aria_content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        for pattern in back_patterns:
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                role = match.group(1)
                name = match.group(2) if len(match.groups()) > 1 else None
                return {
                    'name': name,
                    'role': role,
                    'line': stripped,
                    'line_number': i
                }

        # Also check for common back indicators in button names
        if '- button "' in stripped or '- link "' in stripped:
            name_match = re.search(r'- (button|link) "([^"]+)"', stripped)
            if name_match:
                role = name_match.group(1)
                name = name_match.group(2)
                # Check if name contains back indicators
                back_indicators = ['back', 'return', 'previous', '←', '‹', '<', 'chevron-left']
                if any(ind.lower() in name.lower() for ind in back_indicators):
                    return {
                        'name': name,
                        'role': role,
                        'line': stripped,
                        'line_number': i
                    }

    return None


def detect_back_button_by_context(aria_content: str, current_item_name: str) -> dict | None:
    """
    Detect back button by context: a button with same name as current item.

    When clicking "VALENTINE'S DAY" opens a submenu, the back button is often
    a button labeled "VALENTINE'S DAY" with a left chevron SVG.

    Args:
        aria_content: ARIA content to search
        current_item_name: Name of the item we just clicked (e.g., "VALENTINE'S DAY")

    Returns dict with {name, role, line} if found, None otherwise.
    """
    if not current_item_name:
        return None

    # Look for a button with the same name as what we clicked
    # This is likely a "back" button showing current submenu title
    pattern = rf'- (button) "{re.escape(current_item_name)}"'

    lines = aria_content.split('\n')
    for i, line in enumerate(lines):
        if re.search(pattern, line, re.IGNORECASE):
            return {
                'name': current_item_name,
                'role': 'button',
                'line': line.strip(),
                'line_number': i,
                'detected_by': 'context'  # Mark how we found it
            }

    return None


async def find_back_button(page: Page) -> str | None:
    """
    Look for a back button. Returns selector string if found, None otherwise.
    Prioritizes specific data attributes and SVG patterns over generic aria-label.
    """
    selectors = [
        # Data attributes (most specific, check first)
        '[data-ref*="return" i]',
        '[data-ref*="back" i]',
        '[data-action*="back" i]',
        '[data-action*="return" i]',
        # SVG with left chevron/arrow (common back button pattern in menus)
        'button:has(svg[class*="chevron-left"])',
        'button:has(svg[class*="arrow-left"])',
        'button:has(svg[class*="-left"])',
        'button:has(svg[class*="back"])',
        # Aria-based (only buttons to avoid matching product links with "back" in name)
        'button[aria-label*="back" i]',
        'button[aria-label*="previous" i]',
        'button[aria-label*="go back" i]',
        'button[aria-label*="return" i]',
        # Text-based
        'button:has-text("back")',
        'button:has-text("Back")',
        'button:has-text("previous")',
        'button:has-text("←")',
        'button:has-text("‹")',
        'button:has-text("<")',
        # Role + name
        '[role="button"][name*="back" i]',
        # Class patterns
        'button.back-button',
        'button.btn-back',
        'button[class*="-back"]',
        'button[class*="back-"]',
        # Link-based back buttons (last resort)
        'a[class*="back"]',
        'a:has(svg[class*="chevron-left"])',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                # Skip visibility check - element may be "not visible" due to overlay
                # We'll use force=True when clicking
                return selector
        except:
            continue
    return None


async def click_back_at_level(page: Page, level: int, back_buttons: dict) -> bool:
    """
    Go back one level using stored back button or by finding one.
    back_buttons: {level: selector} - passed in, not global
    """
    # If we already know the back button for this level, use it
    if level in back_buttons:
        selector = back_buttons[level]
        try:
            await page.locator(selector).first.click()
            await page.wait_for_timeout(400)
            return True
        except:
            # Stored selector didn't work, remove it
            del back_buttons[level]

    # Try to find a back button
    selector = await find_back_button(page)
    if selector:
        # Found it! Store for future use at this level
        back_buttons[level] = selector
        print(f"    [NAV] Found back button at level {level}: {selector}")
        try:
            await page.locator(selector).first.click()
            await page.wait_for_timeout(400)
            return True
        except:
            return False

    return False


async def try_click_with_url_check(page: Page, name: str, container=None, prefer_tab: bool = False, skip_url_check: bool = False, prefer_role: str = None, parent_menu: str = None) -> tuple[bool, bool]:
    """
    Try to click an element and check if URL changed.
    Returns: (clicked: bool, navigated_away: bool)

    skip_url_check: For top-level tabs, URL may change but content updates in-place.
                    Set True to accept URL changes without going back.
    parent_menu: If set, look for element inside this menu first (e.g., "Men" inside "Sales" dropdown)
    """
    url_before = page.url
    clicked = await click_button(page, name, container, prefer_tab=prefer_tab, prefer_role=prefer_role, parent_menu=parent_menu)
    if clicked:
        print(f"      [CLICK] Successfully clicked '{name}'")
        # Extra wait for menu animations
        await page.wait_for_timeout(300)

        if skip_url_check:
            # For tabs, URL change is expected, don't treat as navigation
            return True, False

        url_after = page.url
        if url_after != url_before:
            await page.go_back()
            await wait_for_page_ready(page)
            return True, True  # Clicked but navigated away
        return True, False  # Clicked successfully, stayed on page
    print(f"      [CLICK] Could not find '{name}'")
    return False, False  # Could not click


# Navigation strategies
STRATEGY_DIRECT = 'direct'           # Element is directly clickable
STRATEGY_BACK_BUTTON = 'back_button' # Need to click back button first
STRATEGY_RECLICK_PARENT = 'reclick'  # Need to re-click parent to reveal
STRATEGY_RESET = 'reset'             # Need full menu reset


async def navigate_to_path(page: Page, path: list, current_path: list,
                           back_buttons: dict, level_strategies: dict,
                           base_url: str, target_type: str = None) -> tuple[bool, bool]:
    """
    Navigate from current_path to target path using tree navigation.

    Algorithm:
    1. Try clicking the final target directly (handles visible siblings)
    2. If fails, calculate common ancestor between current and target
    3. Go UP from current to common ancestor (using back buttons)
    4. Go DOWN from common ancestor to target

    Args:
        path: Target path like ['Sales', 'Women']
        current_path: Where we are now like ['Sales', 'Men']
        back_buttons: Cache of {level: selector} for back buttons
        level_strategies: Unused, kept for compatibility
        base_url: Base URL for detecting navigation
        target_type: ARIA role of final target ('menuitem', 'tab', 'button')

    Returns: (success: bool, navigated_away: bool)
    """
    if not path:
        return True, False

    target = path[-1]
    prefer_role = target_type

    # Detect if level 0 is a toggle menu (hamburger)
    is_toggle_menu = len(path) > 0 and path[0].lower() in ['menu', 'hamburger', 'nav', 'navigation']

    # ==========================================================================
    # STEP 1: Try clicking the final target directly
    # This handles the common case where siblings are visible in the same dropdown
    # ==========================================================================

    # Determine parent_menu for scoping the search
    parent_menu = path[-2] if len(path) >= 2 else None
    prefer_tab = (len(path) == 1)  # Top-level items are often tabs
    skip_url_check = prefer_tab

    clicked, navigated = await try_click_with_url_check(
        page, target,
        prefer_tab=prefer_tab,
        skip_url_check=skip_url_check,
        prefer_role=prefer_role,
        parent_menu=parent_menu
    )

    if navigated:
        return False, True
    if clicked:
        print(f"    [NAV] Direct click succeeded for '{target}'")
        return True, False

    # ==========================================================================
    # STEP 2: Direct click failed - calculate tree navigation
    # ==========================================================================

    print(f"    [NAV] Direct click failed for '{target}', navigating via tree...")

    # Find common ancestor length
    common_len = 0
    for i in range(min(len(path), len(current_path))):
        if path[i].lower() == current_path[i].lower():
            common_len += 1
        else:
            break

    levels_up = len(current_path) - common_len

    print(f"    [NAV] Current: {current_path}, Target: {path}")
    print(f"    [NAV] Common ancestor depth: {common_len}, Need to go up: {levels_up} level(s)")

    # ==========================================================================
    # STEP 3: Go UP from current position to common ancestor
    # ==========================================================================

    if levels_up > 0:
        for level_idx in range(levels_up):
            # Calculate actual menu level we're going back FROM
            current_depth = len(current_path) - level_idx

            # Check if we have a cached back button for this level
            back_selector = back_buttons.get(current_depth)

            if not back_selector:
                # Find and cache the back button
                back_selector = await find_back_button(page)
                if back_selector:
                    back_buttons[current_depth] = back_selector
                    print(f"    [NAV] Cached back button for level {current_depth}: {back_selector}")

            if back_selector:
                try:
                    locator = page.locator(back_selector)
                    count = await locator.count()
                    clicked_back = False
                    for idx in range(count):
                        element = locator.nth(idx)
                        if await element.is_visible():
                            await element.click()
                            await page.wait_for_timeout(400)
                            print(f"    [NAV] Clicked back button (level {level_idx + 1}/{levels_up})")
                            clicked_back = True
                            break
                    if not clicked_back:
                        print(f"    [NAV] Back button not visible, resetting menu")
                        await page.keyboard.press('Escape')
                        await page.wait_for_timeout(300)
                        common_len = 0
                        break
                except Exception as e:
                    print(f"    [NAV] Back button error: {e}, resetting menu")
                    await page.keyboard.press('Escape')
                    await page.wait_for_timeout(300)
                    common_len = 0
                    break
            else:
                print(f"    [NAV] No back button found, resetting menu")
                await page.keyboard.press('Escape')
                await page.wait_for_timeout(300)
                common_len = 0
                break

    # ==========================================================================
    # STEP 4: Go DOWN from common ancestor to target
    # ==========================================================================

    for i in range(common_len, len(path)):
        element_name = path[i]

        # Skip toggle menu at level 0 if already open
        if is_toggle_menu and i == 0 and common_len == 0:
            # Need to open the toggle menu first
            pass  # Don't skip, we need to click it

        # Determine click parameters for this level
        level_prefer_tab = (i == 0)
        level_skip_url_check = level_prefer_tab
        level_prefer_role = prefer_role if (i == len(path) - 1) else None
        level_parent_menu = path[i-1] if i > 0 else None

        clicked, navigated = await try_click_with_url_check(
            page, element_name,
            prefer_tab=level_prefer_tab,
            skip_url_check=level_skip_url_check,
            prefer_role=level_prefer_role,
            parent_menu=level_parent_menu
        )

        if navigated:
            return False, True

        if not clicked:
            print(f"    [NAV] Failed to click '{element_name}' at level {i}")

            # Last resort: full reset and try from root
            if common_len > 0 or i > 0:
                print(f"    [NAV] Full reset and retry from root...")
                await page.keyboard.press('Escape')
                await page.wait_for_timeout(300)

                # Try clicking entire path from root
                for j in range(len(path)):
                    j_prefer_tab = (j == 0)
                    j_skip_url_check = j_prefer_tab
                    j_prefer_role = prefer_role if (j == len(path) - 1) else None
                    j_parent_menu = path[j-1] if j > 0 else None

                    clicked, navigated = await try_click_with_url_check(
                        page, path[j],
                        prefer_tab=j_prefer_tab,
                        skip_url_check=j_skip_url_check,
                        prefer_role=j_prefer_role,
                        parent_menu=j_parent_menu
                    )

                    if navigated:
                        return False, True
                    if not clicked:
                        print(f"    [NAV] Failed to click '{path[j]}' even after reset")
                        return False, False

                return True, False

            return False, False

    return True, False


# =============================================================================
# State capture
# =============================================================================

async def capture_state(page: Page, path: list, action: str, step: int,
                        new_buttons: set | dict = None, new_links: dict = None,
                        capture_screenshot: bool = False) -> dict:
    """Capture current state after an action."""
    try:
        aria = await asyncio.wait_for(page.locator('body').aria_snapshot(), timeout=10.0)
    except asyncio.TimeoutError:
        print("    [WARN] ARIA snapshot timed out, using header only")
        try:
            aria = await asyncio.wait_for(page.locator('header').aria_snapshot(), timeout=5.0)
        except:
            aria = ""

    screenshot_b64 = None
    if capture_screenshot:
        screenshot = await page.screenshot()
        screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')

    # Handle new_buttons as either set or dict {name: type}
    if new_buttons:
        if isinstance(new_buttons, dict):
            buttons_list = list(new_buttons.keys())
        else:
            buttons_list = list(new_buttons)
    else:
        buttons_list = []

    return {
        'step': step,
        'timestamp': datetime.now().isoformat(),
        'path': path.copy(),
        'action': action,
        'aria': aria,
        'screenshot_b64': screenshot_b64,
        'url': page.url,
        'new_buttons': buttons_list,
        'new_links': new_links if new_links else {}
    }


# =============================================================================
# Structured exploration for toggle menus
# =============================================================================

async def expand_all_collapsed(page: Page) -> int:
    """
    Expand all collapsed sections in the menu.
    Clicks buttons with aria-expanded="false" or expand icons.
    Returns number of sections expanded.
    """
    expanded_count = 0

    # Find all collapsed buttons (aria-expanded="false")
    try:
        collapsed = page.locator('button[aria-expanded="false"], [role="button"][aria-expanded="false"]')
        count = await collapsed.count()
        for i in range(count):
            try:
                btn = collapsed.nth(i)
                if await btn.is_visible():
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(200)
                    expanded_count += 1
            except:
                pass
    except:
        pass

    # Also try clicking buttons with plus/expand icons
    expand_selectors = [
        'button:has(svg[class*="plus"])',
        'button:has(svg[class*="expand"])',
        'button:has(svg[class*="toggle"])',
        '[class*="accordion"]:not([class*="open"]) button',
        '[class*="collapsible"]:not([class*="open"]) button',
    ]
    for selector in expand_selectors:
        try:
            buttons = page.locator(selector)
            count = await buttons.count()
            for i in range(min(count, 10)):  # Limit to avoid infinite loops
                try:
                    btn = buttons.nth(i)
                    if await btn.is_visible():
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(200)
                        expanded_count += 1
                except:
                    pass
        except:
            pass

    return expanded_count


async def explore_toggle_menu(page: Page, menu_structure: dict, states: list, step: int,
                               menu_button_name: str, base_url: str) -> int:
    """
    Explore a hamburger/toggle menu by clicking each accordion and capturing new links.

    Simple approach:
    1. Open menu, expand all collapsed sections
    2. Capture base links
    3. For each accordion: click it, capture NEW links via set difference
    4. Done - no need to click the revealed links
    """
    top_level = menu_structure.get('top_level', [])
    menu_links = menu_structure.get('links', [])

    print(f"\n[HAMBURGER MENU] Exploring:")
    print(f"    Accordions: {[item['name'] for item in top_level]}")
    print(f"    Base links: {[item['name'] for item in menu_links]}")

    # Capture initial menu state (links visible when menu first opens)
    aria = await page.locator('body').aria_snapshot()
    all_links = extract_links_from_aria(aria)
    all_links = filter_utility_links(all_links)

    # Match LLM-identified menu links to actual URLs
    if menu_links:
        base_links = {}
        for item in menu_links:
            link_name = item['name']
            if link_name in all_links:
                base_links[link_name] = all_links[link_name]
            else:
                # Case-insensitive match
                for aria_name, aria_url in all_links.items():
                    if aria_name.lower() == link_name.lower():
                        base_links[link_name] = aria_url
                        break

        if base_links:
            print(f"\n    Captured {len(base_links)} base menu links:")
            state = await capture_state(page, ["Menu"], "menu_opened", step)
            state['new_links'] = base_links
            states.append(state)
            step += 1
            for name, url in base_links.items():
                print(f"      [LNK] {name} → {url}")

    # Track all links we've seen (to compute set difference)
    seen_links = set(all_links.values())

    # Click each accordion and capture NEW links
    for tl_item in top_level:
        tl_name = tl_item['name']
        print(f"\n[{step}] ACCORDION: {tl_name}")

        # ALWAYS refresh and re-open menu before each accordion
        # This ensures clean state - previous accordion clicks may have changed things
        await page.goto(base_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(500)
        await click_button(page, menu_button_name)
        await page.wait_for_timeout(500)

        # Capture links BEFORE clicking this accordion
        aria_before = await page.locator('body').aria_snapshot()
        links_before = extract_links_from_aria(aria_before)
        links_before = filter_utility_links(links_before)
        urls_before = set(links_before.values())

        # Click the accordion
        clicked = await click_button(page, tl_name)
        if not clicked:
            print(f"    Failed to click {tl_name}, skipping...")
            continue

        await page.wait_for_timeout(400)

        # Check if we navigated away (URL changed)
        menu_open = await is_hamburger_menu_open(page, menu_button_name, base_url)
        if not menu_open:
            print(f"    [LINK] '{tl_name}' navigated to {page.url}")
            state = await capture_state(page, [tl_name], f"link: {tl_name}", step)
            state['new_links'] = {tl_name: page.url}
            states.append(state)
            step += 1
            continue

        # Accordion expanded - capture NEW links
        aria_after = await page.locator('body').aria_snapshot()
        links_after = extract_links_from_aria(aria_after)
        links_after = filter_utility_links(links_after)

        # Set difference: new links = links that weren't there before clicking this accordion
        # Don't filter by seen_links - each accordion should show what IT reveals
        new_links = {name: url for name, url in links_after.items()
                     if url not in urls_before}

        if new_links:
            print(f"    [EXPANDED] Revealed {len(new_links)} new links:")
            state = await capture_state(page, [tl_name], f"accordion: {tl_name}", step)
            state['new_links'] = new_links
            states.append(state)
            step += 1
            for name, url in new_links.items():
                print(f"      [LNK] {name} → {url}")
            # Add to seen links
            seen_links.update(new_links.values())
        else:
            print(f"    [NO CHANGE] No new links revealed")

    return step


# =============================================================================
# Tab-based exploration (new unified approach)
# =============================================================================

def get_new_content(aria_before: str, aria_after: str) -> tuple[str, str | None]:
    """
    Extract only NEW lines that appeared after an interaction.
    Returns tuple of (diff_string, parent_context).

    parent_context is the link at a shallower indent level than the first new content
    (the parent container that holds the new content).
    """
    before_lines = set(aria_before.split('\n'))
    after_lines = aria_after.split('\n')

    # Find first new line and its parent by indentation
    parent_context = None
    for i, line in enumerate(after_lines):
        if line not in before_lines:
            new_indent = len(line) - len(line.lstrip())
            # Look backwards for a link at same or shallower indent
            for j in range(i - 1, -1, -1):
                prev_line = after_lines[j]
                prev_indent = len(prev_line) - len(prev_line.lstrip())
                if prev_indent <= new_indent and 'link "' in prev_line:
                    parent_context = prev_line
                    break
            break

    # Keep only lines that weren't there before
    new_lines = [line for line in after_lines if line not in before_lines]
    return '\n'.join(new_lines), parent_context


def get_content_diff(aria_before: str, aria_after: str) -> dict:
    """
    Get both positive (added) and negative (removed) content changes.

    Returns dict with:
        - added: str - lines that appeared
        - removed: str - lines that disappeared
        - added_count: int - number of interactive elements added
        - removed_count: int - number of interactive elements removed
        - is_replacement: bool - True if content was replaced (submenu navigation)
    """
    before_lines = set(aria_before.split('\n'))
    after_lines = set(aria_after.split('\n'))

    added = [line for line in after_lines if line not in before_lines]
    removed = [line for line in before_lines if line not in after_lines]

    def count_interactive(lines):
        return sum(
            1 for line in lines
            if any(kw in line.lower() for kw in ['link', 'button', 'menuitem', 'tab'])
        )

    added_count = count_interactive(added)
    removed_count = count_interactive(removed)

    # Content replacement: significant elements both added AND removed
    is_replacement = added_count >= 3 and removed_count >= 3

    return {
        'added': '\n'.join(added),
        'removed': '\n'.join(removed),
        'added_count': added_count,
        'removed_count': removed_count,
        'is_replacement': is_replacement
    }


async def group_buttons_by_css(page: Page, menu_selector: str = None) -> dict:
    """
    Group buttons in the menu by their CSS class/parent structure.
    Returns dict of {group_key: [button_names]}
    """
    try:
        # Determine container - use Playwright locator for non-CSS selectors
        if menu_selector and ('>>' in menu_selector or menu_selector.startswith('role=')):
            # Playwright-style selector - use locator and evaluate within it
            container = page.locator(menu_selector).first
            if await container.count() == 0:
                return {}
            result = await container.evaluate('''(el) => {
                const buttons = el.querySelectorAll('button');
                const groups = {};

                for (const btn of buttons) {
                    const text = btn.textContent.trim();
                    if (!text || text.length > 50) continue;

                    const parent = btn.parentElement;
                    if (!parent) continue;

                    let groupKey = parent.className || parent.tagName.toLowerCase();
                    const classes = groupKey.split(' ').filter(c => c && !c.includes('--'));
                    groupKey = classes[0] || parent.tagName.toLowerCase();

                    if (!groups[groupKey]) {
                        groups[groupKey] = [];
                    }
                    groups[groupKey].push(text);
                }

                return groups;
            }''')
        else:
            # CSS selector or none - use page.evaluate
            result = await page.evaluate('''(menuSelector) => {
                const container = menuSelector ? document.querySelector(menuSelector) : document.body;
                if (!container) return {};

                const buttons = container.querySelectorAll('button');
                const groups = {};

                for (const btn of buttons) {
                    const text = btn.textContent.trim();
                    if (!text || text.length > 50) continue;

                    const parent = btn.parentElement;
                    if (!parent) continue;

                    let groupKey = parent.className || parent.tagName.toLowerCase();
                    const classes = groupKey.split(' ').filter(c => c && !c.includes('--'));
                    groupKey = classes[0] || parent.tagName.toLowerCase();

                    if (!groups[groupKey]) {
                        groups[groupKey] = [];
                    }
                    groups[groupKey].push(text);
                }

                return groups;
            }''', menu_selector)

        # Filter out groups with only 1 button
        return {k: v for k, v in result.items() if len(v) > 1}

    except Exception as e:
        print(f"    [GROUP] Error grouping buttons: {e}")
        return {}


async def identify_main_menu_group(page: Page, groups: dict) -> list[str]:
    """
    Use LLM to identify which button group is the main navigation menu.
    Returns list of button names from the main menu group.
    """
    if not groups:
        return []

    # Build prompt
    group_list = []
    for i, (key, buttons) in enumerate(groups.items()):
        group_list.append(f"Group {i+1}: {buttons}")

    prompt = f"""Look at these groups of buttons from a website menu. Which group contains the main product category navigation (like Women, Men, Clothing, Shoes)?

{chr(10).join(group_list)}

Reply with just the group number (e.g., "2") or "NONE" if no group is the main menu.
IMPORTANT: Ignore groups that are clearly utility buttons (language, country, currency selectors)."""

    try:
        llm = _get_llm_handler()
        result = llm.call_text(prompt, max_tokens=50, operation="identify_main_menu_group")
        _track_llm_result(result)
        response = result.get('response', '').strip()

        # Parse response
        if 'NONE' in response.upper():
            return []

        # Extract number
        import re
        match = re.search(r'(\d+)', response)
        if match:
            group_num = int(match.group(1))
            keys = list(groups.keys())
            if 1 <= group_num <= len(keys):
                main_group = groups[keys[group_num - 1]]
                print(f"    [GROUP] LLM selected group {group_num}: {main_group}")
                return main_group

    except Exception as e:
        print(f"    [GROUP] LLM error: {e}")

    # Fallback: return largest group
    if groups:
        largest = max(groups.values(), key=len)
        print(f"    [GROUP] Fallback to largest group: {largest}")
        return largest
    return []


def find_expandable_elements(aria: str) -> list[dict]:
    """
    Find elements that might reveal content when clicked.
    Returns list of {name, role, nearby_link, indent} for buttons, menuitems, tabs.

    The 'nearby_link' field contains the name of a link found near this button.
    The caller should use LLM to determine if the button expands that link's category
    or is a separate category itself.

    The 'indent' field is the ARIA indent level, used for caching LLM decisions
    per depth level (buttons at the same level behave consistently on a site).
    """
    expandables = []
    lines = aria.split('\n')

    # Track the most recent link at each indent level
    last_link_at_indent = {}  # indent -> link_name

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        # Check for link - track as potential nearby link for buttons
        link_match = re.search(r'link\s+"([^"]+)"', stripped, re.IGNORECASE)
        if link_match:
            link_name = link_match.group(1).strip()
            # Skip utility links
            skip_words = [
                'close', 'search', 'back', 'menu', 'hamburger', 'nav',
                'cart', 'bag', 'checkout', 'wishlist',
                'account', 'login', 'sign in', 'sign up', 'register',
                'usd', 'eur', 'gbp', 'cad', 'aud', 'currency', 'language', 'country',
                'info', 'about', 'contact', 'faq', 'help', 'support', 'subscribe',
                'store locator', 'size guide', 'shipping', 'returns',
            ]
            if not any(skip in link_name.lower() for skip in skip_words):
                last_link_at_indent[indent] = link_name
                # Also set for nearby indents (within 4 spaces)
                for nearby in range(indent - 4, indent + 5):
                    if nearby >= 0:
                        last_link_at_indent[nearby] = link_name

        # Match button, menuitem, tab (not link - those navigate away)
        for role in ['button', 'menuitem', 'tab']:
            pattern = rf'{role}\s+"([^"]+)"'
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Skip utility buttons
                skip_words = [
                    'close', 'search', 'back', 'menu', 'hamburger', 'nav', 'open',
                    'cart', 'bag', 'checkout', 'wishlist',
                    'account', 'login', 'sign in', 'sign up', 'register', 'my account',
                    'usd', 'eur', 'gbp', 'cad', 'aud', 'currency', 'language', 'country',
                    'info', 'about', 'contact', 'faq', 'help', 'support',
                    'store locator', 'size guide', 'shipping', 'returns',
                    'subscribe', 'newsletter', 'follow', 'instagram', 'facebook', 'tiktok',
                    'gift', 'gift card', 'rewards', 'loyalty',
                    'helpful links', 'banner',
                ]
                if any(skip in name.lower() for skip in skip_words):
                    continue
                if len(name) > 50:
                    continue

                # Find nearby link (at same or similar indent)
                nearby_link = last_link_at_indent.get(indent)

                expandables.append({
                    'name': name,
                    'role': role,
                    'nearby_link': nearby_link,
                    'indent': indent
                })
                break

    return expandables


async def classify_button_relationship(button_name: str, link_name: str) -> str:
    """
    Use LLM to determine if a button expands the nearby link's category,
    or is a separate category itself.

    Returns: 'EXPANDS' if button expands the link's category
             'SEPARATE' if button is its own category

    Examples:
    - ("See More", "CATEGORIES") → EXPANDS (button reveals more of that category)
    - ("Lingerie & Intimates", "Bikinis & Swimsuits") → SEPARATE (different categories)
    """
    prompt = f"""In a website navigation menu, there's a button "{button_name}" near a link "{link_name}".

Does this button EXPAND/SHOW MORE of the "{link_name}" category, or is it a SEPARATE category?

Answer with ONE word only:
- EXPANDS (if the button reveals more items within "{link_name}")
- SEPARATE (if "{button_name}" is its own distinct category)

Answer:"""

    try:
        llm = _get_llm_handler()
        result = llm.call_text(prompt, max_tokens=10, operation="classify_button")
        _track_llm_result(result)
        response = result.get('response', '').strip().upper()

        if 'EXPAND' in response:
            return 'EXPANDS'
        elif 'SEPARATE' in response:
            return 'SEPARATE'
        else:
            # Default to SEPARATE if unclear (safer - treats as unique item)
            print(f"    [LLM] Unclear response '{response}', defaulting to SEPARATE")
            return 'SEPARATE'

    except Exception as e:
        print(f"    [LLM] Error classifying button: {e}")
        return 'SEPARATE'


def prompt_bulk_extract(tab_name: str, aria: str) -> str:
    """Prompt for extracting all categories from a tab in one shot."""
    return f"""This is the "{tab_name}" section of a fashion website's navigation menu.
The site shows all categories at once (no hidden content).

Extract ALL product category links visible in this menu section.
Include both parent categories and subcategories.

ARIA SNAPSHOT:
{aria[:12000]}

RESPOND IN THIS EXACT FORMAT:
CATEGORIES:
- CategoryName: /url/path
- CategoryName: /url/path
- ParentCategory > SubCategory: /url/path

Only include product categories (clothing, shoes, accessories, etc).
Skip utility links (cart, account, search, etc).
"""


def parse_bulk_categories(response: str) -> dict:
    """
    Parse bulk extraction response into {name: url} dict.
    """
    categories = {}
    lines = response.split('\n')

    in_categories = False
    for line in lines:
        line = line.strip()

        if line.upper().startswith('CATEGORIES:'):
            in_categories = True
            continue

        if in_categories and line.startswith('-'):
            # Parse "- Name: /url" or "- Parent > Child: /url"
            content = line[1:].strip()
            if ':' in content:
                # Find last colon (URL might have colons in http://)
                parts = content.rsplit(':', 1)
                if len(parts) == 2:
                    name = parts[0].strip()
                    url = parts[1].strip()
                    if url and not url.startswith('#'):
                        categories[name] = url

    return categories


async def bulk_extract_tab(page: Page, tab: dict, tab_aria: str, base_url: str) -> dict:
    """
    Extract all categories from a tab in one LLM call.
    Used when site pre-loads everything (no show/hide behavior).

    Returns dict with extracted categories and metadata.
    """
    tab_name = tab['text']
    print(f"\n[BULK] Extracting all categories from '{tab_name}' in one call...")

    llm = _get_llm_handler()
    result = llm.call_text(
        prompt=prompt_bulk_extract(tab_name, tab_aria),
        max_tokens=2000,
        operation="bulk_extract_tab"
    )
    _track_llm_result(result)

    if not result.get('success'):
        print(f"    LLM call failed: {result.get('error')}")
        return {'tab': tab_name, 'categories': {}, 'mode': 'bulk', 'error': result.get('error')}

    response = result.get('response', '')
    categories = parse_bulk_categories(response)

    # Make URLs absolute
    from urllib.parse import urljoin
    for name, url in list(categories.items()):
        if url.startswith('/'):
            categories[name] = urljoin(base_url, url)

    print(f"    Extracted {len(categories)} categories:")
    for name, url in list(categories.items())[:10]:
        print(f"      [LNK] {name} → {url}")
    if len(categories) > 10:
        print(f"      ... and {len(categories) - 10} more")

    return {
        'tab': tab_name,
        'categories': categories,
        'mode': 'bulk',
        'llm_response': response
    }


async def dfs_explore_tab(
    page: Page,
    tab: dict,
    tab_aria: str,
    base_url: str,
    menu_ctx: Optional[MenuContext] = None
) -> dict:
    """
    DFS exploration of a tab, sending only ARIA diffs to LLM.
    Used when site reveals content on click/hover.

    Returns dict with all discovered categories.
    """
    tab_name = tab['text']
    print(f"\n[DFS] Exploring '{tab_name}' with diff-based extraction...")

    all_categories = {}
    states = []
    step = 0

    # Truncate ARIA at boundary to only include menu content
    boundary_marker = menu_ctx.boundary_marker if menu_ctx else None
    if boundary_marker:
        tab_aria = truncate_aria_at_boundary(tab_aria, boundary_marker)

    # Initialize with items visible under this tab
    initial_expandables = find_expandable_elements(tab_aria)
    initial_links = extract_links_from_aria(tab_aria)
    initial_links = filter_utility_links(initial_links)

    # Add initial links
    all_categories.update(initial_links)

    # Stack: (path, item_name, item_role)
    # Note: 'context' is for uniqueness only, not for building hierarchy paths
    def build_path(item):
        return [tab_name, item['name']]

    stack = [(build_path(item), item['name'], item['role'])
             for item in reversed(initial_expandables)]

    explored = set()
    current_path = [tab_name]
    back_button_position = None  # Cache back button position
    back_buttons = {}  # {level: selector}

    # Track (parent_path, role) combos where clicking navigates away
    # If [Tab, Parent] + button navigates, skip other buttons under [Tab, Parent]
    # Key: (parent_path_tuple, role) -> means "don't click this role under this parent"
    navigates_away = set()

    llm = _get_llm_handler()

    while stack:
        path, item_name, item_role = stack.pop()
        path_key = tuple(path)

        # DEBUG: Print stack state
        print(f"\n{'='*60}")
        print(f"STACK ({len(stack)} remaining):")
        for i, (p, n, r) in enumerate(stack[-5:]):  # Show last 5
            print(f"  [{i}] [{r}] {' > '.join(p)}")
        if len(stack) > 5:
            print(f"  ... and {len(stack) - 5} more")
        print(f"CURRENT: [{item_role}] {' > '.join(path)}")
        print(f"EXPLORED: {len(explored)} | NAVIGATES_AWAY: {len(navigates_away)}")
        print(f"{'='*60}")

        if path_key in explored:
            print(f"    SKIP (already explored)")
            continue

        # Check if we've learned this (parent, role) combo navigates away
        parent_path = tuple(path[:-1])
        if (parent_path, item_role) in navigates_away:
            print(f"    SKIP (learned: {item_role}s under {' > '.join(path[:-1])} navigate away)")
            # Already recorded as link when we learned this, skip
            continue

        explored.add(path_key)

        print(f"\n[{step}] {' > '.join(path)}")

        # Capture ARIA before interaction
        aria_before = await page.locator('body').aria_snapshot()

        # Try hover first (if not disabled for this site)
        revealed = False
        aria_after = aria_before
        if _should_try_hover():
            revealed, aria_after = await hover_and_check(page, item_name, item_type=item_role, menu_ctx=menu_ctx)
            _track_hover(revealed)
        else:
            print(f"    [HOVER] Skipped (disabled for this site)")

        if not revealed:
            # Hover didn't work, try click
            url_before = page.url
            clicked = await click_button(page, item_name, prefer_role=item_role, menu_ctx=menu_ctx)

            if not clicked:
                # Element not found - try back button or reset
                print(f"    Element not found, trying back button...")

                # Try cached back button position first
                if back_button_position:
                    try:
                        await page.mouse.click(back_button_position[0], back_button_position[1])
                        await page.wait_for_timeout(300)
                        # Retry click
                        clicked = await click_button(page, item_name, prefer_role=item_role, menu_ctx=menu_ctx)
                        if not clicked:
                            # Cached position didn't work, clear it
                            print(f"    Cached back button didn't work, clearing cache")
                            back_button_position = None
                    except:
                        # Cache failed, clear it
                        back_button_position = None

                # Try finding back button
                if not clicked:
                    back_selector = await find_back_button(page)
                    if back_selector:
                        try:
                            loc = page.locator(back_selector).first
                            bbox = await loc.bounding_box()
                            if bbox:
                                back_button_position = (bbox['x'] + bbox['width']/2,
                                                       bbox['y'] + bbox['height']/2)
                            await loc.click()
                            await page.wait_for_timeout(300)
                            clicked = await click_button(page, item_name, prefer_role=item_role, menu_ctx=menu_ctx)
                            if not clicked:
                                # Back button found but didn't help, clear cache
                                back_button_position = None
                        except:
                            # Back button interaction failed, don't cache
                            back_button_position = None

                # Last resort: reset menu
                if not clicked:
                    print(f"    Resetting menu...")
                    await page.goto(base_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(500)
                    # Re-open menu using cache (fast) or full detection (slow)
                    if not await reopen_menu_fast(page):
                        result = await open_menu_and_capture(page)
                        if not result['opened']:
                            continue
                    # Click tab if this isn't the no-tabs case
                    if tab['text'] != 'Menu':
                        await click_button(page, tab['text'], prefer_role=tab['role'])
                        await page.wait_for_timeout(300)
                    continue

            if clicked:
                await page.wait_for_timeout(300)

                # Check for URL change (not allowed except at tab level)
                url_after = page.url
                if url_after != url_before:
                    print(f"    URL changed: {url_before} -> {url_after}")
                    print(f"    Recording '{item_name}' as link and resetting...")
                    # Record this as a link with hierarchy
                    # path = [Tab, Parent, ItemName] -> use Parent > ItemName
                    path_parts = path[1:]  # Exclude tab
                    if len(path_parts) > 1:
                        hierarchy_key = ' > '.join(path_parts)
                    else:
                        hierarchy_key = item_name
                    all_categories[hierarchy_key] = url_after

                    # Learn: this (parent_path, role) combo navigates away
                    # Skip other items with same role under same parent
                    parent_path = tuple(path[:-1])
                    navigates_away.add((parent_path, item_role))
                    print(f"    LEARNED: [{item_role}]s under '{' > '.join(path[:-1])}' navigate away")

                    # Extract all sibling links from current ARIA before we reset
                    # (they're probably all links too - same parent as the navigating item)
                    aria_now = await page.locator('body').aria_snapshot()
                    if boundary_marker:
                        aria_now = truncate_aria_at_boundary(aria_now, boundary_marker)
                    sibling_links = extract_links_from_aria(aria_now)
                    sibling_links = filter_utility_links(sibling_links)
                    # Add with same parent hierarchy
                    parent_parts = path[1:-1]  # Exclude tab and the item itself
                    for link_name, url in sibling_links.items():
                        if parent_parts:
                            sibling_key = ' > '.join(parent_parts + [link_name])
                        else:
                            sibling_key = link_name
                        if sibling_key not in all_categories:
                            all_categories[sibling_key] = url
                    print(f"    Extracted {len(sibling_links)} sibling links from ARIA")
                    # Reset
                    await page.goto(base_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(500)
                    # Re-open menu using cache (fast) or full detection (slow)
                    if not await reopen_menu_fast(page):
                        print(f"    Cache miss, detecting menu...")
                        result = await open_menu_and_capture(page)
                        if not result['opened']:
                            print(f"    Failed to reopen menu!")
                            current_path = [tab_name]
                            continue
                    # Click tab if this isn't the no-tabs case
                    if tab['text'] != 'Menu':
                        print(f"    Clicking tab '{tab['text']}' to restore state...")
                        await click_button(page, tab['text'], prefer_role=tab['role'])
                        await page.wait_for_timeout(300)
                    current_path = [tab_name]

                    # Navigate path to get back to where we need to be
                    # (next stack item might be at a deeper level)
                    if len(path) > 2:
                        # Need to navigate intermediate path elements
                        # path is [Tab, Parent, Child] - we need to click Parent
                        for intermediate in path[1:-1]:  # Skip tab and target
                            print(f"    Navigating to '{intermediate}' to restore depth...")
                            nav_result = await click_button(page, intermediate, menu_ctx=menu_ctx)
                            if nav_result:
                                await page.wait_for_timeout(300)
                            else:
                                print(f"    Could not navigate to '{intermediate}'")
                                break

                    print(f"    Reset complete. Current path: {current_path}")
                    step += 1
                    continue

                aria_after = await page.locator('body').aria_snapshot()

        # Get diff - only new content
        diff, _ = get_new_content(aria_before, aria_after)

        # Count interactive elements in diff
        interactive_keywords = ['link', 'button', 'menuitem', 'tab']
        interactive_count = sum(
            1 for line in diff.split('\n')
            if any(kw in line.lower() for kw in interactive_keywords)
        )

        if interactive_count < 2:
            print(f"    No meaningful content revealed ({interactive_count} interactive) - leaf node")
            step += 1
            continue

        print(f"    Diff: {len(diff)} chars, {interactive_count} interactive elements")

        # Extract links from diff
        diff_links = extract_links_from_aria(diff)
        diff_links = filter_utility_links(diff_links)

        # Ask LLM about the NEW content only
        subcat_result = llm.call_text(
            prompt=prompt_subcategories(diff, path, diff_links),
            max_tokens=1000,
            operation="nav_subcategories_diff"
        )
        _track_llm_result(subcat_result)

        if subcat_result.get('success'):
            raw = subcat_result.get('response', '')
            expandable_items, leaf_links, is_product = parse_subcategories(raw)

            # Add leaf links to results with hierarchy
            for link in leaf_links:
                link_name = link['name']
                # Find URL from extracted links
                for name, url in diff_links.items():
                    if name.lower() == link_name.lower():
                        # Build hierarchical key from path (excluding tab and the button itself)
                        # path = [Tab, Parent, ButtonName] -> use just Parent
                        # The parent was set by find_expandable_elements based on sibling links
                        path_parts = path[1:-1]  # Exclude tab (first) and button (last)
                        if path_parts:
                            hierarchy_key = ' > '.join(path_parts + [link_name])
                        else:
                            hierarchy_key = link_name
                        all_categories[hierarchy_key] = url
                        break

            # Add expandable items to stack with proper parent context
            # Use find_expandable_elements on the DIFF to detect parent for each button
            diff_expandables = find_expandable_elements(diff)

            for item in reversed(expandable_items):
                # Find this item's parent from diff_expandables
                # Build path - 'context' is for uniqueness only, not for hierarchy
                child_path = path + [item['name']]

                if tuple(child_path) not in explored:
                    stack.append((child_path, item['name'], item['type']))

            print(f"    Found {len(expandable_items)} expandable, {len(leaf_links)} links")

        current_path = path
        step += 1

    print(f"\n[DFS] Done with '{tab_name}': {len(all_categories)} categories found")

    return {
        'tab': tab_name,
        'categories': all_categories,
        'mode': 'dfs',
        'steps': step
    }


async def explore_tab(
    page: Page,
    tab: dict,
    base_url: str,
    menu_ctx: Optional[MenuContext] = None
) -> dict:
    """
    Explore one tab - automatically chooses bulk or DFS mode.

    1. Click tab
    2. Try clicking first expandable element
    3. If no diff → bulk extraction (site pre-loads everything)
    4. If diff exists → DFS exploration with diffs
    """
    tab_name = tab['text']
    print(f"\n{'='*60}")
    print(f"TAB: {tab_name}")
    print(f"{'='*60}")

    # Click the tab
    clicked = await click_button(page, tab_name, prefer_role=tab['role'])
    if not clicked:
        print(f"    Could not click tab '{tab_name}'")
        return {'tab': tab_name, 'categories': {}, 'error': 'Could not click tab'}

    await page.wait_for_timeout(400)

    # Capture tab state
    tab_aria = await page.locator('body').aria_snapshot()

    # Truncate ARIA at boundary to only include menu content
    boundary_marker = menu_ctx.boundary_marker if menu_ctx else None
    if boundary_marker:
        tab_aria = truncate_aria_at_boundary(tab_aria, boundary_marker)

    # Find expandable elements
    expandables = find_expandable_elements(tab_aria)
    print(f"    Found {len(expandables)} expandable elements")

    if not expandables:
        # No expandables - just extract links directly
        print(f"    No expandable elements, extracting links...")
        links = extract_links_from_aria(tab_aria)
        links = filter_utility_links(links)
        return {
            'tab': tab_name,
            'categories': links,
            'mode': 'direct',
        }

    # Try clicking first expandable to detect mode
    first = expandables[0]
    print(f"    Testing '{first['name']}' to detect mode...")

    aria_before = tab_aria

    # Try hover first (if not disabled for this site)
    revealed = False
    aria_after = aria_before
    if _should_try_hover():
        revealed, aria_after = await hover_and_check(page, first['name'], item_type=first['role'], menu_ctx=menu_ctx)
        _track_hover(revealed)

    if not revealed:
        # Try click
        url_before = page.url
        clicked = await click_button(page, first['name'], prefer_role=first['role'], menu_ctx=menu_ctx)
        if clicked:
            await page.wait_for_timeout(300)
            # Check if click navigated away - if so, this is a link, not expandable
            url_after = page.url
            if url_after != url_before:
                print(f"    Click navigated away! '{first['name']}' is a link → BULK MODE")
                # Reset and use bulk extraction (site has flat links)
                await page.goto(base_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(500)
                if not await reopen_menu_fast(page):
                    result = await open_menu_and_capture(page)
                    if not result['opened']:
                        return {'tab': tab_name, 'categories': {}, 'mode': 'failed'}
                await click_button(page, tab_name, prefer_role=tab['role'])
                await page.wait_for_timeout(300)
                refreshed_aria = await page.locator('body').aria_snapshot()
                return await bulk_extract_tab(page, tab, refreshed_aria, base_url)
            aria_after = await page.locator('body').aria_snapshot()

    # Check for meaningful diff (navigation content, not just dynamic changes)
    diff, _ = get_new_content(aria_before, aria_after)

    # Count interactive elements in diff (links, buttons, menuitems)
    interactive_keywords = ['link', 'button', 'menuitem', 'tab']
    interactive_count = sum(
        1 for line in diff.split('\n')
        if any(kw in line.lower() for kw in interactive_keywords)
    )

    # Need at least 3 interactive elements to consider it a real reveal
    # (avoids false positives from dynamic page changes)
    if interactive_count < 3:
        # No meaningful diff - site pre-loads everything, use bulk extraction
        print(f"    No meaningful diff ({interactive_count} interactive elements) → BULK MODE")
        return await bulk_extract_tab(page, tab, tab_aria, base_url)
    else:
        # Real navigation content revealed - use DFS
        print(f"    Navigation revealed ({interactive_count} interactive elements) → DFS MODE")
        # Reset state before DFS (we already clicked something)
        await page.goto(base_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(500)
        # Re-open menu using cache (fast) or full detection (slow)
        if not await reopen_menu_fast(page):
            result = await open_menu_and_capture(page)
            if result['opened']:
                menu_ctx = MenuContext.from_menu_result(result, base_url)
        await click_button(page, tab_name, prefer_role=tab['role'])
        await page.wait_for_timeout(300)
        tab_aria = await page.locator('body').aria_snapshot()

        return await dfs_explore_tab(page, tab, tab_aria, base_url, menu_ctx)


async def explore_all_tabs(
    page: Page,
    tabs: list[dict],
    base_url: str,
    menu_result: dict = None
) -> dict:
    """
    Main entry point: explore all tabs and collect categories.

    Args:
        page: Playwright page (already at site with menu open)
        tabs: List of tabs from find_tabs_in_dom() [{text, role, x, y}, ...]
              If None or empty, explores the menu directly without tabs.
        base_url: Base URL for resetting
        menu_result: Result from open_menu_and_capture() for MenuContext

    Returns:
        Dict with all results per tab and combined categories
    """
    # Reset hover tracking for this site
    _reset_hover_stats()

    menu_ctx = None
    if menu_result:
        menu_ctx = MenuContext.from_menu_result(menu_result, base_url)

    all_results = {}
    all_categories = {}

    # Handle no-tabs case: explore menu directly
    if not tabs:
        print(f"\n{'='*70}")
        print(f"NO TABS - Exploring menu directly")
        print(f"{'='*70}")

        # Get menu ARIA - but verify menu is still open first
        # (popup dismissal might have closed it)
        current_aria = await page.locator('body').aria_snapshot()
        menu_aria = menu_result.get('menu_aria') if menu_result else None

        # Check if menu content is still visible in current ARIA
        # (popup dismissal from earlier might have closed the menu)
        if menu_aria and menu_ctx and menu_ctx.menu_start_line:
            if menu_ctx.menu_start_line not in current_aria:
                print(f"    [WARNING] Menu appears closed! Reopening...")
                # NOTE: Do NOT call dismiss_popups here - that's what closed it!
                if await reopen_menu_fast(page):
                    await page.wait_for_timeout(300)
                    menu_aria = await page.locator('body').aria_snapshot()
                    print(f"    Menu reopened, fresh ARIA captured")
                else:
                    # Full menu detection (no popup dismissal!)
                    result = await open_menu_and_capture(page)
                    if result['opened']:
                        menu_aria = result.get('menu_aria') or await page.locator('body').aria_snapshot()
                        menu_ctx = MenuContext.from_menu_result(result, base_url)
                        print(f"    Menu reopened via detection")
            else:
                # Menu is still open, use current ARIA (fresher)
                menu_aria = current_aria
        elif not menu_aria:
            menu_aria = current_aria

        # Create a fake "root" tab to use existing exploration logic
        root_tab = {'text': 'Menu', 'role': 'menu'}

        # Truncate ARIA at boundary to only include menu content (not footer, etc.)
        boundary_marker = menu_ctx.boundary_marker if menu_ctx else None
        if boundary_marker:
            menu_aria_truncated = truncate_aria_at_boundary(menu_aria, boundary_marker)
            print(f"    Truncated ARIA at boundary: {boundary_marker[:40]}...")
            print(f"    Before: {len(menu_aria)} chars → After: {len(menu_aria_truncated)} chars")
        else:
            menu_aria_truncated = menu_aria

        # Debug: show truncated menu ARIA
        print(f"    Menu ARIA ({len(menu_aria_truncated)} chars, {len(menu_aria_truncated.split(chr(10)))} lines):")
        for line in menu_aria_truncated.split('\n'):
            print(f"      {line}")

        # Check if site pre-loads or uses show/hide (use truncated ARIA)
        expandables = find_expandable_elements(menu_aria_truncated)
        print(f"    Found {len(expandables)} expandable elements")

        if not expandables:
            # No expandables - just extract links (use truncated ARIA)
            print(f"    No expandable elements, extracting links...")
            links = extract_links_from_aria(menu_aria_truncated)
            links = filter_utility_links(links)
            all_results['Menu'] = {
                'tab': 'Menu',
                'categories': links,
                'mode': 'direct',
            }
            all_categories.update(links)
        else:
            # Test first expandable for mode detection
            first = expandables[0]
            aria_before = menu_aria_truncated

            revealed, aria_after = await hover_and_check(page, first['name'], item_type=first['role'], menu_ctx=menu_ctx)

            if not revealed:
                # Check if hover closed the menu - reopen if needed
                current_aria = await page.locator('body').aria_snapshot()
                if menu_ctx and menu_ctx.menu_start_line and menu_ctx.menu_start_line not in current_aria:
                    print(f"    [WARNING] Menu closed after hover! Reopening...")
                    if await reopen_menu_fast(page):
                        await page.wait_for_timeout(300)
                    else:
                        result = await open_menu_and_capture(page)
                        if result['opened']:
                            menu_ctx = MenuContext.from_menu_result(result, base_url)

                url_before = page.url
                clicked = await click_button(page, first['name'], prefer_role=first['role'], menu_ctx=menu_ctx)
                if clicked:
                    await page.wait_for_timeout(300)
                    # Check if click navigated away - if so, use bulk mode
                    url_after = page.url
                    if url_after != url_before:
                        print(f"    Click navigated away! '{first['name']}' is a link → BULK MODE")
                        await page.goto(base_url, wait_until="domcontentloaded")
                        await page.wait_for_timeout(500)
                        if not await reopen_menu_fast(page):
                            menu_res = await open_menu_and_capture(page)
                            if menu_res['opened']:
                                menu_ctx = MenuContext.from_menu_result(menu_res, base_url)
                                menu_aria = menu_res.get('menu_aria') or await page.locator('body').aria_snapshot()
                        else:
                            menu_aria = await page.locator('body').aria_snapshot()
                        # Truncate at boundary before extraction
                        if menu_ctx and menu_ctx.boundary_marker:
                            menu_aria = truncate_aria_at_boundary(menu_aria, menu_ctx.boundary_marker)
                        result = await bulk_extract_tab(page, root_tab, menu_aria, base_url)
                        all_results['Menu'] = result
                        if result.get('categories'):
                            all_categories.update(result['categories'])
                        # Skip the rest of no-tabs processing
                        print(f"\n{'='*70}")
                        print(f"EXPLORATION COMPLETE")
                        print(f"{'='*70}")
                        print(f"Total categories: {len(all_categories)}")
                        return {
                            'tabs': all_results,
                            'all_categories': all_categories,
                            'llm_usage': _llm_usage.copy()
                        }
                    aria_after = await page.locator('body').aria_snapshot()

            diff, _ = get_new_content(aria_before, aria_after)

            # Count interactive elements in diff
            interactive_keywords = ['link', 'button', 'menuitem', 'tab']
            interactive_count = sum(
                1 for line in diff.split('\n')
                if any(kw in line.lower() for kw in interactive_keywords)
            )

            if interactive_count < 3:
                # Bulk mode - no meaningful navigation revealed
                print(f"    No meaningful diff ({interactive_count} interactive) → BULK MODE")
                result = await bulk_extract_tab(page, root_tab, menu_aria_truncated, base_url)
            else:
                # DFS mode - navigation content revealed
                print(f"    Navigation revealed ({interactive_count} interactive) → DFS MODE")
                await page.goto(base_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(500)
                # Re-open menu using cache (fast) or full detection (slow)
                if not await reopen_menu_fast(page):
                    menu_res = await open_menu_and_capture(page)
                    if menu_res['opened']:
                        menu_ctx = MenuContext.from_menu_result(menu_res, base_url)
                        menu_aria = menu_res.get('menu_aria') or await page.locator('body').aria_snapshot()
                else:
                    menu_aria = await page.locator('body').aria_snapshot()

                result = await dfs_explore_tab(page, root_tab, menu_aria, base_url, menu_ctx)

            all_results['Menu'] = result
            if result.get('categories'):
                all_categories.update(result['categories'])

        print(f"\n{'='*70}")
        print(f"EXPLORATION COMPLETE")
        print(f"{'='*70}")
        print(f"Total categories: {len(all_categories)}")

        return {
            'tabs': all_results,
            'all_categories': all_categories,
            'llm_usage': _llm_usage.copy()
        }

    # Normal case: explore each tab
    print(f"\n{'='*70}")
    print(f"EXPLORING {len(tabs)} TABS")
    print(f"{'='*70}")

    for i, tab in enumerate(tabs):
        print(f"\n[{i+1}/{len(tabs)}] Processing tab: {tab['text']}")

        # Ensure we're at base with menu open
        if i > 0:
            await page.goto(base_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(500)
            # Re-open menu using cache (fast) or full detection (slow)
            if not await reopen_menu_fast(page):
                result = await open_menu_and_capture(page)
                if result['opened']:
                    menu_ctx = MenuContext.from_menu_result(result, base_url)

        # Explore this tab
        tab_result = await explore_tab(page, tab, base_url, menu_ctx)
        all_results[tab['text']] = tab_result

        # Merge categories
        if tab_result.get('categories'):
            # Prefix with tab name for hierarchy
            for name, url in tab_result['categories'].items():
                key = f"{tab['text']} > {name}" if ' > ' not in name else name
                all_categories[key] = url

    print(f"\n{'='*70}")
    print(f"EXPLORATION COMPLETE")
    print(f"{'='*70}")
    print(f"Total categories: {len(all_categories)}")

    results = {
        'tabs': all_results,
        'all_categories': all_categories,
        'llm_usage': _llm_usage.copy()
    }

    # Build and attach NavTree
    tree = build_tree_from_results(results)
    results['tree'] = tree

    return results


def print_nav_tree(results: dict, show_urls: bool = True) -> str:
    """
    Pretty print the navigation tree from exploration results.

    Args:
        results: Dict from explore_all_tabs()
        show_urls: Whether to show URLs next to categories

    Returns:
        Formatted tree string
    """
    if 'tree' in results:
        tree = results['tree']
    else:
        tree = build_tree_from_results(results)

    output = tree.print(show_urls=show_urls)
    print(output)
    return output


# =============================================================================
# Main explorer
# =============================================================================

async def explore(url: str) -> tuple:
    """
    Explore navigation menu using DFS.
    Returns tuple of (list of captured states, llm_usage dict).
    """
    global _llm_usage
    _llm_usage = {"input_tokens": 0, "output_tokens": 0}  # Reset tracking

    print(f"\n{'='*70}")
    print("DYNAMIC NAV EXPLORER")
    print(f"{'='*70}")
    print(f"URL: {url}\n")

    states = []  # All captured states
    step = 0

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    # Use desktop viewport (1280px) to ensure desktop navigation is visible
    # Many sites hide desktop nav below 992px (CSS media queries)
    # Use 768px width - tablet size that often has hamburger menu but with URL navigation
    # (500px mobile often uses SPA navigation where URLs don't change)
    page = await browser.new_page(viewport={'width': 768, 'height': 900})

    try:
        # Setup
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await wait_for_page_ready(page)

        print("[2] Dismissing popups...")
        await dismiss_popups_with_llm(page)
        await page.wait_for_timeout(300)

        # PHASE 1: Try to detect and open hamburger menu FIRST
        # At mobile viewport (768px), nav is often hidden behind hamburger
        print("[3] Checking for hamburger menu...")
        menu_opened = await open_menu(page)

        if menu_opened:
            print("    Menu opened - will analyze menu contents")
            await page.wait_for_timeout(500)
            # Dismiss any popups that appeared after opening menu
            await dismiss_popups_with_llm(page, menu_is_open=True)
            await page.wait_for_timeout(300)

        # Capture state (with screenshot for LLM)
        print("[4] Capturing state...")
        initial_state = await capture_state(page, [], "initial_load", step, capture_screenshot=True)
        states.append(initial_state)
        step += 1

        # Get ARIA for analysis
        print("[5] Analyzing navigation structure...")
        try:
            header_aria = await asyncio.wait_for(page.locator('header').aria_snapshot(), timeout=5.0)
        except (Exception, asyncio.TimeoutError):
            header_aria = None
        body_aria = initial_state['aria']

        llm = _get_llm_handler()

        # If menu was opened, analyze menu structure directly
        if menu_opened:
            print("    Analyzing open menu structure with LLM...")
            menu_result = llm.call_text(
                prompt=prompt_menu_structure(body_aria),
                max_tokens=1500,
                operation="nav_menu_structure"
            )
            _track_llm_result(menu_result)

            if not menu_result.get("success"):
                print(f"    LLM call failed: {menu_result.get('error')}")
                return states, _llm_usage

            menu_structure = parse_menu_structure(menu_result.get("response", ""))
            print(f"    LLM identified structure:")
            print(f"      Top-level: {[item['name'] for item in menu_structure['top_level']]}")
            print(f"      Subcategories: {[item['name'] for item in menu_structure['subcategories']]}")
            print(f"      Links: {[item['name'] for item in menu_structure.get('links', [])]}")

            # Use structured exploration for the open menu
            step = await explore_toggle_menu(page, menu_structure, states, step,
                                             menu_button_name="Menu", base_url=url)

            print(f"\n{'='*70}")
            print(f"EXPLORATION COMPLETE (hamburger menu mode)")
            print(f"{'='*70}")
            return states, _llm_usage

        # PHASE 2: No hamburger menu found - use standard top-level discovery
        print("    No hamburger menu - analyzing visible navigation...")
        top_level_result = llm.call_with_image(
            prompt=prompt_top_level(header_aria, body_aria),
            image_b64=initial_state['screenshot_b64'],
            media_type="image/png",
            max_tokens=1500,
            operation="nav_top_level"
        )
        _track_llm_result(top_level_result)

        if not top_level_result.get("success"):
            print(f"    LLM call failed: {top_level_result.get('error')}")
            return states, _llm_usage

        llm_response_text = top_level_result.get("response", "")
        print(f"    LLM raw response:\n{llm_response_text}")
        top_level = parse_items(llm_response_text)

        # Keywords for hamburger/toggle menus - keep these even when filtering by majority type
        toggle_menu_keywords = ['menu', 'hamburger', 'nav', 'navigation']

        # Filter to majority type - but keep items with URLs and toggle menu buttons
        # This removes stray utility buttons (no URL) when main nav is links
        if len(top_level) > 1:
            from collections import Counter
            type_counts = Counter(item['type'] for item in top_level)
            majority_type = type_counts.most_common(1)[0][0]
            if type_counts[majority_type] > 1:  # Only filter if majority has >1 item
                original_count = len(top_level)
                # Keep items that match majority type OR have a URL OR are toggle menu buttons
                top_level = [item for item in top_level
                             if item['type'] == majority_type
                             or item.get('url')
                             or any(kw in item['name'].lower() for kw in toggle_menu_keywords)]
                if len(top_level) < original_count:
                    print(f"    Filtered to {majority_type} items (majority type), kept URLs and toggle buttons")

        print(f"    Found {len(top_level)} items:")
        for item in top_level:
            type_label = {'button': 'BTN', 'tab': 'TAB', 'group': 'GRP', 'link': 'LNK'}.get(item['type'], '???')
            t = f"[{type_label}] {item['name']}"
            if item.get('url'):
                t += f" → {item['url']}"
            print(f"      {t}")

        # Check if LLM found a toggle menu that our scanner missed
        toggle_item = None
        visible_category_tabs = [item for item in top_level
                                  if item['type'] == 'tab'
                                  and not any(kw in item['name'].lower() for kw in toggle_menu_keywords)]

        if not visible_category_tabs:
            for item in top_level:
                if item['type'] in ['button', 'tab']:
                    item_name_lower = item['name'].lower()
                    if any(kw in item_name_lower for kw in toggle_menu_keywords):
                        toggle_item = item
                        break

        if toggle_item:
            # LLM found a toggle menu - try to open it
            print(f"\n[6] LLM detected toggle menu: {toggle_item['name']}")
            print("    Opening menu and analyzing structure...")

            clicked = await click_button(page, toggle_item['name'])
            if not clicked:
                print("    ERROR: Could not open toggle menu")
                return states, _llm_usage

            await page.wait_for_timeout(500)

            aria = await page.locator('body').aria_snapshot()
            print("[7] Analyzing menu structure with LLM...")

            menu_result = llm.call_text(
                prompt=prompt_menu_structure(aria),
                max_tokens=1500,
                operation="nav_menu_structure"
            )
            _track_llm_result(menu_result)

            if not menu_result.get("success"):
                print(f"    LLM call failed: {menu_result.get('error')}")
                return states, _llm_usage

            menu_structure = parse_menu_structure(menu_result.get("response", ""))
            print(f"    LLM identified structure:")
            print(f"      Top-level: {[item['name'] for item in menu_structure['top_level']]}")
            print(f"      Subcategories: {[item['name'] for item in menu_structure['subcategories']]}")
            print(f"      Links: {[item['name'] for item in menu_structure.get('links', [])]}")

            # Use structured exploration
            step = await explore_toggle_menu(page, menu_structure, states, step,
                                             menu_button_name=toggle_item['name'], base_url=url)

            print(f"\n{'='*70}")
            print(f"EXPLORATION COMPLETE")
            print(f"{'='*70}")
            print(f"Total states captured: {len(states)}")

            return states, _llm_usage

        # Not a toggle menu - use normal DFS exploration
        # Initialize stack with button/tab/link/group paths to explore
        # Links are included because some sites use links that reveal menus on hover/click
        # Groups are included for sites like Khaite that use group elements for nav
        # If a link navigates away, we handle that by going back
        # Stack items are tuples: (path_list, item_type) where item_type is for the last item
        stack = []
        top_level_types = {}  # Map name -> type for top-level items
        top_level_urls = {}  # Map name -> url for top-level items that are links
        for item in top_level:
            if item['type'] in ['button', 'tab', 'link', 'group']:
                stack.append(([item['name']], item['type']))
                top_level_types[item['name']] = item['type']
                if item.get('url'):
                    # Make URL absolute
                    item_url = item['url']
                    if item_url.startswith('/'):
                        from urllib.parse import urljoin
                        item_url = urljoin(url, item_url)
                    top_level_urls[item['name']] = item_url

        # Reverse for DFS (first item explored first)
        stack = list(reversed(stack))

        print(f"\n[5] Starting DFS exploration...")
        print(f"    Stack: {[s[0][-1] for s in stack]}")

        explored = set()  # Track what we've explored
        current_path = []  # Track where we currently are
        back_buttons = {}  # {level: selector} - learned back buttons
        level_strategies = {}  # {level: strategy} - learned nav strategies per level
        base_url = url  # For detecting navigation away

        # Track levels with no expandable children - skip LLM after 5 consecutive empty results
        level_no_expandable_count = {}  # {level: count of consecutive items with no expandable}
        skip_llm_at_level = set()  # Levels where we've confirmed no expandable children

        # Track items discovered at each path - used to filter out siblings from LLM responses
        # Prevents infinite loops when LLM sees persistent nav tabs and reports them as children
        # Store (name, type) tuples so menuitems don't get filtered by same-named buttons
        items_at_path = {}
        items_at_path[()] = {(item['name'], item['type']) for item in top_level}

        while stack:
            # Stack items are tuples: (path_list, item_type)
            path, item_type = stack.pop()
            path_key = tuple(path)

            # Skip if already explored or too deep
            if path_key in explored:
                continue

            explored.add(path_key)

            print(f"\n{'='*60}")
            print(f"[{step}] EXPLORING: {' > '.join(path)} ({item_type})")
            print(f"    Current: {' > '.join(current_path) if current_path else '(root)'}")
            print(f"    Stack remaining: {len(stack)}")

            # For top-level items, try hover first to reveal dropdown menus
            # Some sites (like Eckhaus Latta) use hover to reveal, click navigates away
            # Skip hover for 'group' type (<details><summary>) - hover opens dropdown and blocks other items
            if len(path) == 1 and not current_path and item_type != 'group':
                revealed, aria_after_hover = await hover_and_check(page, path[0], item_type)
                if revealed:
                    # Only skip click if it's a link/button (click would navigate away)
                    # For tabs, clicking is still needed to explore subcategories
                    if item_type in ['link', 'button']:
                        print(f"    [HOVER] Menu revealed on hover ({item_type}), capturing without clicking...")

                        # Extract links from hover-revealed content
                        all_links = extract_links_from_aria(aria_after_hover)
                        all_links = filter_utility_links(all_links)

                        # Ask LLM to filter hover-revealed links
                        print(f"    Found {len(all_links)} links via hover, asking LLM to filter...")
                        hover_result = llm.call_text(
                            prompt=prompt_subcategories(aria_after_hover, path, all_links),
                            max_tokens=1000,
                            operation="nav_subcategories"
                        )
                        _track_llm_result(hover_result)
                        if hover_result.get("success"):
                            raw_response = hover_result.get("response", "")
                            _, hover_leaf_links, is_leaf = parse_subcategories(raw_response)
                            hover_approved = {link['name'].lower() for link in hover_leaf_links}
                            approved_links = {name: url for name, url in all_links.items()
                                             if name.lower() in hover_approved}
                            print(f"    LLM approved {len(approved_links)} of {len(all_links)} links")
                            # Show reasoning when 0 approved
                            if len(approved_links) == 0 and len(all_links) > 0:
                                print(f"    [REASONING] LLM response:")
                                for line in raw_response.split('\n')[:15]:
                                    print(f"      {line}")
                        else:
                            approved_links = all_links
                            print(f"    LLM failed, keeping all {len(all_links)} links")

                        # Add the top-level item's own URL if it has one
                        if path[0] in top_level_urls:
                            approved_links[path[0]] = top_level_urls[path[0]]

                        # Try hovering each revealed link to find nested content
                        # (e.g., hovering CLOTHING reveals clothing subcategories)
                        nested_links = {}
                        current_aria_urls = set(approved_links.values())
                        for link_name, link_url in list(approved_links.items()):
                            try:
                                # Re-hover parent to ensure menu stays open
                                await hover_and_check(page, path[0], item_type)
                                await page.wait_for_timeout(200)

                                # Capture ARIA before nested hover
                                aria_before_nested = await page.locator('body').aria_snapshot()

                                # Hover by URL selector (contains, to handle full vs relative URLs)
                                link_locator = page.locator(f'a[href*="{link_url}"]').first
                                if await link_locator.count() > 0 and await link_locator.is_visible():
                                    print(f"        [HOVER] Hovering '{link_name}' by URL {link_url}")
                                    await link_locator.hover(timeout=3000, force=True)
                                    await page.wait_for_timeout(400)

                                    # Capture ARIA after and check for changes
                                    aria_after_nested = await page.locator('body').aria_snapshot()
                                    nested_revealed, reason = hover_revealed_content(aria_before_nested, aria_after_nested)

                                    if nested_revealed:
                                        print(f"      [NESTED HOVER] '{link_name}' revealed more content ({reason})")
                                        nested_all = extract_links_from_aria(aria_after_nested)
                                        nested_all = filter_utility_links(nested_all)
                                        # Add any new links not already captured
                                        for n_name, n_url in nested_all.items():
                                            if n_url not in current_aria_urls and n_url not in nested_links.values():
                                                nested_links[n_name] = n_url
                                                current_aria_urls.add(n_url)
                                    else:
                                        print(f"        [HOVER] No new content from '{link_name}'")
                            except Exception as e:
                                print(f"      [NESTED HOVER] Error hovering '{link_name}': {e}")

                        if nested_links:
                            print(f"    [NESTED HOVER] Found {len(nested_links)} additional links")
                            approved_links.update(nested_links)

                        # Capture state
                        state = await capture_state(page, path, f"hovered: {path[-1]}", step)
                        state['new_links'] = approved_links
                        state['aria'] = aria_after_hover
                        states.append(state)

                        for name, url in approved_links.items():
                            print(f"      [LNK] {name} → {url}")

                        step += 1

                        # Move mouse away to close hover menu
                        await page.mouse.move(0, 0)
                        await page.wait_for_timeout(300)

                        # Don't add children to stack - hover menus typically show all links at once
                        continue
                    else:
                        print(f"    [HOVER] Content revealed on hover, but {item_type} needs click to explore subcategories")

            # Detect top-level category change - return to base URL for clean transition
            if current_path and path and current_path[0].lower() != path[0].lower():
                print(f"    [NAV] Top-level change: {current_path[0]} → {path[0]}")
                current_path = []  # Reset path tracking
                if page.url.rstrip('/') != base_url.rstrip('/'):
                    await page.goto(base_url, wait_until="domcontentloaded")
                    await wait_for_page_ready(page)

            # Navigate to this path from current position
            # Pass item_type as target_type so we click the right element (e.g., menuitem vs button)
            success, navigated_away = await navigate_to_path(page, path, current_path, back_buttons, level_strategies, base_url, target_type=item_type)

            if navigated_away:
                # Clicking this item caused URL navigation - it's a link, not expandable
                print(f"    Item '{path[-1]}' is a link (navigated away), skipping")
                current_path = current_path  # Stay where we were
                continue

            if not success:
                print(f"    FAILED to navigate to: {' > '.join(path)}")
                # Return to base URL since we don't know where we are
                print(f"    [NAV] Returning to base URL after failure")
                await page.goto(base_url, wait_until="domcontentloaded")
                await wait_for_page_ready(page)
                current_path = []
                continue

            # Update current path
            current_path = path.copy()

            # Wait for menu to fully expand/animate before capturing state
            await page.wait_for_timeout(1000)

            # Wait for any animations to complete
            await page.wait_for_timeout(200)

            # Get ARIA for analysis
            aria = await page.locator('body').aria_snapshot()

            # Extract links early so we can pass them to LLM for product page detection
            current_links = extract_links_from_aria(aria)
            current_links = filter_utility_links(current_links)

            # Check if we should skip LLM for this level (already know it has no expandable children)
            current_level = len(path)
            if current_level in skip_llm_at_level:
                print(f"    [SKIP-LLM] Level {current_level} confirmed to have no expandable items")
                expandable_items = []
                leaf_links = []
                new_buttons = {}
                llm_links = {}
            else:
                # Ask LLM what subcategories are available
                print(f"    Asking LLM for subcategories under '{path[-1]}'...")
                subcat_result = llm.call_text(
                    prompt=prompt_subcategories(aria, path, current_links),
                    max_tokens=1000,
                    operation="nav_subcategories"
                )
                _track_llm_result(subcat_result)
                if not subcat_result.get("success"):
                    print(f"    LLM call failed: {subcat_result.get('error')}")
                    raw_response = ""
                else:
                    raw_response = subcat_result.get("response", "")
                print(f"    LLM raw response:\n{raw_response[:500]}")
                expandable_items, leaf_links, is_product_listing = parse_subcategories(raw_response)

                # Handle product listing page - treat as leaf, record URL, skip link extraction
                if is_product_listing:
                    print(f"    [PRODUCT_LISTING] This is a product page, treating as leaf")
                    new_buttons = {}
                    # Use known URL from initial scan if available, otherwise fall back to page.url
                    item_name = path[-1]
                    if len(path) == 1 and item_name in top_level_urls:
                        recorded_url = top_level_urls[item_name]
                    else:
                        recorded_url = page.url
                    new_links = {item_name: recorded_url}
                    # Capture state and continue to next item
                    action = f"product_listing: {item_name}"
                    state = await capture_state(page, path, action, step, new_buttons, new_links)
                    states.append(state)
                    print(f"    Recorded as link: {item_name} → {recorded_url}")
                    current_path = path
                    step += 1
                    continue

                # Convert to dict format {name: type} for compatibility - only expandable items go on stack
                new_buttons = {s['name']: s['type'] for s in expandable_items}
                llm_links = {s['name']: 'link' for s in leaf_links}

                # Record these items as siblings at this path (for filtering later)
                if new_buttons:
                    items_at_path[tuple(path)] = {(name, typ) for name, typ in new_buttons.items()}

                print(f"    LLM identified: {list(new_buttons.keys())}")
                if llm_links:
                    print(f"    LLM links (won't explore): {list(llm_links.keys())}")

                # Track consecutive items with no expandable children at this level
                if len(expandable_items) == 0:
                    level_no_expandable_count[current_level] = level_no_expandable_count.get(current_level, 0) + 1
                    if level_no_expandable_count[current_level] >= 5:
                        print(f"    [LEARN] Level {current_level} has no expandable items (5 consecutive), skipping LLM for rest")
                        skip_llm_at_level.add(current_level)
                else:
                    # Reset counter if we find expandable items
                    level_no_expandable_count[current_level] = 0

            # Use LLM-approved links only (match by name to get URLs from extracted links)
            # This filters out products that the LLM identified as non-category links
            llm_approved_names = {name.lower() for name in llm_links.keys()}
            new_links = {name: url for name, url in current_links.items()
                        if name.lower() in llm_approved_names}
            print(f"    LLM approved {len(new_links)} of {len(current_links)} links")
            # Show reasoning when 0 approved
            if len(new_links) == 0 and len(current_links) > 0:
                print(f"    [REASONING] LLM found no matching links. LLM links: {list(llm_links.keys())}")
                print(f"    [REASONING] Extracted links: {list(current_links.keys())[:10]}")
                if is_product_listing:
                    print(f"    [REASONING] Marked as LEAF/PRODUCT_LISTING page")

            # Add the top-level item's own URL if this is a top-level path
            if len(path) == 1 and path[0] in top_level_urls:
                new_links[path[0]] = top_level_urls[path[0]]

            # Capture state with discovered items
            action = f"clicked: {path[-1]}"
            state = await capture_state(page, path, action, step, new_buttons, new_links)
            states.append(state)

            print(f"    Found {len(new_buttons)} subcategories, {len(new_links)} new links")
            for name, typ in new_buttons.items():
                print(f"      [{typ.upper()}] {name}")
            for name, url in new_links.items():
                print(f"      [LNK] {name} → {url}")

            # Add new buttons/tabs to stack for further exploration (reversed for DFS order)
            # Sort alphabetically for consistent order, reverse so first item is explored first
            # Use actual type (button or tab) from extraction

            # Get siblings at current level (to filter out LLM mistakes with persistent nav)
            parent_path = tuple(path[:-1]) if len(path) > 1 else ()
            siblings = items_at_path.get(parent_path, set())

            sorted_buttons = sorted(new_buttons.keys())
            filtered_count = 0
            for btn in reversed(sorted_buttons):
                btn_type = new_buttons[btn]
                # Skip if this exact (name, type) is a known sibling (LLM confused by persistent nav)
                if (btn, btn_type) in siblings:
                    filtered_count += 1
                    continue
                child_path = path + [btn]
                if tuple(child_path) not in explored:
                    stack.append((child_path, btn_type))

            if filtered_count > 0:
                print(f"    [FILTER] Removed {filtered_count} sibling items (persistent nav)")

            step += 1

        print(f"\n{'='*70}")
        print(f"EXPLORATION COMPLETE")
        print(f"{'='*70}")
        print(f"Total states captured: {len(states)}")

        return states, _llm_usage

    finally:
        await page.wait_for_timeout(1000)
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python dynamic_explorer.py <url>")
        sys.exit(1)

    url = sys.argv[1]

    # Extract domain for output dir
    domain = urlparse(url).netloc.replace('www.', '').split('.')[0]
    output_dir = Path(__file__).parent.parent.parent / 'extractions' / domain
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run exploration
    states = await explore(url)

    # Save states (without screenshots for smaller file)
    states_summary = []
    for s in states:
        states_summary.append({
            'step': s['step'],
            'timestamp': s['timestamp'],
            'path': s['path'],
            'action': s['action'],
            'url': s['url'],
            'new_buttons': s.get('new_buttons', []),
            'new_links': s.get('new_links', {}),
            'aria_length': len(s['aria']),
            'aria_preview': s['aria'][:500] + '...' if len(s['aria']) > 500 else s['aria']
        })

    summary_file = output_dir / 'exploration_states.json'
    with open(summary_file, 'w') as f:
        json.dump(states_summary, f, indent=2)
    print(f"\nSaved state summary: {summary_file}")

    # Build and save tree
    from build_tree import build_tree, find_cross_toplevel_urls, dedupe_parent_child_links
    base_url = states[0].get("url", url) if states else url
    cross_toplevel_urls = find_cross_toplevel_urls(states)
    tree = build_tree(states, base_url, filter_urls=cross_toplevel_urls)
    dedupe_parent_child_links(tree)

    tree_file = output_dir / 'navigation_tree.json'
    with open(tree_file, 'w') as f:
        json.dump(tree, f, indent=2)
    print(f"Saved navigation tree: {tree_file}")

    # Save full states (with ARIA, without screenshots for size)
    full_states = []
    for s in states:
        full_states.append({
            'step': s['step'],
            'timestamp': s['timestamp'],
            'path': s['path'],
            'action': s['action'],
            'url': s['url'],
            'new_buttons': s.get('new_buttons', []),
            'new_links': s.get('new_links', {}),
            'aria': s['aria']
        })

    full_file = output_dir / 'exploration_full.json'
    with open(full_file, 'w') as f:
        json.dump(full_states, f, indent=2)
    print(f"Saved full states: {full_file}")

    # Save screenshots separately (if captured)
    screenshots_saved = 0
    for s in states:
        if s.get('screenshot_b64'):
            screenshots_dir = output_dir / 'screenshots'
            screenshots_dir.mkdir(exist_ok=True)
            img_data = base64.b64decode(s['screenshot_b64'])
            img_file = screenshots_dir / f"step_{s['step']:03d}.png"
            with open(img_file, 'wb') as f:
                f.write(img_data)
            screenshots_saved += 1
    if screenshots_saved:
        print(f"Saved {screenshots_saved} screenshots to: {screenshots_dir}")


if __name__ == "__main__":
    asyncio.run(main())
