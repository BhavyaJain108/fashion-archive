"""
LLM-driven navigation explorer.

Tree holds ALL known nodes. Stack holds paths to unexplored nodes.
LLM interprets ARIA to find children at each level.
"""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent / 'config' / '.env')

from anthropic import Anthropic
from playwright.async_api import async_playwright, Page

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scraper.navigation.llm_popup_dismiss import dismiss_popups_with_llm

client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))


# =============================================================================
# LLM Prompts
# =============================================================================

def prompt_top_level(aria: str) -> str:
    """Prompt to find top-level navigation items."""
    return f"""Look at this ARIA snapshot of a fashion website's navigation.

List ALL top-level navigation categories (the main menu items).

ARIA:
{aria[:8000]}

RESPOND EXACTLY LIKE THIS:

ITEMS:
- BUTTON: Category Name
- LINK: Category Name | /url/path
(list all top-level items)

RULES:
- BUTTON = expandable (will reveal subcategories)
- LINK = direct page (has URL)
- Only product categories (Women, Men, Kids, Shoes, Bags, etc.)
- IGNORE: Search, Cart, Login, Account, Language, Country
- IGNORE: About, Contact, FAQ, Careers, Legal, Newsletter
"""


def extract_aria_section(aria: str, parent_name: str) -> str:
    """Extract the relevant section of ARIA around the expanded parent."""
    import re
    lines = aria.split('\n')

    # Use word boundary matching to avoid MEN matching WOMEN
    # Match: "MEN" or 'MEN' surrounded by quotes
    pattern = rf'["\']({re.escape(parent_name)})["\']'

    # Find the expanded element or its region
    start_idx = None
    for i, line in enumerate(lines):
        if re.search(pattern, line, re.IGNORECASE):
            if '[expanded]' in line or 'region' in line.lower():
                start_idx = i
                break

    if start_idx is None:
        # Fallback: find any exact match
        for i, line in enumerate(lines):
            if re.search(pattern, line, re.IGNORECASE):
                start_idx = i
                break

    if start_idx is None:
        return aria[:4000]

    # Get the indent of the found element
    base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())

    # Collect: the element + everything MORE indented below it (its children)
    section_lines = [lines[start_idx]]

    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        current_indent = len(line) - len(line.lstrip())

        # Stop when we hit same or lower indent (sibling or parent level)
        if current_indent <= base_indent:
            break

        section_lines.append(line)

        # Limit to 60 lines
        if len(section_lines) >= 60:
            break

    return '\n'.join(section_lines)


async def extract_all_links_from_html(page) -> dict:
    """Extract all links with URLs from raw HTML. Returns {url: text}"""
    links = {}
    try:
        # Get all <a> tags with href
        anchors = await page.locator('a[href]').all()
        for anchor in anchors:
            try:
                href = await anchor.get_attribute('href')
                text = (await anchor.inner_text()).strip()
                if href and text and len(text) < 100:  # skip empty or huge text
                    links[href] = text
            except:
                continue
    except:
        pass
    return links


def extract_all_buttons(aria: str) -> set:
    """Extract all button names from ARIA."""
    import re
    buttons = set()
    for line in aria.split('\n'):
        btn_match = re.search(r'- button "([^"]+)"', line)
        if btn_match:
            buttons.add(btn_match.group(1))
    return buttons


def find_new_links(before_links: dict, after_links: dict, debug: bool = False) -> list:
    """
    Compare before/after HTML links to find newly revealed ones.
    before_links/after_links: {url: text}
    Returns list of {type: 'link', name, url}
    """
    # URL patterns to skip
    skip_patterns = [
        'login', 'cart', 'wishlist', 'account', 'saved',
        'faq', 'contact', 'careers', 'legal', 'privacy', 'cookie', 'terms',
        'facebook', 'instagram', 'tiktok', 'pinterest', 'linkedin', 'twitter',
        'tel:', 'mailto:', 'javascript:', '#',
        'track-order', 'returns', 'shipping', 'payment', 'newsletter'
    ]

    new_links = []
    skipped_links = []

    # Find URLs that are in after but not in before
    new_urls = set(after_links.keys()) - set(before_links.keys())

    if debug and new_urls:
        print(f"    [DEBUG] Found {len(new_urls)} new URLs")

    for url in new_urls:
        text = after_links[url]
        # Skip utility links
        url_lower = url.lower()
        if any(skip in url_lower for skip in skip_patterns):
            skipped_links.append((text, url, 'url_pattern'))
            continue
        if text.lower() in ['login', 'cart', 'search', 'close', 'back']:
            skipped_links.append((text, url, 'text_filter'))
            continue
        new_links.append({'type': 'link', 'name': text, 'url': url})

    if debug and skipped_links:
        print(f"    [DEBUG] Skipped {len(skipped_links)} links:")
        for text, url, reason in skipped_links[:5]:
            print(f"      - {text} | {url} ({reason})")

    return new_links


def parse_items(response: str) -> list:
    """Parse LLM response into list of items."""
    items = []
    in_section = False

    for line in response.split('\n'):
        line = line.strip()

        if 'ITEMS:' in line.upper() or 'CHILDREN:' in line.upper():
            in_section = True
            continue

        if in_section:
            if line.startswith('- BUTTON:'):
                name = line[9:].strip()
                if name.lower() not in ['none', '']:
                    items.append({'type': 'button', 'name': name, 'url': None})
            elif line.startswith('- LINK:'):
                parts = line[7:].strip().split('|')
                name = parts[0].strip()
                url = parts[1].strip() if len(parts) > 1 else None
                if name.lower() not in ['none', '']:
                    items.append({'type': 'link', 'name': name, 'url': url})

    return items


# =============================================================================
# Tree Operations
# =============================================================================

def add_to_tree(tree: dict, path: list, children: list):
    """Add children to tree at the given path."""
    # Navigate to parent
    node = tree
    for p in path:
        node = node[p]['children']

    # Add each child
    for child in children:
        name = child['name']
        if name not in node:
            node[name] = {
                'explored': child['type'] == 'link',  # links are already "explored"
                'url': child.get('url'),
                'children': {}
            }


def mark_explored(tree: dict, path: list):
    """Mark a node as explored."""
    node = tree
    for i, p in enumerate(path):
        if i == len(path) - 1:
            node[p]['explored'] = True
        else:
            node = node[p]['children']


def get_node(tree: dict, path: list) -> dict:
    """Get node at path."""
    node = tree
    for i, p in enumerate(path):
        if i == len(path) - 1:
            return node[p]
        node = node[p]['children']
    return None


# =============================================================================
# Navigation
# =============================================================================

async def click_element(page: Page, name: str, container=None) -> bool:
    """
    Click an element by name.
    If container is provided, search within that container only.
    """
    search_context = container if container else page

    for role in ['button', 'tab', 'menuitem']:
        try:
            locator = search_context.get_by_role(role, name=name, exact=False)
            if await locator.count() > 0:
                await locator.first.click()
                await page.wait_for_timeout(600)
                return True
        except:
            continue
    return False


async def find_container(page: Page, name: str):
    """Find the region/container for an element after clicking it."""
    # Try to find region with this name
    for role in ['region', 'menu', 'dialog', 'tabpanel']:
        try:
            locator = page.get_by_role(role, name=name, exact=False)
            if await locator.count() > 0:
                return locator.first
        except:
            continue

    # Fallback: find any expanded element's adjacent region
    try:
        # Look for [aria-expanded="true"] and its associated content
        expanded = page.locator(f'[aria-expanded="true"]:has-text("{name}")')
        if await expanded.count() > 0:
            # Try to find sibling or child region
            region = expanded.locator('~ [role="region"], + [role="region"]')
            if await region.count() > 0:
                return region.first
    except:
        pass

    return None


async def navigate_to_path(page: Page, path: list) -> bool:
    """
    Navigate through menu to reach path.
    Returns True if navigation succeeded, False otherwise.
    """
    # Reset menu state
    await page.keyboard.press('Escape')
    await page.wait_for_timeout(300)

    container = None

    # Click through each element in path
    for i, name in enumerate(path):
        success = await click_element(page, name, container)
        if not success:
            print(f"      [NAV] Could not click: {name}")
            return False

        # Try to find container for scoping next click (optional)
        new_container = await find_container(page, name)
        if new_container:
            container = new_container
            print(f"      [NAV] Entered container for: {name}")
        else:
            print(f"      [NAV] Clicked: {name} (no container)")

    return True


# =============================================================================
# Main Explorer
# =============================================================================

async def explore(url: str, max_depth: int = 10):
    """
    Explore navigation menu using DFS.

    Tree: all known nodes
    Stack: paths to unexplored nodes
    """

    print(f"\n{'='*70}")
    print("NAVIGATION EXPLORER")
    print(f"{'='*70}")
    print(f"URL: {url}\n")

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()

    try:
        # Setup
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        print("[2] Dismissing popups...")
        await dismiss_popups_with_llm(page)
        await page.wait_for_timeout(500)

        # Get initial ARIA
        print("[3] Getting initial ARIA...")
        aria = await page.locator('body').aria_snapshot()
        screenshot = await page.screenshot()
        screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')

        # Ask LLM for top-level items
        print("[4] Finding top-level items...")
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}},
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

        # Initialize tree with all top-level items
        tree = {}
        stack = []

        for item in top_level:
            tree[item['name']] = {
                'explored': item['type'] == 'link',
                'url': item.get('url'),
                'children': {}
            }
            if item['type'] == 'button':
                stack.append([item['name']])

        # Reverse stack so first item is explored first (DFS)
        stack = list(reversed(stack))

        print(f"\n[5] Starting DFS exploration...")
        print(f"    Stack: {[s[-1] for s in stack]}")

        iteration = 0

        while stack:
            iteration += 1
            path = stack.pop()

            # Skip if too deep
            if len(path) > max_depth:
                print(f"\n[{iteration}] SKIP (depth {len(path)}): {' > '.join(path)}")
                continue

            print(f"\n{'='*60}")
            print(f"[{iteration}] EXPLORING: {' > '.join(path)}")
            print(f"    Stack remaining: {len(stack)}")

            # Navigate to parent path (all but last element)
            parent_path = path[:-1]
            target = path[-1]

            # Reset and navigate to parent
            await page.keyboard.press('Escape')
            await page.wait_for_timeout(300)

            container = None
            for name in parent_path:
                await click_element(page, name, container)
                new_container = await find_container(page, name)
                if new_container:
                    container = new_container

            # Get state BEFORE clicking target
            before_links = await extract_all_links_from_html(page)
            aria_before = await page.locator('body').aria_snapshot()
            before_buttons = extract_all_buttons(aria_before)

            # Click the target element
            success = await click_element(page, target, container)
            if not success:
                print(f"    Could not click {target}, skipping")
                continue

            await page.wait_for_timeout(500)

            # Get state AFTER clicking target
            after_links = await extract_all_links_from_html(page)
            aria_after = await page.locator('body').aria_snapshot()
            after_buttons = extract_all_buttons(aria_after)

            print(f"    [DIFF] Links: {len(before_links)} → {len(after_links)}, Buttons: {len(before_buttons)} → {len(after_buttons)}")

            # Find NEW elements
            new_links = find_new_links(before_links, after_links, debug=True)
            new_buttons = after_buttons - before_buttons

            # Filter utility buttons
            skip_buttons = {'back', 'close', 'search', 'login', 'cart', 'shipping to the us',
                           'change language', 'subscribe', 'play', 'pause', 'mute', 'unmute',
                           'chat support', 'cookie settings', 'link', 'chat', 'support',
                           'cookies', 'settings', 'help', 'menu', 'navigation'}

            def clean_button_name(name):
                """Clean up button names - remove duplicates like 'Sweaters Sweaters'"""
                words = name.split()
                # If first half equals second half, take first half
                if len(words) >= 2 and len(words) % 2 == 0:
                    half = len(words) // 2
                    if words[:half] == words[half:]:
                        return ' '.join(words[:half])
                return name

            new_buttons = {clean_button_name(b) for b in new_buttons
                          if b.lower() not in skip_buttons
                          and not any(skip in b.lower() for skip in skip_buttons)}

            buttons = [{'type': 'button', 'name': name} for name in new_buttons]
            links = new_links
            children = buttons + links  # combine for tree

            print(f"    Found: {len(buttons)} buttons, {len(links)} links")
            for b in buttons:
                print(f"      [BTN] {b['name']}")
            for l in links[:5]:
                print(f"      [LNK] {l['name']}")
            if len(links) > 5:
                print(f"      ... and {len(links) - 5} more links")

            # Add children to tree
            add_to_tree(tree, path, children)
            mark_explored(tree, path)

            # Push unexplored buttons to stack (reversed for DFS)
            for child in reversed(buttons):
                child_path = path + [child['name']]
                stack.append(child_path)
                print(f"    → Stack push: {' > '.join(child_path)}")

        # Done
        print(f"\n{'='*70}")
        print("COMPLETE")
        print(f"{'='*70}")

        # Clean tree for output (remove 'explored' flags)
        def clean_tree(node):
            result = {}
            for name, data in node.items():
                result[name] = {'url': data.get('url')}
                if data.get('children'):
                    result[name]['children'] = clean_tree(data['children'])
            return result

        output = clean_tree(tree)
        print(json.dumps(output, indent=2))

        return output

    finally:
        await page.wait_for_timeout(2000)
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python explorer.py <url>")
        sys.exit(1)

    tree = await explore(sys.argv[1])

    if tree:
        out = Path(__file__).parent / 'tree.json'
        with open(out, 'w') as f:
            json.dump(tree, f, indent=2)
        print(f"\nSaved: {out}")


if __name__ == "__main__":
    asyncio.run(main())
