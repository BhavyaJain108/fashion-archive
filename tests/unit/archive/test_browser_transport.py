"""PlaywrightTransport tested with a fake Playwright context — no real browser in CI."""

import pytest

from backend.archive.browser.transport import PlaywrightTransport
from backend.archive.domain.brand import TransportLevel


class FakeResponse:
    def __init__(self, status, text, headers=None):
        self.status = status
        self._text = text
        self.headers = headers or {}

    def text(self):
        return self._text


class FakePage:
    def __init__(self, ctx):
        self._ctx = ctx
        self.url = None
        self.closed = False

    def goto(self, url, wait_until=None, timeout=None):
        self.url = url
        self._ctx.calls.append(("goto", url))
        return FakeResponse(200, "", {"content-type": "text/html"})

    def content(self):
        return "<html><body>rendered</body></html>"

    def close(self):
        self.closed = True


class FakeRequest:
    def __init__(self, ctx):
        self._ctx = ctx

    def get(self, url):
        self._ctx.calls.append(("request", url))
        return FakeResponse(200, '{"products": [{"id": 1}]}', {"content-type": "application/json"})


class FakeContext:
    def __init__(self):
        self.calls = []
        self.request = FakeRequest(self)
        self.pages = []

    def new_page(self):
        p = FakePage(self)
        self.pages.append(p)
        return p


@pytest.mark.unit
def test_html_url_uses_page_goto():
    ctx = FakeContext()
    t = PlaywrightTransport(context=ctx)
    resp = t.get("https://gentlemonster.com/us/en/products/some-glasses")
    assert ctx.calls == [("goto", "https://gentlemonster.com/us/en/products/some-glasses")]
    assert "rendered" in resp.text and resp.status_code == 200
    assert t.level == TransportLevel.T2
    assert ctx.pages[0].closed  # page always closed


@pytest.mark.unit
def test_json_url_uses_context_request():
    ctx = FakeContext()
    t = PlaywrightTransport(context=ctx)
    resp = t.get("https://staud.clothing/products.json?limit=250&page=1")
    assert ctx.calls == [("request", "https://staud.clothing/products.json?limit=250&page=1")]
    assert resp.json() == {"products": [{"id": 1}]}


@pytest.mark.unit
def test_ledger_records_browser_requests():
    ctx = FakeContext()
    t = PlaywrightTransport(context=ctx)
    t.get("https://x.com/products.json")
    t.get("https://x.com/products/a")
    assert [e["url"] for e in t.ledger] == [
        "https://x.com/products.json",
        "https://x.com/products/a",
    ]
    assert all(e["status"] == 200 for e in t.ledger)


class ChallengingRequest:
    """Serves a challenge (403) to bare API requests until a real page load happens —
    the Akamai/Cloudflare behaviour seen live on gentlemonster & viviennewestwood (2026-08-30)."""

    def __init__(self, ctx, ever_succeeds=True):
        self._ctx = ctx
        self._ever_succeeds = ever_succeeds

    def get(self, url):
        self._ctx.calls.append(("request", url))
        if self._ctx.warmed and self._ever_succeeds:
            return FakeResponse(200, "<urlset><url><loc>x</loc></url></urlset>", {})
        return FakeResponse(403, "", {})


class ChallengingContext(FakeContext):
    def __init__(self, ever_succeeds=True):
        super().__init__()
        self.warmed = False
        self.request = ChallengingRequest(self, ever_succeeds)

    def new_page(self):
        ctx = self

        class WarmingPage(FakePage):
            def goto(self, url, wait_until=None, timeout=None):
                ctx.warmed = True
                ctx.calls.append(("goto", url))
                return FakeResponse(200, "", {})

        p = WarmingPage(self)
        self.pages.append(p)
        return p


@pytest.mark.unit
def test_challenged_api_request_warms_up_via_page_then_retries():
    ctx = ChallengingContext()
    t = PlaywrightTransport(context=ctx)
    resp = t.get("https://www.viviennewestwood.com/sitemap_index.xml")
    assert resp.status_code == 200 and "urlset" in resp.text
    assert [c[0] for c in ctx.calls] == ["request", "goto", "request"]  # blocked → warm → retry
    assert t.ledger[-1]["status"] == 200


@pytest.mark.unit
def test_still_blocked_after_warmup_reports_the_failure_honestly():
    ctx = ChallengingContext(ever_succeeds=False)
    resp = PlaywrightTransport(context=ctx).get("https://x.com/sitemap.xml")
    assert resp.status_code == 403  # no pretending
