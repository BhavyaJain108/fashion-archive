"""A real browser that waits out a JavaScript challenge before asking again.

Gentle Monster (2026-09-17): its pages sit behind an AWS WAF challenge: the
first load answers 202 with a small page whose script works out a token, sets the
`aws-waf-token` cookie about two seconds later, and from then on the site answers 200.
PlaywrightTransport retried immediately after loading the page, before the token existed,
so it always saw the challenge and the brand looked like an empty room.

This does what a visitor's browser does — lets the page's own script run and waits for it
— and nothing more. It does not compute or forge the token itself.

The browser is then put away. The token is a cookie, and the site answers ordinary HTTP
that carries it: measured on Gentle Monster, a product page comes back 200 in 0.3s over
curl_cffi against 3s through the browser. So a run costs one 2.5-second browser launch
rather than one per page — 1,332 products in about seven minutes instead of an hour, and
33 MB of resident memory instead of 477.

`render=True` keeps every request in the browser, for a site whose products only exist
after its JavaScript has run. Nothing on the roster needs that today; Gentle Monster's
pages carry their JSON-LD in the HTML once the token is accepted.

It also paces itself: Gentle Monster's robots.txt asks for `Crawl-delay: 1`.
"""

import time

from backend.archive.browser.stealth import STEALTH_USER_AGENT
from backend.archive.browser.transport import PlaywrightTransport

_TOKEN_COOKIES = ("aws-waf-token",)
_CHALLENGE_MARKERS = ("gokuProps", "challenge.js")


def is_challenge(status: int, text: str) -> bool:
    return status == 202 or any(m in text[:5000] for m in _CHALLENGE_MARKERS)


class ChallengeAwareBrowser(PlaywrightTransport):
    def __init__(
        self, *args, gap: float = 1.1, token_wait: float = 20.0, render: bool = False, **kw
    ):
        super().__init__(*args, **kw)
        # When true, every request goes through the browser. Only a site that builds its
        # products in the page needs that; a challenge alone does not.
        self.render = render
        self._cheap = None
        self.gap = gap
        self.token_wait = token_wait
        self._last = 0.0

    def get(self, url: str):
        if not self.render:
            cheap = self._over_http(url)
            if cheap is not None and not is_challenge(cheap.status_code, cheap.text):
                return cheap
            # Either we hold no token yet or the one we hold has expired. Mint another
            # with a short browser visit, then go back to plain HTTP.
            if self._await_token(url):
                cheap = self._over_http(url)
                if cheap is not None and not is_challenge(cheap.status_code, cheap.text):
                    return cheap

        resp = self._paced(url)
        if is_challenge(resp.status_code, resp.text) and self._await_token(url):
            resp = self._paced(url)
        return resp

    def _over_http(self, url: str):
        """The same request without a browser, carrying whatever cookies we hold."""
        if self._context is None:
            return None  # nothing has been minted yet, so there is no cookie to carry
        session = self._cheap_session()
        wait = self._last + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            resp = session.get(url, allow_redirects=True)
        except Exception:  # noqa: BLE001 — fall back to the browser rather than fail here
            return None
        finally:
            self._last = time.monotonic()
        self.ledger.append({"url": url, "status": resp.status_code, "bytes": len(resp.content)})
        return resp

    def _cheap_session(self):
        from curl_cffi import requests as cffi_requests

        from backend.archive.transport import DEFAULT_IMPERSONATE

        if self._cheap is None:
            self._cheap = cffi_requests.Session(impersonate=DEFAULT_IMPERSONATE, timeout=20.0)
            self._cheap.headers.update({"User-Agent": STEALTH_USER_AGENT})
        # Re-read every time: a fresh mint replaces the token the old cookie held.
        for cookie in self._ensure_context().cookies():
            self._cheap.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"])
        return self._cheap

    def _paced(self, url: str):
        wait = self._last + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return super().get(url)
        finally:
            self._last = time.monotonic()

    def _await_token(self, url: str) -> bool:
        """Hold a tab open on the challenge until its script has set the token.

        The parent transport reads a page and closes it at once, which kills the challenge
        script mid-calculation — so no token ever appears. This is the difference between
        the automated probe failing and the same site opening by hand (2026-09-17).
        """
        ctx = self._ensure_context()
        if self._has_token(ctx):
            return True
        page = ctx.new_page()
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:  # noqa: BLE001 — the challenge may navigate while loading
                pass
            deadline = time.monotonic() + self.token_wait
            while time.monotonic() < deadline:
                if self._has_token(ctx):
                    return True
                page.wait_for_timeout(500)
            return False
        finally:
            page.close()

    def close(self) -> None:
        if self._cheap is not None:
            self._cheap.close()
            self._cheap = None
        super().close()

    @staticmethod
    def _has_token(ctx) -> bool:
        return any(c["name"] in _TOKEN_COOKIES for c in ctx.cookies())
