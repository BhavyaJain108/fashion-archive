"""
Page loader using Playwright.

Loads a page and captures HTML and JSON API responses.
"""

import asyncio
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from playwright.async_api import async_playwright, Page, Response


@dataclass
class PageData:
    """Data captured from page load."""
    url: str
    html: str = ""
    json_responses: Dict[str, Any] = field(default_factory=dict)
    request_headers: Dict[str, Dict[str, str]] = field(default_factory=dict)  # url -> headers
    aria: Optional[dict] = None


# Domains to ignore when capturing responses
IGNORE_DOMAINS = [
    'google', 'facebook', 'analytics', 'tracking', 'pixel',
    'doubleclick', 'criteo', 'onetrust', 'cookielaw',
]


def _is_tracking_domain(url: str) -> bool:
    """Check if URL is from a tracking/analytics domain."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in IGNORE_DOMAINS)


async def load_page(url: str, wait_time: int = 5000, headless: bool = True) -> PageData:
    """
    Load a page and capture HTML and JSON responses.

    Args:
        url: URL to load
        wait_time: Time to wait for dynamic content (ms)
        headless: Run browser in headless mode

    Returns:
        PageData with HTML and captured JSON responses
    """
    page_data = PageData(url=url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        async def capture_response(response: Response):
            """Capture JSON API responses."""
            req_url = response.url
            content_type = response.headers.get('content-type', '')

            # Skip non-JSON and tracking domains
            if 'json' not in content_type:
                return
            if _is_tracking_domain(req_url):
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

    return page_data


async def load_page_minimal(url: str) -> str:
    """
    Minimal page load - just get HTML, no response capture.

    Faster when we don't need API interception.
    """
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
