"""One cell of the matrix: this brand, that strategy, what happened and what it cost."""

import ssl

import httpx
import pytest

from backend.archive.access.outcome import Outcome
from backend.archive.access.probe import AccessResult, try_access
from backend.archive.access.strategy import Strategy
from backend.archive.domain.brand import TransportLevel
from backend.archive.transport import HttpxTransport

SHOP_HOME = (
    "<html><head><title>KUURTH</title></head>"
    '<body><script src="https://cdn.shopify.com/x.js"></script></body></html>'
)
THIN_HOME = "<html><head><title>Psylos1</title></head><body><div id=__next></div></body></html>"

OPEN_SHOPIFY = {
    "/robots.txt": httpx.Response(200, text="Sitemap: https://kuurth.com/sitemap.xml\n"),
    "/products.json": httpx.Response(200, json={"products": [{"id": 1}]}),
    "/meta.json": httpx.Response(200, json={"currency": "USD"}),
    "/": httpx.Response(200, text=SHOP_HOME),
}


def strategy_over(routes: dict, *, name="fake", tier=0, usd=0.0, kind="http") -> Strategy:
    """A strategy whose transport answers from a routing table instead of the network."""

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404))

    def factory():
        return HttpxTransport(
            client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        )

    return Strategy(name, tier, kind, TransportLevel.T0, usd, None, factory)


def raising_strategy(exc: BaseException, name="boom") -> Strategy:
    def factory():
        def handler(request):
            raise exc

        return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))

    return Strategy(name, 0, "http", TransportLevel.T0, 0.0, None, factory)


@pytest.mark.unit
def test_an_open_shop_is_reported_as_ok_with_its_capability_kept():
    r = try_access("kuurth.com", strategy_over(OPEN_SHOPIFY), retry_pause=0)
    assert r.outcome is Outcome.OK
    assert r.domain == "kuurth.com" and r.strategy == "fake"
    assert r.capability is not None and r.capability.bulk_json is True


@pytest.mark.unit
def test_the_requests_it_took_are_counted_and_the_statuses_kept():
    r = try_access("kuurth.com", strategy_over(OPEN_SHOPIFY), retry_pause=0)
    assert r.requests >= 4
    assert len(r.statuses) == r.requests  # every request the probe made is recorded
    assert r.statuses.count(200) >= 4
    assert r.seconds >= 0.0


@pytest.mark.unit
def test_a_refusing_shop_is_reported_as_a_waf_block():
    routes = dict.fromkeys(["/robots.txt", "/products.json", "/", "/sitemap.xml"], None)
    routes = {k: httpx.Response(403, text="Access Denied") for k in routes}
    r = try_access("viviennewestwood.com", strategy_over(routes), retry_pause=0)
    assert r.outcome is Outcome.WAF_403


@pytest.mark.unit
def test_a_reachable_shop_with_nothing_readable_is_an_empty_room():
    routes = {
        "/robots.txt": httpx.Response(200, text="Sitemap: https://psylos1.com/sitemap.xml\n"),
        "/products.json": httpx.Response(404),
        "/sitemap.xml": httpx.Response(200, text="<urlset></urlset>"),
        "/": httpx.Response(200, text=THIN_HOME),
    }
    r = try_access("psylos1.com", strategy_over(routes), retry_pause=0)
    assert r.outcome is Outcome.OK_THIN


@pytest.mark.unit
def test_a_refused_handshake_is_a_tls_block_and_keeps_the_reason():
    r = try_access("vancleefarpels.com", raising_strategy(ssl.SSLError("alert")), retry_pause=0)
    assert r.outcome is Outcome.TLS_BLOCKED
    assert r.capability is None
    assert "alert" in r.note


@pytest.mark.unit
def test_a_dead_host_is_unreachable():
    r = try_access(
        "gone.example", raising_strategy(httpx.ConnectTimeout("timed out")), retry_pause=0
    )
    assert r.outcome is Outcome.UNREACHABLE


@pytest.mark.unit
def test_cost_is_charged_per_request_at_the_strategy_rate():
    s = strategy_over(OPEN_SHOPIFY, usd=2.0)  # $2 per 1000 requests
    r = try_access("kuurth.com", s, retry_pause=0)
    assert r.usd == pytest.approx(r.requests * 2.0 / 1000)


@pytest.mark.unit
def test_free_strategies_cost_nothing():
    r = try_access("kuurth.com", strategy_over(OPEN_SHOPIFY, usd=0.0), retry_pause=0)
    assert r.usd == 0.0


@pytest.mark.unit
def test_each_cell_gets_its_own_transport():
    """A browser context that already holds a challenge cookie would make the next
    strategy look better than it is, so nothing may be carried between cells."""
    built = []

    def factory():
        t = HttpxTransport(
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda r: OPEN_SHOPIFY.get(r.url.path, httpx.Response(404))
                ),
                follow_redirects=True,
            )
        )
        built.append(t)
        return t

    s = Strategy("fresh", 0, "http", TransportLevel.T0, 0.0, None, factory)
    try_access("kuurth.com", s, retry_pause=0)
    try_access("kuurth.com", s, retry_pause=0)
    assert len(built) == 2 and built[0] is not built[1]


@pytest.mark.unit
def test_whether_our_own_daemon_was_working_the_host_is_carried_through():
    """A 429 measured while our Render worker is scraping the same host may be us."""
    r = try_access("staud.clothing", strategy_over(OPEN_SHOPIFY), retry_pause=0, daemon_active=True)
    assert r.daemon_active is True


@pytest.mark.unit
def test_not_knowing_whether_the_daemon_was_active_is_not_the_same_as_no():
    r = try_access("kuurth.com", strategy_over(OPEN_SHOPIFY), retry_pause=0)
    assert r.daemon_active is None


@pytest.mark.unit
def test_a_result_round_trips_through_a_plain_dict_for_storage():
    r = try_access("kuurth.com", strategy_over(OPEN_SHOPIFY), retry_pause=0)
    row = r.to_row()
    assert row["domain"] == "kuurth.com" and row["outcome"] == "ok"
    assert AccessResult.from_row(row).outcome is Outcome.OK
