"""The dated notebook.

Whatever works today stops working eventually. A store that only holds the current
answer lets a brand go quietly dark until a customer notices; one that holds dated
sweeps lets us see it coming.
"""

import pytest

from backend.archive.access import store as A
from backend.archive.access.outcome import Outcome
from backend.archive.access.probe import AccessResult
from backend.archive.store.objects import DirectoryObjectStore


@pytest.fixture
def objects(tmp_path):
    return DirectoryObjectStore(tmp_path)


def result(domain, strategy, outcome, **kw) -> AccessResult:
    return AccessResult(domain, strategy, outcome, requests=4, **kw)


@pytest.mark.unit
def test_a_sweep_is_kept_under_the_moment_it_was_taken(objects):
    A.save_sweep(objects, [result("a.com", "httpx", Outcome.OK)], at="2026-09-13T22:00:00Z")
    assert objects.list("access/sweeps/") == ["access/sweeps/2026-09-13T22:00:00Z.json"]


@pytest.mark.unit
def test_a_saved_sweep_reads_back_as_the_results_that_went_in(objects):
    rows = [
        result("staud.clothing", "httpx", Outcome.RATE_429),
        result("staud.clothing", "cffi:chrome124", Outcome.OK, seconds=0.21),
    ]
    A.save_sweep(objects, rows, at="2026-09-13T22:00:00Z")
    back = A.load_sweep(objects, "2026-09-13T22:00:00Z")
    assert [(r.strategy, r.outcome) for r in back] == [
        ("httpx", Outcome.RATE_429),
        ("cffi:chrome124", Outcome.OK),
    ]


@pytest.mark.unit
def test_sweeps_never_overwrite_each_other(objects):
    A.save_sweep(objects, [result("a.com", "httpx", Outcome.OK)], at="2026-09-13T22:00:00Z")
    A.save_sweep(objects, [result("a.com", "httpx", Outcome.WAF_403)], at="2026-10-01T09:00:00Z")
    assert len(objects.list("access/sweeps/")) == 2


@pytest.mark.unit
def test_the_current_answer_records_the_winning_strategy_per_brand(objects):
    A.save_sweep(
        objects,
        [
            result("staud.clothing", "httpx", Outcome.RATE_429),
            result("staud.clothing", "cffi:chrome124", Outcome.OK),
        ],
        at="2026-09-13T22:00:00Z",
    )
    current = A.load_current(objects)
    assert current["staud.clothing"]["strategy"] == "cffi:chrome124"
    assert current["staud.clothing"]["outcome"] == "ok"


@pytest.mark.unit
def test_first_seen_survives_a_later_sweep_that_confirms_the_same_strategy(objects):
    """How long a lane has held is the useful number; last_verified moves, first_seen
    must not."""
    rows = [result("staud.clothing", "cffi:chrome124", Outcome.OK)]
    A.save_sweep(objects, rows, at="2026-09-13T22:00:00Z")
    A.save_sweep(objects, rows, at="2026-10-01T09:00:00Z")
    entry = A.load_current(objects)["staud.clothing"]
    assert entry["first_seen"] == "2026-09-13T22:00:00Z"
    assert entry["last_verified"] == "2026-10-01T09:00:00Z"


@pytest.mark.unit
def test_a_brand_that_moves_to_a_different_strategy_starts_a_new_first_seen(objects):
    A.save_sweep(
        objects, [result("x.com", "cffi:chrome124", Outcome.OK)], at="2026-09-13T22:00:00Z"
    )
    A.save_sweep(objects, [result("x.com", "patchright", Outcome.OK)], at="2026-10-01T09:00:00Z")
    entry = A.load_current(objects)["x.com"]
    assert entry["strategy"] == "patchright"
    assert entry["first_seen"] == "2026-10-01T09:00:00Z"


@pytest.mark.unit
def test_a_brand_that_stops_working_is_marked_lost_not_deleted(objects):
    """Losing a brand is the event worth seeing. Dropping the row would hide it."""
    A.save_sweep(objects, [result("x.com", "httpx", Outcome.OK)], at="2026-09-13T22:00:00Z")
    A.save_sweep(objects, [result("x.com", "httpx", Outcome.WAF_403)], at="2026-10-01T09:00:00Z")
    entry = A.load_current(objects)["x.com"]
    assert entry["strategy"] is None
    assert entry["outcome"] == "waf_403"
    assert entry["lost_at"] == "2026-10-01T09:00:00Z"


@pytest.mark.unit
def test_a_brand_absent_from_a_later_sweep_keeps_the_answer_it_had(objects):
    """Sweeping one domain must not wipe what we know about the other thirty-six."""
    A.save_sweep(objects, [result("a.com", "httpx", Outcome.OK)], at="2026-09-13T22:00:00Z")
    A.save_sweep(objects, [result("b.com", "httpx", Outcome.OK)], at="2026-10-01T09:00:00Z")
    current = A.load_current(objects)
    assert set(current) == {"a.com", "b.com"}
    assert current["a.com"]["strategy"] == "httpx"


@pytest.mark.unit
def test_an_empty_room_is_recorded_with_no_winning_strategy(objects):
    A.save_sweep(
        objects, [result("psylos1.com", "patchright", Outcome.OK_THIN)], at="2026-09-13T22:00:00Z"
    )
    entry = A.load_current(objects)["psylos1.com"]
    assert entry["strategy"] is None and entry["outcome"] == "ok_thin"


@pytest.mark.unit
def test_reading_from_an_empty_store_is_not_an_error(objects):
    assert A.load_current(objects) == {}
    assert A.sweep_dates(objects) == []


@pytest.mark.unit
def test_the_sweeps_taken_can_be_listed_newest_last(objects):
    A.save_sweep(objects, [result("a.com", "httpx", Outcome.OK)], at="2026-10-01T09:00:00Z")
    A.save_sweep(objects, [result("a.com", "httpx", Outcome.OK)], at="2026-09-13T22:00:00Z")
    assert A.sweep_dates(objects) == ["2026-09-13T22:00:00Z", "2026-10-01T09:00:00Z"]


@pytest.mark.unit
def test_the_history_of_one_brand_can_be_read_back_across_sweeps(objects):
    A.save_sweep(objects, [result("x.com", "httpx", Outcome.OK)], at="2026-09-13T22:00:00Z")
    A.save_sweep(objects, [result("x.com", "httpx", Outcome.WAF_403)], at="2026-10-01T09:00:00Z")
    history = A.history(objects, "x.com")
    assert [(at, r.outcome) for at, r in history] == [
        ("2026-09-13T22:00:00Z", Outcome.OK),
        ("2026-10-01T09:00:00Z", Outcome.WAF_403),
    ]
