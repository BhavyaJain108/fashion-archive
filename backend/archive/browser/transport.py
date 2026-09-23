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

DRIVERS = ("playwright", "patchright")


def stealth_scripts(driver: str) -> list[str]:
    """What to inject before every page load, for this driver.

    Plain Playwright needs STEALTH_JS: it announces itself, and the patches cover the
    properties Cloudflare & friends read.

    Patchright must be given nothing. It removes the automation traces down at the CDP
    layer, and a JS patch on top puts back the very thing it stripped — a property whose
    getter does not read as native is itself the signal detectors look for now, so
    "extra stealth" here makes the browser more detectable, not less.
    """
    return [STEALTH_JS] if driver == "playwright" else []


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

    def __init__(self, context=None, headless: bool = True, driver: str = "playwright"):
        """context: an injected Playwright BrowserContext (tests pass a fake). If None, a real
        stealthed Chromium is launched lazily on first use.

        driver: which library drives it. Patchright is API-compatible with Playwright but
        patches the automation traces at the CDP layer instead of in page JS, so the two
        are genuinely different lanes and worth measuring against each other.
        """
        if driver not in DRIVERS:
            raise ValueError(f"unknown driver {driver!r}; expected one of {', '.join(DRIVERS)}")
        self.driver = driver
        self._context = context
        self._headless = headless
        self._pw = None
        self._browser = None
        self.ledger: list[dict] = []

    def _ensure_context(self):
        if self._context is not None:
            return self._context
        if self.driver == "patchright":
            from patchright.sync_api import sync_playwright
        else:
            from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        # Not sandboxed. Chromium's sandbox needs unprivileged user namespaces, and
        # Render's containers do not grant them: with it on, both workers hung in
        # the browser launch for the first gated brand of the day (2026-09-23,
        # 17:09) and never came back. The container runs as pwuser instead, so a
        # renderer escape still lands in an unprivileged process.
        self._browser = self._pw.chromium.launch(
            headless=self._headless, args=stealth_args(), chromium_sandbox=False
        )
        self._context = self._browser.new_context(user_agent=STEALTH_USER_AGENT)
        for script in stealth_scripts(self.driver):
            self._context.add_init_script(script)
        return self._context

    def statuses(self) -> list[int]:
        """Every status this transport saw, in order. What the classifier reads."""
        return [row["status"] for row in self.ledger]

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
        # The driver is stopped even when the browser refuses to close (a crashed
        # Chromium): otherwise the node process outlives the run.
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:  # noqa: BLE001
            pass
        if self._pw is not None:
            self._pw.stop()
