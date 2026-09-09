"""Browser transport (T2): drives one persistent stealthed Chromium context, but presents
the exact same .get()/ledger surface as HttpxTransport so connectors never know the difference.

HTML pages go through page.goto (executes JS, passes challenges); JSON/XML endpoints go through
context.request.get (rides the challenge cookies the context already holds). Playwright is
imported lazily so importing this module never requires a browser to be installed.
"""

import re

from backend.archive.browser.stealth import STEALTH_JS, STEALTH_USER_AGENT, stealth_args
from backend.archive.domain.brand import TransportLevel

_JSON_OR_XML = re.compile(r"\.(json|xml)(\?|$)|/wp-json/", re.I)


class BrowserResponse:
    """Duck-types the slice of httpx.Response that connectors use."""

    def __init__(self, url: str, status_code: int, text: str, headers: dict):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.headers = headers

    @property
    def content(self) -> bytes:
        return self.text.encode("utf-8", "replace")

    def json(self):
        import json

        return json.loads(self.text)


class PlaywrightTransport:
    level = TransportLevel.T2

    def __init__(self, context=None, headless: bool = True):
        """context: an injected Playwright BrowserContext (tests pass a fake). If None, a real
        stealthed Chromium is launched lazily on first use."""
        self._context = context
        self._headless = headless
        self._pw = None
        self._browser = None
        self.ledger: list[dict] = []

    def _ensure_context(self):
        if self._context is not None:
            return self._context
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless, args=stealth_args())
        self._context = self._browser.new_context(user_agent=STEALTH_USER_AGENT)
        self._context.add_init_script(STEALTH_JS)
        return self._context

    def get(self, url: str) -> BrowserResponse:
        ctx = self._ensure_context()
        if _JSON_OR_XML.search(url):
            resp = ctx.request.get(url)
            if resp.status != 200:
                # A bare API request executes no JS, so it never clears a bot challenge.
                # Load the URL as a page (which does), then retry — the context now holds
                # the challenge cookies. Live bug: gentlemonster/viviennewestwood 2026-08-30.
                self._warm_up(ctx, url)
                resp = ctx.request.get(url)
            out = BrowserResponse(url, resp.status, resp.text(), dict(resp.headers))
        else:
            page = ctx.new_page()
            try:
                nav = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                status = nav.status if nav else 0
                out = BrowserResponse(
                    page.url, status, page.content(), dict(nav.headers) if nav else {}
                )
            finally:
                page.close()
        self.ledger.append({"url": url, "status": out.status_code, "bytes": len(out.content)})
        return out

    def _warm_up(self, ctx, url: str) -> None:
        """Navigate a real page so the context collects challenge cookies."""
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass  # a failed warm-up just means the retry will report the block honestly
        finally:
            page.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
