import json
from pathlib import Path

import httpx
import pytest

from backend.archive.connectors.base import ChannelBlocked
from backend.archive.connectors.woocommerce import WooConnector
from backend.archive.domain.brand import Brand
from backend.archive.transport import HttpxTransport

FIX = Path(__file__).parent / "fixtures"
BRAND = Brand(domain="wiacollections.com", homepage_url="https://wiacollections.com")


def make_transport(v1_ok=True) -> HttpxTransport:
    products = json.loads((FIX / "woo_products_page1.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/wp-json/wc/store/v1/products" and not v1_ok:
            return httpx.Response(404)
        if request.url.path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
            page = request.url.params.get("page", "1")
            return httpx.Response(200, json=products if page == "1" else [])
        return httpx.Response(404)

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.unit
def test_discover_and_map_with_minor_unit_prices():
    refs = WooConnector().discover(BRAND, make_transport())
    assert len(refs) == 2
    rec = WooConnector().fetch(refs[0], transport=None)
    assert rec.product_title == "Wia Jacket" and rec.product_code == "WIA-J1"
    assert rec.price == 199.0 and rec.full_price == 250.0 and rec.currency == "EUR"
    assert rec.in_stock is True
    assert rec.size_info == "S, M, L"
    assert rec.category1 == "Jackets"
    assert rec.description == "Wool twill."


@pytest.mark.unit
def test_no_sale_and_out_of_stock():
    refs = WooConnector().discover(BRAND, make_transport())
    rec = WooConnector().fetch(refs[1], transport=None)
    assert rec.full_price is None and rec.price == 45.0 and rec.in_stock is False


@pytest.mark.unit
def test_change_hint_is_stable_and_price_sensitive():
    refs_a = WooConnector().discover(BRAND, make_transport())
    refs_b = WooConnector().discover(BRAND, make_transport())
    assert refs_a[0].change_hint == refs_b[0].change_hint  # deterministic
    assert refs_a[0].change_hint != refs_a[1].change_hint


@pytest.mark.unit
def test_falls_back_to_legacy_store_path():
    refs = WooConnector().discover(BRAND, make_transport(v1_ok=False))
    assert len(refs) == 2


@pytest.mark.unit
def test_blocked_raises():
    t = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    )
    with pytest.raises(ChannelBlocked):
        WooConnector().discover(BRAND, t)


@pytest.mark.unit
def test_a_zero_price_on_an_unpurchasable_product_is_not_a_price():
    """wiacollections quotes 0 for variable products it will not sell. Storing 0.0
    asserts they are free, which the shop never said."""
    from backend.archive.connectors.woocommerce import map_woo_product

    base = {
        "id": 1, "name": "Nightmare Set", "permalink": "https://w.test/product/set/",
        "images": [], "categories": [], "attributes": [], "is_in_stock": False,
        "prices": {"price": "0", "regular_price": "0", "currency_minor_unit": 0},
    }
    unpurchasable = map_woo_product({**base, "is_purchasable": False})
    assert unpurchasable.price is None
    assert unpurchasable.full_price is None  # the struck-through price is no more real
    # a purchasable product priced at zero is a giveaway, and that is a real price
    assert map_woo_product({**base, "is_purchasable": True}).price == 0
