"""
Stealth Browser Module

Provides a Playwright browser that evades common bot detection.
"""

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from typing import Optional
import asyncio

from .patches import STEALTH_JS, get_stealth_args, get_stealth_user_agent


async def create_stealth_browser(headless: bool = True) -> tuple:
    """
    Create a stealth browser that evades detection.

    Returns:
        (playwright, browser) - caller must close both
    """
    playwright = await async_playwright().start()

    browser = await playwright.chromium.launch(
        headless=headless,
        args=get_stealth_args(),
    )

    return playwright, browser


async def create_stealth_context(browser: Browser) -> BrowserContext:
    """Create a browser context with stealth settings."""
    context = await browser.new_context(
        user_agent=get_stealth_user_agent(),
        viewport={'width': 1920, 'height': 1080},
        locale='en-US',
        timezone_id='America/New_York',
        # Add realistic headers
        extra_http_headers={
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        },
    )

    # Inject stealth scripts before any page loads
    await context.add_init_script(STEALTH_JS)

    return context


async def create_stealth_page(context: BrowserContext) -> Page:
    """Create a page with stealth settings."""
    page = await context.new_page()
    return page


class StealthBrowser:
    """
    Context manager for stealth browsing.

    Usage:
        async with StealthBrowser() as browser:
            page = await browser.new_page()
            await page.goto('https://example.com')
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self):
        self._playwright, self._browser = await create_stealth_browser(self.headless)
        self._context = await create_stealth_context(self._browser)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def new_page(self) -> Page:
        """Create a new stealth page."""
        return await create_stealth_page(self._context)

    @property
    def context(self) -> BrowserContext:
        return self._context

    @property
    def browser(self) -> Browser:
        return self._browser
