"""
Menu button caching for fast menu reopening.
"""
from playwright.async_api import Page

# Cached menu button info - avoids re-detecting on every reset
# Format: {'selector': str, 'method': 'click'|'hover'}
_cached_menu_button = None


def cache_menu_button(selector: str, method: str = 'click'):
    """Cache the menu button selector for fast reopening."""
    global _cached_menu_button
    _cached_menu_button = {'selector': selector, 'method': method}
    print(f"    [NAV] Cached menu button: {selector} ({method})")


def clear_menu_cache():
    """Clear the menu button cache."""
    global _cached_menu_button
    _cached_menu_button = None


def get_cached_menu_button() -> dict | None:
    """Get the cached menu button info."""
    return _cached_menu_button


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
        clear_menu_cache()
        return False
