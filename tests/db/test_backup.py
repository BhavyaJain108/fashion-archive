"""The nightly dump and the per-brand restore against a real Postgres: every column
type in schema.sql has to survive the trip through gzip-compressed JSON and back —
jsonb, text[], timestamptz, tsvector, bigserial."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.archive import backup as bk  # noqa: E402
from backend.archive.domain.product import ProductRecord  # noqa: E402
from backend.archive.domain.run import Coverage  # noqa: E402
from backend.archive.store.objects import DirectoryObjectStore, dumps  # noqa: E402
from backend.archive.store.pg_catalog import PgCatalog  # noqa: E402

psycopg = pytest.importorskip("psycopg")
from psycopg_pool import ConnectionPool  # noqa: E402

DEFAULT_URL = "postgresql://postgres@127.0.0.1:55432/fashion_archive_test"
URL = os.getenv("TEST_DATABASE_URL", DEFAULT_URL)
NOW = datetime(2026, 9, 24, 3, 0, tzinfo=timezone.utc)


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
        all_images=json.dumps([f"{url}/1.jpg"]),
        raw={"src": "test", "note": "café au lait"},
        **extra,
    )


def _seed(cat: PgCatalog, domain: str, n: int) -> None:
    run = cat.open_run(domain, "full")
    for i in range(n):
        cat.record_product(
            domain,
            run,
            _record(
                f"https://{domain}/products/p{i}",
                f"Item {i}",
                10.0 + i,
                category1="MENS",
                category2="SHIRTS",
                material_info="cotton",
            ),
            None,
        )
    cat.finalize_run(run, 0, Coverage(extracted=n, coverage_pct=1.0, verdict="ok"), domain=domain)
    url = f"https://{domain}/products/p0"
    cat.record_image(domain, url, f"{url}/1.jpg", "h", stored_url=f"https://r2/{domain}/1.jpg")


def test_backup_dumps_every_table_and_restore_puts_one_brand_back(tmp_path, pool, clean):
    store = DirectoryObjectStore(tmp_path)
    cat = PgCatalog(store, pool=pool)
    _seed(cat, "x.com", 3)
    _seed(cat, "y.com", 2)
    store.put("fleet.json", dumps({"x.com": {}}))
    store.put("rules/x.com.json", dumps({"book": {}}))

    m = bk.backup(cat, store, NOW)
    assert m["day"] == "2026-09-24"
    assert {t: v["rows"] for t, v in m["tables"].items()} == {
        "catalogue_brands": 2,
        "products": 5,
        "product_raw": 5,
        "product_observations": 5,
        "product_images": 2,
    }
    assert m["r2"]["copied"] == 2 and m["pruned"] == []
    assert bk.manifest(store, "2026-09-24")["rows"] == 19
    rows = list(bk.load_rows(store.get("backups/2026-09-24/pg/products.ndjson.gz")[0]))
    assert rows[0]["categories"] == ["MENS", "SHIRTS"]
    assert isinstance(rows[0]["record"], dict) and "raw" not in rows[0]["record"]
    assert "'cotton'" in rows[0]["search"]  # the tsvector's text form
    raw = list(bk.load_rows(store.get("backups/2026-09-24/pg/product_raw.ndjson.gz")[0]))
    assert raw[0]["raw"]["note"] == "café au lait"

    # damage x.com every way a brand can be damaged; y.com must not be touched
    with pool.connection() as conn:
        conn.execute("DELETE FROM products WHERE brand = 'x.com' AND itemurl LIKE '%%p1'")
        conn.execute("UPDATE products SET price = 1 WHERE brand = 'x.com'")
        conn.execute("DELETE FROM product_images WHERE brand = 'x.com'")
        conn.execute("DELETE FROM product_observations WHERE brand = 'x.com'")
        conn.execute("UPDATE catalogue_brands SET live_run = 'nope' WHERE brand = 'x.com'")
    cat.close()

    cat = PgCatalog(store, pool=pool)
    assert cat.current_products("x.com") == []
    counts = bk.restore(cat, store, "2026-09-24", "x.com")
    assert counts == {
        "catalogue_brands": 1,
        "products": 3,
        "product_raw": 3,
        "product_observations": 3,
        "product_images": 1,
    }
    live = cat.current_products("x.com")
    assert sorted(r["product_title"] for r in live) == ["Item 0", "Item 1", "Item 2"]
    assert sorted(r["price"] for r in live) == [10.0, 11.0, 12.0]
    assert live[0]["raw"]["note"] == "café au lait"
    assert cat.observation_count("x.com") == 3
    assert cat.archived_images("x.com") == {"https://x.com/products/p0": ["https://r2/x.com/1.jpg"]}
    assert [t for _, r in cat.search_products(["x.com"], "cotton") for t in [r["product_title"]]]
    assert cat.live_product_counts() == {"x.com": 3, "y.com": 2}
    # the sequence is past the restored ids: a new observation gets a fresh one
    run = cat.open_run("x.com", "full")
    cat.record_product("x.com", run, _record("https://x.com/products/p9", "Item 9", 99), None)
    cat.finalize_run(run, 0, Coverage(extracted=1, coverage_pct=1.0, verdict="ok"), domain="x.com")
    assert cat.observation_count("x.com") == 4
    cat.close()


def test_restore_of_an_unknown_day_says_so(tmp_path, pool, clean):
    cat = PgCatalog(DirectoryObjectStore(tmp_path), pool=pool)
    with pytest.raises(FileNotFoundError):
        bk.restore(cat, cat.store, "2020-01-01", "x.com")
    cat.close()
