"""The per-field timeline on the object-store catalogue.

A run that sees the same value extends the open period; a different value closes it
and opens the next; nothing is stored per run except a boundary.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage
from backend.archive.store import periods
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import Conflict, _etag

COV = Coverage(extracted=1, coverage_pct=1.0, verdict="ok")
URL = "https://kuurth.com/products/nemo"


class MemoryObjectStore:
    """The ObjectStore protocol over a dict."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def get(self, key):
        body = self.objects.get(key)
        return None if body is None else (body, _etag(body))

    def put(self, key, body, *, if_match=None, if_none_match=False):
        held = self.objects.get(key)
        if if_none_match and held is not None:
            raise Conflict(key)
        if if_match is not None and (held is None or _etag(held) != if_match):
            raise Conflict(key)
        self.objects[key] = body
        return _etag(body)

    def list(self, prefix):
        return sorted(k for k in self.objects if k.startswith(prefix))

    def delete(self, key):
        self.objects.pop(key, None)


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
    }
    return ProductRecord(**{**fields, **extra})


@pytest.fixture()
def cat():
    return Catalog(MemoryObjectStore())


def _run(cat: Catalog, hour: int, *records: ProductRecord, seen: Sequence[str] = ()) -> str:
    """One run at `hour` o'clock, written straight into the run index with its own
    id so the period stamps are predictable."""
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
    cat.finalize_run(run_id, 0, COV, domain="kuurth.com")
    return run_id


def price_periods(cat: Catalog) -> list[tuple]:
    held = cat.product_history("kuurth.com", URL)[URL]["periods"]["price"]
    return [(p["value"], p["from"], p["to"]) for p in held]


@pytest.mark.unit
def test_the_hoodie_180_126_126_180_yields_three_periods(cat):
    for hour, price in enumerate((180, 126, 126, 180)):
        _run(cat, hour, rec(price=price))
    assert price_periods(cat) == [
        (180.0, _at(0), _at(1)),
        (126.0, _at(1), _at(3)),
        (180.0, _at(3), _at(3)),
    ]
    # the other fields never moved: one period each, reaching the last run
    h = cat.product_history("kuurth.com", URL)[URL]["periods"]
    assert h["product_title"] == [{"value": "Nemo Hoodie", "from": _at(0), "to": _at(3)}]
    assert h["in_stock"] == [{"value": True, "from": _at(0), "to": _at(3)}]
    assert set(h) == {
        "price",
        "in_stock",
        "size_info",
        "product_title",
        "currency",
        "description_sha1",
    }  # blanks (full_price, colour...) open nothing


@pytest.mark.unit
def test_a_reserialised_equal_value_never_opens_a_period(cat):
    _run(cat, 0, rec(price=126.0, size_info="S, M, L", description="A hoodie."))
    _run(cat, 1, rec(price=126.004, size_info=" S, M, L ", description="A hoodie. "))
    _run(cat, 2, rec(price=126, in_stock="true"))
    h = cat.product_history("kuurth.com", URL)[URL]["periods"]
    assert all(len(held) == 1 for held in h.values()), h
    assert h["price"][0]["to"] == _at(2)
    assert periods.normalise("price", "1,299") is None  # unreadable is blank
    assert periods.normalise("in_stock", "1") is True
    assert periods.normalise("description_sha1", " x ") == periods.normalise(
        "description_sha1", "x"
    )


@pytest.mark.unit
def test_mark_seen_extends_every_open_period(cat):
    _run(cat, 0, rec(price=180))
    _run(cat, 5, seen=[URL])
    assert price_periods(cat) == [(180.0, _at(0), _at(5))]
    assert cat.product_history("kuurth.com", URL)[URL]["periods"]["currency"][0]["to"] == _at(5)


@pytest.mark.unit
def test_at_most_fifty_periods_the_oldest_pruned(cat):
    for hour in range(60):
        _run(cat, hour, rec(price=100 + hour))
    held = price_periods(cat)
    assert len(held) == periods.MAX_PERIODS
    assert held[0][0] == 110.0 and held[-1][0] == 159.0


@pytest.mark.unit
def test_changes_are_period_boundaries_newest_first(cat):
    _run(cat, 0, rec(price=180))
    _run(cat, 1, rec(price=126))
    _run(cat, 2, rec(price=126))  # nothing moved: no row
    _run(cat, 3, rec(price=126, in_stock=False, color_info="Black"))
    changes = cat.catalogue_changes("kuurth.com")
    assert [c["run_id"] for c in changes] == [_run_id(3), _run_id(1), _run_id(0)]
    assert (
        changes[0]["changed"] == 2
        and changes[0]["changed_names"]
        == [
            "Nemo Hoodie: in_stock True → False",
        ]
        or changes[0]["changed_names"] == ["Nemo Hoodie: in_stock True → False"]
    )
    # colour went from nothing to Black: a first period, not a change
    assert changes[0]["changed"] == 1
    assert changes[1] == {
        "run_id": _run_id(1),
        "at": _run_id(1).rsplit("-", 1)[0],
        "added": 0,
        "removed": 0,
        "added_names": [],
        "removed_names": [],
        "changed": 1,
        "changed_names": ["Nemo Hoodie: price 180 → 126"],
    }
    assert changes[2]["added"] == 1 and changes[2]["changed"] == 0
    assert cat.catalogue_changes("kuurth.com", limit=1) == changes[:1]


@pytest.mark.unit
def test_migration_replays_observations_and_is_idempotent(cat):
    # A catalogue written before periods existed: products and history objects only.
    for hour, price in enumerate((180, 126, 126, 180)):
        _run(cat, hour, rec(price=price))
    body = json.loads(cat._store.get("catalogue/kuurth.com.json")[0])
    body["products"][URL].pop("periods")
    cat._store.put("catalogue/kuurth.com.json", json.dumps(body).encode())
    cat._open.clear()
    assert cat.product_history("kuurth.com", URL)[URL]["periods"] == {}

    first = cat.migrate_periods("kuurth.com")
    assert first == {"domain": "kuurth.com", "observations": 3, "periods": 4}
    # observations carry the four watched fields; the open period reaches the
    # product's last sighting even though the last observation was earlier
    assert price_periods(cat) == [
        (180.0, _at(0), _at(1)),
        (126.0, _at(1), _at(3)),
        (180.0, _at(3), _at(3)),
    ]
    again = cat.migrate_periods("kuurth.com")
    assert again == first
    assert price_periods(cat)[-1] == (180.0, _at(3), _at(3))


@pytest.mark.unit
def test_the_object_stores_pairs_and_readers_get_dicts(cat):
    _run(cat, 0, rec(price=180))
    body = json.loads(cat._store.get("catalogue/kuurth.com.json")[0])
    # [value, from] in epoch seconds; `to` is the next period's start, or last_seen_run
    assert body["products"][URL]["periods"]["price"] == [[180.0, periods.epoch(_run_id(0))]]
    assert cat.product_history("kuurth.com")[URL]["periods"]["price"] == [
        {"value": 180.0, "from": _at(0), "to": _at(0)}
    ]
    assert cat.product_history("kuurth.com", "https://kuurth.com/products/none") == {}
