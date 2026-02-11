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

# WAF/bot challenge detection threshold and markers
WAF_MAX_LENGTH = 5000  # Real product pages are much larger than this

WAF_MARKERS = [
    'aws-waf', 'awswaf', 'challenge.js',
    'captcha', 'cf-browser-verification',
    'challenge-platform', 'challenge-form',
    'just a moment', 'checking your browser',
    'attention required', 'cf-challenge',
    'verify you are human', 'bot detection',
]


def _is_waf_page(html: str) -> bool:
    """Detect if the loaded page is a WAF/bot challenge instead of real content."""
    if not html or len(html) > WAF_MAX_LENGTH:
        return False
    html_lower = html.lower()
    return any(marker in html_lower for marker in WAF_MARKERS)


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
        PageData with HTML and captured JSON responses.
        If stealth triggers a WAF challenge, automatically retries with vanilla
        and sets page_data.waf_detected = True so callers can cache the preference.
    """
    page_data = PageData(url=url)

    if stealth:
        await _load_page_stealth(page_data, url, wait_time, headless)

        # Check if stealth triggered a WAF/bot challenge
        if _is_waf_page(page_data.html):
            print(f"[PageLoader] WAF detected with stealth browser ({len(page_data.html)} chars), retrying vanilla...")
            # Reset page_data and retry without stealth
            page_data = PageData(url=url)
            await _load_page_vanilla(page_data, url, wait_time, headless)
            page_data.waf_detected = True
            print(f"[PageLoader] Vanilla retry: {len(page_data.html)} chars (WAF {'still present' if _is_waf_page(page_data.html) else 'bypassed'})")
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

            # Capture image URLs (including GIFs)
            if 'image' in content_type or any(ext in req_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
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

            # Capture image URLs (including GIFs)
            if 'image' in content_type or any(ext in req_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
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
        # Capture image URLs (including GIFs)
        if 'image' in content_type or any(ext in req_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
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

        # Detect WAF/bot challenge pages (stealth patches in pool browsers can trigger these)
        if _is_waf_page(page_data.html):
            page_data.waf_detected = True
            page_data.loaded = False
            print(f"[PageLoader] WAF challenge detected ({len(page_data.html)} chars) for {url}")
            return page_data

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


async def extract_gallery_images(page, gallery_config, ancestry_depth: int = 4) -> List[str]:
    """
    Extract product images from the gallery using DOM ancestry-based clustering.

    The key insight: product images share a common DOM ancestor. By clustering
    images by their ancestry path, we can filter out recommendation sections,
    related products, and other non-product images that live in different
    parts of the DOM tree.

    Args:
        page: Playwright Page object (already loaded)
        gallery_config: Either a config dict with keys:
            - image_selector: CSS selector targeting image elements directly
            - url_attribute: which attribute holds the URL (default "src")
            - container_selector: gallery container (for context)
          Or a plain CSS selector string (legacy/fallback format)
        ancestry_depth: How many levels up to consider for clustering (default 4)

    Returns:
        List of full-resolution image URLs from the primary product cluster
    """
    try:
        # Normalize config format
        if isinstance(gallery_config, dict):
            # New format: multiple selectors
            image_selectors = gallery_config.get("image_selectors", [])
            # Legacy format: single selector
            if not image_selectors:
                single = gallery_config.get("image_selector", "")
                if single:
                    image_selectors = [single]
            url_attribute = gallery_config.get("url_attribute", "src")
            container_selector = gallery_config.get("container_selector", "")

            # Build combined selector
            if image_selectors:
                selector = ", ".join(image_selectors)
            elif container_selector:
                selector = f"{container_selector} img, {container_selector} source"
            else:
                return []
        else:
            # Legacy string format — treat as container selector
            url_attribute = "src"
            selector = f"{gallery_config} img, {gallery_config} source"

        # Extract images WITH their ancestry paths using JavaScript
        # This lets us cluster images by their DOM position
        images_with_ancestry = await page.evaluate(f"""(config) => {{
            const selector = config.selector;
            const urlAttr = config.urlAttr;
            const depth = config.depth;

            const elements = document.querySelectorAll(selector);
            const results = [];

            for (let i = 0; i < elements.length; i++) {{
                const el = elements[i];

                // Get the image URL from various attributes
                let url = null;
                const attrs = [urlAttr, 'src', 'data-src', 'data-zoom', 'data-large', 'data-high-res'];
                for (const attr of attrs) {{
                    const val = el.getAttribute(attr);
                    if (val && (val.startsWith('http') || val.startsWith('//'))) {{
                        url = val.startsWith('//') ? 'https:' + val : val;
                        break;
                    }}
                }}

                // Try srcset if no URL yet
                if (!url) {{
                    const srcset = el.getAttribute('srcset');
                    if (srcset) {{
                        // Get largest from srcset
                        let bestUrl = null;
                        let bestWidth = 0;
                        for (const part of srcset.split(',')) {{
                            const pieces = part.trim().split(/\\s+/);
                            if (pieces.length >= 2) {{
                                const w = parseInt(pieces[1]);
                                if (w > bestWidth) {{
                                    bestWidth = w;
                                    bestUrl = pieces[0];
                                }}
                            }} else if (pieces[0] && pieces[0].startsWith('http')) {{
                                bestUrl = bestUrl || pieces[0];
                            }}
                        }}
                        url = bestUrl;
                    }}
                }}

                if (!url) continue;

                // Build ancestry path: walk up N levels and capture tag.class signatures
                const ancestry = [];
                let node = el.parentElement;
                for (let j = 0; j < depth && node && node !== document.body; j++) {{
                    const tag = node.tagName.toLowerCase();
                    const cls = (node.className && typeof node.className === 'string')
                        ? '.' + node.className.trim().split(/\\s+/).slice(0, 2).join('.')
                        : '';
                    ancestry.push(tag + cls);
                    node = node.parentElement;
                }}

                results.push({{
                    url: url,
                    ancestry: ancestry.join(' > '),
                    domIndex: i  // preserve DOM order
                }});
            }}

            return results;
        }}""", {"selector": selector, "urlAttr": url_attribute, "depth": ancestry_depth})

        if not images_with_ancestry:
            return []

        # Cluster images by their ancestry path
        # Images sharing the same ancestor chain are likely in the same gallery section
        clusters = {}
        for img in images_with_ancestry:
            ancestry = img.get("ancestry", "")
            if ancestry not in clusters:
                clusters[ancestry] = []
            clusters[ancestry].append(img)

        if not clusters:
            return []

        # Pick the primary cluster: the LARGEST one (product galleries have the most images)
        # If there's only one cluster, use it
        if len(clusters) == 1:
            primary_cluster = list(clusters.values())[0]
        else:
            # Sort clusters by size (descending), then by DOM order as tiebreaker
            sorted_clusters = sorted(
                clusters.values(),
                key=lambda c: (-len(c), min(img["domIndex"] for img in c))
            )
            primary_cluster = sorted_clusters[0]

            # Debug logging
            print(f"[GalleryExtract] Found {len(clusters)} clusters, selected primary with {len(primary_cluster)} images")
            for ancestry, imgs in clusters.items():
                marker = "→" if imgs == primary_cluster else " "
                print(f"  {marker} [{len(imgs)} imgs] {ancestry[:60]}...")

        # Extract URLs from primary cluster, preserving order
        raw_urls = [img["url"] for img in sorted(primary_cluster, key=lambda x: x["domIndex"])]

        return _dedupe_and_clean(raw_urls)

    except Exception as e:
        print(f"[GalleryExtract] Error: {e}")
        import traceback
        traceback.print_exc()
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
