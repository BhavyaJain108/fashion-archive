"""The bag over a real Postgres.

The unit suite (tests/unit/api/test_bag_routes.py) pins what the handlers do
with rows; this pins what Postgres does with the SQL — in particular the
ON CONFLICT over an index built on COALESCE(variant_id, ''), which a fake
connection cannot tell is wrong, and the per-user scoping of every statement.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("flask", reason="flask not installed")

from auth import repository as repo  # noqa: E402
from flask import Flask  # noqa: E402

from backend.api import bag_routes as routes  # noqa: E402
from backend.userdata import bag  # noqa: E402

pytestmark = pytest.mark.db

TILE = {
    "brand_id": "kuurth.com",
    "url": "https://kuurth.com/products/nemo-hoodie",
    "title": "Nemo Hoodie",
    "image": None,
    "handle": "nemo-hoodie",
    "platform": "shopify",
    "price": 126.0,
    "currency": "USD",
    "in_stock": True,
    "sizes": [{"size": "M", "available": True, "variant_id": "41"}],
    "offers": [{"size": "M", "variant_id": "41", "available": True, "price": 126.0}],
}


@pytest.fixture
def user(conn):
    return repo.create_user(conn, email="one@example.com", display_name="One")


@pytest.fixture
def client(conn, user, monkeypatch):
    @contextmanager
    def transaction():
        yield conn

    monkeypatch.setattr(routes.db, "transaction", transaction)
    monkeypatch.setattr(routes, "current_user", lambda: user)
    monkeypatch.setattr(routes, "_tile_for", lambda b, u: TILE if u == TILE["url"] else None)
    monkeypatch.setattr(routes, "_brand_name", lambda b: "Kuurth")
    monkeypatch.delenv("CHECKOUT_PROVIDER", raising=False)
    app = Flask(__name__)
    routes.register_bag_routes(app)
    return app.test_client()


def add(client, **extra):
    return client.post(
        "/api/bag/lines", json={"brand": "kuurth.com", "itemurl": TILE["url"], **extra}
    )


def test_add_list_patch_delete_round_trip(client, conn):
    r = add(client, size="M", qty=2)
    assert r.status_code == 201
    [line] = r.get_json()["shops"][0]["lines"]
    assert line["variant_id"] == "41" and line["price"] == 126.0 and line["qty"] == 2
    assert conn.execute("SELECT count(*) FROM bag_lines").fetchone()[0] == 1

    # The same variant again is the same row, with more in it.
    add(client, size="M")
    assert conn.execute("SELECT qty FROM bag_lines").fetchone()[0] == 3

    r = client.patch(f"/api/bag/lines/{line['id']}", json={"qty": 1})
    assert r.get_json()["shops"][0]["lines"][0]["qty"] == 1
    assert client.delete(f"/api/bag/lines/{line['id']}").get_json()["line_count"] == 0
    assert conn.execute("SELECT count(*) FROM bag_lines").fetchone()[0] == 0


def test_a_line_without_a_variant_is_still_one_row(conn, user):
    """COALESCE in the unique index: two NULL variant ids must still collide."""
    kw = dict(
        user_id=user.id,
        brand="page.com",
        itemurl="https://page.com/p/coat",
        variant_id=None,
        size=None,
        qty=1,
        title="Coat",
        image=None,
        handle=None,
        platform=None,
        price=300.0,
        currency="GBP",
    )
    bag.add_line(conn, **kw)
    bag.add_line(conn, **kw)
    rows = bag.list_lines(conn, user_id=user.id)
    assert len(rows) == 1 and rows[0]["qty"] == 2 and rows[0]["price"] == 300.0


def test_quantity_is_capped_at_the_maximum(conn, user):
    kw = dict(
        user_id=user.id,
        brand="kuurth.com",
        itemurl=TILE["url"],
        variant_id="41",
        size="M",
        qty=bag.MAX_QTY,
        title="Nemo Hoodie",
        image=None,
        handle="nemo-hoodie",
        platform="shopify",
        price=126.0,
        currency="USD",
    )
    bag.add_line(conn, **kw)
    assert bag.add_line(conn, **kw)["qty"] == bag.MAX_QTY


def test_lines_are_scoped_to_their_user(conn, user):
    other = repo.create_user(conn, email="two@example.com", display_name="Two")
    mine = bag.add_line(
        conn,
        user_id=user.id,
        brand="kuurth.com",
        itemurl=TILE["url"],
        variant_id="41",
        size="M",
        qty=1,
        title="Nemo Hoodie",
        image=None,
        handle="nemo-hoodie",
        platform="shopify",
        price=126.0,
        currency="USD",
    )
    assert bag.list_lines(conn, user_id=other.id) == []
    assert bag.set_qty(conn, user_id=other.id, line_id=mine["id"], qty=5) is None
    assert bag.remove_line(conn, user_id=other.id, line_id=mine["id"]) is False
    assert bag.clear(conn, user_id=other.id) == 0
    assert bag.count(conn, user_id=user.id) == 1


def test_checkout_over_real_rows(client):
    add(client, size="M", qty=2)
    body = client.get("/api/bag/checkout").get_json()
    [shop] = body["shops"]
    assert shop["links"][0]["url"] == "https://kuurth.com/cart/41:2"
    assert shop["quote"]["subtotal"] == 252.0
