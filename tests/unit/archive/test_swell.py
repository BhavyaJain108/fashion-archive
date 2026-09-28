"""Swell storefronts (yeezy.com): the catalogue behind the API, read with the page's key."""

import httpx
import pytest

from backend.archive.connectors.swell import SwellConnector, api_url, map_product
from backend.archive.domain.brand import Brand, DiscoveryChannel, TransportLevel
from backend.archive.fingerprint import probe
from backend.archive.learn.signature import signature_of
from backend.archive.planner import compose_plan
from tests.unit.archive.test_fingerprint import NO_WOO, make_transport

BRAND = Brand(domain="yeezy.com", homepage_url="https://yeezy.com")
HOME = (
    '<html><body><img src="https://cdn.swell.store/yzy-prod/6ab6/c011/tile.jpg">'
    '<script>{"public_key":"pk_UDtBUDIgX4j2StzcMPjwb7pfsmM1deoK"}</script>'
    '<button data-id="6904bd75cf2f2e0012ba2388">TS-03</button></body></html>'
)
PRODUCT = {
    "id": "6a91f2d30942e900131a077b",
    "name": "YS 02",
    "slug": "ys-02",
    "sku": "YS-02",
    "price": 50,
    "sale": True,
    "sale_price": 40,
    "orig_price": 50,
    "currency": "USD",
    "stock_status": "in_stock",
    "stock_level": 1830,
    "description": "<p>A shoe.</p>",
    "tags": ["new"],
    "attributes": {"collection": {"name": "Collection", "value": "W-01"}},
    "images": [{"file": {"url": "https://cdn.swell.store/yzy-prod/a/b"}}],
    "options": [
        {"name": "Color", "values": [{"name": "Coal"}, {"name": "Brown"}]},
        {"name": "Size", "values": [{"name": "7"}, {"name": "8"}]},
    ],
    "date_updated": "2026-09-27T00:00:00Z",
}
VARIANTS = {
    "results": [
        {"name": "Coal, 7", "stock_status": "in_stock", "stock_level": 3},
        {"name": "Coal, 8", "stock_status": "out_of_stock", "stock_level": 0},
    ]
}


class ApiTransport:
    level = TransportLevel.T1

    def __init__(self):
        self.urls: list[str] = []
        self.ledger: list[dict] = []

    def get(self, url):
        self.urls.append(url)
        if "/api/products?" in url:
            return httpx.Response(200, json={"page": 1, "count": 1, "results": [PRODUCT]})
        if "/variants" in url:
            return httpx.Response(200, json=VARIANTS)
        return httpx.Response(404)


@pytest.mark.unit
def test_the_key_rides_as_basic_auth_in_the_api_url():
    assert api_url("yzy-prod", "pk_x", "products?limit=1") == (
        "https://yzy-prod:pk_x@yzy-prod.swell.store/api/products?limit=1"
    )


@pytest.mark.unit
def test_a_swell_catalogue_is_read_from_the_api_with_per_size_stock():
    t = ApiTransport()
    c = SwellConnector("yzy-prod", "pk_x")
    refs = c.discover(BRAND, t)
    assert [r.url for r in refs] == ["https://yeezy.com/products/ys-02"]
    rec = c.fetch(refs[0], t)
    assert rec.product_title == "YS 02" and rec.product_code == "YS-02"
    assert rec.price == 40.0 and rec.full_price == 50.0 and rec.currency == "USD"
    assert rec.in_stock is True and rec.quantity == 1830
    assert rec.size_info == "7, 8" and rec.size_availability == "in_stock, out_of_stock"
    assert rec.color_info == "Coal, Brown" and rec.category1 == "W-01"
    assert rec.main_image_url == "https://cdn.swell.store/yzy-prod/a/b"
    assert rec.brand == "YEEZY" and rec.description == "A shoe." and rec.platform == "swell"
    assert any("/variants" in u for u in t.urls)


@pytest.mark.unit
def test_a_placeholder_without_price_or_photograph_is_not_a_product():
    from backend.archive.connectors.base import SkipProduct

    with pytest.raises(SkipProduct):
        map_product({"name": "Soon", "slug": "soon"}, "https://y.com/products/soon", [], "Y", None)


@pytest.mark.unit
def test_the_probe_finds_the_store_and_key_on_the_page_and_the_planner_takes_the_api():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(403),
            "/sitemap.xml": httpx.Response(403),
            "/products.json": httpx.Response(403),
            "/": httpx.Response(200, text=HOME),
            # the storefront API, on the store's own host (the fake routes by path)
            "/api/products": httpx.Response(200, json={"count": 35, "results": [PRODUCT]}),
            **NO_WOO,
        }
    )
    cap = probe("yeezy.com", t, retry_pause=0)
    assert cap.platform == "swell"
    assert cap.swell_store == "yzy-prod" and cap.swell_key == "pk_UDtBUDIgX4j2StzcMPjwb7pfsmM1deoK"
    assert cap.readable() and cap.evidence["swell"] == "200-yzy-prod"
    plan = compose_plan(cap)
    assert plan.discovery == DiscoveryChannel.SWELL_API and plan.status == "ready"
    assert plan.swell_store == "yzy-prod"
    assert signature_of(cap).feed == "api" and signature_of(cap).platform == "swell"
