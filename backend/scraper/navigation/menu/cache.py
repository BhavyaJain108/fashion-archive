"""
Menu button caching for fast menu reopening.

DEPRECATED: This module is deprecated. Use session.py instead:

    from scraper.navigation.session import (
        SiteSession,
        cache_menu_button,
        clear_menu_cache,
        get_cached_menu_button,
        reopen_menu_fast,
    )

This file re-exports from session.py for backwards compatibility.
"""

from scraper.navigation.session import (
    cache_menu_button,
    clear_menu_cache,
    get_cached_menu_button,
    reopen_menu_fast,
)

__all__ = [
    'cache_menu_button',
    'clear_menu_cache',
    'get_cached_menu_button',
    'reopen_menu_fast',
]
