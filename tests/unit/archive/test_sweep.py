"""A sweep: stock and price from the bulk feed, on products already held, and
nothing else — not a covered run, not the brand's turn, never a product added or
removed, never a photograph or a stamp touched."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.archive.connectors.base import ChannelBusy
from backend.archive.domain.brand import Brand, Capability, TransportLevel
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.domain.run import Coverage
from backend.archive.planner import compose_plan
from backend.archive.runner.daemon import run_once
from backend.archive.runner.sweep import NO_CHEAP_SOURCE, sweep_brand
from backend.archive.scheduler import SWEEP_CLEARANCE_SECONDS, Scheduler
from backend.archive.store.catalog import Catalog, stock_patch
from backend.archive.store.objects import DirectoryObjectStore

T0 = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
DOMAIN = "kuurth.com"
COV = Coverage(extracted=2, coverage_pct=1.0, verdict="ok")


def _url(i: int) -> str:
    return f"https://{DOMAIN}/products/{i}"


def _record(i: int, **over) -> ProductRecord:
    fields: dict[str, Any] = dict(
        itemurl=_url(i),
        product_title=f"Item {i}",
        price=40.0,
        full_price=None,
        currency="USD",
        in_stock=True,
        size_info="S, M",
        size_availability="in_stock, in_stock",
        size_stock_counts="3, 2",
        main_image_url="https://cdn.x/a.jpg",
        all_images='["https://cdn.x/a.jpg"]',
        offers=[
            {"size": "S", "variant_id": "1", "available": True, "price": 40.0},
            {"size": "M", "variant_id": "2", "available": True, "price": 40.0},
        ],
    )
    fields.update(over)
    return ProductRecord(**fields)


def _seeded(tmp_path) -> tuple[Catalog, str]:
    """A brand with two covered products from one real run."""
    cat = Catalog(DirectoryObjectStore(tmp_path))
    cat.upsert_brand(Brand(domain=DOMAIN, homepage_url=f"https://{DOMAIN}"))
    run = cat.open_run(DOMAIN, "full")
    cat.record_product(DOMAIN, run, _record(1), "h1")
    cat.record_product(DOMAIN, run, _record(2), "h2")
    cat.finalize_run(run, 0, COV)
    return cat, run


# --- the write: only stock, nothing added, nothing removed -----------------------------


@pytest.mark.unit
def test_stock_patch_takes_only_stock_fields_and_patches_offers_by_variant():
    previous = json.loads(_record(1).model_dump_json())
    fresh = json.loads(
        _record(
            1,
            product_title="Renamed",
            price=30.0,
            full_price=40.0,
            promotion_type="sale",
            size_availability="in_stock, out_of_stock",
            size_stock_counts="3, 0",
            main_image_url="https://cdn.x/new.jpg",
            offers=[
                {"size": "S", "variant_id": "1", "available": True, "price": 30.0},
                {"size": "M", "variant_id": "2", "available": False, "price": 30.0},
                {"size": "L", "variant_id": "3", "available": True, "price": 30.0},
            ],
        ).model_dump_json()
    )
    patch = stock_patch(previous, fresh)
    assert set(patch) == {
        "price",
        "full_price",
        "promotion_type",
        "size_availability",
        "size_stock_counts",
        "offers",
    }
    assert [o["variant_id"] for o in patch["offers"]] == ["1", "2"]  # L is not added
    assert patch["offers"][1] == {"size": "M", "variant_id": "2", "available": False, "price": 30.0}
    assert stock_patch(previous, previous) == {}


@pytest.mark.unit
def test_a_size_list_that_moved_keeps_the_availability_for_the_delta_run():
    previous = json.loads(_record(1).model_dump_json())
    fresh = json.loads(
        _record(
            1, size_info="S, M, L", size_availability="in_stock, in_stock, in_stock"
        ).model_dump_json()
    )
    fresh["price"] = 35.0
    patch = stock_patch(previous, fresh)
    assert patch == {"price": 35.0}  # not "in_stock, in_stock, in_stock" against "S, M"


@pytest.mark.unit
def test_update_stock_changes_stock_only_and_adds_or_removes_nothing(tmp_path):
    cat, real_run = _seeded(tmp_path)
    before = {r["itemurl"]: r for r in cat.current_products(DOMAIN)}
    history_before = cat.product_history(DOMAIN)
    sweep = cat.open_run(DOMAIN, "sweep")

    updates = [
        {
            "itemurl": _url(1),
            "size_info": "S, M",
            "in_stock": True,
            "size_availability": "in_stock, out_of_stock",
            "size_stock_counts": "3, 0",
            "price": 30.0,
            "full_price": 40.0,
            "promotion_type": "sale",
            "currency": "USD",
            "offers": [{"variant_id": "2", "available": False, "price": 30.0}],
        },
        {"itemurl": _url(2), "price": 40.0, "in_stock": True},  # unchanged
        {"itemurl": _url(9), "price": 1.0, "in_stock": True},  # not in the catalogue
    ]
    assert cat.update_stock(DOMAIN, sweep, updates) == 1
    cat.finalize_run(sweep, 0, None)

    after = {r["itemurl"]: r for r in cat.current_products(DOMAIN)}
    assert set(after) == set(before)  # nothing added, nothing removed
    one = after[_url(1)]
    assert (one["price"], one["full_price"], one["promotion_type"]) == (30.0, 40.0, "sale")
    assert one["size_availability"] == "in_stock, out_of_stock"
    assert one["offers"][1]["available"] is False and one["offers"][0]["available"] is True
    # Everything that is not stock is exactly as it was.
    for field in ("product_title", "main_image_url", "all_images", "size_info", "description"):
        assert one[field] == before[_url(1)][field]
    assert after[_url(2)] == before[_url(2)]
    # No stamp moved and the reference run is still the real one.
    assert cat.product_history(DOMAIN) == history_before
    assert cat._latest_covered_run(DOMAIN) == real_run
    assert cat.get_change_hints(DOMAIN) == {_url(1): "h1", _url(2): "h2"}
    # The watched change left an observation under the sweep run.
    assert cat.observation_count(DOMAIN) == 3  # two from the real run, one from the sweep
    held = cat._read(f"history/{DOMAIN}/{sweep}.json")
    assert held["observations"][0]["price"] == 30.0
    # The fleet line is still the real run's.
    assert cat.fleet()[DOMAIN]["verdict"] == "ok" and cat.fleet()[DOMAIN]["mode"] == "full"


# --- the run ---------------------------------------------------------------------------


def _cap(**over) -> Capability:
    fields: dict[str, Any] = dict(
        domain=DOMAIN, platform="shopify", transport=TransportLevel.T0, bulk_json=True
    )
    fields.update(over)
    return Capability(**fields)


class _Feed:
    """A connector whose discovery already carries every record — a bulk feed."""

    kind = "shopify"

    def __init__(self, records):
        self.records = records
        self.discovered = 0

    def discover(self, brand, transport):
        self.discovered += 1
        return [
            ProductRef(url=r.itemurl, change_hint="h", payload={"i": r.itemurl})
            for r in self.records
        ]

    def fetch(self, ref, transport):
        return next(r for r in self.records if r.itemurl == ref.url)


@pytest.mark.unit
def test_a_sweep_reads_the_feed_updates_stock_and_is_not_a_covered_run(tmp_path):
    cat, real_run = _seeded(tmp_path)
    cat.save_plan(compose_plan(_cap()))
    feed = _Feed(
        [
            _record(1, price=30.0, full_price=40.0, promotion_type="sale"),
            _record(2),
            _record(3),  # in the feed, not in the catalogue: not added
        ]
    )
    code = sweep_brand(
        Brand(domain=DOMAIN, homepage_url=f"https://{DOMAIN}"),
        cat,
        transport=None,
        locks_dir=tmp_path / "locks",
        log_dir=tmp_path / "logs",
        connector_factory=lambda plan, **kw: feed,
    )
    assert code == 0 and feed.discovered == 1
    run = cat.latest_run(DOMAIN)
    assert run["mode"] == "sweep" and run["exit_status"] == 0 and run["coverage"] is None
    assert run["checked"] == 3 and run["changed"] == 1 and run["seconds"] >= 0
    assert cat._latest_covered_run(DOMAIN) == real_run
    products = {r["itemurl"]: r for r in cat.current_products(DOMAIN)}
    assert set(products) == {_url(1), _url(2)}
    assert products[_url(1)]["price"] == 30.0 and products[_url(1)]["promotion_type"] == "sale"
    assert cat.stored_image_count(DOMAIN) == 0
    text = cat.load_run_log(DOMAIN, run["id"])
    assert '"event": "swept"' in text


@pytest.mark.unit
def test_a_structured_brand_is_skipped_with_the_reason_and_nothing_is_fetched(tmp_path):
    cat, real_run = _seeded(tmp_path)
    cat.save_plan(
        compose_plan(
            _cap(
                platform=None,
                bulk_json=False,
                ldjson_product=True,
                sitemap_url=f"https://{DOMAIN}/sitemap.xml",
            )
        )
    )
    assert cat.load_plan(DOMAIN).discovery.value == "sitemap"

    class NoFetch:
        def get(self, url):
            raise AssertionError(f"a sweep must not fetch {url}")

    def no_connector(plan, **kw):
        raise AssertionError("no connector should be built")

    code = sweep_brand(
        Brand(domain=DOMAIN, homepage_url=f"https://{DOMAIN}"),
        cat,
        transport=NoFetch(),
        locks_dir=tmp_path / "locks",
        log_dir=tmp_path / "logs",
        connector_factory=no_connector,
        transport_factory=lambda level: NoFetch(),
    )
    assert code == 0
    run = cat.latest_run(DOMAIN)
    assert run["mode"] == "sweep" and run["reason"] == NO_CHEAP_SOURCE
    assert run["checked"] == 0 and run["coverage"] is None
    assert cat._latest_covered_run(DOMAIN) == real_run


@pytest.mark.unit
def test_a_brand_with_no_plan_is_skipped_rather_than_probed(tmp_path):
    cat, _ = _seeded(tmp_path)
    code = sweep_brand(
        Brand(domain=DOMAIN, homepage_url=f"https://{DOMAIN}"),
        cat,
        transport=None,
        locks_dir=tmp_path / "locks",
        log_dir=tmp_path / "logs",
        connector_factory=lambda plan, **kw: pytest.fail("no connector without a plan"),
    )
    assert code == 0
    assert "no working plan" in cat.latest_run(DOMAIN)["reason"]


# --- the schedule: offered between turns, never in front of one ------------------------


@pytest.mark.unit
def test_the_scheduler_offers_a_sweep_on_its_cadence_and_withholds_it_near_a_turn(tmp_path):
    s = Scheduler(DirectoryObjectStore(tmp_path), worker_id="w1")
    s.add(DOMAIN, cadence_seconds=86400, now=T0)
    s.release(DOMAIN, 86400, now=T0)  # the real turn is a day away
    assert s.claim_next(T0 + timedelta(minutes=1)) is None  # sweep_seconds is 0: off

    s.set_sweep(DOMAIN, 900)
    assert s.rows()[0]["sweep_seconds"] == 900
    due = s.claim_next(T0 + timedelta(minutes=1))
    assert due is not None and due.mode == "sweep" and due.domain == DOMAIN
    row = s.row(DOMAIN)
    assert row["claimed_by"] == "w1" and row["claimed_mode"] == "sweep"
    assert row["next_due"] == (T0 + timedelta(days=1)).isoformat()  # the turn is untouched
    assert s.claim_next(T0 + timedelta(minutes=2)) is None  # held

    swept_at = T0 + timedelta(minutes=5)
    s.release_after_sweep(DOMAIN, now=swept_at)
    row = s.row(DOMAIN)
    assert row["claimed_by"] is None and row["last_sweep"] == swept_at.isoformat()
    assert row["next_due"] == (T0 + timedelta(days=1)).isoformat()
    assert s.claim_next(swept_at + timedelta(seconds=899)) is None  # not yet
    assert s.claim_next(swept_at + timedelta(seconds=901)).mode == "sweep"
    s.release_after_sweep(DOMAIN, now=swept_at + timedelta(seconds=901))

    # Within ten minutes of the real turn the sweep is withheld, and the turn itself
    # is offered as a delta run when it comes.
    close = T0 + timedelta(days=1) - timedelta(seconds=SWEEP_CLEARANCE_SECONDS - 30)
    assert s.claim_next(close) is None
    assert s.claim_next(T0 + timedelta(days=1, seconds=1)).mode == "delta"


@pytest.mark.unit
def test_a_paused_brand_and_a_queued_learn_run_are_not_swept(tmp_path):
    s = Scheduler(DirectoryObjectStore(tmp_path), worker_id="w1")
    s.add(DOMAIN, cadence_seconds=86400, now=T0)
    s.release(DOMAIN, 86400, now=T0)
    s.set_sweep(DOMAIN, 60)
    s.set_enabled(DOMAIN, False)
    assert s.claim_next(T0 + timedelta(hours=1)) is None
    s.set_enabled(DOMAIN, True)
    assert s.learn_now(DOMAIN, now=T0 + timedelta(hours=1)) == "queued"
    assert s.claim_next(T0 + timedelta(hours=1)).mode == "learn"  # the learn run goes first


@pytest.mark.unit
def test_a_busy_host_holds_the_next_sweep_back(tmp_path):
    s = Scheduler(DirectoryObjectStore(tmp_path), worker_id="w1")
    s.add(DOMAIN, cadence_seconds=86400, now=T0)
    s.release(DOMAIN, 86400, now=T0)
    s.set_sweep(DOMAIN, 60)
    assert s.claim_next(T0).mode == "sweep"
    s.release_after_sweep(DOMAIN, now=T0, not_before=1800)
    assert s.claim_next(T0 + timedelta(seconds=120)) is None
    assert s.claim_next(T0 + timedelta(seconds=1801)).mode == "sweep"


@pytest.mark.unit
def test_sweep_now_queues_one_sweep_whatever_the_cadence_and_answers_like_run_now(tmp_path):
    s = Scheduler(DirectoryObjectStore(tmp_path), worker_id="w1", stale_claim_seconds=900)
    s.add(DOMAIN, cadence_seconds=86400, now=T0)
    s.release(DOMAIN, 86400, now=T0)
    assert s.sweep_now("nobody.example") == "unknown"
    assert s.sweep_now(DOMAIN, now=T0) == "queued"
    assert s.row(DOMAIN)["sweep_asap"] == 1
    due = s.claim_next(T0)
    assert due.mode == "sweep" and s.row(DOMAIN)["sweep_asap"] == 0
    assert s.sweep_now(DOMAIN, now=T0) == "held"
    assert s.sweep_now(DOMAIN, now=T0 + timedelta(seconds=901)) == "dead"
    s.release_after_sweep(DOMAIN, now=T0)
    assert s.claim_next(T0 + timedelta(seconds=5)) is None  # one sweep, not a cadence

    s.set_enabled(DOMAIN, False)
    assert s.sweep_now(DOMAIN, now=T0) == "queued_once"
    assert s.claim_next(T0).mode == "sweep"
    s.release_after_sweep(DOMAIN, now=T0)
    assert s.row(DOMAIN)["enabled"] == 0


# --- the daemon: a sweep is done, logged, and the turn handed back as it was -----------


@pytest.mark.unit
def test_the_daemon_runs_a_sweep_without_a_scorecard_and_keeps_the_turn(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain=DOMAIN, homepage_url=f"https://{DOMAIN}"))
    s = Scheduler(store, worker_id="w1")
    s.add(DOMAIN, cadence_seconds=86400, now=T0)
    later = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    s._amend(DOMAIN, next_due=later, sweep_seconds=60)
    seen = []

    def do_brand(brand, mode="delta", retry_searched=False):
        seen.append(mode)
        run = cat.open_run(brand.domain, "sweep")
        cat.annotate_run(brand.domain, run, checked=340, changed=12, seconds=9.0)
        cat.finalize_run(run, 0, None)
        return None, 0.0

    lines = []
    assert run_once(cat, s, do_brand, log=lines.append) is True
    assert seen == ["sweep"]
    assert lines == [f"{DOMAIN} sweep done: 340 checked, 12 changed, 9.0 s"]
    row = s.row(DOMAIN)
    assert row["claimed_by"] is None and row["next_due"] == later and row["last_sweep"]
    assert cat.scorecards(DOMAIN) == []

    def busy(brand, mode="delta", retry_searched=False):
        raise ChannelBusy("429")

    s._amend(DOMAIN, last_sweep=None)
    assert run_once(cat, s, busy, log=lambda *a: None) is True
    row = s.row(DOMAIN)
    assert row["claimed_by"] is None and row["next_due"] == later and row["sweep_not_before"]
