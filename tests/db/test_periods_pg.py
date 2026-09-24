"""The per-field timeline on Postgres agrees with the object-store one.

Same assertions as tests/unit/archive/test_periods.py, against product_periods.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from backend.archive.domain.product import ProductRecord
from backend.archive.store import periods
from backend.archive.store.objects import DirectoryObjectStore
from backend.archive.store.pg_catalog import PgCatalog
from tests.db.test_pg_catalog import URL as DB_URL  # noqa: F401 — the fixture's address
from tests.db.test_pg_catalog import _coverage, clean, pool  # noqa: F401

psycopg = pytest.importorskip("psycopg")

URL = "https://kuurth.com/products/nemo"


def _run_id(hour: int) -> str:
    return f"2026-09-{10 + hour // 24:02d}T{hour % 24:02d}:00:00.123456+00:00-abc{hour:03d}"


def _at(hour: int) -> str:
    return f"2026-09-{10 + hour // 24:02d}T{hour % 24:02d}:00:00Z"


def rec(price=126.0, **extra) -> ProductRecord:
    fields = {
        "itemurl": URL,
        "product_title": "Nemo Hoodie",
        "price": price,
        "currency": "USD",
        "in_stock": True,
        "size_info": "S, M, L",
        "description": "A hoodie.",
        "raw": {"src": "test"},
    }
    return ProductRecord(**{**fields, **extra})


def _run(cat: PgCatalog, hour: int, *records: ProductRecord, seen: Sequence[str] = ()) -> str:
    run_id = _run_id(hour)
    cat._write(
        f"runs/kuurth.com/{run_id}.json",
        {"id": run_id, "domain": "kuurth.com", "mode": "full", "started_at": run_id},
    )
    index = cat._read("runs/kuurth.com/index.json", {"runs": []})
    index["runs"].append(run_id)
    cat._write("runs/kuurth.com/index.json", index)
    for r in records:
        cat.record_product("kuurth.com", run_id, r, None)
    if seen:
        cat.mark_seen("kuurth.com", run_id, list(seen))
    cat.finalize_run(run_id, 0, _coverage(), domain="kuurth.com")
    return run_id


def price_periods(cat: PgCatalog) -> list[tuple]:
    held = cat.product_history("kuurth.com", URL)[URL]["periods"]["price"]
    return [(p["value"], p["from"], p["to"]) for p in held]


@pytest.fixture
def cat(tmp_path, pool, clean):  # noqa: F811
    c = PgCatalog(DirectoryObjectStore(tmp_path), pool=pool)
    yield c
    c.close()


def test_the_hoodie_180_126_126_180_yields_three_periods(cat):
    for hour, price in enumerate((180, 126, 126, 180)):
        _run(cat, hour, rec(price=price))
    assert price_periods(cat) == [
        (180.0, _at(0), _at(1)),
        (126.0, _at(1), _at(3)),
        (180.0, _at(3), _at(3)),
    ]
    h = cat.product_history("kuurth.com", URL)[URL]["periods"]
    assert h["product_title"] == [{"value": "Nemo Hoodie", "from": _at(0), "to": _at(3)}]
    assert h["in_stock"] == [{"value": True, "from": _at(0), "to": _at(3)}]
    assert "full_price" not in h  # a blank opens nothing
    with cat._pg() as conn:
        n = conn.execute("SELECT count(*) FROM product_periods").fetchone()[0]
    assert n == 3 + 5  # three price periods, one each for the five other filled fields


def test_a_reserialised_equal_value_never_opens_a_period(cat):
    _run(cat, 0, rec(price=126.0))
    _run(cat, 1, rec(price=126.004, size_info=" S, M, L ", description="A hoodie. "))
    h = cat.product_history("kuurth.com", URL)[URL]["periods"]
    assert all(len(held) == 1 for held in h.values()), h
    assert h["price"][0]["to"] == _at(1)


def test_mark_seen_extends_every_open_period_in_the_row_write(cat):
    _run(cat, 0, rec(price=180))
    _run(cat, 5, seen=[URL])
    assert price_periods(cat) == [(180.0, _at(0), _at(5))]
    assert cat.product_history("kuurth.com", URL)[URL]["last_seen"].startswith("2026-09-10T05")


def test_at_most_fifty_periods_the_oldest_pruned(cat):
    for hour in range(60):
        _run(cat, hour, rec(price=100 + hour))
    held = price_periods(cat)
    assert len(held) == periods.MAX_PERIODS
    assert held[0][0] == 110.0 and held[-1][0] == 159.0


def test_changes_are_period_boundaries_newest_first(cat):
    _run(cat, 0, rec(price=180))
    _run(cat, 1, rec(price=126))
    _run(cat, 2, rec(price=126))
    _run(cat, 3, rec(price=126, in_stock=False, color_info="Black"))
    changes = cat.catalogue_changes("kuurth.com")
    assert [c["run_id"] for c in changes] == [_run_id(3), _run_id(1), _run_id(0)]
    assert changes[0]["changed"] == 1
    assert changes[0]["changed_names"] == ["Nemo Hoodie: in_stock True → False"]
    assert changes[1]["changed_names"] == ["Nemo Hoodie: price 180 → 126"]
    assert changes[2]["added"] == 1 and changes[2]["changed"] == 0
    assert cat.catalogue_changes("kuurth.com", limit=1) == changes[:1]


def test_migration_replays_observations_and_is_idempotent(cat):
    for hour, price in enumerate((180, 126, 126, 180)):
        _run(cat, hour, rec(price=price))
    with cat._pg() as conn:
        conn.execute("DELETE FROM product_periods")
    assert cat.product_history("kuurth.com", URL)[URL]["periods"] == {}
    first = cat.migrate_periods("kuurth.com")
    assert first == {"domain": "kuurth.com", "observations": 3, "periods": 4}
    assert price_periods(cat) == [
        (180.0, _at(0), _at(1)),
        (126.0, _at(1), _at(3)),
        (180.0, _at(3), _at(3)),
    ]
    assert cat.migrate_periods("kuurth.com") == first
    assert price_periods(cat)[-1] == (180.0, _at(3), _at(3))
