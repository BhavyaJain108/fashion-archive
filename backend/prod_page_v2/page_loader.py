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
from typing import Dict, Any, Optional, List

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
            try:
                await page.wait_for_load_state('networkidle', timeout=wait_time)
            except Exception:
                pass

            # Capture HTML and visible text
            page_data.html = await page.content()
            try:
                page_data.visible_text = await page.inner_text('body')
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
            try:
                await page.wait_for_load_state('networkidle', timeout=wait_time)
            except Exception:
                pass

            # Capture HTML and visible text
            page_data.html = await page.content()
            try:
                page_data.visible_text = await page.inner_text('body')
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

    # Patterns that indicate an error/rate-limit page (not a real product)
    ERROR_PAGE_PATTERNS = [
        "too many requests", "rate limit", "access denied", "forbidden",
        "please try again", "temporarily unavailable", "service unavailable",
        "blocked", "captcha", "verify you are human", "just a moment",
        "checking your browser", "attention required",
    ]

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

    import time as _time

    try:
        # Navigate to URL and capture the HTTP response
        t0 = _time.monotonic()
        response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        t_goto = _time.monotonic()

        # Capture HTTP status
        if response:
            page_data.status_code = response.status
            if response.status >= 400:
                page_data.loaded = False
                print(f"[PageLoader] HTTP {response.status} for {url}")
                return page_data

        # Wait for dynamic content — use networkidle instead of fixed delay
        try:
            await page.wait_for_load_state('networkidle', timeout=wait_time)
        except Exception:
            pass  # Timeout is fine — we waited the max allowed time
        t_idle = _time.monotonic()

        # Force-load lazy images without scrolling
        try:
            await page.evaluate("""() => {
                document.querySelectorAll('img[loading="lazy"]').forEach(img => {
                    img.loading = 'eager';
                });
                document.querySelectorAll('img[data-src]').forEach(img => {
                    if (!img.src || img.src.includes('data:')) img.src = img.dataset.src;
                });
                document.querySelectorAll('img[data-srcset]').forEach(img => {
                    if (!img.srcset) img.srcset = img.dataset.srcset;
                });
            }""")
            await page.wait_for_timeout(200)
        except Exception:
            pass
        t_lazy = _time.monotonic()

        # Check for redirect to different domain (error page redirect)
        from urllib.parse import urlparse
        requested_domain = urlparse(url).netloc
        actual_domain = urlparse(page.url).netloc
        if actual_domain and requested_domain and actual_domain != requested_domain:
            page_data.loaded = False
            print(f"[PageLoader] Domain redirect: {requested_domain} → {actual_domain} for {url}")
            return page_data

        # Capture final HTML and visible text
        page_data.html = await page.content()
        try:
            page_data.visible_text = await page.inner_text('body')
        except Exception:
            pass
        t_html = _time.monotonic()

        # Detect soft error/rate-limit pages by scanning HTML content
        if page_data.html:
            html_lower = page_data.html.lower()
            # Only flag if page is suspiciously short (real product pages are large)
            if len(page_data.html) < 5000:
                for pattern in ERROR_PAGE_PATTERNS:
                    if pattern in html_lower:
                        page_data.loaded = False
                        page_data.status_code = 429  # Treat as rate limit
                        print(f"[PageLoader] Soft rate limit detected ('{pattern}') for {url}")
                        return page_data

        # Log timing breakdown for slow pages (> 3s total)
        total = t_html - t0
        if total > 3.0:
            import sys as _sys
            slug = url.split('/')[-1][:30]
            print(f"[PageLoader SLOW] {slug}: goto={t_goto-t0:.1f}s idle={t_idle-t_goto:.1f}s lazy={t_lazy-t_idle:.1f}s html={t_html-t_lazy:.1f}s TOTAL={total:.1f}s", file=_sys.stderr)

    except Exception as e:
        page_data.loaded = False
        print(f"[PageLoader] Error loading {url}: {e}")

    finally:
        # IMPORTANT: Remove the response listener to prevent memory leaks
        # Without this, each page load adds another listener, and they accumulate
        page.remove_listener('response', capture_response)

    return page_data


async def extract_gallery_images(page, gallery_config) -> List[str]:
    """
    Extract product images from the gallery using a config dict or CSS selector string.

    Args:
        page: Playwright Page object (already loaded)
        gallery_config: Either a config dict with keys:
            - image_selector: CSS selector targeting image elements directly
            - url_attribute: which attribute holds the URL (default "src")
            - container_selector: gallery container (for context)
          Or a plain CSS selector string (legacy/fallback format)

    Returns:
        List of full-resolution image URLs (size suffixes stripped)
    """
    try:
        # Normalize: accept both dict and string
        if isinstance(gallery_config, dict):
            image_selector = gallery_config.get("image_selector", "")
            url_attribute = gallery_config.get("url_attribute", "src")
            container_selector = gallery_config.get("container_selector", "")
        else:
            # Legacy string format — treat as container selector
            image_selector = ""
            url_attribute = "src"
            container_selector = str(gallery_config)

        # Strategy 1: Use image_selector directly (new LLM format)
        if image_selector:
            elements = await page.query_selector_all(image_selector)
            if elements:
                raw_urls = []
                for el in elements:
                    # If LLM said srcset, parse it for the largest URL
                    if url_attribute == "srcset":
                        srcset = await el.get_attribute("srcset")
                        if srcset:
                            best_url = _best_from_srcset(srcset)
                            if best_url:
                                raw_urls.append(best_url)
                                continue

                    # Try the specified attribute first, then fallbacks
                    got_url = False
                    for attr in [url_attribute, "src", "data-src", "data-zoom", "data-large", "data-high-res"]:
                        val = await el.get_attribute(attr)
                        if val and (val.startswith("http") or val.startswith("//")):
                            if val.startswith("//"):
                                val = "https:" + val
                            raw_urls.append(val)
                            got_url = True
                            break

                    # Fallback: check srcset if nothing yet
                    if not got_url:
                        srcset = await el.get_attribute("srcset")
                        if srcset:
                            best_url = _best_from_srcset(srcset)
                            if best_url:
                                raw_urls.append(best_url)

                return _dedupe_and_clean(raw_urls)

        # Strategy 2: Use container_selector + find img/source inside (legacy format)
        if container_selector:
            elements = await page.query_selector_all(
                f"{container_selector} img, {container_selector} source"
            )
            if elements:
                raw_urls = []
                for el in elements:
                    for attr in ["src", "data-src", "data-zoom", "data-large", "data-high-res"]:
                        val = await el.get_attribute(attr)
                        if val and (val.startswith("http") or val.startswith("//")):
                            if val.startswith("//"):
                                val = "https:" + val
                            raw_urls.append(val)

                    srcset = await el.get_attribute("srcset")
                    if srcset:
                        best_url = _best_from_srcset(srcset)
                        if best_url:
                            raw_urls.append(best_url)

                return _dedupe_and_clean(raw_urls)

        return []

    except Exception as e:
        print(f"[GalleryExtract] Error: {e}")
        return []


def _dedupe_and_clean(raw_urls: List[str]) -> List[str]:
    """Deduplicate and strip size suffixes from image URLs."""
    import re
    from urllib.parse import urlparse, parse_qs, unquote

    seen = set()
    cleaned = []
    for url in raw_urls:
        # Unwrap Next.js /_next/image?url=... wrapper
        if '/_next/image' in url:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if 'url' in params:
                url = unquote(params['url'][0])

        clean = _strip_size_suffix(url)
        # Upgrade CDN path-based size variants to largest available
        # e.g. cloudfront.net/r/s/123.jpg or /r/g/123.jpg → /r/b/123.jpg
        clean = re.sub(r'/r/[sgtm]/', '/r/b/', clean)
        identity = clean.split("?")[0].split("/")[-1]  # filename as identity
        if identity not in seen:
            seen.add(identity)
            cleaned.append(clean)
    return cleaned


def _best_from_srcset(srcset: str) -> Optional[str]:
    """Pick the largest image from a srcset attribute."""
    best_url = None
    best_width = 0
    for part in srcset.split(","):
        part = part.strip()
        pieces = part.split()
        if len(pieces) >= 2:
            url = pieces[0]
            descriptor = pieces[1]
            try:
                w = int(descriptor.rstrip("w"))
                if w > best_width:
                    best_width = w
                    best_url = url
            except ValueError:
                pass
        elif len(pieces) == 1 and pieces[0].startswith("http"):
            best_url = best_url or pieces[0]
    return best_url


def _strip_size_suffix(url: str) -> str:
    """
    Strip size/resize parameters from image URLs to get full resolution.

    Handles:
    - ?width=960 → removed
    - &width=750 → removed
    - _140x140.jpg → _140x140 removed
    - Keeps ?v=timestamp (cache busting)
    """
    import re
    from urllib.parse import urlparse, urlencode, parse_qs

    parsed = urlparse(url)

    # Remove size-related query params, keep others (like v=timestamp)
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        size_keys = {"width", "height", "w", "h", "size", "sw", "sh", "resize",
                     "crop", "fit", "quality", "q", "format", "auto"}
        filtered = {k: v[0] for k, v in params.items() if k.lower() not in size_keys}
        new_query = urlencode(filtered) if filtered else ""
        url = parsed._replace(query=new_query).geturl()

    # Remove inline size patterns from filename: _140x140, _500x500, _20x_crop_center, etc.
    url = re.sub(r'_\d{1,4}x\d{0,4}(?:_crop_center)?(?=\.\w{3,4})', '', url)

    return url
