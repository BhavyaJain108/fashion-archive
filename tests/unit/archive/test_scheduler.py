from datetime import datetime, timedelta, timezone

import pytest

from backend.archive.domain.brand import Brand
from backend.archive.scheduler import Scheduler
from backend.archive.store.catalog_objects import Catalog
from backend.archive.store.objects import DirectoryObjectStore

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def cat(tmp_path):
    """The store, not a catalogue. The scheduler reads the control plane directly —
    it never needed the products, and coupling it to the catalogue was an artefact of
    both living in one database file."""
    store = DirectoryObjectStore(tmp_path)
    catalog = Catalog(store)
    for d in ("kuurth.com", "staud.clothing"):
        catalog.upsert_brand(Brand(domain=d, homepage_url=f"https://{d}"))
    return store


@pytest.mark.unit
def test_a_brand_is_added_dropped_and_retimed_by_writing_rows(cat):
    s = Scheduler(cat)
    s.add("kuurth.com", cadence_seconds=600, now=T0)
    assert [r["domain"] for r in s.rows()] == ["kuurth.com"]

    s.set_cadence("kuurth.com", 120)
    assert s.rows()[0]["cadence_seconds"] == 120

    s.set_enabled("kuurth.com", False)
    assert s.claim_next(T0) is None  # disabled brands are never handed out

    s.set_enabled("kuurth.com", True)
    assert s.claim_next(T0).domain == "kuurth.com"


@pytest.mark.unit
def test_two_workers_never_take_the_same_brand(cat):
    a, b = Scheduler(cat, "worker-a"), Scheduler(cat, "worker-b")
    a.add("kuurth.com", now=T0)
    a.add("staud.clothing", now=T0)
    first, second = a.claim_next(T0), b.claim_next(T0)
    assert {first.domain, second.domain} == {"kuurth.com", "staud.clothing"}
    assert b.claim_next(T0) is None  # nothing left unclaimed


@pytest.mark.unit
def test_a_released_brand_comes_back_only_when_it_is_next_due(cat):
    s = Scheduler(cat)
    s.add("kuurth.com", cadence_seconds=3600, now=T0)
    due = s.claim_next(T0)
    s.release(due.domain, due.cadence_seconds, now=T0)
    assert s.claim_next(T0) is None
    assert s.claim_next(T0 + timedelta(seconds=3601)).domain == "kuurth.com"


@pytest.mark.unit
def test_a_deferred_brand_waits_without_counting_as_done(cat):
    """A host asking us to wait should not consume the brand's turn."""
    s = Scheduler(cat)
    s.add("kuurth.com", cadence_seconds=86400, now=T0)
    s.claim_next(T0)
    s.defer("kuurth.com", seconds=300, now=T0)
    assert s.claim_next(T0 + timedelta(seconds=299)) is None
    assert s.claim_next(T0 + timedelta(seconds=301)).domain == "kuurth.com"


@pytest.mark.unit
def test_a_claim_left_by_a_dead_worker_is_reclaimed(cat):
    """Nothing resumes the run, but the brand must not be locked out for ever."""
    s = Scheduler(cat, "worker-a", stale_claim_seconds=3600)
    s.add("kuurth.com", now=T0)
    s.claim_next(T0)
    assert s.claim_next(T0 + timedelta(seconds=60)) is None  # still held
    assert s.claim_next(T0 + timedelta(seconds=4000)).domain == "kuurth.com"


@pytest.mark.unit
def test_stopping_is_a_flag(cat):
    s = Scheduler(cat)
    assert s.should_stop() is False
    s.request_stop()
    assert s.should_stop() is True
    s.request_stop(False)
    assert s.should_stop() is False
