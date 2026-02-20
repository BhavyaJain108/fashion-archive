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

        if len(included) == 1:
            # Single container - use it
            best = included[0]
            selector = await _get_element_selector(page, best['el'], best['role'], best['idx'])
            print(f"    [ARIA-DIFF] Using single container: {best['role']}[{best['idx']}] ({best['size']} chars)")
            return best['aria'], selector, []

        # Multiple containers - check if nested or siblings
        # If one container's content is mostly contained in another, they're nested
        # Sort by size descending
        included_sorted = sorted(included, key=lambda c: c['size'], reverse=True)
        largest = included_sorted[0]
        largest_lines = set(largest['aria'].split('\n'))

        # Check each smaller container - if its content overlaps significantly with largest, it's nested
        siblings = [largest]
        for c in included_sorted[1:]:
            c_lines = set(c['aria'].split('\n'))
            overlap = len(c_lines & largest_lines) / len(c_lines) if c_lines else 1.0

            if overlap < 0.5:
                # Less than 50% overlap - this is a sibling with distinct content
                siblings.append(c)
                print(f"    [ARIA-DIFF] Including sibling: {c['role']}[{c['idx']}] ({c['size']} chars, {overlap:.0%} overlap)")
            else:
                print(f"    [ARIA-DIFF] Skipping nested: {c['role']}[{c['idx']}] ({overlap:.0%} overlap with largest)")

        if len(siblings) == 1:
            # All others were nested - use largest
            best = siblings[0]
            selector = await _get_element_selector(page, best['el'], best['role'], best['idx'])
            print(f"    [ARIA-DIFF] Using largest container: {best['role']}[{best['idx']}] ({best['size']} chars)")
            return best['aria'], selector, []
        else:
            # Multiple siblings - combine their ARIA
            combined_aria = '\n'.join(c['aria'] for c in siblings)
            # Use largest for selector
            selector = await _get_element_selector(page, largest['el'], largest['role'], largest['idx'])
            total_size = sum(c['size'] for c in siblings)
            print(f"    [ARIA-DIFF] Combined {len(siblings)} sibling containers ({total_size} chars total)")
            return combined_aria, selector, []

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


