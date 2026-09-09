import json
from pathlib import Path

import httpx
import pytest

from backend.archive.connectors.base import ChannelBlocked
from backend.archive.connectors.shopify import ShopifyConnector, map_product
from backend.archive.domain.brand import Brand
from backend.archive.transport import HttpxTransport

FIX = Path(__file__).parent / "fixtures"
BRAND = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")


def make_transport() -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        name = "shopify_products_page1.json" if page == "1" else "shopify_products_page2.json"
        return httpx.Response(200, json=json.loads((FIX / name).read_text()))

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.unit
def test_discover_pages_until_empty_and_carries_payloads():
    refs = ShopifyConnector().discover(BRAND, make_transport())
    assert [r.url for r in refs] == [
        "https://kuurth.com/products/nemo-hoodie",
        "https://kuurth.com/products/ring-one",
    ]
    assert refs[0].change_hint == "2026-08-20T09:30:00-04:00"
    assert refs[0].payload["title"] == "Nemo Hoodie"


@pytest.mark.unit
def test_fetch_maps_payload_without_http():
    refs = ShopifyConnector().discover(BRAND, make_transport())
    rec = ShopifyConnector().fetch(refs[0], transport=None)  # no HTTP needed → None is safe
    # product_code is the brand's SKU, not the URL slug
    assert rec.product_title == "Nemo Hoodie" and rec.product_code == "NEMO-M"
    assert (rec.additional_code_1, rec.additional_code_1_type) == ("4901234567894", "EAN")
    assert rec.price == 126.0 and rec.full_price == 180.0  # compare_at_price → sale detection
    assert rec.in_stock is True
    assert rec.size_info == "M, L"
    assert rec.size_availability == "in_stock, out_of_stock"  # aligned with size_info
    # category1..10 is a navigation path; tags are a flat set and belong in their own
    # field. "Hoodies > unisex > fleece" was never a hierarchy the shop published.
    assert (rec.category1, rec.category2) == ("Hoodies", None)
    assert rec.additional_tags == "unisex, fleece"
    assert rec.main_image_url == "https://cdn.shopify.com/s/files/nemo-1.jpg"
    assert rec.description == "Heavy fleece."


@pytest.mark.unit
def test_no_compare_at_price_means_no_full_price():
    rec = map_product(
        json.loads((FIX / "shopify_products_page1.json").read_text())["products"][1], "kuurth.com"
    )
    assert rec.full_price is None and rec.price == 95.0


@pytest.mark.unit
def test_challenge_raises_channel_blocked():
    t = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    )
    with pytest.raises(ChannelBlocked):
        ShopifyConnector().discover(BRAND, t)


@pytest.mark.unit
def test_the_store_currency_reaches_the_record():
    """/products.json states prices with no currency; the store states it at
    /meta.json, once, for every product."""
    from backend.archive.connectors.shopify import map_product

    p = {
        "handle": "tee",
        "title": "Tee",
        "variants": [{"price": "40.00", "available": True, "option1": "S"}],
        "images": [],
        "tags": [],
    }
    assert map_product(p, "kuurth.com").currency is None
    assert map_product(p, "kuurth.com", "USD").currency == "USD"


def _product(options, variants):
    return {
        "handle": "tee",
        "title": "Tee",
        "options": [{"name": n} for n in options],
        "variants": variants,
        "images": [],
        "tags": [],
    }


@pytest.mark.unit
def test_option1_is_not_always_the_size():
    """437 products in a five-brand sample are laid out ("Color", "Size"): reading
    option1 as the size stored colours as sizes and left colour empty."""
    rec = map_product(
        _product(
            ["Color", "Size"],
            [
                {"option1": "Black", "option2": "S", "price": "40.00", "available": True},
                {"option1": "Black", "option2": "M", "price": "40.00", "available": False},
                {"option1": "Cream", "option2": "S", "price": "40.00", "available": False},
            ],
        ),
        "kuurth.com",
    )
    assert rec.size_info == "S, M"
    assert rec.color_info == "Black, Cream"
    # S is in stock in black even though the cream S is not
    assert rec.size_availability == "in_stock, out_of_stock"


@pytest.mark.unit
def test_a_single_variant_product_has_no_size():
    """860 products in the same sample carry one option, "Title", whose only value is
    "Default Title" — which was being stored as a size."""
    rec = map_product(
        _product(["Title"], [{"option1": "Default Title", "price": "40.00", "available": True}]),
        "kuurth.com",
    )
    assert rec.size_info is None
    assert rec.in_stock is True


@pytest.mark.unit
def test_options_are_matched_by_name_in_any_position_or_wording():
    rec = map_product(
        _product(
            ["Select the material", "Select the size"],
            [
                {"option1": "Silver", "option2": "16 mm", "price": "90.00", "available": True},
                {"option1": "Gold", "option2": "18 mm", "price": "95.00", "available": True},
            ],
        ),
        "kuurth.com",
    )
    assert rec.size_info == "16 mm, 18 mm"
    assert rec.material_info == "Silver, Gold"


@pytest.mark.unit
def test_variant_axes_that_are_neither_size_nor_colour_are_kept_separately():
    """Shoes are sold by width, jewellery by stone. E0005 keeps those out of the size
    and colour fields so those stay comparable across brands."""
    rec = map_product(
        _product(
            ["Size", "Width"],
            [
                {"option1": "42", "option2": "D", "price": "120.00", "available": True},
                {"option1": "42", "option2": "EE", "price": "120.00", "available": True},
            ],
        ),
        "kuurth.com",
    )
    assert rec.size_info == "42"
    assert rec.variant_info == "Width: D, EE"


@pytest.mark.unit
def test_a_sale_is_a_relation_between_two_prices_not_something_on_the_page():
    on_sale = map_product(
        _product(
            ["Size"],
            [{"option1": "S", "price": "40.00", "compare_at_price": "80.00", "available": True}],
        ),
        "kuurth.com",
    )
    assert (on_sale.price, on_sale.full_price, on_sale.promotion_type) == (40.0, 80.0, "sale")

    # compare_at_price equal to the price is not a discount
    not_on_sale = map_product(
        _product(
            ["Size"],
            [{"option1": "S", "price": "40.00", "compare_at_price": "40.00", "available": True}],
        ),
        "kuurth.com",
    )
    assert not_on_sale.full_price is None and not_on_sale.promotion_type is None


@pytest.mark.unit
def test_a_barcode_is_labelled_with_the_kind_of_barcode_it_is():
    ean = map_product(
        _product(["Size"], [{"option1": "S", "barcode": "4901234567894", "price": "1"}]),
        "kuurth.com",
    )
    assert (ean.additional_code_1, ean.additional_code_1_type) == ("4901234567894", "EAN")
    upc = map_product(
        _product(["Size"], [{"option1": "S", "barcode": "012345678905", "price": "1"}]),
        "kuurth.com",
    )
    assert upc.additional_code_1_type == "UPC"
    other = map_product(
        _product(["Size"], [{"option1": "S", "barcode": "STAUD-12-9383", "price": "1"}]),
        "kuurth.com",
    )
    assert other.additional_code_1_type == "MPN"


@pytest.mark.unit
def test_a_rate_limit_is_retried_then_reported_as_busy_not_blocked():
    """429 says the store is fine and wants us to slow down — it is not evidence about
    the brand, so it must not be allowed to rewrite the brand's plan."""
    from backend.archive.connectors.base import ChannelBusy

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)  # the store asks us to slow down
        if calls["n"] == 2:
            page = json.loads((FIX / "shopify_products_page1.json").read_text())
            return httpx.Response(200, json=page)
        return httpx.Response(200, json={"products": []})  # end of the feed

    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    refs = ShopifyConnector(retry_pause=0).discover(BRAND, t)
    assert calls["n"] == 3 and refs  # 429, one patient retry, then the empty page

    always_busy = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    )
    with pytest.raises(ChannelBusy):
        ShopifyConnector(retry_pause=0).discover(BRAND, always_busy)
