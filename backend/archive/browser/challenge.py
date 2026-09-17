"""A real browser that waits out a JavaScript challenge before asking again.

Gentle Monster (2026-09-17): its pages sit behind an AWS WAF challenge: the
first load answers 202 with a small page whose script works out a token, sets the
`aws-waf-token` cookie about two seconds later, and from then on the site answers 200.
PlaywrightTransport retried immediately after loading the page, before the token existed,
so it always saw the challenge and the brand looked like an empty room.

This does what a visitor's browser does — lets the page's own script run and waits for it
— and nothing more. It does not compute or forge the token itself.

It also paces itself: Gentle Monster's robots.txt asks for `Crawl-delay: 1`.
"""

import time

from backend.archive.browser.transport import PlaywrightTransport

_TOKEN_COOKIES = ("aws-waf-token",)
_CHALLENGE_MARKERS = ("gokuProps", "challenge.js")


def is_challenge(status: int, text: str) -> bool:
    return status == 202 or any(m in text[:5000] for m in _CHALLENGE_MARKERS)


class ChallengeAwareBrowser(PlaywrightTransport):
    def __init__(self, *args, gap: float = 1.1, token_wait: float = 20.0, **kw):
        super().__init__(*args, **kw)
        self.gap = gap
        self.token_wait = token_wait
        self._last = 0.0

    def get(self, url: str):
        resp = self._paced(url)
        if is_challenge(resp.status_code, resp.text) and self._await_token(url):
            resp = self._paced(url)
        return resp

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

    @staticmethod
    def _has_token(ctx) -> bool:
        return any(c["name"] in _TOKEN_COOKIES for c in ctx.cookies())
