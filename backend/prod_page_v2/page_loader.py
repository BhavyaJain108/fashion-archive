"""
Page loader using Playwright with stealth mode.

Loads a page and captures HTML and JSON API responses.
Uses stealth patches to evade bot detection.

TWO MODES OF OPERATION:
    1. Standalone (original): load_page() creates a new browser per request
       - Simple, but high memory usage at scale
       - Good for: single extractions, testing, discovery phase

    2. Pooled (new): load_page_with_pool() uses pre-acquired page from BrowserPool
       - Memory-efficient, reuses browser instances
       - Good for: batch extraction of 100s-1000s of products
"""

import asyncio
import json
from typing import Dict, Any, Optional

from playwright.async_api import async_playwright, Page, Response

import sys
sys.path.insert(0, str(__file__).rsplit('/', 1)[0])

from stealth import StealthBrowser
from models import PageData


# Domains to ignore when capturing responses
IGNORE_DOMAINS = [
    'google', 'facebook', 'analytics', 'tracking', 'pixel',
    'doubleclick', 'criteo', 'onetrust', 'cookielaw',
]


def _is_tracking_domain(url: str) -> bool:
    """Check if URL is from a tracking/analytics domain."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in IGNORE_DOMAINS)


async def load_page(url: str, wait_time: int = 5000, headless: bool = True, stealth: bool = True) -> PageData:
    """
    Load a page and capture HTML and JSON responses.

    Args:
        url: URL to load
        wait_time: Time to wait for dynamic content (ms)
        headless: Run browser in headless mode
        stealth: Use stealth mode to evade bot detection (default True)

    Returns:
        PageData with HTML and captured JSON responses
    """
    page_data = PageData(url=url)

    if stealth:
        await _load_page_stealth(page_data, url, wait_time, headless)
    else:
        await _load_page_vanilla(page_data, url, wait_time, headless)

    return page_data


async def _load_page_stealth(page_data: PageData, url: str, wait_time: int, headless: bool):
    """Load page with stealth mode enabled."""
    async with StealthBrowser(headless=headless) as sb:
        page = await sb.new_page()

        async def capture_response(response: Response):
            """Capture JSON API responses and image URLs."""
            req_url = response.url
            content_type = response.headers.get('content-type', '')

            # Skip tracking domains
            if _is_tracking_domain(req_url):
                return

            # Capture image URLs
            if 'image' in content_type or any(ext in req_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                page_data.image_urls.append(req_url)
                return

            # Capture JSON responses
            if 'json' not in content_type:
                return

            try:
                body = await response.json()
                page_data.json_responses[req_url] = body

                # Capture request headers for GraphQL/API endpoints
                request = response.request
                if request and ('graphql' in req_url.lower() or 'api' in req_url.lower()):
                    page_data.request_headers[req_url] = dict(request.headers)
            except Exception:
                pass

        page.on('response', capture_response)

        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(wait_time)

            # Capture HTML
            page_data.html = await page.content()

            # Capture ARIA snapshot
            try:
                page_data.aria = await page.accessibility.snapshot(interesting_only=False)
            except Exception:
                pass

        except Exception as e:
            print(f"Error loading page: {e}")


async def _load_page_vanilla(page_data: PageData, url: str, wait_time: int, headless: bool):
    """Load page without stealth mode (original behavior)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        async def capture_response(response: Response):
            """Capture JSON API responses and image URLs."""
            req_url = response.url
            content_type = response.headers.get('content-type', '')

            # Skip tracking domains
            if _is_tracking_domain(req_url):
                return

            # Capture image URLs
            if 'image' in content_type or any(ext in req_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                page_data.image_urls.append(req_url)
                return

            # Capture JSON responses
            if 'json' not in content_type:
                return

            try:
                body = await response.json()
                page_data.json_responses[req_url] = body

                # Capture request headers for GraphQL/API endpoints
                request = response.request
                if request and ('graphql' in req_url.lower() or 'api' in req_url.lower()):
                    page_data.request_headers[req_url] = dict(request.headers)
            except Exception:
                pass

        page.on('response', capture_response)

        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(wait_time)

            # Capture HTML
            page_data.html = await page.content()

            # Capture ARIA snapshot
            try:
                page_data.aria = await page.accessibility.snapshot(interesting_only=False)
            except Exception:
                pass

        except Exception as e:
            print(f"Error loading page: {e}")

        await browser.close()


async def load_page_minimal(url: str, stealth: bool = True) -> str:
    """
    Minimal page load - just get HTML, no response capture.

    Faster when we don't need API interception.
    """
    if stealth:
        async with StealthBrowser(headless=True) as sb:
            page = await sb.new_page()
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_timeout(2000)
                html = await page.content()
            except Exception as e:
                print(f"Error loading page: {e}")
                html = ""
    else:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_timeout(2000)
                html = await page.content()
            except Exception as e:
                print(f"Error loading page: {e}")
                html = ""

            await browser.close()

    return html


# =============================================================================
# POOLED PAGE LOADING
# =============================================================================
#
# These functions work with BrowserPool for memory-efficient batch extraction.
#
# The key difference from standalone mode:
# - Page is already acquired from pool (browser already running)
# - We just load the URL and capture data
# - Page cleanup is handled by the pool, not here
#
# This avoids:
# - Browser startup cost (1-3 seconds saved per request)
# - Excessive memory from many concurrent browsers
# =============================================================================


async def load_page_on_existing(
    page: Page,
    url: str,
    wait_time: int = 5000
) -> PageData:
    """
    Load a URL on an existing page (from BrowserPool).

    DIFFERENCE FROM load_page():
        load_page()           -> Creates browser, loads URL, closes browser
        load_page_on_existing() -> Uses provided page, loads URL, returns data

    This is for use with BrowserPool:

        async with pool.acquire() as page:
            page_data = await load_page_on_existing(page, url)
            # ... extract product from page_data
        # Page returned to pool automatically

    Args:
        page: Playwright Page object (already acquired from pool)
        url: URL to load
        wait_time: Time to wait for dynamic content (ms)

    Returns:
        PageData with HTML and captured JSON responses
    """
    page_data = PageData(url=url)

    # Set up response capture
    # We need to capture JSON API responses for strategy extraction
    async def capture_response(response: Response):
        """Capture JSON API responses and image URLs."""
        req_url = response.url
        content_type = response.headers.get('content-type', '')

        # Skip tracking domains (analytics, pixels, etc.)
        if _is_tracking_domain(req_url):
            return

        # Capture image URLs (for image filtering later)
        if 'image' in content_type or any(ext in req_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
            page_data.image_urls.append(req_url)
            return

        # Only capture JSON responses
        if 'json' not in content_type:
            return

        try:
            body = await response.json()
            page_data.json_responses[req_url] = body

            # Capture request headers for GraphQL/API endpoints
            # (needed to replay API requests in some strategies)
            request = response.request
            if request and ('graphql' in req_url.lower() or 'api' in req_url.lower()):
                page_data.request_headers[req_url] = dict(request.headers)
        except Exception:
            pass  # Response wasn't valid JSON, ignore

    # Attach response listener
    # NOTE: We need to remove this listener after we're done to prevent
    # memory leaks from accumulated handlers on reused pages
    page.on('response', capture_response)

    try:
        # Navigate to URL
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)

        # Wait for dynamic content (JS-rendered products, lazy loading, etc.)
        await page.wait_for_timeout(wait_time)

        # Capture final HTML
        page_data.html = await page.content()

        # Capture ARIA snapshot (accessibility tree - useful for some strategies)
        try:
            page_data.aria = await page.accessibility.snapshot(interesting_only=False)
        except Exception:
            pass  # ARIA snapshot not always available

    except Exception as e:
        print(f"Error loading page {url}: {e}")

    finally:
        # IMPORTANT: Remove the response listener to prevent memory leaks
        # Without this, each page load adds another listener, and they accumulate
        page.remove_listener('response', capture_response)

    return page_data
