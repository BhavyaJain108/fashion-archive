"""
Step-by-step navigation explorer.

Simple DFS model:
1. Pop item from stack
2. Click it
3. Extract links + children
4. Push children to stack
5. Mark explored
"""
from dataclasses import dataclass, field
from typing import Optional
from playwright.async_api import Page
from pydantic import BaseModel, Field

from scraper.navigation.extraction.nav_elements import extract_and_filter_nav_elements
from scraper.navigation.llm.client import get_llm_handler
from scraper.navigation.dynamic_explorer import (
    open_menu_and_capture,
    click_button,
    identify_tabs_with_llm,
    find_tabs_in_dom,
)
from scraper.navigation.llm_popup_dismiss import dismiss_popups_with_llm
from scraper.navigation.llm.classification import classify_button_relationships_batch


class BackButtonIdentification(BaseModel):
    """Response format for back button identification."""
    back_button_index: int = Field(
        description="1-indexed number of the button that is most likely the back/close button, or 0 if none"
    )


@dataclass
class StepResult:
    """Result of a single step."""
    success: bool
    action: str
    item_name: str
    item_path: list[str]
    links_found: dict = field(default_factory=dict)
    children_added: int = 0
    error: str = None


class NavExplorer:
    """
    Simple DFS navigation explorer.

    Usage:
        explorer = NavExplorer(page)
        await explorer.setup(url)

        while not explorer.done():
            result = await explorer.step()
            print(result)
    """

    def __init__(self, page: Page):
        self.page = page
        self.base_url: str = None
        self.menu_selector: str = None

        # DFS state
        self.stack: list[tuple] = []  # [(path, name, role, expands_info, is_tab), ...] where expands_info is None or {'link_name': str, 'link_url': str}
        self.explored: set = set()    # path tuples we've clicked
        self.categories: dict = {}    # path_key -> url

        # Tab tracking
        self.tabs: list = []
        self.current_tab: str = None

        # CSS cache per (tab, depth) - different tabs may have different CSS
        self.css_cache: dict = {}  # (tab, depth) -> nav_css_classes

        # Back button cache (reset on tab switch)
        self.back_button_selector: str = None

        # LLM exclusion cache per depth level (CSS classes reused differently at each level)
        self.excluded_groups_cache: dict = {}  # {depth: set of excluded groups}


    def _add_to_tree(self, path: list[str], name: str, url: str):
        """Add a link to the categories tree."""
        key = ' > '.join(path + [name])
        self.categories[key] = url

    def _has_children(self, path: list[str], name: str) -> bool:
        """Check if an expandable already has children in the tree."""
        prefix = ' > '.join(path + [name]) + ' > '
        for key in self.categories:
            if key.startswith(prefix):
                return True
        return False

    async def setup(self, url: str) -> dict:
        """Navigate, open menu, detect structure, build initial stack."""
        self.base_url = url

        print(f"[SETUP] Navigating to {url}")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self.page.wait_for_timeout(1500)

        # Dismiss popups
        print("[SETUP] Dismissing popups...")
        await dismiss_popups_with_llm(self.page, max_attempts=2)

        # Open menu
        print("[SETUP] Opening menu...")
        menu_result = await open_menu_and_capture(self.page)

        if not menu_result.get('opened'):
            return {'success': False, 'error': 'Could not open menu'}

        self.menu_selector = menu_result.get('menu_container_selector')
        menu_aria = menu_result.get('menu_aria', '')

        print(f"[SETUP] Menu opened ({len(menu_aria)} chars)")
        print(f"[SETUP] Menu selector: {self.menu_selector}")

        # Dismiss popups after menu open (with menu_is_open=True to skip risky selectors)
        popups_dismissed = await dismiss_popups_with_llm(self.page, max_attempts=1, menu_is_open=True)

        # Only check if menu closed if we actually clicked something
        # When popups_dismissed=0 and menu_is_open=True, we skipped all risky operations
        if popups_dismissed > 0 and not await self._is_menu_open():
            print("[SETUP] Menu closed after popup dismissal, reopening...")
            menu_result = await open_menu_and_capture(self.page)
            if not menu_result.get('opened'):
                return {'success': False, 'error': 'Could not reopen menu'}
            self.menu_selector = menu_result.get('menu_container_selector')
            menu_aria = menu_result.get('menu_aria', '')
            print(f"[SETUP] Menu reopened ({len(menu_aria)} chars)")

        # Detect tabs
        print("[SETUP] Detecting tabs...")
        llm_result = await identify_tabs_with_llm(self.page, menu_aria)
        tab_names = llm_result.get('tab_names', [])

        if tab_names:
            dom_result = await find_tabs_in_dom(self.page, tab_names, menu_aria)
            if dom_result.get('found'):
                self.tabs = dom_result['tabs']
                print(f"[SETUP] Found tabs: {[t['text'] for t in self.tabs]}")

                # Add tabs to stack (reversed so first tab is on top)
                for tab in reversed(self.tabs):
                    path = [tab['text']]
                    self.stack.append((path, tab['text'], tab['role'], None, True))  # is_tab=True
            else:
                print("[SETUP] Could not find tabs in DOM")

        # If no tabs, analyze menu content now
        if not self.tabs:
            print("[SETUP] No tabs - analyzing menu content...")
            print(f"[SETUP] Menu ARIA ({len(menu_aria)} chars):")
            for line in menu_aria.splitlines():
                print(f"  {line}")

            # Extract all nav elements with CSS grouping and LLM filtering
            result = await extract_and_filter_nav_elements(
                self.page, menu_aria, self.menu_selector
            )
            elements = result['elements']
            # Store at depth 1 (root menu level, same as tab level)
            if result['excluded_groups']:
                self.excluded_groups_cache[1] = result['excluded_groups']

            # Collect button-link pairs for batch classification
            pairs_to_classify = []
            for el in elements:
                if el['type'] in ('button', 'tab', 'menuitem'):
                    nearby_link = el.get('nearby_link')
                    if nearby_link:
                        pairs_to_classify.append((el['name'], nearby_link))

            # Batch classify all pairs (one LLM call)
            classifications = {}
            if pairs_to_classify:
                classifications = await classify_button_relationships_batch(pairs_to_classify)

            # Process elements in DOM order
            links_added = 0
            expandables_added = 0

            for el in elements:
                name = el['name']
                parent = el['parent']
                path = [parent] if parent else []

                if el['type'] == 'link':
                    # Add link to tree
                    self._add_to_tree(path, name, el['url'])
                    links_added += 1

                elif el['type'] in ('button', 'tab', 'menuitem'):
                    # Check if button expands a nearby link's category
                    nearby_link = el.get('nearby_link')
                    nearby_link_url = el.get('nearby_link_url')
                    expands_info = None

                    # If expandable itself has a URL (link with chevron icon), record it
                    if el.get('url'):
                        self._add_to_tree(path, name, el['url'])
                        links_added += 1
                        print(f"[SETUP] Expandable '{name}' has URL: {el['url']}")

                    if nearby_link:
                        # Use batch classification result
                        relationship = classifications.get(name, 'SEPARATE')
                        if relationship == 'EXPANDS':
                            print(f"[SETUP] Button '{name}' EXPANDS link '{nearby_link}'")
                            # Button expands the link - children attach to the link node
                            expands_info = {
                                'link_name': nearby_link,
                                'link_url': nearby_link_url
                            }
                            # Also add the link itself to the tree (it's a category)
                            self._add_to_tree(path, nearby_link, nearby_link_url)
                            links_added += 1

                    # Check if expandable already has children in tree
                    if not self._has_children(path, name):
                        # No children yet, add to stack
                        # Use aria_role for clicking (actual DOM role), not logical type
                        full_path = path + [name]
                        click_role = el.get('aria_role', el['type'])
                        self.stack.append((full_path, name, click_role, expands_info, False))  # is_tab=False
                        expandables_added += 1
                        print(f"[SETUP] Expandable '{name}': added to stack")
                    else:
                        print(f"[SETUP] Expandable '{name}': already has children, skipping")

            print(f"[SETUP] Total: {links_added} links, {expandables_added} expandables")

        print(f"[SETUP] Stack: {[name for _, name, _, _, _ in self.stack]}")
        return {'success': True, 'stack_size': len(self.stack)}

    async def _get_aria(self) -> str:
        """Get ARIA from menu container or body."""
        # Try stored selector first
        if self.menu_selector:
            try:
                el = self.page.locator(self.menu_selector).first
                if await el.count() > 0:
                    aria = await el.aria_snapshot()
                    if aria and 'link' in aria.lower():
                        return aria
            except:
                pass

        # Fallback: try common menu container patterns
        for selector in ['[role="dialog"]', '[role="navigation"]', 'nav', '[class*="menu"][class*="drawer"]']:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0 and await el.is_visible():
                    aria = await el.aria_snapshot()
                    # Must have links to be a menu
                    if aria and 'link' in aria.lower() and len(aria) > 200:
                        print(f"  [ARIA] Using fallback container: {selector}")
                        self.menu_selector = selector  # Cache for future
                        return aria
            except:
                continue

        # Last resort: body
        print(f"  [ARIA] WARNING: No menu container found, using body")
        return await self.page.locator('body').aria_snapshot()

    async def _is_menu_open(self) -> bool:
        """Check if menu is currently open."""
        if self.menu_selector:
            try:
                el = self.page.locator(self.menu_selector).first
                if await el.count() > 0 and await el.is_visible():
                    return True
            except:
                pass
        return False

    async def _ensure_menu_open(self) -> bool:
        """Ensure menu is open, reopen if closed."""
        if await self._is_menu_open():
            return True

        # Menu closed - reopen it
        print(f"  [MENU] Reopening menu...")
        menu_result = await open_menu_and_capture(self.page)
        if menu_result.get('opened'):
            self.menu_selector = menu_result.get('menu_container_selector')
            print(f"  [MENU] Reopened")
            return True
        else:
            print(f"  [MENU] Failed to reopen")
            return False

    async def _click_back(self) -> bool:
        """Click back button to return to parent level."""
        # Try stored element first (from fallback detection)
        if hasattr(self, '_back_button_element') and self._back_button_element:
            try:
                await self._back_button_element.click(timeout=3000, force=True)
                await self.page.wait_for_timeout(100)
                print(f"    [BACK] Clicked stored element")
                return True
            except Exception as e:
                print(f"    [BACK] Stored element click failed: {e}")
                self._back_button_element = None

        # Search within menu container only
        container = self.page.locator(self.menu_selector) if self.menu_selector else self.page

        if self.back_button_selector:
            try:
                loc = container.locator(self.back_button_selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000, force=True)
                    await self.page.wait_for_timeout(100)
                    print(f"    [BACK] Clicked: {self.back_button_selector}")
                    return True
                else:
                    print(f"    [BACK] Selector not found in menu")
                    self.back_button_selector = None
            except Exception as e:
                print(f"    [BACK] Click failed: {e}")
                self.back_button_selector = None

        # Find back button within menu (not carousel controls)
        back_sel = await self._find_menu_back_button(container)
        if back_sel:
            self.back_button_selector = back_sel
            try:
                loc = container.locator(back_sel).first
                await loc.click(timeout=3000, force=True)
                await self.page.wait_for_timeout(100)
                print(f"    [BACK] Found and clicked: {back_sel}")
                return True
            except Exception as e:
                print(f"    [BACK] Click failed: {e}")
                self.back_button_selector = None

        print(f"    [BACK] No back button found in menu")
        return False

    async def _find_menu_back_button(self, container) -> str | None:
        """Find back button within menu container or nearby, excluding carousel controls."""
        # Menu-specific back button patterns (not carousel)
        selectors = [
            # SVG chevron/arrow patterns (most common in mobile menus)
            'button:has(svg[class*="chevron-left"])',
            'button:has(svg[class*="arrow-left"])',
            # Text patterns
            'button:has-text("Back")',
            'button:has-text("← ")',
            'button:has-text("‹")',
            # Aria patterns - but NOT carousel
            'button[aria-label^="Back"]',  # Starts with "Back"
            'button[aria-label="Back"]',
            'button[aria-label*="go back" i]',
            'button[aria-label*="return" i]:not([aria-label*="carousel" i])',
            # Class patterns
            'button[class*="back"]:not([class*="carousel"])',
            '[data-testid*="back"]',
        ]

        # First search inside the menu container
        for selector in selectors:
            try:
                loc = container.locator(selector).first
                if await loc.count() > 0:
                    # Verify it's not a carousel control
                    aria_label = await loc.get_attribute('aria-label') or ''
                    if 'carousel' not in aria_label.lower() and 'slider' not in aria_label.lower():
                        return selector
            except:
                continue

        # If not found inside, try parent container (back button often near menu borders)
        if self.menu_selector:
            try:
                # Get parent of menu container
                parent = self.page.locator(f'{self.menu_selector} >> xpath=..')
                if await parent.count() > 0:
                    for selector in selectors:
                        try:
                            loc = parent.locator(selector).first
                            if await loc.count() > 0:
                                aria_label = await loc.get_attribute('aria-label') or ''
                                if 'carousel' not in aria_label.lower() and 'slider' not in aria_label.lower():
                                    print(f"    [BACK] Found in parent container: {selector}")
                                    return selector
                        except:
                            continue
            except:
                pass

        return None

    async def _identify_back_button_with_llm(self, candidates: list):
        """
        Use LLM to identify which icon-only button is the back/close button.

        Args:
            candidates: List of Playwright locator elements (icon-only buttons)

        Returns:
            The identified back button element, or None if not found
        """
        if not candidates:
            return None

        # Get outer HTML for each candidate
        button_descriptions = []
        for i, btn in enumerate(candidates):
            try:
                outer_html = await btn.evaluate("el => el.outerHTML")
                # Truncate long HTML
                if len(outer_html) > 500:
                    outer_html = outer_html[:500] + "..."
                button_descriptions.append(f"{i+1}. {outer_html}")
            except Exception as e:
                button_descriptions.append(f"{i+1}. [Could not get HTML: {e}]")

        prompt = f"""In a mobile navigation menu, identify which button is the BACK or CLOSE button.

These are icon-only buttons (SVG icons, no text):

{chr(10).join(button_descriptions)}

Which button is most likely the back/close button for navigating back in the menu?
Look for:
- Arrow or chevron pointing left (back)
- X or close icon
- Class names containing "back", "close", "prev", "return"

Return the 1-indexed number of the back button, or 0 if none of these is a back button."""

        try:
            llm = get_llm_handler()
            result = llm.call(
                prompt,
                expected_format="json",
                response_model=BackButtonIdentification,
                max_tokens=50,
                operation="identify_back_button"
            )

            if result.get('success') and result.get('data'):
                idx = result['data'].get('back_button_index', 0)
                print(f"    [LLM] Back button identification: index={idx}")

                if idx > 0 and idx <= len(candidates):
                    return candidates[idx - 1]  # Convert to 0-indexed
            else:
                print(f"    [LLM] Back button identification failed: {result.get('error', 'unknown')}")

        except Exception as e:
            print(f"    [LLM] Error identifying back button: {e}")

        return None

    async def _recover_navigation(self, target_path: list, target_role: str, skip_back: bool = False) -> bool:
        """
        Try to recover navigation state.
        Strategy:
        1. Try back button (unless skip_back=True)
        2. If that fails: refresh page → open menu → click tab → navigate path
        Returns True if recovery was successful.
        """
        # Try clicking back button first (unless we already know it failed)
        if not skip_back:
            if await self._click_back():
                print(f"  [RECOVER] Back button worked")
                return True

        # Full recovery: refresh page, reopen menu, navigate to target
        print(f"  [RECOVER] Full recovery: refreshing page...")

        # Refresh page
        try:
            await self.page.goto(self.base_url, wait_until="load", timeout=15000)
            await self.page.wait_for_timeout(1000)
        except Exception as e:
            print(f"  [RECOVER] Refresh failed: {e}")
            return False

        # Dismiss popups
        await dismiss_popups_with_llm(self.page, max_attempts=1)

        # Reopen menu
        print(f"  [RECOVER] Reopening menu...")
        menu_result = await open_menu_and_capture(self.page)
        if not menu_result.get('opened'):
            print(f"  [RECOVER] Could not reopen menu")
            return False

        self.menu_selector = menu_result.get('menu_container_selector')
        self.back_button_selector = None  # Clear back button cache

        # Click tab if we have one
        if self.current_tab:
            print(f"  [RECOVER] Clicking tab '{self.current_tab}'")
            await click_button(self.page, self.current_tab, prefer_role='tab')
            await self.page.wait_for_timeout(100)

        # Navigate down to target path (skip tab if it's first in path)
        for i, item_name in enumerate(target_path[:-1]):
            if i == 0 and self.current_tab and item_name == self.current_tab:
                continue  # Skip tab itself, already clicked
            print(f"  [RECOVER] Navigating to '{item_name}'")
            clicked = await click_button(self.page, item_name, prefer_role='button')
            if not clicked:
                print(f"  [RECOVER] Could not navigate to '{item_name}'")
                return False
            await self.page.wait_for_timeout(100)

        print(f"  [RECOVER] Recovery complete, ready for '{target_path[-1]}'")
        return True

    def done(self) -> bool:
        """Check if exploration is complete."""
        return len(self.stack) == 0

    async def step(self) -> StepResult:
        """
        Execute one step:
        1. Pop item from stack
        2. Click it
        3. Extract links + children
        4. Push children
        5. Mark explored
        """
        if not self.stack:
            return StepResult(
                success=False,
                action='done',
                item_name='',
                item_path=[],
                error='Stack empty'
            )

        # Pop item
        path, item_name, role, expands_info, is_tab = self.stack.pop()
        path_key = tuple(path)

        # Check if this button expands a link - if so, children attach to link's node
        target_path = path  # Default: use button's path
        if expands_info:
            link_name = expands_info['link_name']
            # Replace button name with link name in path
            # e.g., ['See More'] -> ['SHOP ALL']
            if path and path[-1] == item_name:
                target_path = path[:-1] + [link_name]
                print(f"  [EXPANDS] '{item_name}' expands '{link_name}' - children attach to '{link_name}'")

        # Skip if already explored
        if path_key in self.explored:
            return StepResult(
                success=True,
                action='skip',
                item_name=item_name,
                item_path=path,
                error='Already explored'
            )

        print(f"\n[STEP] {' > '.join(path)} ({role})", flush=True)
        print(f"  Stack: {len(self.stack)} remaining", flush=True)

        # is_tab was stored in stack when item was added
        is_tab_switch = is_tab

        # Track current tab - reset state when switching
        if is_tab_switch:
            self.current_tab = item_name
            self.back_button_selector = None  # Clear back button cache for new tab
            print(f"  [TAB] Switching to: {item_name}")

            # Ensure menu is open before clicking tab
            await self._ensure_menu_open()

        # CSS exclusion cache is per-depth (CSS classes reused differently at each level)
        depth = len(path)
        depth_cache = self.excluded_groups_cache.get(depth)

        # For TABS: skip BEFORE capture - we want ALL content, no diff
        # For EXPANDABLES: capture BEFORE for diff
        elements_before = []
        if not is_tab_switch:
            aria_before = await self._get_aria()
            print(f"  [ARIA BEFORE] {len(aria_before)} chars, {len(aria_before.splitlines())} lines")
            # Print ARIA for debugging
            for line in aria_before.splitlines():
                print(f"    {line}")

            # Extract nav elements from BEFORE (for diff)
            result_before = await extract_and_filter_nav_elements(
                self.page, aria_before, self.menu_selector,
                excluded_groups_cache=depth_cache
            )
            elements_before = result_before['elements']

        # Click the item (with recovery for submenu navigation)
        url_before = self.page.url
        print(f"  [CLICK] {item_name}")
        clicked = await click_button(self.page, item_name, prefer_role=role)

        if not clicked:
            # For submenu navigation (back button exists), try full recovery
            # For in-place expansion, skip recovery - menu state unchanged
            if self.back_button_selector:
                recovered = await self._recover_navigation(path, role)
                if recovered:
                    # Retry click after recovery
                    clicked = await click_button(self.page, item_name, prefer_role=role)

            if not clicked:
                return StepResult(
                    success=False,
                    action='click',
                    item_name=item_name,
                    item_path=path,
                    error=f"Could not click '{item_name}'"
                )

        await self.page.wait_for_timeout(100)

        # Check if click caused navigation (URL changed)
        # For tabs, URL might change (hash or query params) - that's expected
        # For expandables, URL should NOT change - if it did, we navigated away
        url_after = self.page.url
        if role != 'tab' and url_after != url_before:
            print(f"  [URL-CHANGE] Click navigated away: {url_before} → {url_after}")
            print(f"  [RECOVER] Resetting menu state...")
            await self._recover_navigation(path[:-1] if len(path) > 1 else path, role)
            # Skip this item - it's a link, not an expandable
            return StepResult(
                success=False,
                action='click',
                item_name=item_name,
                item_path=path,
                error=f"'{item_name}' navigated away (link, not expandable)"
            )

        # Detect back button when entering submenu (not for tabs)
        entered_submenu = False
        is_in_place_expansion = False
        if role != 'tab' and not self.back_button_selector:
            container = self.page.locator(self.menu_selector) if self.menu_selector else self.page
            back_sel = await self._find_menu_back_button(container)
            if back_sel:
                self.back_button_selector = back_sel
                entered_submenu = True
                print(f"  [BACK] Detected: {back_sel}")
            else:
                is_in_place_expansion = True
                print(f"  [EXPAND] Content expanded in place (no back button)")

        # Get ARIA after and extract elements
        aria_after = await self._get_aria()
        print(f"  [ARIA AFTER] {len(aria_after)} chars, {len(aria_after.splitlines())} lines")
        # Print ARIA for debugging
        for line in aria_after.splitlines():
            print(f"    {line}")

        # Extract nav elements from AFTER
        result_after = await extract_and_filter_nav_elements(
            self.page, aria_after, self.menu_selector,
            excluded_groups_cache=depth_cache
        )
        elements_after = result_after['elements']

        # Update cache for this depth if we got new exclusions
        if result_after['excluded_groups']:
            self.excluded_groups_cache[depth] = result_after['excluded_groups']

        # Build sets for diff
        # - Tab switch: capture all content (no diff) - is_tab_switch already set above
        # - Submenu navigation (back button exists): position-based diff (old content hidden)
        # - In-place expansion (no back button): context-based diff (name + parent/nearby_link)
        use_position_diff = self.back_button_selector is not None

        if is_tab_switch:
            existing_positions = set()
            existing_contexts = set()
            print(f"  [TAB-SWITCH] Capturing all content (no diff)")
        elif use_position_diff:
            # Submenu navigation: old content is hidden, use position-based diff
            existing_positions = {(el['name'], el.get('dom_index', -1)) for el in elements_before}
            existing_contexts = set()  # Not used for position-based
            print(f"  [SUBMENU] Using position-based diff (back button detected)")
        else:
            # In-place expansion: old content pushed down, use context-based diff
            # (name, context) where context = parent or nearby_link - so "See More" under
            # different categories are treated as different elements
            existing_positions = set()  # Not used for context-based
            existing_contexts = {
                (el['name'], el.get('parent') or el.get('nearby_link') or '')
                for el in elements_before
            }
            print(f"  [IN-PLACE] Using context-based diff (name + parent/nearby_link)")

        # Calculate new elements based on diff strategy
        new_elements = []
        for el in elements_after:
            if use_position_diff or is_tab_switch:
                # Position-based: element is new if (name, index) pair is new
                pos = (el['name'], el.get('dom_index', -1))
                if pos not in existing_positions:
                    new_elements.append(el)
            else:
                # Context-based: element is new if (name, context) pair is new
                ctx = (el['name'], el.get('parent') or el.get('nearby_link') or '')
                if ctx not in existing_contexts:
                    new_elements.append(el)

        if is_tab_switch:
            diff_method = "tab-switch"
        elif use_position_diff:
            diff_method = "position"
        else:
            diff_method = "context"
        print(f"  [DIFF] {len(new_elements)} new elements (by {diff_method}):")
        for el in new_elements[:15]:
            idx = el.get('dom_index', '?')
            print(f"    [{el['type']}] {el['name']} (idx:{idx}, near:{el.get('nearby_link')})")
        if len(new_elements) > 15:
            print(f"    ... +{len(new_elements) - 15} more")

        # Batch classify button-link pairs for new expandables
        pairs_to_classify = []
        for el in new_elements:
            if el['type'] in ('button', 'tab', 'menuitem'):
                nearby_link = el.get('nearby_link')
                if nearby_link:
                    pairs_to_classify.append((el['name'], nearby_link))

        classifications = {}
        if pairs_to_classify:
            classifications = await classify_button_relationships_batch(pairs_to_classify)

        # Process elements: add links to tree first, then check expandables
        added_to_stack = 0
        total_links_added = 0
        new_links = []
        pending_expandables = []  # Defer stack decision until all links added

        # Build set of (name, role) tuples for tabs (tabs are root-level only, never children)
        tab_identifiers = {(t['text'], t['role']) for t in self.tabs} if self.tabs else set()

        for el in elements_after:
            name = el['name']
            el_type = el['type']

            # Skip tabs - exact name AND type match (tabs are root-level only)
            if (name, el_type) in tab_identifiers:
                continue

            # Skip if element existed before (using same diff strategy as above)
            # Tab switch: capture all (no skipping based on diff)
            if not is_tab_switch:
                if use_position_diff:
                    # Position-based: skip if same (name, index) existed
                    el_position = (name, el.get('dom_index', -1))
                    if el_position in existing_positions:
                        continue
                else:
                    # Context-based: skip if same (name, context) existed
                    ctx = (name, el.get('parent') or el.get('nearby_link') or '')
                    if ctx in existing_contexts:
                        continue

            # Skip expandables that are inside the back button element (only for NEW elements)
            # Skip if back_button_selector is '_element' (signal value, not a real selector)
            if self.back_button_selector and self.back_button_selector != '_element' and el_type != 'link':
                try:
                    container = self.page.locator(self.menu_selector) if self.menu_selector else self.page
                    back_btn = container.locator(self.back_button_selector).first
                    back_btn_text = await back_btn.text_content() or ''
                    if name in back_btn_text:
                        print(f"  [SKIP] '{name}' is inside back button (text: '{back_btn_text.strip()}')")
                        continue
                except:
                    pass

            # When switching tabs, ignore ARIA parent - use tab as root
            # This prevents "Kids" bleeding into "Women > Kids > ..."
            if is_tab_switch:
                parent = None
            else:
                parent = el['parent']

            # Use target_path (link's path if button expands a link)
            el_path = target_path + ([parent] if parent else [])

            if el['type'] == 'link':
                # Add link to tree
                self._add_to_tree(el_path, name, el['url'])
                total_links_added += 1
                new_links.append({'name': name, 'url': el['url']})
                print(f"  [NAV] Link: {name}", flush=True)

            elif el['type'] in ('button', 'tab', 'menuitem'):
                # Check if button expands a nearby link's category
                nearby_link = el.get('nearby_link')
                nearby_link_url = el.get('nearby_link_url')
                expands_info = None

                # If expandable itself has a URL (link with chevron icon), record it
                if el.get('url'):
                    self._add_to_tree(el_path, name, el['url'])
                    total_links_added += 1
                    new_links.append({'name': name, 'url': el['url']})
                    print(f"  [NAV] Expandable+Link: {name} (URL: {el['url']})", flush=True)

                if nearby_link:
                    # Use batch classification result
                    relationship = classifications.get(name, 'SEPARATE')
                    if relationship == 'EXPANDS':
                        print(f"  [CLASSIFY] Button '{name}' EXPANDS link '{nearby_link}'")
                        # Button expands the link - children attach to the link node
                        expands_info = {
                            'link_name': nearby_link,
                            'link_url': nearby_link_url
                        }
                        # Also add the link itself to the tree (it's a category)
                        self._add_to_tree(el_path, nearby_link, nearby_link_url)
                        total_links_added += 1

                # Collect expandable for later - check _has_children after all links added
                pending_expandables.append({
                    'name': name,
                    'el_path': el_path,
                    'click_role': el.get('aria_role', el['type']),
                    'expands_info': expands_info
                })

        # Now check expandables - tree has all links, _has_children works correctly
        for exp in pending_expandables:
            if not self._has_children(exp['el_path'], exp['name']):
                full_path = exp['el_path'] + [exp['name']]
                self.stack.append((full_path, exp['name'], exp['click_role'], exp['expands_info'], False))  # is_tab=False
                added_to_stack += 1
                print(f"  [NAV] Expandable: {exp['name']} (added to stack)", flush=True)
            else:
                print(f"  [NAV] Expandable: {exp['name']} (has children, skipped)", flush=True)

        print(f"  [NAV] Total: {total_links_added} links added, {added_to_stack} expandables queued", flush=True)
        print(f"  [TREE] Total categories: {len(self.categories)}", flush=True)

        # Fallback: if no back button found, look for icon-only buttons not in discovered elements
        # Skip if we already determined it's in-place expansion (no back button needed)
        if role != 'tab' and not self.back_button_selector and not is_in_place_expansion:
            discovered_names = {el['name'] for el in elements_after}
            container = self.page.locator(self.menu_selector) if self.menu_selector else self.page
            try:
                icon_buttons = await container.locator('button:has(svg)').all()
                candidates = []
                for btn in icon_buttons:
                    text = (await btn.text_content() or '').strip()
                    if not text or len(text) < 2:
                        aria_label = await btn.get_attribute('aria-label') or ''
                        if aria_label not in discovered_names:
                            candidates.append(btn)

                print(f"  [BACK] Fallback: {len(icon_buttons)} icon buttons, {len(candidates)} candidates")
                if len(candidates) == 1:
                    self._back_button_element = candidates[0]
                    self.back_button_selector = '_element'  # Signal that we have a back button
                    print(f"  [BACK] Found single icon-only button as fallback")
                elif len(candidates) > 1:
                    # Multiple candidates - ask LLM to identify back button
                    back_btn = await self._identify_back_button_with_llm(candidates)
                    if back_btn:
                        self._back_button_element = back_btn
                        self.back_button_selector = '_element'  # Signal that we have a back button
                        print(f"  [BACK] LLM identified back button")
            except Exception as e:
                print(f"  [BACK] Fallback search failed: {e}")

        children = [None] * added_to_stack  # For stack print count

        print(f"  [STACK] Added {len(children)} (LIFO - last added = next to pop)", flush=True)
        print(f"  [STACK] ({len(self.stack)} items, top first):", flush=True)
        # Print stack in reverse (top = last = next to pop)
        for i, (p, n, r, _, _) in enumerate(reversed(self.stack)):
            path_str = ' > '.join(p)
            role_tag = f" [{r}]" if r == 'tab' else ""
            marker = "→ " if i == 0 else "  "
            print(f"    {marker}{path_str}{role_tag}", flush=True)

        # Mark explored
        self.explored.add(path_key)

        # Go back if next item is at same or shallower depth (not a child we just pushed)
        # Skip for in-place expansion - no back button needed, all content still visible
        if self.stack and len(children) == 0 and self.back_button_selector:
            next_path, _, next_role, _, _ = self.stack[-1]

            if next_role == 'tab':
                # Next is a tab - go back to level 1 (tab level)
                # From Women > Gift Cards (depth 2) → need 1 back to reach tab level
                backs_needed = len(path) - 1
            else:
                # Calculate how many levels to go back for siblings
                # Current: Women > Clothing > Dresses (depth 3)
                # Next: Women > Trending (depth 2) → go back 2 levels
                # Next: Women > Clothing > Tops (depth 3, sibling) → go back 1 level
                backs_needed = len(path) - len(next_path) + 1

            if backs_needed > 0:
                print(f"  [BACK] Going back {backs_needed} level(s) to reach '{next_path[-1]}'")
                back_failed = False
                for _ in range(backs_needed):
                    if not await self._click_back():
                        back_failed = True
                        break

                # If back button failed, recover now (reopen menu, navigate to target)
                if back_failed:
                    print(f"  [RECOVER] Back button failed, recovering to reach '{next_path[-1]}'")
                    await self._recover_navigation(next_path, next_role, skip_back=True)

        return StepResult(
            success=True,
            action='click',
            item_name=item_name,
            item_path=path,
            links_found={l['name']: l['url'] for l in new_links},
            children_added=len(children)
        )

    def show_state(self):
        """Print current state."""
        print(f"\n{'='*50}")
        print(f"Stack: {len(self.stack)}")
        for path, name, role, _, _ in self.stack[-5:]:
            print(f"  [{role}] {' > '.join(path)}")
        if len(self.stack) > 5:
            print(f"  ... +{len(self.stack)-5} more")
        print(f"Explored: {len(self.explored)}")
        print(f"Categories: {len(self.categories)}")
        print(f"{'='*50}")

    def print_tree(self):
        """Print categories as tree."""
        if not self.categories:
            print("No categories found")
            return

        # Build tree where each node is {'_url': url, 'children': {...}}
        tree = {}
        for key, url in self.categories.items():
            parts = key.split(' > ')
            node = tree
            for part in parts[:-1]:
                if part not in node:
                    node[part] = {'_url': None, '_children': {}}
                elif isinstance(node[part], str):
                    # Convert leaf to node with children
                    node[part] = {'_url': node[part], '_children': {}}
                node = node[part]['_children']

            last = parts[-1]
            if last in node and isinstance(node[last], dict):
                # Already a node with children, just set URL
                node[last]['_url'] = url
            else:
                node[last] = url

        def print_node(d, prefix=''):
            items = list(d.items())
            for i, (k, v) in enumerate(items):
                is_last = i == len(items) - 1
                connector = '└── ' if is_last else '├── '
                child_prefix = prefix + ('    ' if is_last else '│   ')

                if isinstance(v, str):
                    # Leaf node with URL
                    print(f"{prefix}{connector}{k} → {v}")
                elif isinstance(v, dict):
                    # Node with possible URL and children
                    url = v.get('_url', '')
                    children = v.get('_children', {})
                    url_str = f" → {url}" if url else ""
                    print(f"{prefix}{connector}{k}{url_str}")
                    if children:
                        print_node(children, child_prefix)

        print(f"\n[TREE] {len(self.categories)} categories")
        print_node(tree)
