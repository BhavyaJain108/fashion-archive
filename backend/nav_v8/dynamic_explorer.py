"""
Dynamic navigation explorer.

Explores menu by clicking buttons, captures state at each step.
Stores all states for later LLM processing.
"""

import asyncio
import base64
import json
import os
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
- LINK: Category Name | /url/path

RULES:
- BUTTON = expandable (will reveal subcategories)
- LINK = direct page (has URL)
- Only product categories (Women, Men, Kids, Shoes, Bags, etc.)
- IGNORE: Search, Cart, Login, Account, Language, Country
- IGNORE: About, Contact, FAQ, Careers, Legal, Newsletter
"""


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

def extract_buttons_from_aria(aria: str) -> set:
    """Extract all button names from ARIA."""
    import re
    buttons = set()
    for line in aria.split('\n'):
        btn_match = re.search(r'- button "([^"]+)"', line)
        if btn_match:
            name = btn_match.group(1)
            # Clean duplicated names like "Sweaters Sweaters"
            words = name.split()
            if len(words) >= 2 and len(words) % 2 == 0:
                half = len(words) // 2
                if words[:half] == words[half:]:
                    name = ' '.join(words[:half])
            buttons.add(name)
    return buttons


def extract_links_from_aria(aria: str) -> dict:
    """Extract all links from ARIA. Returns {name: url}."""
    import re
    links = {}
    for line in aria.split('\n'):
        # Match: - link "Text": followed by /url: path
        link_match = re.search(r'- link "([^"]+)"', line)
        if link_match:
            name = link_match.group(1).strip()
            # Look for URL on same line or next line
            url_match = re.search(r'/url:\s*([^\s]+)', line)
            if url_match:
                url = url_match.group(1)
                if name and url and len(name) < 100:
                    links[name] = url
    return links


def filter_utility_links(links: dict) -> dict:
    """Filter out utility/non-product links."""
    skip_patterns = [
        'login', 'cart', 'wishlist', 'account', 'saved',
        'faq', 'contact', 'careers', 'legal', 'privacy', 'cookie', 'terms',
        'facebook', 'instagram', 'tiktok', 'pinterest', 'linkedin', 'twitter',
        'tel:', 'mailto:', 'javascript:', '#',
        'track-order', 'returns', 'shipping', 'payment', 'newsletter',
        'store-locator', 'find-store', 'appointments'
    ]

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

        filtered[name] = url

    return filtered


def filter_utility_buttons(buttons: set) -> set:
    """Filter out utility/non-product buttons."""
    skip_buttons = {
        'back', 'close', 'search', 'login', 'cart', 'menu',
        'shipping to the us', 'change language', 'subscribe',
        'play', 'pause', 'mute', 'unmute',
        'chat support', 'cookie settings', 'link', 'chat', 'support',
        'cookies', 'settings', 'help', 'navigation'
    }

    filtered = set()
    for b in buttons:
        b_lower = b.lower()
        if b_lower in skip_buttons:
            continue
        if any(skip in b_lower for skip in skip_buttons):
            continue
        filtered.add(b)
    return filtered


# =============================================================================
# Navigation helpers
# =============================================================================

async def click_button(page: Page, name: str, container=None, prefer_tab: bool = False) -> bool:
    """Click a button by name, optionally scoped to a container."""
    search_context = container if container else page

    # Order of roles to try - tabs first if prefer_tab
    roles = ['tab', 'button', 'menuitem', 'link'] if prefer_tab else ['button', 'tab', 'menuitem', 'link']

    for role in roles:
        try:
            # Use exact=True for tabs to avoid 'men' matching 'women'
            use_exact = (role == 'tab')
            locator = search_context.get_by_role(role, name=name, exact=use_exact)
            count = await locator.count()
            if count > 0:
                # Find first VISIBLE element (some sites have duplicate hidden elements)
                for i in range(count):
                    element = locator.nth(i)
                    if await element.is_visible():
                        print(f"        [CLICK-DETAIL] Found '{name}' as {role} (#{i+1} of {count}, visible)")
                        await element.click()
                        await page.wait_for_timeout(150)
                        return True
                print(f"        [CLICK-DETAIL] Found '{name}' as {role} but none visible")
        except Exception as e:
            print(f"        [CLICK-DETAIL] Error with {role}: {e}")
            continue
    return False


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
    # Common patterns for menu opener buttons
    selectors = [
        # Hamburger menu patterns
        'button:has-text("menu")',
        'button:has-text("Menu")',
        '[aria-label*="menu" i]',
        '[aria-label*="navigation" i]',
        '[aria-label*="open" i]',
        '.hamburger',
        '.menu-toggle',
        '[class*="hamburger"]',
        '[class*="menu-button"]',
        '[class*="nav-toggle"]',
        # Category/Shop buttons
        'button:has-text("Category")',
        'button:has-text("Shop")',
        'button:has-text("Categories")',
        # Generic nav button
        'nav button',
        'header button:not([aria-label*="search" i]):not([aria-label*="cart" i])',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                if await locator.is_visible():
                    print(f"    [NAV] Opening menu with: {selector}")
                    await locator.click()
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


async def try_click_with_url_check(page: Page, name: str, container=None, prefer_tab: bool = False, skip_url_check: bool = False) -> tuple[bool, bool]:
    """
    Try to click an element and check if URL changed.
    Returns: (clicked: bool, navigated_away: bool)

    skip_url_check: For top-level tabs, URL may change but content updates in-place.
                    Set True to accept URL changes without going back.
    """
    url_before = page.url
    clicked = await click_button(page, name, container, prefer_tab=prefer_tab)
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
            await page.wait_for_timeout(500)
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
                           base_url: str) -> tuple[bool, bool]:
    """
    Navigate from current_path to target path efficiently.

    Learns and caches what strategy works at each level:
    - level_strategies[level] = 'direct' | 'back_button' | 'reclick' | 'reset'
    - back_buttons[level] = selector (if strategy is back_button)

    Fallback chain (only used when level not yet learned):
    1. Try clicking target directly
    2. If not found → use back button, retry
    3. If no back button → try clicking higher level element
    4. Last resort → reset menu with Escape

    Returns: (success: bool, navigated_away: bool)
    """
    # Special case: navigating to sibling at level 1 (same parent tab)
    # Don't re-click the tab - use back button to get to menu, then click target
    if (len(path) >= 2 and len(current_path) >= 2 and
        current_path[0].lower() == path[0].lower() and
        current_path[1].lower() != path[1].lower()):
        print(f"    [NAV] Sibling navigation: {current_path[1]} → {path[1]} (same tab: {path[0]})")
        # Use back button if we know it, or find it
        back_selector = back_buttons.get(1)
        if not back_selector:
            back_selector = await find_back_button(page)
            if back_selector:
                back_buttons[1] = back_selector
                print(f"    [NAV] Found back button: {back_selector}")

        if back_selector:
            try:
                # Find a VISIBLE back button (selector may match multiple elements)
                locator = page.locator(back_selector)
                count = await locator.count()
                clicked = False
                for i in range(count):
                    element = locator.nth(i)
                    if await element.is_visible():
                        await element.click()
                        await page.wait_for_timeout(400)
                        print(f"    [NAV] Clicked back button #{i+1} to return to {path[0]} menu")
                        clicked = True
                        break
                if not clicked:
                    print(f"    [NAV] Back button not visible, trying fallback...")
            except Exception as e:
                print(f"    [NAV] Back button failed: {e}")

        # Now click the target at level 1
        clicked, navigated = await try_click_with_url_check(page, path[1], prefer_tab=False, skip_url_check=False)
        if navigated:
            return False, True
        if clicked:
            return True, False
        # If failed, fall through to normal navigation

    for i, target in enumerate(path):
        level = i  # Level we're trying to reach
        # Use prefer_tab for top-level items (level 0) - they're often tabs in site headers
        prefer_tab = (level == 0)
        # For top-level tabs, URL changes are expected (don't go back)
        skip_url_check = prefer_tab

        # Check if we already know the strategy for this level
        known_strategy = level_strategies.get(level)

        if known_strategy == STRATEGY_DIRECT:
            # We know direct click works at this level
            clicked, navigated = await try_click_with_url_check(page, target, prefer_tab=prefer_tab, skip_url_check=skip_url_check)
            if navigated:
                return False, True
            if clicked:
                continue
            # Direct didn't work this time - clear cached strategy and rediscover
            print(f"    [NAV] Cached 'direct' failed for level {level}, rediscovering...")
            del level_strategies[level]
            known_strategy = None

        elif known_strategy == STRATEGY_BACK_BUTTON and level in back_buttons:
            # We know we need back button at this level
            print(f"    [NAV] Using cached back button for level {level}")
            try:
                await page.locator(back_buttons[level]).first.click()
                await page.wait_for_timeout(400)
            except:
                pass
            clicked, navigated = await try_click_with_url_check(page, target, prefer_tab=prefer_tab, skip_url_check=skip_url_check)
            if navigated:
                return False, True
            if clicked:
                continue
            # Back button didn't work - clear and rediscover
            print(f"    [NAV] Cached back button failed for level {level}, rediscovering...")
            del level_strategies[level]
            del back_buttons[level]
            known_strategy = None

        elif known_strategy == STRATEGY_RECLICK_PARENT and i > 0:
            # We know we need to re-click parent at this level
            print(f"    [NAV] Using cached 'reclick parent' for level {level}")
            parent_prefer_tab = (i - 1 == 0)
            parent_skip_url_check = parent_prefer_tab
            await try_click_with_url_check(page, path[i-1], prefer_tab=parent_prefer_tab, skip_url_check=parent_skip_url_check)
            clicked, navigated = await try_click_with_url_check(page, target, prefer_tab=prefer_tab, skip_url_check=skip_url_check)
            if navigated:
                return False, True
            if clicked:
                continue
            # Re-click didn't work - clear and rediscover
            print(f"    [NAV] Cached 'reclick' failed for level {level}, rediscovering...")
            del level_strategies[level]
            known_strategy = None

        elif known_strategy == STRATEGY_RESET:
            # We know we need full reset at this level
            print(f"    [NAV] Using cached 'reset' for level {level}")
            await page.keyboard.press('Escape')
            await page.wait_for_timeout(300)
            await open_menu(page)
            await page.wait_for_timeout(300)
            # Re-click from root
            for j in range(i + 1):
                j_prefer_tab = (j == 0)
                j_skip_url_check = j_prefer_tab
                clicked, navigated = await try_click_with_url_check(page, path[j], prefer_tab=j_prefer_tab, skip_url_check=j_skip_url_check)
                if navigated:
                    return False, True
                if not clicked:
                    return False, False
            continue

        # No cached strategy or it failed - discover what works
        if known_strategy is None:
            # Strategy 1: Try direct click
            clicked, navigated = await try_click_with_url_check(page, target, prefer_tab=prefer_tab, skip_url_check=skip_url_check)
            if navigated:
                return False, True
            if clicked:
                level_strategies[level] = STRATEGY_DIRECT
                print(f"    [NAV] Learned: level {level} uses 'direct'")
                continue

            print(f"    [NAV] '{target}' not found directly, trying fallbacks...")

            # Strategy 2: Look for back button
            back_selector = await find_back_button(page)
            if back_selector:
                print(f"    [NAV] Found back button, clicking and retrying...")
                try:
                    await page.locator(back_selector).first.click()
                    await page.wait_for_timeout(400)
                except:
                    pass

                clicked, navigated = await try_click_with_url_check(page, target, prefer_tab=prefer_tab, skip_url_check=skip_url_check)
                if navigated:
                    return False, True
                if clicked:
                    level_strategies[level] = STRATEGY_BACK_BUTTON
                    back_buttons[level] = back_selector
                    print(f"    [NAV] Learned: level {level} uses 'back_button' ({back_selector})")
                    continue

            # Strategy 3: Re-click parent
            if i > 0:
                print(f"    [NAV] Trying to re-click parent '{path[i-1]}'...")
                parent_prefer_tab = (i - 1 == 0)
                parent_skip_url_check = parent_prefer_tab
                clicked_parent, _ = await try_click_with_url_check(page, path[i-1], prefer_tab=parent_prefer_tab, skip_url_check=parent_skip_url_check)
                if clicked_parent:
                    clicked, navigated = await try_click_with_url_check(page, target, prefer_tab=prefer_tab, skip_url_check=skip_url_check)
                    if navigated:
                        return False, True
                    if clicked:
                        level_strategies[level] = STRATEGY_RECLICK_PARENT
                        print(f"    [NAV] Learned: level {level} uses 'reclick_parent'")
                        continue

            # Strategy 4: Full reset
            print(f"    [NAV] Resetting menu and clicking from root...")
            await page.keyboard.press('Escape')
            await page.wait_for_timeout(300)
            await open_menu(page)
            await page.wait_for_timeout(300)

            success = True
            for j in range(i + 1):
                j_prefer_tab = (j == 0)
                j_skip_url_check = j_prefer_tab
                clicked, navigated = await try_click_with_url_check(page, path[j], prefer_tab=j_prefer_tab, skip_url_check=j_skip_url_check)
                if navigated:
                    return False, True
                if not clicked:
                    print(f"    [NAV] Failed to click '{path[j]}' even after reset")
                    success = False
                    break

            if not success:
                return False, False

            level_strategies[level] = STRATEGY_RESET
            print(f"    [NAV] Learned: level {level} uses 'reset'")

    return True, False


# =============================================================================
# State capture
# =============================================================================

async def capture_state(page: Page, path: list, action: str, step: int,
                        new_buttons: set = None, new_links: dict = None,
                        capture_screenshot: bool = False) -> dict:
    """Capture current state after an action."""
    aria = await page.locator('body').aria_snapshot()

    screenshot_b64 = None
    if capture_screenshot:
        screenshot = await page.screenshot()
        screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')

    return {
        'step': step,
        'timestamp': datetime.now().isoformat(),
        'path': path.copy(),
        'action': action,
        'aria': aria,
        'screenshot_b64': screenshot_b64,
        'url': page.url,
        'new_buttons': list(new_buttons) if new_buttons else [],
        'new_links': new_links if new_links else {}
    }


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
    page = await browser.new_page()

    try:
        # Setup
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

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
        print(f"    Found {len(top_level)} items:")
        for item in top_level:
            t = f"[{'BTN' if item['type'] == 'button' else 'LNK'}] {item['name']}"
            if item.get('url'):
                t += f" → {item['url']}"
            print(f"      {t}")

        # Initialize stack with button paths to explore
        stack = []
        for item in top_level:
            if item['type'] == 'button':
                stack.append([item['name']])

        # Reverse for DFS (first item explored first)
        stack = list(reversed(stack))

        print(f"\n[5] Starting DFS exploration...")
        print(f"    Stack: {[s[-1] for s in stack]}")

        explored = set()  # Track what we've explored
        current_path = []  # Track where we currently are
        back_buttons = {}  # {level: selector} - learned back buttons
        level_strategies = {}  # {level: strategy} - learned nav strategies per level
        base_url = url  # For detecting navigation away

        while stack:
            path = stack.pop()
            path_key = tuple(path)

            # Skip if already explored or too deep
            if path_key in explored:
                continue
            if len(path) > max_depth:
                print(f"\n    SKIP (depth {len(path)}): {' > '.join(path)}")
                continue

            explored.add(path_key)

            print(f"\n{'='*60}")
            print(f"[{step}] EXPLORING: {' > '.join(path)}")
            print(f"    Current: {' > '.join(current_path) if current_path else '(root)'}")
            print(f"    Stack remaining: {len(stack)}")

            # Detect top-level category change - reset menu first for clean transition
            if current_path and path and current_path[0].lower() != path[0].lower():
                print(f"    [NAV] Top-level change: {current_path[0]} → {path[0]}, resetting menu")
                await page.keyboard.press('Escape')
                await page.wait_for_timeout(500)  # Wait for menu close animation
                # Check for popups that may have appeared during tab switch
                await dismiss_popups_with_llm(page)
                # Don't call open_menu - tabs are usually always visible in header
                # Clear cached navigation strategies since menu state changed
                level_strategies.clear()
                # Keep back_buttons - the back button selector should work across all tabs
                current_path = []  # We're now at root
                print(f"    [NAV] Menu reset complete, kept back button selectors")

            # Navigate to this path from current position
            success, navigated_away = await navigate_to_path(page, path, current_path, back_buttons, level_strategies, base_url)

            if navigated_away:
                # Clicking this item caused URL navigation - it's a link, not expandable
                print(f"    Item '{path[-1]}' is a link (navigated away), skipping")
                current_path = current_path  # Stay where we were
                continue

            if not success:
                print(f"    FAILED to navigate to: {' > '.join(path)}")
                # Reset menu and current_path since we don't know where we are
                await page.keyboard.press('Escape')
                await page.wait_for_timeout(300)
                await open_menu(page)
                await page.wait_for_timeout(300)
                current_path = []
                continue

            # Update current path
            current_path = path.copy()

            # Wait for menu to fully expand/animate before capturing state
            await page.wait_for_timeout(1000)

            # Check for popups that may have appeared (especially after navigating to new tab)
            if len(path) == 1:  # Top-level navigation - popups often appear here
                await dismiss_popups_with_llm(page)
                await page.wait_for_timeout(300)

            # Get ARIA for analysis
            aria = await page.locator('body').aria_snapshot()

            # Find new buttons (compared to initial state)
            current_buttons = extract_buttons_from_aria(aria)
            current_buttons = filter_utility_buttons(current_buttons)
            initial_buttons = extract_buttons_from_aria(states[0]['aria'])
            initial_buttons = filter_utility_buttons(initial_buttons)
            new_buttons = current_buttons - initial_buttons

            # Exclude buttons in our path (parent categories)
            path_buttons = set(p.lower() for p in path)
            new_buttons = {b for b in new_buttons if b.lower() not in path_buttons}

            # Find new links (compared to initial state)
            current_links = extract_links_from_aria(aria)
            current_links = filter_utility_links(current_links)
            initial_links = extract_links_from_aria(states[0]['aria'])
            initial_links = filter_utility_links(initial_links)
            new_links = {k: v for k, v in current_links.items() if k not in initial_links}

            # Capture state with discovered items
            action = f"clicked: {path[-1]}"
            state = await capture_state(page, path, action, step, new_buttons, new_links)
            states.append(state)

            print(f"    Found {len(new_buttons)} new buttons, {len(new_links)} new links")
            print(f"    [DEBUG] Total buttons in ARIA: {len(current_buttons)}, Initial: {len(initial_buttons)}")
            for btn in list(new_buttons)[:5]:
                print(f"      [BTN] {btn}")
            if len(new_buttons) > 5:
                print(f"      ... and {len(new_buttons) - 5} more buttons")
            for name, url in list(new_links.items())[:5]:
                print(f"      [LNK] {name} → {url}")
            if len(new_links) > 5:
                print(f"      ... and {len(new_links) - 5} more links")

            # Add new buttons to stack for further exploration (reversed for DFS order)
            # Sort alphabetically for consistent order, reverse so first item is explored first
            sorted_buttons = sorted(new_buttons)
            for btn in reversed(sorted_buttons):
                child_path = path + [btn]
                if tuple(child_path) not in explored:
                    stack.append(child_path)

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
