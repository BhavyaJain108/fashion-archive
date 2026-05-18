"""
Site session state management for navigation scraping.

This module provides proper state isolation for:
- Per-site state (menu cache, hover behavior, popup tracking)
- Enables parallel scraping by avoiding global state
- Clean lifecycle management

State Hierarchy:
- SiteSession: Per-site state (create one per URL)
  - MenuState: Menu button cache for fast reopening
  - HoverStats: Hover behavior tracking with circuit breaker
"""

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


@dataclass
class MenuState:
    """
    Menu button cache for fast reopening.

    Once we find the menu button (expensive: LLM + screenshot),
    cache it for recovery scenarios.
    """
    cached_button: dict | None = None  # {'selector': str, 'method': 'click'|'hover'}
    controls_id: str | None = None     # aria-controls target element ID
    container_selector: str | None = None  # CSS selector for menu container

    def cache(self, selector: str, method: str = 'click', controls_id: str = None):
        """Cache menu button info for fast reopening."""
        self.cached_button = {'selector': selector, 'method': method}
        self.controls_id = controls_id
        print(f"    [NAV] Cached menu button: {selector} ({method})")
        if controls_id:
            print(f"    [NAV] Controls: #{controls_id}")

    def clear(self):
        """Clear cache (e.g., when button becomes stale)."""
        self.cached_button = None
        self.controls_id = None
        # Note: container_selector intentionally NOT cleared
        # Container is usually stable even if button changes

    def clear_all(self):
        """Full reset including container."""
        self.cached_button = None
        self.controls_id = None
        self.container_selector = None

    async def reopen_fast(self, page: 'Page') -> bool:
        """
        Reopen menu using cached button info (no LLM detection).

        Returns True if successful, False if cache miss or failure.
        """
        if not self.cached_button:
            return False

        selector = self.cached_button['selector']
        method = self.cached_button['method']

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
            self.clear()
            return False


@dataclass
class HoverStats:
    """
    Track hover behavior for circuit breaker pattern.

    Some sites don't respond to hover (click-only menus).
    After threshold failures with 0 successes, disable hover
    for this site to avoid wasted time.
    """
    attempts: int = 0
    successes: int = 0
    disabled: bool = False
    threshold: int = 3  # Disable after this many failures with 0 success

    def track(self, success: bool):
        """Track a hover attempt result."""
        self.attempts += 1
        if success:
            self.successes += 1
        else:
            # Check if we should disable hover
            if self.attempts >= self.threshold and self.successes == 0:
                self.disabled = True
                print(f"    [HOVER] Disabled for this site ({self.attempts} failures, 0 successes)")

    def should_try(self) -> bool:
        """Check if we should attempt hover."""
        return not self.disabled

    def reset(self):
        """Reset stats (e.g., for new site)."""
        self.attempts = 0
        self.successes = 0
        self.disabled = False


@dataclass
class SiteSession:
    """
    Per-site state container.

    Create one per URL being scraped. Encapsulates all state that
    should reset between sites but persist within a site exploration.

    Usage:
        session = SiteSession("https://example.com")
        explorer = NavExplorer(page, session)
        await explorer.setup(session.base_url)

        # Session state persists across recovery:
        # - Menu button cache survives page refresh
        # - Hover stats track site behavior
        # - Popup flag prevents re-dismissal
    """
    base_url: str
    menu: MenuState = field(default_factory=MenuState)
    hover: HoverStats = field(default_factory=HoverStats)
    popups_dismissed: bool = False

    def reset(self):
        """Reset all state for new exploration of same site."""
        self.menu.clear_all()
        self.hover.reset()
        self.popups_dismissed = False

    def mark_popups_dismissed(self):
        """Mark that initial popups have been dismissed."""
        self.popups_dismissed = True


# =============================================================================
# Backwards Compatibility Layer
# =============================================================================
# These provide module-level access for gradual migration.
# New code should use SiteSession directly.

_current_session: Optional[SiteSession] = None


def get_current_session() -> SiteSession:
    """
    Get current session or create a default one.

    For backwards compatibility with code that uses module-level state.
    New code should create and pass SiteSession explicitly.
    """
    global _current_session
    if _current_session is None:
        _current_session = SiteSession("")
    return _current_session


def set_current_session(session: SiteSession):
    """
    Set the current session.

    Called by run_exploration() to establish session context.
    """
    global _current_session
    _current_session = session


def clear_current_session():
    """Clear the current session (e.g., between sites)."""
    global _current_session
    _current_session = None


# =============================================================================
# Convenience wrappers for backwards compatibility
# =============================================================================
# These mirror the old dynamic_explorer.py API but use session state.

def cache_menu_button(selector: str, method: str = 'click', controls_id: str = None):
    """Backwards-compatible wrapper for menu caching."""
    get_current_session().menu.cache(selector, method, controls_id)


def clear_menu_cache():
    """Backwards-compatible wrapper for clearing menu cache."""
    get_current_session().menu.clear()


def get_cached_menu_button() -> dict | None:
    """Backwards-compatible wrapper for getting cached button."""
    return get_current_session().menu.cached_button


async def reopen_menu_fast(page: 'Page') -> bool:
    """Backwards-compatible wrapper for fast menu reopen."""
    return await get_current_session().menu.reopen_fast(page)


def track_hover(success: bool):
    """Backwards-compatible wrapper for hover tracking."""
    get_current_session().hover.track(success)


def should_try_hover() -> bool:
    """Backwards-compatible wrapper for hover check."""
    return get_current_session().hover.should_try()


def reset_site_state():
    """Backwards-compatible wrapper for resetting site state."""
    session = get_current_session()
    session.reset()
