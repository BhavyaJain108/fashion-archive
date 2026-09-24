"""The bag endpoints, with the rows in memory and the catalogue faked.

What is pinned here is the route logic: what an add needs, how a size becomes a
variant id, what "changed" and "unavailable" mean, how lines group by shop and
what /checkout hands back. The SQL is pinned against a real Postgres in
tests/db/test_bag_routes.py; here `bag` is replaced by a dict so these run on a
machine with no database.
"""

from __future__ import annotations

from contextlib import contextmanager
from itertools import count
from types import SimpleNamespace
from uuid import UUID

import pytest
from flask import Flask

from backend.api import bag_routes as routes

pytestmark = pytest.mark.unit

USER = SimpleNamespace(id=UUID("11111111-1111-1111-1111-111111111111"))

HOODIE = {
    "brand_id": "kuurth.com",
    "url": "https://kuurth.com/products/nemo-hoodie",
    "title": "Nemo Hoodie",
    "image": "https://cdn/nemo.jpg",
    "handle": "nemo-hoodie",
    "platform": "shopify",
    "price": 126.0,
    "currency": "USD",
    "in_stock": True,
    "sizes": [
        {"size": "M", "available": True, "variant_id": "41"},
        {"size": "L", "available": False, "variant_id": "42"},
    ],
    "offers": [
        {"size": "M", "variant_id": "41", "available": True, "price": 126.0},
        {"size": "L", "variant_id": "42", "available": False, "price": 126.0},
    ],
}
TOTE = {
    "brand_id": "kuurth.com",
    "url": "https://kuurth.com/products/tote",
    "title": "Tote",
    "image": None,
    "handle": "tote",
    "platform": "shopify",
    "price": 80.0,
    "currency": "USD",
    "in_stock": True,
    "sizes": [],
    "offers": [{"size": None, "variant_id": "9", "available": True, "price": 80.0}],
}
JACKET = {
    "brand_id": "wiacollections.com",
    "url": "https://wiacollections.com/product/wia-jacket/",
    "title": "Wia Jacket",
    "image": "https://cdn/jacket.jpg",
    "handle": "wia-jacket",
    "platform": "woo",
    "price": 199.0,
    "currency": "EUR",
    "in_stock": True,
    "sizes": [{"size": "S", "available": True, "variant_id": "201"}],
    "offers": [{"size": "S", "variant_id": "201", "available": True, "price": 199.0}],
}
PAGE_ONLY = {  # read from a page, no feed: no offers, no platform
    "brand_id": "page.com",
    "url": "https://page.com/p/coat",
    "title": "Coat",
    "image": "https://cdn/coat.jpg",
    "handle": "coat",
    "platform": None,
    "price": 300.0,
    "currency": "GBP",
    "in_stock": True,
    "sizes": [{"size": "S", "available": True}],
    "offers": [],
}


class MemoryBag:
    """`backend.userdata.bag` over a dict, with the same semantics."""

    MAX_LINES = 50
    MAX_QTY = 20

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.ids = count(1)

    def list_lines(self, conn, *, user_id):
        return [dict(r) for r in self.rows.values() if r["user_id"] == user_id]

    def count(self, conn, *, user_id):
        return len(self.list_lines(conn, user_id=user_id))

    def add_line(self, conn, *, user_id, **f):
        key = (user_id, f["itemurl"], f["variant_id"] or "", f["size"] or "")
        for r in self.rows.values():
            if (r["user_id"], r["itemurl"], r["variant_id"] or "", r["size"] or "") == key:
                r["qty"] = min(r["qty"] + f["qty"], self.MAX_QTY)
                return dict(r)
        row = {"id": next(self.ids), "user_id": user_id, **f}
        self.rows[row["id"]] = row
        return dict(row)

    def set_qty(self, conn, *, user_id, line_id, qty):
        r = self.rows.get(line_id)
        if not r or r["user_id"] != user_id:
            return None
        r["qty"] = qty
        return dict(r)

    def remove_line(self, conn, *, user_id, line_id):
        r = self.rows.get(line_id)
        if not r or r["user_id"] != user_id:
            return False
        del self.rows[line_id]
        return True

    def clear(self, conn, *, user_id):
        gone = [k for k, r in self.rows.items() if r["user_id"] == user_id]
        for k in gone:
            del self.rows[k]
        return len(gone)


@pytest.fixture()
def world(monkeypatch):
    tiles = {(t["brand_id"], t["url"]): dict(t) for t in (HOODIE, TOTE, JACKET, PAGE_ONLY)}
    names = {"kuurth.com": "Kuurth", "wiacollections.com": "Wia", "page.com": "Page"}
    state = SimpleNamespace(tiles=tiles, warming=False, bag=MemoryBag())

    def tile_for(brand, url):
        if state.warming:
            raise routes.Warming()
        return state.tiles.get((brand, url))

    @contextmanager
    def transaction():
        yield None

    monkeypatch.setattr(routes, "_tile_for", tile_for)
    monkeypatch.setattr(routes, "_brand_name", lambda b: names.get(b, b))
    monkeypatch.setattr(routes.db, "transaction", transaction)
    monkeypatch.setattr(routes, "current_user", lambda: USER)
    monkeypatch.setattr(routes, "bag", state.bag)
    monkeypatch.delenv("CHECKOUT_PROVIDER", raising=False)
    return state


@pytest.fixture()
def client(world):
    app = Flask(__name__)
    routes.register_bag_routes(app)
    return app.test_client()


def add(client, brand, url, **extra):
    return client.post("/api/bag/lines", json={"brand": brand, "itemurl": url, **extra})


def lines(body):
    return [ln for s in body["shops"] for ln in s["lines"]]


def test_an_empty_bag(client):
    r = client.get("/api/bag")
    assert r.status_code == 200
    body = r.get_json()
    assert body["shops"] == [] and body["line_count"] == 0 and body["checked"] is True


def test_adding_a_size_resolves_the_variant_and_prices_the_line(client):
    r = add(client, "kuurth.com", HOODIE["url"], size="M", qty=2)
    assert r.status_code == 201
    [ln] = lines(r.get_json())
    assert ln["variant_id"] == "41" and ln["size"] == "M" and ln["qty"] == 2
    assert ln["price"] == 126.0 and ln["currency"] == "USD" and ln["platform"] == "shopify"
    assert ln["title"] == "Nemo Hoodie" and ln["brand_name"] == "Kuurth"
    assert ln["checked"] and not ln["changed"] and not ln["unavailable"]


def test_adding_a_variant_id_fills_in_its_size(client):
    r = add(client, "kuurth.com", HOODIE["url"], variant_id="42")
    [ln] = lines(r.get_json())
    assert ln["size"] == "L" and ln["unavailable"] is True  # L is out of stock now


def test_a_one_variant_product_needs_no_choice(client):
    r = add(client, "kuurth.com", TOTE["url"])
    [ln] = lines(r.get_json())
    assert ln["variant_id"] == "9" and ln["size"] is None


def test_what_an_add_refuses(client, world):
    assert add(client, "", "").status_code == 400
    assert add(client, "kuurth.com", "https://kuurth.com/products/nope").status_code == 404
    r = add(client, "kuurth.com", HOODIE["url"], variant_id="999")
    assert r.status_code == 400 and r.get_json()["code"] == "UNKNOWN_VARIANT"
    r = add(client, "kuurth.com", HOODIE["url"], size="XXL")
    assert r.status_code == 400 and r.get_json()["code"] == "UNKNOWN_SIZE"
    assert add(client, "kuurth.com", HOODIE["url"], size="M", qty=0).status_code == 400
    assert add(client, "kuurth.com", HOODIE["url"], size="M", qty="two").status_code == 400
    assert add(client, "kuurth.com", HOODIE["url"], size="M", qty=21).status_code == 400
    world.warming = True
    r = add(client, "kuurth.com", HOODIE["url"], size="M")
    assert r.status_code == 503 and r.get_json()["code"] == "WARMING"


def test_the_same_variant_twice_is_one_line_with_more_in_it(client):
    add(client, "kuurth.com", HOODIE["url"], size="M")
    body = add(client, "kuurth.com", HOODIE["url"], size="M", qty=2).get_json()
    assert [ln["qty"] for ln in lines(body)] == [3]
    # A different size of the same product is a second line.
    body = add(client, "kuurth.com", HOODIE["url"], size="L").get_json()
    assert body["line_count"] == 2 and body["item_count"] == 4


def test_a_bag_is_grouped_by_shop_with_a_quote_each(client):
    add(client, "kuurth.com", HOODIE["url"], size="M", qty=2)
    add(client, "wiacollections.com", JACKET["url"], size="S")
    add(client, "kuurth.com", TOTE["url"])
    body = client.get("/api/bag").get_json()
    assert [s["brand"] for s in body["shops"]] == ["kuurth.com", "wiacollections.com"]
    kuurth, wia = body["shops"]
    assert kuurth["platform"] == "shopify" and kuurth["currency"] == "USD"
    assert kuurth["quote"]["subtotal"] == 332.0 and kuurth["quote"]["lines_priced"] == 2
    assert wia["currency"] == "EUR" and wia["quote"]["subtotal"] == 199.0
    assert [ln["title"] for ln in kuurth["lines"]] == ["Nemo Hoodie", "Tote"]


def test_a_price_change_and_a_stockout_are_reported_not_hidden(client, world):
    add(client, "kuurth.com", HOODIE["url"], size="M")
    tile = world.tiles[("kuurth.com", HOODIE["url"])]
    tile["offers"] = [{"size": "M", "variant_id": "41", "available": False, "price": 99.0}]
    [ln] = lines(client.get("/api/bag").get_json())
    assert ln["price"] == 126.0 and ln["current_price"] == 99.0
    assert ln["changed"] is True and ln["unavailable"] is True
    # The variant leaves the feed altogether.
    tile["offers"] = []
    [ln] = lines(client.get("/api/bag").get_json())
    assert ln["unavailable"] is True and ln["current_price"] is None


def test_a_product_the_site_stopped_showing_is_unchecked(client, world):
    add(client, "kuurth.com", HOODIE["url"], size="M")
    del world.tiles[("kuurth.com", HOODIE["url"])]
    body = client.get("/api/bag").get_json()
    [ln] = lines(body)
    assert ln["checked"] is False and ln["available"] is None
    assert body["checked"] is True  # the index was there; this product was not
    # The stored price still makes the quote, so the total is not silently 0.
    assert body["shops"][0]["quote"]["subtotal"] == 126.0


def test_while_the_index_warms_the_bag_is_served_unchecked(client, world):
    add(client, "kuurth.com", HOODIE["url"], size="M")
    world.warming = True
    body = client.get("/api/bag").get_json()
    assert body["checked"] is False and lines(body)[0]["checked"] is False


def test_quantity_remove_and_clear(client):
    add(client, "kuurth.com", HOODIE["url"], size="M")
    [ln] = lines(client.get("/api/bag").get_json())
    r = client.patch(f"/api/bag/lines/{ln['id']}", json={"qty": 4})
    assert r.status_code == 200 and lines(r.get_json())[0]["qty"] == 4
    assert client.patch(f"/api/bag/lines/{ln['id']}", json={"qty": 0}).status_code == 400
    assert client.patch(f"/api/bag/lines/{ln['id']}", json={}).status_code == 400
    assert client.patch("/api/bag/lines/999", json={"qty": 1}).status_code == 404
    assert client.delete("/api/bag/lines/999").status_code == 404
    r = client.delete(f"/api/bag/lines/{ln['id']}")
    assert r.status_code == 200 and r.get_json()["line_count"] == 0
    add(client, "kuurth.com", HOODIE["url"], size="M")
    add(client, "kuurth.com", TOTE["url"])
    assert client.delete("/api/bag").get_json()["line_count"] == 0


def test_another_users_line_is_not_reachable(client, world, monkeypatch):
    add(client, "kuurth.com", HOODIE["url"], size="M")
    [ln] = lines(client.get("/api/bag").get_json())
    other = SimpleNamespace(id=UUID("22222222-2222-2222-2222-222222222222"))
    monkeypatch.setattr(routes, "current_user", lambda: other)
    assert client.get("/api/bag").get_json()["line_count"] == 0
    assert client.patch(f"/api/bag/lines/{ln['id']}", json={"qty": 2}).status_code == 404
    assert client.delete(f"/api/bag/lines/{ln['id']}").status_code == 404


def test_checkout_hands_back_one_link_per_shop_and_the_totals(client):
    assert client.get("/api/bag/checkout").status_code == 400  # empty
    add(client, "kuurth.com", HOODIE["url"], size="M", qty=2)
    add(client, "kuurth.com", TOTE["url"])
    add(client, "wiacollections.com", JACKET["url"], size="S")
    add(client, "page.com", PAGE_ONLY["url"], size="S")
    r = client.get("/api/bag/checkout")
    assert r.status_code == 200
    body = r.get_json()
    assert body["provider"] == "cart_links" and body["checked"] is True
    by_brand = {s["brand"]: s for s in body["shops"]}
    kuurth = by_brand["kuurth.com"]
    assert kuurth["kind"] == "cart_links"
    assert [k["url"] for k in kuurth["links"]] == ["https://kuurth.com/cart/41:2,9:1"]
    assert kuurth["quote"]["subtotal"] == 332.0 and kuurth["currency"] == "USD"
    wia = by_brand["wiacollections.com"]
    assert [k["url"] for k in wia["links"]] == [
        "https://wiacollections.com/?add-to-cart=201&quantity=1"
    ]
    page = by_brand["page.com"]
    assert [(k["url"], k["kind"]) for k in page["links"]] == [(PAGE_ONLY["url"], "product")]
    assert page["note"] and "no cart link" in page["note"]


def test_checkout_names_the_lines_that_cannot_be_bought(client, world):
    add(client, "kuurth.com", HOODIE["url"], size="L")  # out of stock
    add(client, "kuurth.com", HOODIE["url"], size="M")
    [shop] = client.get("/api/bag/checkout").get_json()["shops"]
    [l_line] = [ln for ln in lines(client.get("/api/bag").get_json()) if ln["size"] == "L"]
    assert shop["unavailable_line_ids"] == [l_line["id"]]
    assert shop["quote"]["lines_unavailable"] == 1


def test_the_buyer_of_record_provider_answers_with_a_session_stub(client, monkeypatch):
    monkeypatch.setenv("CHECKOUT_PROVIDER", "buyer_of_record")
    add(client, "kuurth.com", HOODIE["url"], size="M")
    body = client.get("/api/bag/checkout").get_json()
    assert body["provider"] == "buyer_of_record"
    assert body["shops"][0]["kind"] == "provider_session" and body["shops"][0]["links"] == []
