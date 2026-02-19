"""
Link extraction and filtering from ARIA snapshots.
"""
import re


def extract_links_from_aria(aria: str) -> dict:
    """Extract all links from ARIA. Returns {name: url}."""
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


# URL patterns that indicate utility/non-product pages
SKIP_URL_PATTERNS = [
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

# Link names that indicate utility/non-product links
SKIP_LINK_NAMES = [
    'login', 'cart', 'search', 'close', 'back', 'menu',
    'saved items', 'wishlist', 'account', 'sign in',
    # Utility links
    'skip to content', 'skip to main', 'powered by',
    'book appointment', 'book a call', 'schedule',
    # Generic non-category link
    'explore',
]


def extract_links_by_heading(aria: str) -> dict[str, dict]:
    """
    Extract links grouped by their parent heading/button in the ARIA hierarchy.

    Returns: {category_name: {link_name: url, ...}, ...}

    Links not under any category go under '' (empty string key).
    Detects both heading "..." and button "..." as potential category labels.
    """
    result = {'': {}}  # '' for links not under any category
    current_category = ''
    current_category_indent = -1

    lines = aria.split('\n')
    for i, line in enumerate(lines):
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())

        # Check for heading or button (both can be category labels)
        heading_match = re.search(r'heading "([^"]+)"', line)
        button_match = re.search(r'button "([^"]+)"', line)

        if heading_match or button_match:
            match = heading_match or button_match
            name = match.group(1).strip()
            # Only treat as category if it's a short name (not a long description)
            if len(name) < 30:
                current_category = name
                current_category_indent = indent
                if current_category not in result:
                    result[current_category] = {}
                continue

        # If we're at same or lower indent than category, reset
        if current_category and indent <= current_category_indent:
            current_category = ''
            current_category_indent = -1

        # Check for link
        named_match = re.search(r'- link "([^"]+)"', line)
        if named_match:
            name = named_match.group(1).strip()

            # Look for URL
            url_match = re.search(r'/url:\s*([^\s]+)', line)
            if url_match:
                url = url_match.group(1)
            else:
                url = None
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j]
                    url_match = re.search(r'/url:\s*([^\s]+)', next_line)
                    if url_match:
                        url = url_match.group(1)
                        break
                    if re.match(r'\s*-\s+(link|button|tab|img|text|listitem|menu)', next_line):
                        break

            if url and name and len(name) < 100:
                if current_category not in result:
                    result[current_category] = {}
                result[current_category][name] = url

    return result


def filter_utility_links(links: dict) -> dict:
    """Filter out utility/non-product links."""
    filtered = {}
    for name, url in links.items():
        name_lower = name.lower()
        url_lower = url.lower() if url else ''

        # Skip by name
        if any(skip in name_lower for skip in SKIP_LINK_NAMES):
            continue
        # Skip by URL pattern
        if any(skip in url_lower for skip in SKIP_URL_PATTERNS):
            continue
        # Skip anchor-only links
        if url.startswith('#') or url == '#':
            continue

        filtered[name] = url

    return filtered


# Button names that indicate utility/non-product buttons
SKIP_BUTTON_NAMES = {
    'back', 'close', 'search', 'login', 'cart', 'menu',
    'shipping to the us', 'change language', 'subscribe',
    'play', 'pause', 'mute', 'unmute',
    'chat support', 'cookie settings', 'link', 'chat', 'support',
    'cookies', 'settings', 'help', 'navigation'
}


def filter_utility_buttons(buttons: set | dict) -> set | dict:
    """
    Filter out utility/non-product buttons.

    Args:
        buttons: Either a set of names or dict {name: type}

    Returns:
        Same type as input, with utility buttons removed
    """
    def should_skip(name: str) -> bool:
        name_lower = name.lower()
        if name_lower in SKIP_BUTTON_NAMES:
            return True
        if any(skip in name_lower for skip in SKIP_BUTTON_NAMES):
            return True
        return False

    if isinstance(buttons, dict):
        return {name: typ for name, typ in buttons.items() if not should_skip(name)}
    else:
        return {b for b in buttons if not should_skip(b)}
