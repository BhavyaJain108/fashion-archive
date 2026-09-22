"""The loop closes: a failure expires instead of scarring a brand for good, a brand that
keeps needing a person is looked at less often and said so, the finder has a daily
ceiling shared across workers, and what to fix next is written down after every run
rather than re-derived by hand."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.archive.domain.brand import Brand, Capability, PlanAttempt, TransportLevel
from backend.archive.domain.product import ProductRecord
from backend.archive.planner import ATTEMPT_MEMORY_DAYS, compose_plan
from backend.archive.runner.daemon import ATTENTION_PATIENCE, backoff, run_once
from backend.archive.scheduler import Scheduler
from backend.archive.spend_cap import DailyCap, FinderBudgetSpent
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import DirectoryObjectStore

NOW = "2026-09-22T12:00:00+00:00"
BULK = "t0×bulk_json×platform_json×per_item"


def _cap() -> Capability:
    return Capability(domain="x.com", transport=TransportLevel.T0, bulk_json=True)


def _failed(days_ago: float, composition: str = BULK) -> PlanAttempt:
    at = datetime.fromisoformat(NOW) - timedelta(days=days_ago)
    return PlanAttempt(composition=composition, failed_at=at.isoformat(), reason="test")


# --- failures expire ---------------------------------------------------------------


@pytest.mark.unit
def test_a_recent_failure_still_keeps_its_rung_off_the_ladder():
    plan = compose_plan(_cap(), tried=[_failed(1)], now=NOW)
    assert plan.status == "needs_attention"


@pytest.mark.unit
def test_an_old_failure_is_offered_again_and_the_history_is_kept():
    plan = compose_plan(_cap(), tried=[_failed(ATTEMPT_MEMORY_DAYS + 1)], now=NOW)
    assert plan.status == "ready"
    assert plan.composition == BULK
    assert len(plan.tried) == 1  # remembered; it just no longer blocks


@pytest.mark.unit
def test_a_naive_timestamp_is_read_as_utc():
    naive = _failed(1).model_copy(update={"failed_at": "2026-09-21T12:00:00"})
    assert compose_plan(_cap(), tried=[naive], now=NOW).status == "needs_attention"


# --- stuck brands back off ----------------------------------------------------------


@pytest.mark.unit
def test_backoff_waits_out_patience_then_doubles_up_to_a_cap():
    assert backoff(3600, 0) == 3600
    assert backoff(3600, ATTENTION_PATIENCE - 1) == 3600
    assert backoff(3600, ATTENTION_PATIENCE) == 7200
    assert backoff(3600, ATTENTION_PATIENCE + 1) == 14400
    assert backoff(3600, 50) == 3600 * 16


@pytest.mark.unit
def test_attention_counts_up_and_a_good_run_clears_it(tmp_path):
    cat = Catalog(DirectoryObjectStore(tmp_path))
    assert cat.record_attention("x.com", "no lane") == 1
    assert cat.record_attention("x.com", "no lane") == 2
    assert cat.attention("x.com") == (2, "no lane")
    assert cat.record_attention("x.com", None) == 0
    assert cat.attention("x.com") == (0, None)


# --- what to fix next is written down ------------------------------------------------


@pytest.mark.unit
def test_recommendations_are_kept_and_the_top_line_reaches_the_fleet(tmp_path):
    cat = Catalog(DirectoryObjectStore(tmp_path))
    cat.save_recommendations(
        "x.com",
        "r1",
        [
            (4, "3 fields never looked for on the page", "one finder call covers several"),
            (6, "$2.00 for this brand", "rules are being learned more than reused"),
        ],
    )
    kept = cat.load_recommendations("x.com")
    assert kept["run_id"] == "r1" and kept["findings"][0]["priority"] == 4
    assert cat.fleet()["x.com"]["next_action"] == "3 fields never looked for on the page"
    assert cat.fleet()["x.com"]["open_findings"] == 2


def _record() -> ProductRecord:
    return ProductRecord(
        itemurl="https://kuurth.com/products/a",
        product_title="Tee",
        price=40.0,
        in_stock=True,
        main_image_url="https://cdn.x/a.jpg",
        all_images='["https://cdn.x/a.jpg"]',
    )


@pytest.mark.unit
def test_the_daemon_writes_what_to_fix_next_after_every_run(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    sched = Scheduler(store)
    sched.add("kuurth.com", cadence_seconds=3600)
    run = cat.open_run("kuurth.com", "full")
    cat.finalize_run(run, 0, None)

    assert run_once(cat, sched, lambda b: ([_record()], 0.0), log=lambda *a: None) is True
    kept = cat.load_recommendations("kuurth.com")
    assert kept is not None and kept["run_id"] == run
    # Nothing was stored through the catalogue in this run, and that is the first
    # thing recommend() says — the point is that it said it without being asked.
    assert kept["findings"][0]["headline"] == "nothing stored"


@pytest.mark.unit
def test_a_brand_that_keeps_needing_a_person_is_next_wanted_later(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    sched = Scheduler(store)
    sched.add("kuurth.com", cadence_seconds=3600)
    run = cat.open_run("kuurth.com", "full")
    cat.finalize_run(run, 1, None)
    for _ in range(ATTENTION_PATIENCE):
        cat.record_attention("kuurth.com", "no lane: nothing readable")

    before = datetime.now(timezone.utc)
    assert run_once(cat, sched, lambda b: ([], 0.0), log=lambda *a: None) is True
    next_due = datetime.fromisoformat(sched.rows()[0]["next_due"])
    assert next_due - before >= timedelta(seconds=7200 - 5)


# --- a run's own log is kept with the run --------------------------------------------


@pytest.mark.unit
def test_a_run_leaves_its_event_log_in_the_store(tmp_path):
    from backend.archive.domain.product import ProductRef
    from backend.archive.planner import compose_plan
    from backend.archive.runner.run import run_brand

    brand = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")
    cap = Capability(
        domain="kuurth.com", platform="shopify", transport=TransportLevel.T0, bulk_json=True
    )

    class Conn:
        kind = "shopify"

        def discover(self, b, t):
            return [ProductRef(url="https://kuurth.com/products/a", change_hint="h1", payload={})]

        def fetch(self, r, t):
            return ProductRecord(itemurl=r.url, product_title="A")

    cat = Catalog(DirectoryObjectStore(tmp_path))
    cat.upsert_brand(brand)
    code = run_brand(
        brand,
        cat,
        transport=None,
        mode="full",
        locks_dir=tmp_path / "locks",
        log_dir=tmp_path / "logs",
        prober=lambda d, t: cap,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: Conn(),
    )
    assert code == 0
    run = cat.latest_run("kuurth.com")
    text = cat.load_run_log("kuurth.com", run["id"])
    assert text is not None
    events = [__import__("json").loads(line)["event"] for line in text.splitlines() if line]
    assert events[0] == "planned" and "finalized" in events


@pytest.mark.unit
def test_a_run_left_running_by_a_replaced_worker_is_closed_by_the_next_one(tmp_path):
    cat = Catalog(DirectoryObjectStore(tmp_path))
    cat.upsert_brand(Brand(domain="x.com", homepage_url="https://x.com"))
    lost = cat.open_run("x.com", "delta")  # never finalised: the container went away
    fresh = cat.open_run("x.com", "delta")
    rows = {r["id"]: r for r in cat.recent_runs("x.com", 5)}
    assert rows[lost]["exit_status"] == 2 and "replaced" in rows[lost]["abandoned"]
    assert rows[fresh]["exit_status"] is None  # the live one is still live


@pytest.mark.unit
def test_a_refused_key_stops_the_finder_for_the_run_after_one_answer(tmp_path):
    from backend.archive.domain.product import ProductRef
    from backend.archive.planner import compose_plan
    from backend.archive.runner.run import run_brand

    brand = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")
    cap = Capability(
        domain="kuurth.com", platform="shopify", transport=TransportLevel.T0, bulk_json=True
    )
    calls = []

    class Conn:
        kind = "shopify"

        def discover(self, b, t):
            return [
                ProductRef(url=f"https://kuurth.com/products/{i}", change_hint=f"h{i}", payload={})
                for i in range(4)
            ]

        def fetch(self, r, t):
            return ProductRecord(itemurl=r.url, product_title="A")

        def page_html(self, r, t):
            return "<html></html>"

    def refused(domain, url, missing, transport):
        calls.append(url)
        raise RuntimeError("AuthenticationError: Error code: 401 - invalid x-api-key")

    cat = Catalog(DirectoryObjectStore(tmp_path))
    cat.upsert_brand(brand)
    run_brand(
        brand,
        cat,
        transport=None,
        mode="full",
        locks_dir=tmp_path / "locks",
        log_dir=tmp_path / "logs",
        prober=lambda d, t: cap,
        composer=compose_plan,
        connector_factory=lambda plan, sitemap_url=None, limit=None: Conn(),
        field_finder=refused,
    )
    assert len(calls) == 1, "one refusal is the whole answer for the run"
    text = cat.load_run_log("kuurth.com", cat.latest_run("kuurth.com")["id"])
    assert "finder-unauthorised" in text
    assert cat.latest_run("kuurth.com")["coverage"]["verdict"] == "degraded"


# --- run now is an edit to the schedule, and only when nobody holds the brand ---------


@pytest.mark.unit
def test_run_now_moves_the_turn_forward_and_re_enables(tmp_path):
    from backend.archive.scheduler import Scheduler

    sched = Scheduler(DirectoryObjectStore(tmp_path))
    sched.add("x.com", cadence_seconds=86400)
    sched.set_enabled("x.com", False)
    later = datetime.now(timezone.utc) + timedelta(days=1)
    sched._amend("x.com", next_due=later.isoformat())

    assert sched.run_now("x.com") is True
    row = sched.rows()[0]
    assert row["enabled"] == 1
    assert row["next_due"] <= datetime.now(timezone.utc).isoformat()


@pytest.mark.unit
def test_run_now_is_refused_for_a_held_or_unknown_brand(tmp_path):
    from backend.archive.scheduler import Scheduler

    store = DirectoryObjectStore(tmp_path)
    sched = Scheduler(store, worker_id="w1")
    sched.add("x.com", cadence_seconds=3600)
    assert sched.claim_next() is not None
    assert sched.run_now("x.com") is False  # a worker has it; nothing to bring forward
    assert sched.run_now("nobody.example") is False


# --- the gate tolerates a shop's odd unphotographed item ------------------------------


def _with_photo(i: int, photo: bool = True) -> ProductRecord:
    return ProductRecord(
        itemurl=f"https://x.com/products/{i}",
        product_title=f"Item {i}",
        price=10.0,
        in_stock=True,
        main_image_url="https://cdn.x/a.jpg" if photo else None,
        all_images='["https://cdn.x/a.jpg"]' if photo else None,
    )


@pytest.mark.unit
def test_one_unphotographed_product_in_two_hundred_does_not_fail_the_brand():
    from backend.archive.score import score

    card = score([_with_photo(i, photo=(i != 0)) for i in range(200)])
    assert card.required_ok is True
    assert card.required_gaps == {"main_image_url": 0.005, "all_images": 0.005}  # still said


@pytest.mark.unit
def test_five_in_two_hundred_still_fails_it():
    from backend.archive.score import score

    card = score([_with_photo(i, photo=(i >= 5)) for i in range(200)])
    assert card.required_ok is False


# --- the finder has a ceiling ---------------------------------------------------------


class _Clock:
    def __init__(self, day: int):
        self.day = day

    def __call__(self) -> datetime:
        return datetime(2026, 9, self.day, 12, tzinfo=timezone.utc)


@pytest.mark.unit
def test_the_cap_stops_the_finder_for_the_day_and_a_new_day_starts_clean(tmp_path):
    clock = _Clock(22)
    cap = DailyCap(DirectoryObjectStore(tmp_path), usd_per_day=1.0, clock=clock)
    assert cap.allow()
    cap.charge(0.6)
    cap.charge(0.5)
    assert cap.spent_today() == pytest.approx(1.1)
    with pytest.raises(FinderBudgetSpent):
        cap.check()

    clock.day = 23
    assert cap.spent_today() == 0.0
    cap.check()  # allowed again
    cap.charge(0.1)
    summary = cap.summary()
    assert summary["usd"] == pytest.approx(0.1)
    assert summary["history"]["2026-09-22"] == pytest.approx(1.1)


@pytest.mark.unit
def test_two_workers_share_one_allowance(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    one = DailyCap(store, usd_per_day=1.0, clock=_Clock(22))
    two = DailyCap(store, usd_per_day=1.0, clock=_Clock(22))
    one.charge(0.7)
    assert two.spent_today() == pytest.approx(0.7)
    two.charge(0.4)
    assert not one.allow()


@pytest.mark.unit
def test_a_zero_cap_is_off(tmp_path):
    assert not DailyCap(DirectoryObjectStore(tmp_path), usd_per_day=0).allow()
