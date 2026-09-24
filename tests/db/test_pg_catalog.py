"""The Postgres catalogue behaves like the object-store one, end to end.

record → finalize → current_products / history / search / images, then a
backfill from an object store into the same tables, reconciled.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.archive.domain.product import ProductRecord  # noqa: E402
from backend.archive.domain.run import Coverage  # noqa: E402
from backend.archive.store import backfill as bf  # noqa: E402
from backend.archive.store.catalog import Catalog  # noqa: E402
from backend.archive.store.objects import DirectoryObjectStore  # noqa: E402
from backend.archive.store.pg_catalog import PgCatalog  # noqa: E402

psycopg = pytest.importorskip("psycopg")
from psycopg_pool import ConnectionPool  # noqa: E402

DEFAULT_URL = "postgresql://postgres@127.0.0.1:55432/fashion_archive_test"
URL = os.getenv("TEST_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="module")
def pool():
    try:
        p = ConnectionPool(URL, min_size=1, max_size=3, open=True)
        p.wait(timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Postgres at {URL}: {exc}")
    from backend.auth.migrate import apply_schema

    with p.connection() as conn:
        apply_schema(conn)
    yield p
    p.close()


@pytest.fixture
def clean(pool):
    with pool.connection() as conn:
        for t in (
            "product_observations",
            "product_images",
            "product_raw",
            "products",
            "catalogue_brands",
        ):
            conn.execute(f"DELETE FROM {t}")
    yield


def _record(url: str, title: str, price: float, **extra) -> ProductRecord:
    return ProductRecord(
        itemurl=url,
        product_title=title,
        price=price,
        currency="USD",
        in_stock=True,
        all_images=json.dumps([f"{url}/1.jpg", f"{url}/2.jpg"]),
        raw={"src": "test"},
        **extra,
    )


def _coverage() -> Coverage:
    return Coverage(extracted=2, coverage_pct=1.0, verdict="ok")


def test_record_finalize_read_and_history(tmp_path, pool, clean):
    store = DirectoryObjectStore(tmp_path)
    cat = PgCatalog(store, pool=pool)
    run1 = cat.open_run("x.com", "full")
    cat.record_product(
        "x.com", run1, _record("https://x.com/products/denim-jacket", "Denim Jacket", 300), None
    )
    cat.record_product(
        "x.com", run1, _record("https://x.com/products/wool-sweater", "Wool Sweater", 200), None
    )
    assert cat.current_products("x.com") == []  # nothing is live until a run earns coverage
    cat.finalize_run(run1, 0, _coverage(), domain="x.com")

    live = cat.current_products("x.com")
    assert sorted(r["product_title"] for r in live) == ["Denim Jacket", "Wool Sweater"]
    assert live[0]["raw"] == {"src": "test"}  # raw travels with the record, from its own table
    assert all("raw" not in r for r in cat.current_products("x.com", with_raw=False))

    # a second run: one product changes price, the other is gone
    run2 = cat.open_run("x.com", "full")
    changed = cat.record_product(
        "x.com", run2, _record("https://x.com/products/denim-jacket", "Denim Jacket", 250), None
    )
    assert changed is True
    cat.finalize_run(run2, 0, _coverage(), domain="x.com")
    live = cat.current_products("x.com")
    assert [r["product_title"] for r in live] == ["Denim Jacket"]
    assert live[0]["price"] == 250
    assert cat.observation_count("x.com") == 3  # two first sightings + one price change

    history = cat.product_history("x.com")
    assert history["https://x.com/products/wool-sweater"]["live"] is False
    assert history["https://x.com/products/denim-jacket"]["live"] is True
    changes = cat.catalogue_changes("x.com")
    assert changes[0]["removed"] == 1 and changes[-1]["added"] == 2

    # search, over live rows only
    assert [
        t for _, r in cat.search_products(["x.com"], "denim") for t in [r["product_title"]]
    ] == ["Denim Jacket"]
    assert cat.search_products(["x.com"], "sweater") == []
    assert cat.live_product_counts() == {"x.com": 1}
    cat.close()


def test_images_and_the_queue(tmp_path, pool, clean):
    store = DirectoryObjectStore(tmp_path)
    cat = PgCatalog(store, pool=pool)
    run = cat.open_run("x.com", "full")
    url = "https://x.com/products/denim-jacket"
    cat.record_product("x.com", run, _record(url, "Denim Jacket", 300), None)
    cat.finalize_run(run, 0, _coverage(), domain="x.com")
    assert cat.images_awaiting_archive("x.com") == [(url, [f"{url}/1.jpg", f"{url}/2.jpg"])]
    cat.record_image("x.com", url, f"{url}/1.jpg", "abc", stored_url="https://r2/1.jpg")
    cat.record_image_miss("x.com", url, f"{url}/2.jpg")
    cat.record_image_miss("x.com", url, f"{url}/2.jpg")
    cat.record_image_miss("x.com", url, f"{url}/2.jpg")
    cat._open_images.clear()  # read back from the table, not the cache
    assert cat.images_awaiting_archive("x.com") == []  # one stored, one given up on
    assert cat.archived_images("x.com") == {url: ["https://r2/1.jpg"]}
    assert cat.stored_image_count("x.com") == 1
    cat.close()


def test_backfill_from_object_store_reconciles(tmp_path, pool, clean):
    store = DirectoryObjectStore(tmp_path)
    r2 = Catalog(store)
    run = r2.open_run("y.com", "full")
    r2.record_product("y.com", run, _record("https://y.com/products/a", "A", 10), None)
    r2.record_product("y.com", run, _record("https://y.com/products/b", "B", 20), None)
    r2.finalize_run(run, 0, _coverage(), domain="y.com")
    r2.record_image(
        "y.com",
        "https://y.com/products/a",
        "https://y.com/products/a/1.jpg",
        "h",
        stored_url="https://r2/a1.jpg",
    )
    r2.close()

    pg = PgCatalog(store, pool=pool)
    results = bf.backfill(store, pg, log=lambda *_: None)
    assert [r["ok"] for r in results] == [True]
    assert (
        results[0]["rows_db"] == 2 and results[0]["live_db"] == 2 and results[0]["images_db"] == 1
    )
    assert sorted(r["product_title"] for r in pg.current_products("y.com")) == ["A", "B"]
    assert pg.archived_images("y.com") == {"https://y.com/products/a": ["https://r2/a1.jpg"]}
    # idempotent
    again = bf.backfill(store, pg, log=lambda *_: None)
    assert again[0]["rows_db"] == 2 and again[0]["observations_db"] == results[0]["observations_db"]
    pg.close()


def test_sql_shop_front_matches_the_index_shape(tmp_path, pool, clean):
    from types import SimpleNamespace

    from backend.archive import storefront_sql

    store = DirectoryObjectStore(tmp_path)
    cat = PgCatalog(store, pool=pool)
    run = cat.open_run("x.com", "full")
    cat.record_product(
        "x.com",
        run,
        _record(
            "https://x.com/products/denim-jacket",
            "Denim Jacket",
            300,
            full_price=400,
            color_info="Indigo",
        ),
        None,
    )
    cat.record_product(
        "x.com", run, _record("https://x.com/products/wool-sweater", "Wool Sweater", 200), None
    )
    cat.record_product(
        "x.com",
        run,
        _record("https://x.com/products/leather-boot", "Leather Boot", 500, color_info="Black"),
        None,
    )
    cat.finalize_run(run, 0, _coverage(), domain="x.com")
    roster = [SimpleNamespace(domain="x.com", name="X")]
    storefront_sql.forget_open_domains()
    domains = storefront_sql.open_domains(cat, roster)
    assert domains == ["x.com"]

    page = storefront_sql.query(pool, roster=roster, domains=domains)
    assert page["total"] == 3
    assert {t["title"] for t in page["products"]} == {
        "Denim Jacket",
        "Wool Sweater",
        "Leather Boot",
    }
    assert all("images" not in t for t in page["products"])  # slim for the grid
    assert page["facets"]["sale"] == 1
    assert {c["group"] for c in page["facets"]["categories"]} == {"Clothing", "Shoes"}
    assert page["facets"]["designers"] == [{"brand_id": "x.com", "name": "X", "count": 3}]
    assert {c["colour"] for c in page["facets"]["colours"]} == {"Blue", "Black"}

    cheap = storefront_sql.query(pool, roster=roster, domains=domains, sort="price-asc")
    assert [t["price"] for t in cheap["products"]] == [200.0, 300.0, 500.0]
    shoes = storefront_sql.query(pool, roster=roster, domains=domains, group="Shoes")
    assert shoes["total"] == 1 and {c["group"] for c in shoes["facets"]["categories"]} == {
        "Clothing",
        "Shoes",
    }
    sale = storefront_sql.query(pool, roster=roster, domains=domains, sale=True)
    assert sale["total"] == 1 and sale["products"][0]["discount"] == 0.25
    found = storefront_sql.query(pool, roster=roster, domains=domains, q="denim")
    assert found["total"] == 1

    one = storefront_sql.product(
        pool, roster=roster, domains=domains, brand="x.com", handle="denim-jacket"
    )
    assert (
        one["tile"]["title"] == "Denim Jacket" and one["tile"]["images"] and len(one["more"]) == 2
    )
    assert (
        storefront_sql.product(pool, roster=roster, domains=domains, brand="x.com", handle="nope")
        is None
    )
    cat.close()


def test_boot_backfill_resumes_the_brands_without_a_finished_row(tmp_path, pool, clean):
    store = DirectoryObjectStore(tmp_path)
    r2 = Catalog(store)
    for d in ("a.com", "b.com"):
        run = r2.open_run(d, "full")
        r2.record_product(d, run, _record(f"https://{d}/products/x", "X", 10), None)
        r2.finalize_run(run, 0, _coverage(), domain=d)
    r2.close()
    pg = PgCatalog(store, pool=pool)
    assert sorted(bf.missing_domains(store, pg)) == ["a.com", "b.com"]
    bf.backfill_brand(store, pg, "a.com", log=lambda *_: None)
    assert bf.missing_domains(store, pg) == [
        "b.com"
    ]  # a.com finished; only b.com is copied on the next boot
    bf.backfill(store, pg, bf.missing_domains(store, pg), log=lambda *_: None)
    assert bf.missing_domains(store, pg) == []
    pg.close()


def test_a_sweep_updates_stock_in_place_and_nothing_else(tmp_path, pool, clean):
    store = DirectoryObjectStore(tmp_path)
    cat = PgCatalog(store, pool=pool)
    url = "https://x.com/products/denim-jacket"
    other = "https://x.com/products/wool-sweater"
    run = cat.open_run("x.com", "full")
    cat.record_product(
        "x.com",
        run,
        _record(
            url,
            "Denim Jacket",
            300,
            size_info="S, M",
            size_availability="in_stock, in_stock",
            offers=[
                {"size": "S", "variant_id": "1", "available": True, "price": 300.0},
                {"size": "M", "variant_id": "2", "available": True, "price": 300.0},
            ],
        ),
        "h1",
    )
    cat.record_product("x.com", run, _record(other, "Wool Sweater", 200), "h2")
    cat.finalize_run(run, 0, _coverage(), domain="x.com")
    before = {r["itemurl"]: r for r in cat.current_products("x.com")}

    sweep = cat.open_run("x.com", "sweep")
    n = cat.update_stock(
        "x.com",
        sweep,
        [
            {
                "itemurl": url,
                "size_info": "S, M",
                "in_stock": True,
                "size_availability": "in_stock, out_of_stock",
                "size_stock_counts": "4, 0",
                "price": 250.0,
                "full_price": 300.0,
                "promotion_type": "sale",
                "currency": "USD",
                "offers": [{"variant_id": "2", "available": False, "price": 250.0}],
            },
            {"itemurl": other, "price": 200.0, "in_stock": True},  # unchanged
            {"itemurl": "https://x.com/products/new", "price": 1.0},  # not held: ignored
        ],
    )
    assert n == 1
    cat.finalize_run(sweep, 0, None, domain="x.com")

    after = {r["itemurl"]: r for r in cat.current_products("x.com")}
    assert set(after) == set(before)
    jacket = after[url]
    assert (jacket["price"], jacket["full_price"], jacket["promotion_type"]) == (
        250.0,
        300.0,
        "sale",
    )
    assert jacket["size_availability"] == "in_stock, out_of_stock"
    assert jacket["offers"][1]["available"] is False and jacket["offers"][0]["available"] is True
    assert jacket["product_title"] == "Denim Jacket"
    assert jacket["all_images"] == before[url]["all_images"]
    assert jacket["raw"] == {"src": "test"}
    assert after[other] == before[other]
    # The typed columns moved with the record; the stamps and the hint did not.
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT price, full_price, in_stock, size_availability, size_stock_counts, "
            "change_hint, last_seen_run, last_covered_run FROM products WHERE itemurl = %s",
            (url,),
        ).fetchone()
    assert row == (250.0, 300.0, True, "in_stock, out_of_stock", "4, 0", "h1", run, run)
    assert cat._latest_covered_run("x.com") == run
    assert cat.observation_count("x.com") == 3  # two first sightings + the sweep's price move
    with pool.connection() as conn:
        obs = conn.execute(
            "SELECT price, in_stock FROM product_observations WHERE run_id = %s", (sweep,)
        ).fetchall()
    assert obs == [(250.0, True)]
    cat.close()
