"""
ARIA Snapshot Utilities

Functions for analyzing and comparing ARIA snapshots to detect menu appearances,
state changes, and navigation structure.
"""

import re
from typing import Tuple


def menu_appeared(aria_before: str, aria_after: str, element_name: str = None) -> Tuple[bool, str]:
    """
    Check if a menu/dropdown appeared after an interaction.

    Args:
        aria_before: ARIA snapshot before interaction
        aria_after: ARIA snapshot after interaction
        element_name: Optional name of element we interacted with

    Returns:
        Tuple of (appeared: bool, reason: str)
    """
    # 1. Check if element now shows [expanded]
    if element_name:
        # Look for the element with [expanded] state
        pattern = rf'.*{re.escape(element_name)}.*\[expanded\]'
        if re.search(pattern, aria_after, re.IGNORECASE) and not re.search(pattern, aria_before, re.IGNORECASE):
            return True, "element_expanded"

    # 2. Check for new navigation/menu containers
    containers = ['- navigation', '- dialog', '- menu:', '- tablist', '- tabpanel']
    for container in containers:
        count_before = aria_before.lower().count(container)
        count_after = aria_after.lower().count(container)
        if count_after > count_before:
            return True, f"new_container:{container.strip('- :')}"

    # 3. Check for significant new links (at least 3)
    links_before = aria_before.count('/url:')
    links_after = aria_after.count('/url:')
    new_links = links_after - links_before
    if new_links >= 3:
        return True, f"new_links:{new_links}"

    return False, "no_change"


def url_changed(url_before: str, url_after: str) -> bool:
    """Check if URL changed (indicating navigation occurred)."""
    # Normalize URLs (remove trailing slashes, fragments)
    def normalize(url):
        url = url.rstrip('/')
        if '#' in url:
            url = url.split('#')[0]
        return url

    return normalize(url_before) != normalize(url_after)


def extract_new_content(aria_before: str, aria_after: str) -> list[str]:
    """
    Extract lines that are new in aria_after.

    Returns:
        List of new lines
    """
    lines_before = set(aria_before.splitlines())
    lines_after = aria_after.splitlines()
    return [line for line in lines_after if line not in lines_before]


def find_navigation_elements(aria: str) -> list[dict]:
    """
    Find interactive navigation elements in an ARIA snapshot.

    Returns:
        List of dicts with 'role', 'name', 'state' keys
    """
    elements = []

    # Pattern: - role "name" [state]: or - role "name":
    pattern = r'-\s+(button|tab|link)\s+"([^"]+)"(?:\s+\[([^\]]+)\])?'

    for match in re.finditer(pattern, aria):
        role = match.group(1)
        name = match.group(2)
        state = match.group(3)  # May be None

        elements.append({
            'role': role,
            'name': name,
            'state': state,
        })

    return elements


def find_category_links(aria: str) -> list[dict]:
    """
    Find links that look like product categories.

    Returns:
        List of dicts with 'name', 'url' keys
    """
    links = []

    # Pattern for links with URLs
    # - link "Name":
    #   - /url: https://...
    lines = aria.splitlines()

    for i, line in enumerate(lines):
        link_match = re.search(r'-\s+link\s+"([^"]+)"', line)
        if link_match:
            name = link_match.group(1)
            # Look for URL in next few lines
            for j in range(i + 1, min(i + 3, len(lines))):
                url_match = re.search(r'/url:\s*(\S+)', lines[j])
                if url_match:
                    links.append({
                        'name': name,
                        'url': url_match.group(1),
                    })
                    break

    return links


def get_element_url(aria: str, element_name: str) -> str | None:
    """
    Get the URL associated with a link element.

    Args:
        aria: ARIA snapshot
        element_name: Name of the link to find

    Returns:
        URL string if found, None otherwise
    """
    lines = aria.splitlines()

    for i, line in enumerate(lines):
        # Match link with the given name
        if re.search(rf'-\s+link\s+"{re.escape(element_name)}"', line, re.IGNORECASE):
            # Look for URL in next few lines
            for j in range(i + 1, min(i + 4, len(lines))):
                url_match = re.search(r'/url:\s*(\S+)', lines[j])
                if url_match:
                    return url_match.group(1)

    return None


# =============================================================================
# Pretty printing
# =============================================================================

def summarize_aria(aria: str, max_lines: int = 50) -> str:
    """Return a summarized view of an ARIA snapshot."""
    lines = aria.splitlines()
    if len(lines) <= max_lines:
        return aria

    return '\n'.join(lines[:max_lines]) + f'\n... ({len(lines) - max_lines} more lines)'
