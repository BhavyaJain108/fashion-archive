"""EQL's launch platform: products are draws, and the page data is the record."""

from datetime import datetime, timezone

import httpx
import pytest

from backend.archive.connectors.base import ChannelBlocked, SkipProduct
from backend.archive.connectors.runfair import RunfairConnector, map_draw, selling
from backend.archive.domain.brand import Brand
from backend.archive.transport import HttpxTransport

BRAND = Brand(domain="luar.runfair.com", homepage_url="https://luar.runfair.com")
NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)

INDEX = {
    "result": {
        "pageContext": {
            "retailers": [
                {
                    "draws": [
                        {
                            "id": "LUAR0002US",
                            "country": "US",
                            "slug": "small-ana",
                            "end": "2026-09-01T22:00:00.000Z",
                        },
                        {
                            "id": "LUAR0003US",
                            "country": "US",
                            "slug": "mini-ana",
                            "end": "2026-09-01T22:00:00.000Z",
                        },
                        {"id": "LUAR0001GB", "country": "GB", "slug": "mini-ana", "end": None},
                    ]
                }
            ]
        }
    }
}

DRAW = {
    "id": "LUAR0003US",
    "country": "US",
    "currency": "USD",
    "price": 185,
    "product": "The Limited-Edition Snake Mini Ana",
    "description": "A compact interpretation of the signature Ana.\n\nMaterials & Care\n- 100% leather",
    "sku": "LUAR_MINI_ANA_SNK",
    "slug": "mini-ana",
    "hero": {"url": "https://cdn.eql.media/a.jpg"},
    "gallery": [{"url": "https://cdn.eql.media/a.jpg"}, {"url": "https://cdn.eql.media/b.jpg"}],
    "inventory": [{"name": "Snake", "maxProductQuantityPerEntry": 5}],
    "isPublished": True,
    "start": "2026-08-26T18:00:00.000Z",
    "end": "2026-09-01T22:00:00.000Z",
}


def transport() -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/page-data/index/page-data.json":
            return httpx.Response(200, json=INDEX)
        if path == "/page-data/us/mini-ana/page-data.json":
            return httpx.Response(200, json={"result": {"pageContext": {"draw": DRAW}}})
        return httpx.Response(404)

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.unit
def test_discover_lists_the_markets_draws():
    refs = RunfairConnector(market="US").discover(BRAND, transport())
    assert [r.url for r in refs] == [
        "https://luar.runfair.com/us/small-ana",
        "https://luar.runfair.com/us/mini-ana",
    ]
    assert refs[0].change_hint == "2026-09-01T22:00:00.000Z"


@pytest.mark.unit
def test_without_a_market_every_country_is_read():
    refs = RunfairConnector(market=None).discover(BRAND, transport())
    assert len(refs) == 3 and refs[2].url.endswith("/gb/mini-ana")


@pytest.mark.unit
def test_no_page_data_is_a_blocked_channel():
    def handler(request):
        return httpx.Response(403)

    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ChannelBlocked):
        RunfairConnector().discover(BRAND, t)


@pytest.mark.unit
def test_fetch_reads_the_draw():
    c = RunfairConnector(market="US", now=NOW)
    refs = c.discover(BRAND, transport())
    rec = c.fetch(refs[1], transport())
    assert rec.product_title == "The Limited-Edition Snake Mini Ana"
    assert rec.price == 185.0 and rec.currency == "USD" and rec.market == "US"
    assert rec.product_code == "LUAR_MINI_ANA_SNK"
    assert rec.main_image_url == "https://cdn.eql.media/a.jpg"
    assert rec.all_images == '["https://cdn.eql.media/a.jpg", "https://cdn.eql.media/b.jpg"]'
    assert rec.variant_info == "Snake"
    assert rec.in_stock is True
    assert rec.platform == "runfair"


@pytest.mark.unit
def test_a_draw_the_index_lists_but_the_site_has_dropped_is_skipped():
    c = RunfairConnector(market="US")
    refs = c.discover(BRAND, transport())
    with pytest.raises(SkipProduct):
        c.fetch(refs[0], transport())  # /page-data/us/small-ana/… → 404


@pytest.mark.unit
def test_a_draw_sells_only_inside_its_window():
    assert selling(DRAW, now=NOW) is True
    assert selling(DRAW, now=datetime(2026, 9, 2, tzinfo=timezone.utc)) is False
    assert selling(DRAW, now=datetime(2026, 8, 1, tzinfo=timezone.utc)) is False
    assert selling({**DRAW, "isPublished": False}, now=NOW) is False
    assert selling({**DRAW, "end": None}, now=datetime(2027, 1, 1, tzinfo=timezone.utc)) is True


@pytest.mark.unit
def test_a_draw_without_a_name_is_skipped():
    with pytest.raises(SkipProduct):
        map_draw({**DRAW, "product": None}, "https://luar.runfair.com/us/x")
