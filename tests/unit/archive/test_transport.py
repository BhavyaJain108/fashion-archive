import httpx
import pytest

from backend.archive.domain.brand import TransportLevel
from backend.archive.transport import BROWSER_HEADERS, HttpxTransport


@pytest.mark.unit
def test_get_sends_browser_headers_and_follows_redirects():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("user-agent")
        if request.url.path == "/":
            return httpx.Response(301, headers={"location": "https://www.x.com/home"})
        return httpx.Response(200, text="ok")

    client = httpx.Client(
        transport=httpx.MockTransport(handler), headers=BROWSER_HEADERS, follow_redirects=True
    )
    t = HttpxTransport(client=client)
    resp = t.get("https://x.com/")
    assert resp.status_code == 200 and str(resp.url) == "https://www.x.com/home"
    assert "Mozilla/5.0" in seen["ua"]
    assert t.level == TransportLevel.T0


@pytest.mark.unit
def test_ledger_records_every_request():
    """Auditability: the transport keeps a complete list of what it asked and what came back."""
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="hi")))
    t = HttpxTransport(client=client)
    t.get("https://x.com/a")
    t.get("https://x.com/b")
    assert [e["url"] for e in t.ledger] == ["https://x.com/a", "https://x.com/b"]
    assert t.ledger[0]["status"] == 200 and t.ledger[0]["bytes"] == 2


@pytest.mark.unit
def test_get_does_not_raise_on_4xx():
    """Fingerprinting interprets 429/403/404 as evidence, not errors."""
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    assert HttpxTransport(client=client).get("https://x.com/products.json").status_code == 429


@pytest.mark.unit
def test_a_gzipped_page_is_read_once_and_a_huge_one_is_refused():
    """The streamed read decodes the body; the Response it hands back must not carry
    the encoding header or httpx decodes it again (DecodingError, 2026-09-23, five
    learn runs). And a body past the cap is dropped, not held."""
    import gzip

    import httpx

    from backend.archive.transport import MAX_BODY_BYTES, HttpxTransport, ResponseTooLarge

    page = gzip.compress(b"<html>" + b"x" * 1000 + b"</html>")

    def handler(request):
        if request.url.path == "/big":
            return httpx.Response(
                200, headers={"content-length": str(MAX_BODY_BYTES + 1)}, content=b""
            )
        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=page)

    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    resp = t.get("https://example.com/page")
    assert resp.status_code == 200 and resp.text.startswith("<html>") and len(resp.content) == 1013
    assert "content-encoding" not in resp.headers
    with pytest.raises(ResponseTooLarge):
        t.get("https://example.com/big")
