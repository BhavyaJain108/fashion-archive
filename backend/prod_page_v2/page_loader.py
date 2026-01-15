"""
Page loader using Playwright with stealth mode.

Loads a page and captures HTML and JSON API responses.
Uses stealth patches to evade bot detection.
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
