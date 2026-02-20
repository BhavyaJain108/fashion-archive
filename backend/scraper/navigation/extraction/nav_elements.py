"""
Navigation element extraction with CSS grouping and LLM filtering.

Flow:
1. Parse ARIA for all links + expandables with hierarchy
2. Get CSS class for each element via DIRECT DOM lookup (not separate scan)
3. Group by CSS class
4. LLM excludes utility groups (language, country, etc.)
5. Filter elements whose CSS class is excluded
6. Return filtered elements

CRITICAL DESIGN DECISION: ARIA→DOM Direct Mapping
================================================
We use `page.get_by_role(role, name=name)` to find each element's CSS class.

WHY NOT separate DOM scan?
- ARIA accessible name: "English, Current language"
- DOM textContent.trim(): "English"
- Text mismatch → filter fails → utility elements leak through

WHY this approach works:
- get_by_role matches by accessible name (same as ARIA)
- We find THE SAME element ARIA found
- No text matching issues

See ARCHITECTURE.md "Why ARIA→DOM direct mapping" for full explanation.
"""
import os
import re
from pathlib import Path
from playwright.async_api import Page

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent / 'config' / '.env')

from anthropic import Anthropic

client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))

# Cache LLM exclusion decisions by CSS group keys (frozenset of group names)
# This avoids repeated LLM calls when the same CSS groups appear
_css_exclusion_cache: dict[frozenset, set] = {}


async def extract_and_filter_nav_elements(
    page: Page,
    aria: str,
    menu_selector: str = None,
    excluded_groups_cache: set = None
) -> dict:
    """
    Extract all nav elements with CSS grouping and LLM filtering.

    Steps:
    1. Parse ARIA for all links + expandables with hierarchy
    2. CSS grouping - group elements by parent CSS class
    3. LLM exclusion - ask which groups are NOT navigation
    4. Filter to permitted elements
    5. Order by DOM position

    Args:
        page: Playwright page
        aria: ARIA snapshot string
        menu_selector: Optional menu container selector
        excluded_groups_cache: Optional set of already-excluded group names (for caching)

    Returns: {
        'elements': [  # Ordered by DOM position
            {'name': 'New In', 'type': 'link', 'url': '...', 'parent': None},
            {'name': 'Ready-to-Wear', 'type': 'button', 'url': None, 'parent': None},
            ...
        ],
        'excluded_groups': set()  # For caching
    }
    """
    print(f"  [EXTRACT] Starting extraction...")

    # Step 1: Parse ARIA structure with indentation
    parsed = _parse_aria_with_hierarchy(aria)
    print(f"  [EXTRACT] Parsed {len(parsed)} elements from ARIA:")
    for el in parsed:
        print(f"    [{el['type']}] {el['name']} (url={el.get('url', 'N/A')})")

    if not parsed:
        return {'elements': [], 'excluded_groups': set()}

    # Step 2: Get CSS class for each element directly from DOM
    elements_with_css = await _get_css_for_elements(page, parsed, menu_selector)

    # Step 3: Group by CSS class for LLM
    css_groups = {}
    for el in elements_with_css:
        css_class = el.get('css_class')
        if css_class:
            if css_class not in css_groups:
                css_groups[css_class] = []
            css_groups[css_class].append(el['name'])

    # Filter out groups with only 1 element
    css_groups = {k: v for k, v in css_groups.items() if len(v) > 1}

    print(f"  [EXTRACT] CSS groups: {len(css_groups)}")
    for group_name, names in css_groups.items():
        print(f"    {group_name} ({len(names)} items):")
        for name in names:
            print(f"      - {name}")

    # Skip CSS filtering if only 1 group - can't differentiate utility vs navigation
    if len(css_groups) <= 1:
        print(f"  [EXTRACT] Only {len(css_groups)} CSS group(s) - skipping LLM exclusion")
        excluded_groups = set()
    else:
        # Check cache by CSS group keys (not depth)
        css_group_keys = frozenset(css_groups.keys())

        if css_group_keys in _css_exclusion_cache:
            excluded_groups = _css_exclusion_cache[css_group_keys]
            print(f"  [EXTRACT] Using cached CSS exclusions: {excluded_groups}")
        elif excluded_groups_cache is not None:
            # Legacy cache from caller (depth-based)
            excluded_groups = excluded_groups_cache
            print(f"  [EXTRACT] Using caller cache: {excluded_groups}")
        else:
            # Call LLM to determine exclusions
            excluded_groups = await _exclude_utility_groups(css_groups)
            _css_exclusion_cache[css_group_keys] = excluded_groups
            print(f"  [EXTRACT] LLM excluded groups: {excluded_groups}")

    # Step 5: Filter by CSS groups
    print(f"  [EXTRACT] excluded_groups={excluded_groups}")

    if not css_groups:
        # No CSS groups - keep all elements
        print(f"  [EXTRACT] No CSS groups - keeping all {len(elements_with_css)} elements")
        filtered = elements_with_css
    else:
        # Filter: exclude elements whose CSS class is in excluded_groups
        filtered = []
        excluded_elements = []
        for item in elements_with_css:
            name = item['name']
            css_class = item.get('css_class')

            if css_class and css_class in excluded_groups:
                excluded_elements.append(f"{name} (class={css_class})")
            else:
                filtered.append(item)

        if excluded_elements:
            print(f"  [EXTRACT] Excluded: {excluded_elements}")
        print(f"  [EXTRACT] After CSS filter: {len(filtered)} elements")

    # Step 6: Check DOM for links with expandable indicators (chevron icons)
    final = await _mark_expandable_links(page, filtered, menu_selector)

    return {
        'elements': final,
        'excluded_groups': excluded_groups
    }


def _parse_aria_with_hierarchy(aria: str) -> list[dict]:
    """
    Parse ARIA snapshot and track parent-child relationships via indentation.

    Returns list of:
    {
        'type': 'link' | 'button' | 'tab' | 'menuitem',
        'name': str,
        'url': str (for links, None otherwise),
        'indent': int,
        'parent': str or None (name of parent expandable),
        'nearby_link': str or None (for buttons: link at same indent that this button might expand)
    }
    """
    items = []
    lines = aria.split('\n')

    # Track potential parents at each indent level
    # {indent: name} - the most recent expandable at that indent
    parent_stack = {}

    # Track links at each indent level for nearby_link detection
    # {indent: (name, url)} - the most recent link at that indent
    link_stack = {}

    for i, line in enumerate(lines):
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        # Find parent: closest expandable at lower indent
        parent = None
        for parent_indent in sorted(parent_stack.keys(), reverse=True):
            if parent_indent < indent:
                parent = parent_stack[parent_indent]
                break

        # Check for expandables (button, tab, menuitem)
        for role in ['button', 'tab', 'menuitem']:
            match = re.search(rf'{role}\s+"([^"]+)"', stripped, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean duplicate names like "Shoes Shoes"
                name = _clean_duplicate_name(name)

                if len(name) > 50:
                    continue

                # Skip obvious utility buttons
                name_lower = name.lower()
                if any(skip in name_lower for skip in ['back', 'close', 'search', 'menu', 'cart', 'login', 'sign in', 'change store', 'change location']):
                    continue

                # Find nearby link: closest link at SAME or LOWER indent
                # If button "See More" is at same indent as link "SHOP ALL", they're siblings
                # If button is nested inside the link's listitem, it has higher indent
                nearby_link = None
                nearby_link_url = None
                for link_indent in sorted(link_stack.keys(), reverse=True):
                    if link_indent <= indent:
                        nearby_link, nearby_link_url = link_stack[link_indent]
                        break

                items.append({
                    'type': role,
                    'aria_role': role,  # Actual DOM role for clicking
                    'name': name,
                    'url': None,
                    'indent': indent,
                    'parent': parent,
                    'nearby_link': nearby_link,
                    'nearby_link_url': nearby_link_url
                })

                # This expandable becomes potential parent for deeper items
                parent_stack[indent] = name
                # Clear any parents at deeper indents
                parent_stack = {k: v for k, v in parent_stack.items() if k <= indent}
                break

        # Check for links
        link_match = re.search(r'link\s+"([^"]+)"', stripped, re.IGNORECASE)
        if link_match:
            name = link_match.group(1).strip()
            name = _clean_duplicate_name(name)

            if len(name) > 100:
                continue

            # Get URL
            url = None
            url_match = re.search(r'/url:\s*([^\s]+)', stripped)
            if url_match:
                url = url_match.group(1)
            else:
                # Check next few lines
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j]
                    url_match = re.search(r'/url:\s*([^\s]+)', next_line)
                    if url_match:
                        url = url_match.group(1)
                        break
                    if re.match(r'\s*-\s+(link|button|tab)', next_line):
                        break

            # Check if URL is empty - treat as expandable button instead of link
            # Empty URLs: "", '', or no URL at all
            is_empty_url = not url or url in ('""', "''", '""', "''")

            if is_empty_url:
                # Treat as expandable button (links with empty URLs don't navigate)
                # Skip obvious utility buttons
                name_lower = name.lower()
                if any(skip in name_lower for skip in ['back', 'close', 'search', 'menu', 'cart', 'login', 'sign in', 'change store', 'change location']):
                    continue

                # Find nearby link for this pseudo-button
                nearby_link = None
                nearby_link_url = None
                for link_indent in sorted(link_stack.keys(), reverse=True):
                    if link_indent <= indent:
                        nearby_link, nearby_link_url = link_stack[link_indent]
                        break

                items.append({
                    'type': 'button',  # Logical type: expandable
                    'aria_role': 'link',  # Actual DOM role for clicking
                    'name': name,
                    'url': None,
                    'indent': indent,
                    'parent': parent,
                    'nearby_link': nearby_link,
                    'nearby_link_url': nearby_link_url
                })

                # This becomes potential parent for deeper items
                parent_stack[indent] = name
                parent_stack = {k: v for k, v in parent_stack.items() if k <= indent}

            elif url:
                # Regular link - expandability will be checked via DOM later
                items.append({
                    'type': 'link',
                    'name': name,
                    'url': url,
                    'indent': indent,
                    'parent': parent,
                    'nearby_link': None,
                    'nearby_link_url': None
                })

                # Track this link for nearby_link detection
                link_stack[indent] = (name, url)
                # Clear links at deeper indents
                link_stack = {k: v for k, v in link_stack.items() if k <= indent}

    return items


def _clean_duplicate_name(name: str) -> str:
    """Clean duplicated names like 'Shoes Shoes' -> 'Shoes'."""
    words = name.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            return ' '.join(words[:half])
    return name


async def _get_css_for_elements(page: Page, elements: list[dict], menu_selector: str = None) -> list[dict]:
    """
    Get CSS class for each ARIA element by locating it directly in DOM.

    Args:
        page: Playwright page
        elements: List of parsed ARIA elements with 'name', 'type', 'aria_role'
        menu_selector: Optional menu container selector

    Returns: Same elements with 'css_class' added
    """
    if not elements:
        return elements

    container = None
    if menu_selector and ('>>' in menu_selector or menu_selector.startswith('role=')):
        container = page.locator(menu_selector).first
        if await container.count() == 0:
            container = None
    elif menu_selector:
        container = page.locator(menu_selector).first

    result = []
    for el in elements:
        el_copy = el.copy()
        name = el['name']
        role = el.get('aria_role', el['type'])  # Use aria_role if available

        try:
            # Map our types to Playwright roles
            # IMPORTANT: exact=True prevents substring matching (e.g., 'S' matching 'Sale')
            if role == 'button':
                locator = page.get_by_role('button', name=name, exact=True)
            elif role == 'tab':
                locator = page.get_by_role('tab', name=name, exact=True)
            elif role == 'menuitem':
                locator = page.get_by_role('menuitem', name=name, exact=True)
            elif role == 'link':
                locator = page.get_by_role('link', name=name, exact=True)
            else:
                locator = page.get_by_role('button', name=name, exact=True)

            # If we have a container, scope to it
            if container:
                locator = container.get_by_role(role, name=name, exact=True)

            # Get first match
            if await locator.count() > 0:
                css_class = await locator.first.evaluate('''el => {
                    const parent = el.parentElement;
                    if (!parent) return null;
                    const classes = (parent.className || '').split(' ').filter(c => c && !c.includes('--'));
                    return classes[0] || parent.tagName.toLowerCase();
                }''')
                el_copy['css_class'] = css_class
            else:
                el_copy['css_class'] = None

        except Exception as e:
            print(f"    [CSS] Error getting CSS for {name}: {e}")
            el_copy['css_class'] = None

        result.append(el_copy)

    return result


async def _exclude_utility_groups(groups: dict) -> set:
    """
    Ask LLM which CSS groups are NOT navigation (utility, language, country, etc.).

    Returns set of group names to EXCLUDE.
    """
    if not groups:
        return set()

    # Build prompt showing all groups
    group_list = []
    group_keys = list(groups.keys())
    for i, key in enumerate(group_keys):
        items = groups[key]
        group_list.append(f"Group {i+1}: {items}")

    prompt = f"""Groups of elements from a navigation menu:

{chr(10).join(group_list)}

Which groups are UTILITY (NOT product navigation)?
UTILITY = language/country selectors, currency selectors, account/cart/login buttons, help links
NAVIGATION = product categories, subcategories, collections (KEEP these)

IMPORTANT: At least one group MUST be navigation. Do NOT exclude all groups.

Reply with JSON only:
{{"exclude": [2, 4], "reason": "brief reason"}}
or if all are navigation:
{{"exclude": [], "reason": "all are product categories"}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text.strip()
        print(f"    LLM exclusion response: {result}")

        # Parse JSON response
        import json
        try:
            parsed = json.loads(result)
            exclude_nums = parsed.get('exclude', [])
            reason = parsed.get('reason', '')
            if reason:
                print(f"    LLM reason: {reason}")
        except json.JSONDecodeError:
            # Fallback: try to extract JSON from response
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                parsed = json.loads(json_match.group())
                exclude_nums = parsed.get('exclude', [])
            else:
                print(f"    LLM response not valid JSON, defaulting to no exclusions")
                return set()

        excluded = set()
        for num in exclude_nums:
            if isinstance(num, int) and 1 <= num <= len(group_keys):
                excluded.add(group_keys[num - 1])

        # Safety: at least one group must be kept (we're in a nav menu after all)
        if len(excluded) >= len(group_keys):
            print(f"    LLM tried to exclude all groups - keeping all instead")
            return set()

        return excluded

    except Exception as e:
        print(f"  [LLM] Error in exclusion: {e}")
        return set()




async def _mark_expandable_links(page: Page, elements: list[dict], menu_selector: str = None) -> list[dict]:
    """
    Check DOM for links that have expandable indicators (chevron icons).

    Looks for class names containing: chevron, arrow, dropdown, expand, more, toggle, caret, icon
    on child elements of links.

    Returns elements with type changed to 'button' for expandable links.
    """
    if not elements:
        return elements

    # Get names of links with URLs to check
    links_to_check = [el['name'] for el in elements if el['type'] == 'link' and el.get('url')]

    if not links_to_check:
        return elements

    try:
        # Check DOM for expandable indicators
        expandable_keywords = ['chevron', 'arrow', 'dropdown', 'expand', 'more', 'toggle', 'caret', 'icon_new', 'submenu', 'has-child']

        if menu_selector and ('>>' in menu_selector or menu_selector.startswith('role=')):
            container = page.locator(menu_selector).first
            if await container.count() == 0:
                return elements

            expandable_names = await container.evaluate('''(el, args) => {
                const [names, keywords] = args;
                const expandable = [];

                for (const name of names) {
                    // Find links with exact text match
                    const links = el.querySelectorAll('a');
                    for (const link of links) {
                        const linkText = link.textContent?.trim();
                        if (linkText === name) {
                            // Check if link or its children have expandable indicator classes
                            const allElements = [link, ...link.querySelectorAll('*')];
                            for (const child of allElements) {
                                // Handle SVG elements where className is SVGAnimatedString
                                const rawClass = child.className;
                                const classes = (typeof rawClass === 'string' ? rawClass : rawClass?.baseVal || '').toLowerCase();
                                for (const keyword of keywords) {
                                    if (classes.includes(keyword)) {
                                        expandable.push(name);
                                        break;
                                    }
                                }
                                if (expandable.includes(name)) break;
                            }
                            if (expandable.includes(name)) break;
                        }
                    }
                }

                return expandable;
            }''', [links_to_check, expandable_keywords])
        elif menu_selector:
            expandable_names = await page.evaluate('''(args) => {
                const [menuSelector, names, keywords] = args;
                const el = document.querySelector(menuSelector);
                if (!el) return [];

                const expandable = [];

                for (const name of names) {
                    const links = el.querySelectorAll('a');
                    for (const link of links) {
                        const linkText = link.textContent?.trim();
                        if (linkText === name) {
                            const allElements = [link, ...link.querySelectorAll('*')];
                            for (const child of allElements) {
                                // Handle SVG elements where className is SVGAnimatedString
                                const rawClass = child.className;
                                const classes = (typeof rawClass === 'string' ? rawClass : rawClass?.baseVal || '').toLowerCase();
                                for (const keyword of keywords) {
                                    if (classes.includes(keyword)) {
                                        expandable.push(name);
                                        break;
                                    }
                                }
                                if (expandable.includes(name)) break;
                            }
                            if (expandable.includes(name)) break;
                        }
                    }
                }

                return expandable;
            }''', [menu_selector, links_to_check, expandable_keywords])
        else:
            return elements

        # Update elements - mark expandable links as buttons
        if expandable_names:
            print(f"  [EXTRACT] Links with expandable indicators: {expandable_names}")
            result = []
            for el in elements:
                if el['name'] in expandable_names and el['type'] == 'link':
                    el_copy = el.copy()
                    el_copy['type'] = 'button'  # Logical: expandable
                    el_copy['aria_role'] = 'link'  # DOM: still a link
                    result.append(el_copy)
                else:
                    result.append(el)
            return result

        return elements

    except Exception as e:
        print(f"  [DOM] Error checking expandable indicators: {e}")
        return elements


# Legacy function for backwards compatibility
async def extract_nav_elements(page: Page, aria: str, menu_selector: str = None) -> dict:
    """
    Legacy wrapper - converts new format to old format for step_explorer.py.

    TODO: Update step_explorer.py to use extract_and_filter_nav_elements directly.
    """
    result = await extract_and_filter_nav_elements(page, aria, menu_selector)

    # Convert to old format
    categories = {}
    root_links = []

    for el in result['elements']:
        name = el['name']
        parent = el['parent']

        if el['type'] == 'link':
            link_data = {'name': name, 'url': el['url']}
            if parent:
                if parent not in categories:
                    categories[parent] = {'links': [], 'expandable': None}
                categories[parent]['links'].append(link_data)
            else:
                root_links.append(link_data)

        elif el['type'] in ('button', 'tab', 'menuitem'):
            exp_data = {'name': name, 'role': el['type']}
            if name not in categories:
                categories[name] = {'links': [], 'expandable': exp_data}
            else:
                categories[name]['expandable'] = exp_data

    return {
        'categories': categories,
        'root_links': root_links,
        'root_expandables': []
    }
