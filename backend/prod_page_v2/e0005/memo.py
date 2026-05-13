"""
Per-page lazy artifact cache.

The orchestrator visits a product page once and asks the catalog for ~38
fields. Many methods share underlying work — parsing the LD+JSON blob,
rendering the page with JS, capturing network XHRs, opening an accordion
to read its text. Without caching, we'd redo all of that 38 times.

PageMemo solves it: every shared artifact is exposed as an `async`
accessor that computes on first call and returns the cached value
thereafter. Methods declare in their `requires` set which artifacts they
need; the memo provisions them lazily.

Three classes of artifact:

1. **Cheap / always-on**: raw HTML (static fetch), parsed LD+JSON dict,
   HTML meta tags. Computed once on first access. ~50ms total.
2. **Render-required**: rendered DOM after JS, network capture log,
   full-page screenshot. Triggers a Playwright load on first access;
   subsequent calls reuse. ~3-8s.
3. **Interactive**: accordion-clicked content. Each panel opened at most
   once, keyed by accordion identifier. Requires render to be active.

Construction is cheap — actual work happens on first accessor call.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass
class NetworkCapture:
    """One network event captured during a Playwright render."""

    url: str
    method: str
    status: int
    content_type: str
    response_body: Optional[Any]  # parsed JSON when applicable; else None
    timing_ms: float = 0.0


class PageMemo:
    """Lazy cache of per-page artifacts. One instance per product URL."""

    def __init__(self, url: str, *, render_wait_ms: int = 4000, stealth: bool = True,
                 external_page: Any = None):
        """Create a PageMemo for `url`.

        external_page (optional): an already-opened Playwright Page from
        outside (e.g. a BrowserPool). When provided, this memo does NOT
        launch its own Chromium — it navigates the given page to `url`
        during `_ensure_rendered()` and reuses it for accordion clicks.
        On `close()`, it does NOT close the page; ownership stays with
        the caller.
        """
        self.url = url
        self.render_wait_ms = render_wait_ms
        self.stealth = stealth

        # Cheap artifacts.
        self._raw_html: Optional[str] = None
        self._ld_json: Optional[List[dict]] = None
        self._ld_json_product: Optional[dict] = None
        self._meta_tags: Optional[Dict[str, str]] = None

        # Render-required artifacts.
        self._rendered_html: Optional[str] = None
        self._visible_text: Optional[str] = None
        self._network: List[NetworkCapture] = []
        self._screenshot_png: Optional[bytes] = None
        self._render_in_flight: Optional[asyncio.Task] = None
        # Held Playwright handles so we can do interactive operations (clicks)
        # after the initial render without re-loading the page.
        self._playwright = None
        self._browser = None
        self._page = external_page
        self._owns_browser = external_page is None

        # Interactive (accordions).
        self._accordion_text: Dict[str, str] = {}

        # Discovery hints / scratch.
        self._discovery_hints: Dict[str, Any] = {}
        self._scratch: Dict[str, Any] = {}

    # =========================================================
    # Cheap accessors
    # =========================================================

    async def raw_html(self) -> str:
        """Static HTML via plain HTTP. Cheap; ~50-300ms."""
        if self._raw_html is None:
            self._raw_html = await asyncio.to_thread(self._fetch_raw_html)
        return self._raw_html

    def _fetch_raw_html(self) -> str:
        req = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            if r.headers.get("content-encoding") == "gzip":
                data = gzip.decompress(data)
            return data.decode("utf-8", errors="ignore")

    async def ld_json_blobs(self) -> List[dict]:
        """All <script type='application/ld+json'> blobs as parsed dicts."""
        if self._ld_json is None:
            # Prefer rendered HTML if we've already paid for it (more complete),
            # else use raw HTML to stay cheap.
            html = self._rendered_html or await self.raw_html()
            blobs: List[dict] = []
            for m in re.finditer(
                r'<script[^>]+application/ld\+json[^>]*>(.+?)</script>',
                html, re.DOTALL,
            ):
                body = m.group(1).strip()
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, list):
                        blobs.extend(b for b in parsed if isinstance(b, dict))
                    elif isinstance(parsed, dict):
                        blobs.append(parsed)
                except json.JSONDecodeError:
                    continue
            self._ld_json = blobs
        return self._ld_json

    async def ld_json_product(self) -> Optional[dict]:
        """The single LD+JSON blob (or @graph entry) with @type=Product."""
        if self._ld_json_product is not None:
            return self._ld_json_product
        for blob in await self.ld_json_blobs():
            items = blob.get("@graph") if isinstance(blob, dict) else None
            candidates = items if items else [blob]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                t = item.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    self._ld_json_product = item
                    return item
        return None

    async def meta_tags(self) -> Dict[str, str]:
        """All <meta name|property=...> tags as a flat {name: content} map."""
        if self._meta_tags is None:
            html = self._rendered_html or await self.raw_html()
            out: Dict[str, str] = {}
            for m in re.finditer(
                r'<meta\s+([^>]+?)>', html, re.IGNORECASE,
            ):
                attrs = m.group(1)
                key = None
                for k in ("property", "name", "itemprop"):
                    mm = re.search(rf'{k}\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                    if mm:
                        key = mm.group(1).strip().lower()
                        break
                if key is None:
                    continue
                cm = re.search(r'content\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE)
                if cm:
                    out[key] = cm.group(1)
            self._meta_tags = out
        return self._meta_tags

    # =========================================================
    # Render-required accessors
    # =========================================================

    async def rendered_html(self) -> str:
        """Page HTML after JS has run. Triggers Playwright load on first call."""
        await self._ensure_rendered()
        return self._rendered_html or ""

    async def visible_text(self) -> str:
        await self._ensure_rendered()
        return self._visible_text or ""

    async def network(self) -> List[NetworkCapture]:
        await self._ensure_rendered()
        return self._network

    async def screenshot(self) -> bytes:
        await self._ensure_rendered()
        return self._screenshot_png or b""

    async def _ensure_rendered(self) -> None:
        """Run the Playwright load once. Concurrent callers share one task."""
        if self._rendered_html is not None:
            return
        if self._render_in_flight is None:
            self._render_in_flight = asyncio.create_task(self._do_render())
        await self._render_in_flight

    async def _do_render(self) -> None:
        # If an external page was injected, skip browser launch.
        if self._page is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            ctx = await self._browser.new_context(user_agent=USER_AGENT)
            self._page = await ctx.new_page()

        async def on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                body = None
                if "json" in ct:
                    try:
                        body = await response.json()
                    except Exception:
                        body = None
                self._network.append(NetworkCapture(
                    url=response.url,
                    method=response.request.method if response.request else "",
                    status=response.status,
                    content_type=ct,
                    response_body=body,
                ))
            except Exception:
                pass

        self._page.on("response", on_response)
        try:
            await self._page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
            try:
                await self._page.wait_for_load_state("networkidle", timeout=self.render_wait_ms)
            except Exception:
                pass
            await self._dismiss_common_overlays()
            self._rendered_html = await self._page.content()
            try:
                self._visible_text = await self._page.inner_text("body")
            except Exception:
                self._visible_text = ""
            self._screenshot_png = await self._page.screenshot(full_page=True)
        except Exception as e:
            # Soft-fail: leave artifacts as None / empty so methods degrade
            # gracefully. Callers can check artifacts_loaded() to diagnose.
            print(f"[PageMemo] render failed for {self.url}: {e!r}")

    async def _dismiss_common_overlays(self) -> None:
        """Best-effort dismissal of cookie banners and common popups so they
        don't intercept later click_and_capture calls.

        Reuses the shared selector list from
        `scraper.navigation.popup_selectors` so the dismissal rules stay
        consistent with the rest of the pipeline. Each click is wrapped —
        a failure on any single selector never blocks render.
        """
        if self._page is None:
            return
        try:
            from scraper.navigation.popup_selectors import (
                POPUP_CLOSE_SELECTORS, OVERLAY_REMOVAL_SELECTORS, POPUP_IFRAME_SELECTORS,
            )
        except Exception:
            # Module path varies depending on how callers configured sys.path;
            # without it we just skip and let render continue.
            return
        for sel in POPUP_CLOSE_SELECTORS:
            try:
                loc = self._page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=1500)
                    await self._page.wait_for_timeout(250)
            except Exception:
                continue
        # Remove any remaining overlay iframes / dialogs in DOM.
        for sel in OVERLAY_REMOVAL_SELECTORS + POPUP_IFRAME_SELECTORS:
            try:
                await self._page.evaluate(
                    "(s) => document.querySelectorAll(s).forEach(e => e.remove())", sel,
                )
            except Exception:
                continue
        # Restore body scroll in case a modal locked it.
        try:
            await self._page.evaluate(
                "() => { document.body.style.overflow = ''; document.documentElement.style.overflow = ''; }"
            )
        except Exception:
            pass

    # =========================================================
    # Interactive accessors
    # =========================================================

    async def click_and_capture(
        self,
        trigger_selector: str,
        panel_selector: Optional[str] = None,
        wait_ms: int = 500,
        key: Optional[str] = None,
        click_timeout_ms: int = 3000,
    ) -> Optional[str]:
        """Click `trigger_selector`, wait for content to expand, return revealed text.

        - If `panel_selector` is given, returns its innerText after the click.
        - Else captures body innerText BEFORE click + AFTER click, returns the
          new lines (diff). This catches accordion/dropdown content without
          mis-capturing the whole page header.
        - Memoized by `key` (defaults to trigger_selector).
        """
        await self._ensure_rendered()
        if self._page is None:
            return None
        memo_key = key or trigger_selector
        if memo_key in self._accordion_text:
            return self._accordion_text[memo_key]

        try:
            trigger = self._page.locator(trigger_selector).first
            if await trigger.count() == 0:
                return None

            # Snapshot body lines pre-click for diff.
            pre_body = ""
            if not panel_selector:
                try:
                    pre_body = await self._page.inner_text("body")
                except Exception:
                    pre_body = ""

            # Cheap pre-check: skip if not visible. Saves us the full
            # click timeout when the element is in DOM but hidden.
            try:
                if not await trigger.is_visible():
                    return None
            except Exception:
                return None
            try:
                await trigger.scroll_into_view_if_needed(timeout=500)
            except Exception:
                pass
            await trigger.click(timeout=click_timeout_ms)
            await self._page.wait_for_timeout(wait_ms)

            if panel_selector:
                panel = self._page.locator(panel_selector).first
                text = await panel.inner_text(timeout=3000) if await panel.count() else ""
            else:
                post_body = await self._page.inner_text("body")
                pre_lines = {l.strip() for l in pre_body.split("\n") if l.strip()}
                new_lines = [
                    l for l in post_body.split("\n")
                    if l.strip() and l.strip() not in pre_lines
                ]
                text = "\n".join(new_lines)
        except Exception as e:
            print(f"[PageMemo] click_and_capture {trigger_selector!r} failed: {e!r}")
            return None

        text = (text or "").strip()
        self._accordion_text[memo_key] = text
        return text

    async def refresh_post_interaction(self) -> None:
        """Re-capture rendered_html, visible_text, and screenshot after
        interactive clicks have modified page state. Called by Phase B so
        Phase C sees the post-reveal page."""
        if self._page is None:
            return
        try:
            self._rendered_html = await self._page.content()
            self._visible_text = await self._page.inner_text("body")
            self._screenshot_png = await self._page.screenshot(full_page=True)
            # Invalidate downstream parses so they reparse from the new HTML.
            self._ld_json = None
            self._ld_json_product = None
            self._meta_tags = None
        except Exception as e:
            print(f"[PageMemo] refresh_post_interaction failed: {e!r}")

    # =========================================================
    # Cleanup / discovery hints / introspection
    # =========================================================

    async def close(self) -> None:
        """Release Playwright resources we own.

        If an external page was injected (via `external_page=`), we do
        NOT close that page or its browser — caller (e.g. BrowserPool)
        owns it. We only release Playwright handles we created ourselves.
        """
        if not self._owns_browser:
            # External page; leave it alone.
            self._page = None
            return
        for x, name in ((self._page, "page"), (self._browser, "browser"),
                        (self._playwright, "playwright")):
            try:
                if x is not None:
                    if name == "playwright":
                        await x.stop()
                    else:
                        await x.close()
            except Exception:
                pass
        self._page = None
        self._browser = None
        self._playwright = None

    def discovery_hint(self, name: str) -> Any:
        return self._discovery_hints.get(name)

    def set_discovery_hint(self, name: str, value: Any) -> None:
        self._discovery_hints[name] = value

    def scratch(self) -> Dict[str, Any]:
        return self._scratch

    async def product_api_candidates(self) -> List[Dict[str, Any]]:
        """Return same-host JSON GET responses that look like product APIs.

        Filtering rules:
          - Same-origin host (sub-host okay, e.g. api.brand.com vs brand.com).
          - method == GET (POSTs are usually bot-protection beacons; we
            don't want production to fire them).
          - URL contains a candidate SKU. The SKU is discovered by trying:
              1) LD+JSON Product blob's $.sku / $.productID / $.mpn
              2) URL slug — alphanumeric ids of 8+ chars with mixed case
          - For matched URLs, build a `url_template` by replacing the SKU
            with `{sku}` and group responses by template. One representative
            response per template.

        Returns a list of dicts:
          { "url_template": "https://…/api/availability/{sku}?…",
            "sample_url":   "https://…/api/availability/870312QJAAC4003?…",
            "sku_source":   "ld_json:$.sku",        # the resolver that produced the SKU
            "response":     {...parsed JSON...},
            "response_preview": "{...}"             # truncated str, for prompts
          }
        """
        if not self._network:
            return []

        # Discover candidate SKUs on this page.
        sku_candidates: List[Tuple[str, str]] = []  # (sku, sku_source)
        blob = await self.ld_json_product()
        for path in ("sku", "productID", "mpn"):
            if blob and isinstance(blob, dict):
                v = blob.get(path)
                if isinstance(v, (str, int)) and len(str(v)) >= 4:
                    sku_candidates.append((str(v), f"ld_json:$.{path}"))
                    break
        # URL-slug fallback: look for an 8+ char mixed alnum token at the end
        # of the URL path, like `…-870312QJAAC4003.html`.
        if not sku_candidates:
            slug = self.url.rsplit("/", 1)[-1]
            m = re.search(r"([A-Z0-9]{8,})", slug)
            if m:
                sku_candidates.append((m.group(1), r"url_pattern:([A-Z0-9]{8,})"))

        if not sku_candidates:
            return []

        from urllib.parse import urlparse
        page_host = urlparse(self.url).netloc.replace("www.", "")
        same_host = lambda u: page_host in urlparse(u).netloc

        seen_templates: Dict[str, Dict[str, Any]] = {}
        for cap in self._network:
            if cap.method != "GET":
                continue
            if "json" not in (cap.content_type or "").lower():
                continue
            if cap.response_body is None:
                continue
            if not same_host(cap.url):
                continue
            for sku, src in sku_candidates:
                if sku in cap.url:
                    template = cap.url.replace(sku, "{sku}")
                    if template in seen_templates:
                        break
                    # No artificial per-brand cap. We serialize the entire
                    # API response so the LLM sees the actual data shape
                    # — sizes, variants, options, whatever lives there.
                    # Token budget is bounded by Claude's 200K context
                    # window; in practice product APIs are 5–50KB each
                    # and we capture only same-host SKU-bearing endpoints.
                    try:
                        preview = json.dumps(cap.response_body, ensure_ascii=False)
                    except Exception:
                        preview = str(cap.response_body)
                    seen_templates[template] = {
                        "url_template": template,
                        "sample_url": cap.url,
                        "sku_source": src,
                        "response": cap.response_body,
                        "response_preview": preview,
                    }
                    break
        return list(seen_templates.values())

    def artifacts_loaded(self) -> List[str]:
        loaded = []
        if self._raw_html is not None: loaded.append("raw_html")
        if self._ld_json is not None: loaded.append(f"ld_json[{len(self._ld_json)}]")
        if self._meta_tags is not None: loaded.append(f"meta_tags[{len(self._meta_tags)}]")
        if self._rendered_html is not None: loaded.append("rendered_html")
        if self._network: loaded.append(f"network[{len(self._network)}]")
        if self._screenshot_png is not None: loaded.append("screenshot")
        if self._accordion_text: loaded.append(f"accordions[{len(self._accordion_text)}]")
        return loaded
