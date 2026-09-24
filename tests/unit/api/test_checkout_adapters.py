"""The checkout adapters: the URLs each shop's cart takes, and the sums."""

from __future__ import annotations

import pytest

from backend.api import checkout
from backend.api.checkout import Line, ShopBag, buyer_of_record, cart_links

pytestmark = pytest.mark.unit


def line(id, url, variant_id, qty=1, price=100.0, available=True, size="M"):
    return Line(
        id=id,
        brand=url.split("/")[2],
        itemurl=url,
        variant_id=variant_id,
        size=size,
        qty=qty,
        price=price,
        available=available,
    )


def test_a_shopify_shop_is_one_cart_permalink():
    shop = ShopBag(
        "kuurth.com",
        "Kuurth",
        "shopify",
        "USD",
        [
            line(1, "https://kuurth.com/products/nemo", "41", qty=2),
            line(2, "https://kuurth.com/products/ring", "42"),
        ],
    )
    [out] = cart_links.CartLinkAdapter().checkout([shop])
    assert out.kind == "cart_links" and out.note is None
    assert [(k.url, k.kind, k.line_ids) for k in out.links] == [
        ("https://kuurth.com/cart/41:2,42:1", "cart", [1, 2])
    ]


def test_a_woo_shop_is_one_link_per_line_and_says_so():
    shop = ShopBag(
        "wia.com",
        "Wia",
        "woo",
        "EUR",
        [
            line(1, "https://wia.com/product/jacket/", "201", qty=1),
            line(2, "https://wia.com/product/tee/", "12", qty=3),
        ],
    )
    [out] = cart_links.CartLinkAdapter().checkout([shop])
    assert [k.url for k in out.links] == [
        "https://wia.com/?add-to-cart=201&quantity=1",
        "https://wia.com/?add-to-cart=12&quantity=3",
    ]
    assert all(k.kind == "add_to_cart" for k in out.links)
    assert "2 links" in (out.note or "")


def test_no_variant_id_or_no_platform_means_the_product_page():
    shop = ShopBag(
        "kuurth.com",
        "Kuurth",
        "shopify",
        "USD",
        [
            line(1, "https://kuurth.com/products/nemo", "41"),
            line(2, "https://kuurth.com/products/hat", None),
        ],
    )
    [out] = cart_links.CartLinkAdapter().checkout([shop])
    assert [(k.kind, k.line_ids) for k in out.links] == [("cart", [1]), ("product", [2])]
    assert "1 line(s) have no variant id" in (out.note or "")

    other = ShopBag("x.com", "X", None, "GBP", [line(3, "https://x.com/p/a", "9")])
    [out] = cart_links.CartLinkAdapter().checkout([other])
    assert [(k.url, k.kind) for k in out.links] == [("https://x.com/p/a", "product")]
    assert "no cart link" in (out.note or "")


def test_the_cart_lives_where_the_product_url_does():
    shop = ShopBag(
        "brand.com", "B", "shopify", "USD", [line(1, "https://shop.brand.com/products/a", "1")]
    )
    [out] = cart_links.CartLinkAdapter().checkout([shop])
    assert out.links[0].url == "https://shop.brand.com/cart/1:1"


def test_a_quote_sums_what_has_a_price_in_the_shops_currency():
    shop = ShopBag(
        "wia.com",
        "Wia",
        "woo",
        "EUR",
        [
            line(1, "https://wia.com/p/a", "1", qty=2, price=199.0),
            line(2, "https://wia.com/p/b", "2", qty=1, price=None),
            line(3, "https://wia.com/p/c", "3", qty=1, price=45.0, available=False),
        ],
    )
    [q] = cart_links.CartLinkAdapter().quote([shop])
    assert q.as_dict() == {
        "brand": "wia.com",
        "currency": "EUR",
        "subtotal": 443.0,
        "lines_priced": 2,
        "lines_unpriced": 1,
        "lines_unavailable": 1,
        "excludes": ["shipping", "tax", "duties"],
    }


def test_the_buyer_of_record_stub_quotes_but_does_not_check_out():
    shop = ShopBag("x.com", "X", "shopify", "USD", [line(1, "https://x.com/p/a", "1")])
    a = buyer_of_record.BuyerOfRecordAdapter()
    assert a.quote([shop])[0].subtotal == 100.0
    [out] = a.checkout([shop])
    assert out.kind == "provider_session" and out.links == []
    assert "not configured" in (out.note or "")


def test_the_adapter_is_chosen_by_environment(monkeypatch):
    monkeypatch.delenv("CHECKOUT_PROVIDER", raising=False)
    assert checkout.adapter().name == "cart_links"
    monkeypatch.setenv("CHECKOUT_PROVIDER", "buyer_of_record")
    assert checkout.adapter().name == "buyer_of_record"
    with pytest.raises(ValueError):
        checkout.adapter("stripe")
