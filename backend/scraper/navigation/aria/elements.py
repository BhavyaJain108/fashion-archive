"""
ARIA element extraction utilities.

Parse ARIA snapshots to extract buttons, tabs, links, and other elements.
"""
import re


def extract_buttons_from_aria(aria: str, with_types: bool = False) -> set | dict:
    """
    Extract all button and tab names from ARIA.

    Args:
        aria: ARIA snapshot string
        with_types: If True, return dict {name: type}, else return set of names

    Returns:
        set of names (default) or dict {name: 'button'|'tab'} if with_types=True
    """
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


def extract_elements_from_aria(menu_aria: str) -> set[str]:
    """
    Extract element names (buttons, tabs, links) from menu ARIA snapshot.

    Returns set of element text/names that appear in the menu.
    """
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


def _clean_duplicate_name(name: str) -> str:
    """Clean duplicated names like 'Winter Winter' -> 'Winter'."""
    words = name.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            return ' '.join(words[:half])
    return name


def find_expandable_elements(aria: str) -> list[dict]:
    """
    Find elements that might reveal content when clicked.
    Returns list of {name, role, nearby_link, indent} for buttons, menuitems, tabs.

    The 'nearby_link' field contains the name of a link found near this button.
    The caller should use LLM to determine if the button expands that link's category
    or is a separate category itself.

    The 'indent' field is the ARIA indent level, used for caching LLM decisions
    per depth level (buttons at the same level behave consistently on a site).

    NOTE: No keyword filtering here - LLM decides what's useful via group classification.
    """
    lines = aria.split('\n')

    # Pass 1: Collect all links with their line index and indent
    links = []  # [(line_idx, link_name, indent), ...]

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        link_match = re.search(r'link\s+"([^"]+)"', stripped, re.IGNORECASE)
        if link_match:
            link_name = link_match.group(1).strip()
            link_name = _clean_duplicate_name(link_name)
            links.append((i, link_name, indent))

    # Pass 2: Find expandables and match to parent link
    expandables = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        # Match button, menuitem, tab (not link - those navigate away)
        for role in ['button', 'menuitem', 'tab']:
            pattern = rf'{role}\s+"([^"]+)"'
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                name = _clean_duplicate_name(name)

                # Skip obviously non-interactive (too long)
                if len(name) > 50:
                    continue

                # Skip navigation controls (back/close buttons)
                name_lower = name.lower()
                if name_lower.startswith('back') or name_lower == 'close':
                    continue

                # Find nearby link: closest link BEFORE this button with same or lower indent
                # Same indent = sibling (button expands the sibling link)
                # Lower indent = parent (button expands the parent category)
                nearby_link = None
                for link_line, link_name, link_indent in reversed(links):
                    if link_line < i and link_indent <= indent:
                        # Found a sibling or parent link
                        nearby_link = link_name
                        break
                        break

                expandables.append({
                    'name': name,
                    'role': role,
                    'nearby_link': nearby_link,
                    'indent': indent
                })
                break

    return expandables


def group_elements_by_aria_structure(aria: str) -> dict[str, list[dict]]:
    """
    Group elements by their ARIA parent structure (list, tablist, etc).
    Returns dict of {group_label: [{name, role}]}

    This uses the ARIA tree structure to identify natural groupings,
    which is more reliable than CSS-based grouping.
    """
    groups = {}
    current_group = None
    current_group_elements = []

    lines = aria.split('\n')

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        # Detect group containers (list, tablist, menu) - but NOT listitem
        if (stripped.startswith('- list:') or stripped.startswith('- list ') or stripped == '- list'
            or stripped.startswith('- tablist') or stripped.startswith('- menu:')):
            # Save previous group if it had elements
            if current_group and current_group_elements:
                groups[current_group] = current_group_elements

            # Start new group - try to get a label from context
            current_group = f"group_{len(groups) + 1}"
            current_group_elements = []
            continue

        # Check for heading that might label the next group
        heading_match = re.search(r'heading "([^"]+)"', stripped)
        if heading_match and not current_group_elements:
            # Update current group name with heading
            current_group = _clean_duplicate_name(heading_match.group(1))
            continue

        # Extract elements (buttons, tabs, links, menuitems)
        for role in ['button', 'tab', 'link', 'menuitem']:
            pattern = rf'{role}\s+"([^"]+)"'
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                name = _clean_duplicate_name(match.group(1).strip())
                if len(name) <= 50:
                    current_group_elements.append({
                        'name': name,
                        'role': role
                    })
                break

    # Don't forget last group
    if current_group and current_group_elements:
        groups[current_group] = current_group_elements

    return groups


def find_role_in_aria(menu_aria: str, text: str) -> str:
    """Find the ARIA role for an element with given text."""
    # Look for patterns like: tab "Text", button "Text", link "Text /url"
    for line in menu_aria.split('\n'):
        # Check if this line contains the text
        if f'"{text}"' in line or f'"{text} /' in line:
            # Extract the role
            match = re.search(r'(button|tab|link|menuitem)\s+"', line, re.IGNORECASE)
            if match:
                return match.group(1).lower()

    return 'button'  # Default fallback
