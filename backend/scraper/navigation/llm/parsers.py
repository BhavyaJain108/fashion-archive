"""
LLM response parsers for navigation extraction.
"""
import re


def parse_menu_button_response(response: str) -> tuple[str, int] | None:
    """
    Parse LLM response for menu button identification.
    Returns (type, index) where type is 'C' for candidate or 'B' for button.
    Returns None if no menu found.
    """
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
