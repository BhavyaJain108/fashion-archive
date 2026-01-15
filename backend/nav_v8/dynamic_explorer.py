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
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / 'config' / '.env')

from anthropic import Anthropic
from playwright.async_api import async_playwright, Page

sys.path.insert(0, str(Path(__file__).parent.parent))
from nav_v8.llm_popup_dismiss import dismiss_popups_with_llm
from utils.page_wait import wait_for_page_ready

client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))


# =============================================================================
# LLM: Find top-level nav items
# =============================================================================

def prompt_top_level(aria: str) -> str:
    return f"""Look at this ARIA snapshot of a fashion website's navigation.

List ALL top-level navigation categories (the main menu items).

ARIA:
{aria[:8000]}

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


def prompt_subcategories(aria: str, current_path: list) -> str:
    """Prompt to identify subcategories at the current navigation path."""
    path_str = " > ".join(current_path)

    return f"""PURPOSE: We're building a navigation tree for a fashion site. We need to find all category paths.

CURRENT PATH: {path_str}

TASK: Find EXPANDABLE elements that reveal MORE subcategories, and LINKS to category pages.

PAGE TYPE - Determine first:
- LEAF: No more category navigation exists (only product links, utility links, or nothing)
- HAS_CATEGORIES: There are expandable elements or category links to record

IF this is a LEAF page:
PAGE_TYPE: LEAF

IF there ARE category items:
PAGE_TYPE: HAS_CATEGORIES

CLASSIFICATION - Based on ARIA ROLE, not the name:
- EXPANDABLE: role=button, role=tab, role=menuitem → we click these to explore
- LINK: role=link → we record the URL but don't click

IMPORTANT:
- Look at the actual ARIA role, not what the name suggests.
- "Ready-to-wear" with role=menuitem is EXPANDABLE, not a LINK.
- Include ALL buttons, tabs, and menuitems - do not skip any.
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

CONSTRAINTS:
- Classify by ARIA role, not by name
- Only include CHILDREN of the current path, not siblings or parent items
- Ignore utility controls: Back, Close, Search, Cart, Menu, Login, Account
- Use exact names from the ARIA
- If no expandable elements or category links exist, respond with PAGE_TYPE: LEAF

ARIA SNAPSHOT:
{aria[:6000]}
"""


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
    skip_patterns = [
        'login', 'cart', 'wishlist', 'account', 'saved',
        'faq', 'contact', 'careers', 'legal', 'privacy', 'cookie', 'terms',
        'facebook', 'instagram', 'tiktok', 'pinterest', 'linkedin', 'twitter',
        'tel:', 'mailto:', 'javascript:',
        'track-order', 'returns', 'shipping', 'payment', 'newsletter',
        'store-locator', 'find-store', 'appointments'
    ]

    # Skip anchor-only links (just "#" or "#something" with no path)
    skip_anchor_only = lambda url: url.startswith('#') or url == '#'

    skip_names = [
        'login', 'cart', 'search', 'close', 'back', 'menu',
        'saved items', 'wishlist', 'account', 'sign in'
    ]

    filtered = {}
    for name, url in links.items():
        name_lower = name.lower()
        url_lower = url.lower() if url else ''

        # Skip by name
        if any(skip in name_lower for skip in skip_names):
            continue
        # Skip by URL pattern
        if any(skip in url_lower for skip in skip_patterns):
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


async def click_button(page: Page, name: str, container=None, prefer_tab: bool = False, prefer_role: str = None, parent_menu: str = None) -> bool:
    """Click a button by name, optionally scoped to a container or parent menu."""
    search_context = container if container else page

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
                                await element.click(timeout=3000)
                                await page.wait_for_timeout(150)
                                return True
            except:
                continue

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

            # If exact match fails, try fuzzy match (handles "MENU" vs "Menu" or "Open Menu")
            if count == 0:
                locator = search_context.get_by_role(role, name=name, exact=False)
                count = await locator.count()
                if count > 0:
                    print(f"        [CLICK-DETAIL] Fuzzy match found '{name}' as {role} ({count} matches)")

            if count > 1:
                # Multiple elements with same name - potential ambiguity
                print(f"        [CLICK-DEBUG] WARNING: Found {count} elements for '{name}' as {role}")
            if count > 0:
                # Find first VISIBLE element (some sites have duplicate hidden elements)
                for i in range(count):
                    element = locator.nth(i)
                    if await element.is_visible():
                        print(f"        [CLICK-DETAIL] Found '{name}' as {role} (#{i+1} of {count}, visible)")
                        # Short timeout - fail fast if blocked, try next option
                        await element.click(timeout=3000)
                        await page.wait_for_timeout(150)
                        return True
                print(f"        [CLICK-DETAIL] Found '{name}' as {role} but none visible")
        except Exception as e:
            print(f"        [CLICK-DETAIL] {role} failed, trying next...")
            continue

    # Try <summary> elements (used by <details> pattern, appear as "group" in ARIA)
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
                    try:
                        # First try normal click
                        await element.click(timeout=2000)
                        await page.wait_for_timeout(150)
                        return True
                    except:
                        # If blocked, close dropdowns and force click
                        print(f"        [CLICK-DETAIL] Blocked, pressing Escape and retrying...")
                        await page.keyboard.press('Escape')
                        await page.wait_for_timeout(100)
                        await element.click(timeout=2000, force=True)
                        await page.wait_for_timeout(150)
                        return True
            print(f"        [CLICK-DETAIL] Found '{name}' as summary but none visible")
    except Exception as e:
        print(f"        [CLICK-DETAIL] Error with summary: {e}")

    print(f"      [CLICK] Could not find '{name}' - tried button/tab/menuitem/link/summary")
    return False


def hover_revealed_content(aria_before: str, aria_after: str) -> tuple[bool, str]:
    """
    Check if hover revealed navigation structure (not just char count).

    Looks for new navigation elements: menus, lists, tabs, links.

    Returns (revealed: bool, reason: str)
    """
    import re

    # Count navigation-related structures
    nav_patterns = [
        (r'- menu\b', 'menu'),
        (r'- navigation\b', 'navigation'),
        (r'- menuitem\b', 'menuitem'),
        (r'- tablist\b', 'tablist'),
        (r'- list:', 'list'),
    ]

    for pattern, name in nav_patterns:
        before_count = len(re.findall(pattern, aria_before))
        after_count = len(re.findall(pattern, aria_after))
        if after_count > before_count:
            return True, f"new {name} (+{after_count - before_count})"

    # Check for new links (most common indicator)
    before_links = len(re.findall(r'- link\b', aria_before))
    after_links = len(re.findall(r'- link\b', aria_after))
    if after_links > before_links + 3:  # At least 4 new links
        return True, f"new links (+{after_links - before_links})"

    # Fallback: significant char increase (but higher threshold)
    char_diff = len(aria_after) - len(aria_before)
    if char_diff > 500:
        return True, f"content (+{char_diff} chars)"

    return False, "no change"


async def hover_and_check(page: Page, name: str, item_type: str = None, container=None) -> tuple[bool, str]:
    """
    Hover over an element and check if new content appeared.
    For sites like Eckhaus Latta where menus reveal on hover, not click.

    Args:
        page: Playwright page
        name: Element name to find
        item_type: Optional type hint ('button', 'tab', 'link', 'group') to try first
        container: Optional container to search within

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
                        await element.hover()
                        await page.wait_for_timeout(500)  # Wait for menu animation

                        # Capture ARIA after hover
                        aria_after = await page.locator('body').aria_snapshot()

                        # Check if hover revealed navigation structure
                        revealed, reason = hover_revealed_content(aria_before, aria_after)
                        if revealed:
                            print(f"        [HOVER] Menu revealed! ({reason})")
                        else:
                            print(f"        [HOVER] No new content revealed")
                        return revealed, aria_after
        except Exception as e:
            print(f"        [HOVER] Error with {role}: {e}")
            continue

    # Try <summary> elements as fallback (used by <details> pattern)
    # First close any open dropdowns that might be blocking
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
                    await element.hover(timeout=5000)
                    await page.wait_for_timeout(500)

                    aria_after = await page.locator('body').aria_snapshot()
                    revealed, reason = hover_revealed_content(aria_before, aria_after)
                    if revealed:
                        print(f"        [HOVER] Menu revealed! ({reason})")
                    else:
                        print(f"        [HOVER] No new content revealed")
                    return revealed, aria_after
    except Exception as e:
        print(f"        [HOVER] Error with summary: {e}")

    return False, aria_before


async def find_menu_container(page: Page, name: str):
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


async def open_menu(page: Page) -> bool:
    """
    Try to open the navigation menu (after it's been closed with Escape).
    Returns True if menu was opened.
    """
    # Selectors to AVOID (shipping, location, language, etc.)
    avoid_patterns = ['ship', 'location', 'country', 'region', 'language', 'currency']

    async def is_distraction(el) -> bool:
        """Check if element is a shipping/location/language selector."""
        try:
            text = (await el.text_content() or '').lower()
            label = (await el.get_attribute('aria-label') or '').lower()
            for pattern in avoid_patterns:
                if pattern in text or pattern in label:
                    return True
        except:
            pass
        return False

    # Common patterns for menu opener buttons
    selectors = [
        # Hamburger menu patterns
        'button:has-text("menu")',
        'button:has-text("Menu")',
        '[aria-label*="menu" i]',
        '[aria-label*="navigation" i]',
        '.hamburger',
        '.menu-toggle',
        '[class*="hamburger"]',
        '[class*="menu-button"]',
        '[class*="nav-toggle"]',
        # Category/Shop buttons
        'button:has-text("Category")',
        'button:has-text("Categories")',
        # Generic nav button (checked last, with filtering)
        'nav button',
        'header button:not([aria-label*="search" i]):not([aria-label*="cart" i])',
    ]

    for selector in selectors:
        try:
            elements = await page.locator(selector).all()
            for el in elements:
                if await el.is_visible() and not await is_distraction(el):
                    print(f"    [NAV] Opening menu with: {selector}")
                    await el.click()
                    await page.wait_for_timeout(500)
                    return True
        except:
            continue
    return False


async def find_back_button(page: Page) -> str | None:
    """
    Look for a back button. Returns selector string if found, None otherwise.
    Prioritizes aria-label selectors as they're most reliable.
    """
    selectors = [
        # Aria-based (most reliable, check first)
        '[aria-label*="back" i]',
        '[aria-label*="previous" i]',
        '[aria-label*="go back" i]',
        '[aria-label*="return" i]',
        # Text-based
        'button:has-text("back")',
        'button:has-text("Back")',
        'button:has-text("previous")',
        'button:has-text("←")',
        'button:has-text("‹")',
        'button:has-text("<")',
        # Role + name
        '[role="button"][name*="back" i]',
        # Class patterns (specific to buttons, avoid matching random elements)
        'button.back-button',
        'button.btn-back',
        'button[class*="-back"]',  # Matches "nav-back", "menu-back", etc.
        'button[class*="back-"]',  # Matches "back-button", "back-btn", etc.
        # SVG with back arrow (check parent button)
        'button:has(svg[class*="back"])',
        'button:has(svg[class*="arrow-left"])',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                if await locator.is_visible():
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
    aria = await page.locator('body').aria_snapshot()

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

async def explore_toggle_menu(page: Page, menu_structure: dict, states: list, step: int,
                               menu_button_name: str, base_url: str) -> int:
    """
    Explore a toggle menu with known structure (top_level + subcategories).
    Returns updated step count.

    For sites like Alexander McQueen where menu has parallel dimensions:
    - top_level: Women, Men, Gifts, etc.
    - subcategories: Handbags, Shoes, Ready-to-Wear, etc.

    We explore each combination: Women×Handbags, Women×Shoes, Men×Handbags, etc.
    """
    top_level = menu_structure.get('top_level', [])
    subcategories = menu_structure.get('subcategories', [])

    async def ensure_menu_open():
        """Re-open menu if it got closed (e.g., after navigation)."""
        # Check if we navigated away
        if not page.url.startswith(base_url.rstrip('/')):
            await page.goto(base_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
        # Try to click menu button
        clicked = await click_button(page, menu_button_name)
        if clicked:
            await page.wait_for_timeout(500)
        return clicked

    menu_links = menu_structure.get('links', [])

    print(f"\n[STRUCTURED] Exploring toggle menu:")
    print(f"    Top-level: {[item['name'] for item in top_level]}")
    print(f"    Subcategories (tabs): {[item['name'] for item in subcategories]}")
    print(f"    Direct links (won't click): {[item['name'] for item in menu_links]}")

    for tl_item in top_level:
        tl_name = tl_item['name']
        tl_type = tl_item['type']

        print(f"\n{'='*60}")
        print(f"[{step}] TOP-LEVEL: {tl_name}")

        # Ensure menu is open before each top-level
        await ensure_menu_open()

        # Click the top-level category
        prefer_tab = (tl_type == 'tab')
        clicked = await click_button(page, tl_name, prefer_tab=prefer_tab)
        if not clicked:
            print(f"    Failed to click {tl_name}, skipping...")
            continue

        await page.wait_for_timeout(500)

        # Capture state for this top-level category
        aria = await page.locator('body').aria_snapshot()
        links = extract_links_from_aria(aria)
        links = filter_utility_links(links)

        state = await capture_state(page, [tl_name], f"clicked: {tl_name}", step)
        state['new_links'] = links
        states.append(state)
        step += 1

        print(f"    Found {len(links)} links at top level")

        # Ask LLM to identify subcategories for THIS category
        # This handles any site structure without hardcoding ARIA patterns
        # Pass top-level names so LLM knows to exclude them (always visible nav)
        top_level_names = [item['name'] for item in top_level]
        print(f"    Asking LLM for subcategories...")
        subcat_response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": prompt_subcategories(aria, [tl_name])
            }]
        )
        expandable_items, leaf_links, is_product_listing = parse_subcategories(subcat_response.content[0].text)
        if is_product_listing:
            print(f"    [PRODUCT_LISTING] Top-level '{tl_name}' is a product page, skipping subcategories")
            continue
        if expandable_items:
            print(f"    Expandable: {[s['name'] for s in expandable_items]}")
        if leaf_links:
            print(f"    Links (won't click): {[s['name'] for s in leaf_links]}")

        # Now explore each EXPANDABLE subcategory (skip leaf links - they navigate away)
        for sub_item in expandable_items:
            sub_name = sub_item['name']
            sub_type = sub_item['type']
            print(f"\n  [{step}] {tl_name} > {sub_name}")

            # Ensure menu is open and re-click top-level
            await ensure_menu_open()
            await click_button(page, tl_name, prefer_tab=prefer_tab)
            await page.wait_for_timeout(300)

            # Track URL before click to detect navigation
            url_before = page.url

            # Click the subcategory using the type identified by LLM
            prefer_tab_for_sub = (sub_type == 'tab')
            sub_clicked = await click_button(page, sub_name, prefer_tab=prefer_tab_for_sub)
            if not sub_clicked:
                print(f"      Failed to click {sub_name}, skipping...")
                continue

            await page.wait_for_timeout(500)

            # Check if clicking caused navigation (it's a link, not a tab)
            url_after = page.url
            if url_after != url_before:
                print(f"      [{sub_name}] navigated to {url_after} - capturing as link")
                # Still capture this as a valid state
                state = await capture_state(page, [tl_name, sub_name], f"navigated: {tl_name} > {sub_name}", step)
                state['new_links'] = {sub_name: url_after}
                states.append(state)
                step += 1
                # Go back to home for next iteration
                await page.goto(base_url, wait_until="domcontentloaded")
                await wait_for_page_ready(page)
                continue

            # Capture state for this combination
            aria = await page.locator('body').aria_snapshot()
            links = extract_links_from_aria(aria)
            links = filter_utility_links(links)

            state = await capture_state(page, [tl_name, sub_name], f"clicked: {tl_name} > {sub_name}", step)
            state['new_links'] = links
            states.append(state)
            step += 1

            print(f"      Found {len(links)} links")
            for name, url in list(links.items())[:3]:
                print(f"        [LNK] {name} → {url}")
            if len(links) > 3:
                print(f"        ... and {len(links) - 3} more")

    return step


# =============================================================================
# Main explorer
# =============================================================================

async def explore(url: str, max_depth: int = 3) -> list:
    """
    Explore navigation menu using DFS.
    Returns list of captured states at each step.
    """

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
    page = await browser.new_page(viewport={'width': 1280, 'height': 800})

    try:
        # Setup
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await wait_for_page_ready(page)

        print("[2] Dismissing popups...")
        await dismiss_popups_with_llm(page)
        await page.wait_for_timeout(300)

        # Capture initial state (with screenshot for LLM)
        print("[3] Capturing initial state...")
        initial_state = await capture_state(page, [], "initial_load", step, capture_screenshot=True)
        states.append(initial_state)
        step += 1

        # Get initial ARIA and find top-level items
        print("[4] Finding top-level items...")
        aria = initial_state['aria']

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": initial_state['screenshot_b64']}},
                    {"type": "text", "text": prompt_top_level(aria)}
                ]
            }]
        )

        top_level = parse_items(response.content[0].text)

        # Filter to majority type - nav items should be consistent (all tabs, all buttons, etc.)
        # This removes stray utility buttons when main nav is tabs
        if len(top_level) > 1:
            from collections import Counter
            type_counts = Counter(item['type'] for item in top_level)
            majority_type = type_counts.most_common(1)[0][0]
            if type_counts[majority_type] > 1:  # Only filter if majority has >1 item
                original_count = len(top_level)
                top_level = [item for item in top_level if item['type'] == majority_type]
                if len(top_level) < original_count:
                    print(f"    Filtered to {majority_type} items (majority type)")

        print(f"    Found {len(top_level)} items:")
        for item in top_level:
            type_label = {'button': 'BTN', 'tab': 'TAB', 'group': 'GRP', 'link': 'LNK'}.get(item['type'], '???')
            t = f"[{type_label}] {item['name']}"
            if item.get('url'):
                t += f" → {item['url']}"
            print(f"      {t}")

        # Check if this is a toggle menu site (hamburger menu)
        # BUT: if there are already visible tabs (like women/men/kids), prefer DFS over toggle menu
        toggle_menu_keywords = ['menu', 'hamburger', 'nav', 'navigation']
        toggle_item = None

        # Count visible tabs that are NOT toggle menus (actual category tabs)
        visible_category_tabs = [item for item in top_level
                                  if item['type'] == 'tab'
                                  and not any(kw in item['name'].lower() for kw in toggle_menu_keywords)]

        # Only look for toggle menu if there are NO visible category tabs
        if not visible_category_tabs:
            for item in top_level:
                if item['type'] in ['button', 'tab']:
                    item_name_lower = item['name'].lower()
                    if any(kw in item_name_lower for kw in toggle_menu_keywords):
                        toggle_item = item
                        break

        if toggle_item:
            # This is a toggle menu site - use structured exploration
            print(f"\n[5] Detected toggle menu: {toggle_item['name']}")
            print("    Opening menu and analyzing structure...")

            # Click to open the menu
            clicked = await click_button(page, toggle_item['name'])
            if not clicked:
                print("    ERROR: Could not open toggle menu")
                return states

            await page.wait_for_timeout(1000)
            await dismiss_popups_with_llm(page)
            await page.wait_for_timeout(300)

            # Get ARIA and ask LLM to identify structure
            aria = await page.locator('body').aria_snapshot()
            print("[6] Analyzing menu structure with LLM...")

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": prompt_menu_structure(aria)
                }]
            )

            menu_structure = parse_menu_structure(response.content[0].text)
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

            return states

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
            if len(path) > max_depth:
                print(f"\n    SKIP (depth {len(path)}): {' > '.join(path)}")
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
                        links = extract_links_from_aria(aria_after_hover)
                        links = filter_utility_links(links)

                        # Add the top-level item's own URL if it has one
                        if path[0] in top_level_urls:
                            links[path[0]] = top_level_urls[path[0]]

                        # Capture state
                        state = await capture_state(page, path, f"hovered: {path[-1]}", step)
                        state['new_links'] = links
                        state['aria'] = aria_after_hover
                        states.append(state)

                        print(f"    Found {len(links)} links via hover")
                        for name, url in list(links.items())[:5]:
                            print(f"      [LNK] {name} → {url}")
                        if len(links) > 5:
                            print(f"      ... and {len(links) - 5} more links")

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
                    await dismiss_popups_with_llm(page)

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
                await dismiss_popups_with_llm(page)
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
                subcat_response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1000,
                    messages=[{
                        "role": "user",
                        "content": prompt_subcategories(aria, path)
                    }]
                )
                expandable_items, leaf_links, is_product_listing = parse_subcategories(subcat_response.content[0].text)

                # Handle product listing page - treat as leaf, record URL, skip link extraction
                if is_product_listing:
                    print(f"    [PRODUCT_LISTING] This is a product page, treating as leaf")
                    new_buttons = {}
                    new_links = {path[-1]: page.url}  # Record current URL as the link
                    # Capture state and continue to next item
                    action = f"product_listing: {path[-1]}"
                    state = await capture_state(page, path, action, step, new_buttons, new_links)
                    states.append(state)
                    print(f"    Recorded as link: {path[-1]} → {page.url}")
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

            # Find new links (compared to initial state)
            current_links = extract_links_from_aria(aria)
            current_links = filter_utility_links(current_links)
            initial_links = extract_links_from_aria(states[0]['aria'])
            initial_links = filter_utility_links(initial_links)
            new_links = {k: v for k, v in current_links.items() if k not in initial_links}

            # Add the top-level item's own URL if this is a top-level path
            if len(path) == 1 and path[0] in top_level_urls:
                new_links[path[0]] = top_level_urls[path[0]]

            # Capture state with discovered items
            action = f"clicked: {path[-1]}"
            state = await capture_state(page, path, action, step, new_buttons, new_links)
            states.append(state)

            print(f"    Found {len(new_buttons)} subcategories, {len(new_links)} new links")
            for name, typ in list(new_buttons.items())[:5]:
                print(f"      [{typ.upper()}] {name}")
            if len(new_buttons) > 5:
                print(f"      ... and {len(new_buttons) - 5} more buttons/tabs")
            for name, url in list(new_links.items())[:5]:
                print(f"      [LNK] {name} → {url}")
            if len(new_links) > 5:
                print(f"      ... and {len(new_links) - 5} more links")

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

        return states

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
    output_dir = Path(__file__).parent / 'extractions' / domain
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
