"""The store, over objects. The assertions are the SQLite version's; the fixture changed."""

import pytest

from backend.archive.domain.brand import (
    Brand,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    ScrapePlan,
)
from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import FLUSH_EVERY, Catalog
from backend.archive.store.objects import DirectoryObjectStore

COV = Coverage(extracted=1, channel_counts={}, coverage_pct=1.0, field_fill={}, verdict="ok")


@pytest.fixture()
def store(tmp_path):
    return DirectoryObjectStore(tmp_path)


@pytest.fixture()
def cat(store):
    c = Catalog(store)
    c.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    return c


def rec(slug="nemo", price=126.0, in_stock=True) -> ProductRecord:
    return ProductRecord(
        itemurl=f"https://kuurth.com/products/{slug}",
        product_title=slug.title(),
        price=price,
        in_stock=in_stock,
    )


def make_plan(domain="kuurth.com") -> ScrapePlan:
    from backend.archive.domain.brand import TransportLevel

    return ScrapePlan(
        domain=domain,
        transport=TransportLevel.T0,
        discovery=DiscoveryChannel.BULK_JSON,
        fetch=FetchChannel.PLATFORM_JSON,
        change_signal=ChangeSignal.PER_ITEM,
        status="ready",
        fingerprinted_at="2026-08-27T00:00:00+00:00",
    )


# --- brands, plans, rules, evidence -------------------------------------


@pytest.mark.unit
def test_brand_and_state_round_trip(cat):
    assert cat.get_brand("kuurth.com").homepage_url == "https://kuurth.com"
    assert cat.get_brand_state("kuurth.com") == "new"
    cat.set_brand_state("kuurth.com", "active")
    assert cat.get_brand_state("kuurth.com") == "active"


@pytest.mark.unit
def test_upserting_a_brand_does_not_reset_its_state(cat):
    cat.set_brand_state("kuurth.com", "active")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    assert cat.get_brand_state("kuurth.com") == "active"


@pytest.mark.unit
def test_unknown_brand_reads_as_none(cat):
    assert cat.get_brand("nope.com") is None
    assert cat.load_plan("nope.com") is None
    assert cat.load_recipe_book("nope.com") is None


@pytest.mark.unit
def test_plan_round_trip_and_upsert(cat):
    cat.save_plan(make_plan())
    assert cat.load_plan("kuurth.com").status == "ready"
    stale = make_plan()
    stale.stale = True
    cat.save_plan(stale)
    assert cat.load_plan("kuurth.com").stale is True


@pytest.mark.unit
def test_evidence_round_trips_as_pairs(cat):
    run = cat.open_run("kuurth.com", "full")
    cat.record_evidence("kuurth.com", run, [("color_info", "channel", 10, 4)])
    assert cat.load_evidence("kuurth.com") == {("color_info", "channel"): (10, 4)}


# --- runs ---------------------------------------------------------------


@pytest.mark.unit
def test_run_ids_sort_by_time(cat):
    first = cat.open_run("kuurth.com", "full")
    second = cat.open_run("kuurth.com", "delta")
    assert first < second
    assert cat.run_ids("kuurth.com") == [first, second]


@pytest.mark.unit
def test_latest_run_is_the_last_finalised_one(cat):
    cat.open_run("kuurth.com", "full")  # never finalised
    run = cat.open_run("kuurth.com", "delta")
    cat.finalize_run(run, 0, COV)
    latest = cat.latest_run("kuurth.com")
    assert latest["id"] == run
    assert latest["exit_status"] == 0
    assert latest["mode"] == "delta"


# --- products -----------------------------------------------------------


@pytest.mark.unit
def test_first_sight_always_appends_observation(cat):
    run = cat.open_run("kuurth.com", "full")
    assert cat.record_product("kuurth.com", run, rec(), "hint-1") is True
    cat.flush()
    assert cat.observation_count("kuurth.com") == 1


@pytest.mark.unit
def test_unchanged_product_appends_nothing(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), "hint-1")
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "delta")
    assert cat.record_product("kuurth.com", r2, rec(), "hint-1") is False
    cat.flush()
    assert cat.observation_count("kuurth.com") == 1  # history stores change, not repetition


@pytest.mark.unit
def test_price_change_appends_observation_and_updates_hint(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(price=180.0), "hint-1")
    r2 = cat.open_run("kuurth.com", "delta")
    assert cat.record_product("kuurth.com", r2, rec(price=126.0), "hint-2") is True
    cat.flush()
    assert cat.observation_count("kuurth.com") == 2
    assert cat.get_change_hints("kuurth.com") == {"https://kuurth.com/products/nemo": "hint-2"}


@pytest.mark.unit
def test_delisted_product_leaves_current_view_but_stays_stored(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), None)
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "full")  # product NOT seen this run
    cat.finalize_run(r2, 0, COV)
    assert cat.current_products("kuurth.com", live_only=True) == []
    assert len(cat.current_products("kuurth.com", live_only=False)) == 1  # the archive keeps it


@pytest.mark.unit
def test_mark_seen_keeps_a_product_current_without_refetching_it(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), "h1")
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "delta")
    cat.mark_seen("kuurth.com", r2, ["https://kuurth.com/products/nemo"])
    cat.finalize_run(r2, 0, COV)
    assert len(cat.current_products("kuurth.com")) == 1


@pytest.mark.unit
def test_a_run_with_no_coverage_does_not_hide_the_catalogue(cat):
    """A rate-limited run finalises without coverage. Treating it as the reference
    made 500 stored products stop being visible."""
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), None)
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "delta")
    cat.finalize_run(r2, 1, None)  # busy: never read the catalogue
    assert len(cat.current_products("kuurth.com")) == 1


@pytest.mark.unit
def test_rewrite_field_sets_one_value_across_the_brand(cat):
    run = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", run, rec("a"), None)
    cat.record_product("kuurth.com", run, rec("b"), None)
    cat.finalize_run(run, 0, COV)
    assert cat.rewrite_field("kuurth.com", "brand", "KUURTH") == 2
    assert {r["brand"] for r in cat.current_products("kuurth.com")} == {"KUURTH"}


# --- buffering ----------------------------------------------------------


@pytest.mark.unit
def test_products_survive_a_flush_mid_run(store, cat):
    """Writing a 9.8 MB object per product is not an option, so writes buffer. What
    was flushed must still be there when the store is opened again."""
    run = cat.open_run("kuurth.com", "full")
    for i in range(FLUSH_EVERY + 50):
        cat.record_product("kuurth.com", run, rec(f"p{i}"), None)
    cat.finalize_run(run, 0, COV)
    cat.close()
    assert len(Catalog(store).current_products("kuurth.com")) == FLUSH_EVERY + 50


@pytest.mark.unit
def test_a_store_closed_without_finalising_still_keeps_its_products(store, cat):
    run = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", run, rec(), None)
    cat.close()
    assert len(Catalog(store).current_products("kuurth.com", live_only=False)) == 1


@pytest.mark.unit
def test_the_sidebar_count_does_not_read_the_catalogues(store, cat, monkeypatch):
    """live_product_counts must read the small meta objects. Reading 32 catalogues to
    draw a column of numbers would pull 55 MB over the wire."""
    run = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", run, rec(), None)
    cat.finalize_run(run, 0, COV)
    cat.close()

    read: list[str] = []
    inner = store.get
    monkeypatch.setattr(store, "get", lambda key: (read.append(key), inner(key))[1])
    assert Catalog(store).live_product_counts() == {"kuurth.com": 1}
    assert not [k for k in read if k.startswith("catalogue/") and not k.endswith(".meta.json")], (
        read
    )


# --- images -------------------------------------------------------------


@pytest.mark.unit
def test_images_are_keyed_by_itemurl(cat):
    run = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", run, rec(), None)
    cat.finalize_run(run, 0, COV)
    url = "https://kuurth.com/products/nemo"
    cat.record_image("kuurth.com", url, "https://cdn/x.jpg", "aa", stored_url="https://r2/x.jpg")
    assert cat.stored_image_urls("kuurth.com", url) == {"https://cdn/x.jpg"}
    assert cat.archived_images("kuurth.com") == {url: ["https://r2/x.jpg"]}
    assert cat.stored_image_count("kuurth.com") == 1


@pytest.mark.unit
def test_an_image_recorded_twice_is_one_row(cat):
    url = "https://kuurth.com/products/nemo"
    cat.record_image("kuurth.com", url, "https://cdn/x.jpg", "aa")
    cat.record_image("kuurth.com", url, "https://cdn/x.jpg", "aa", stored_url="https://r2/x.jpg")
    assert cat.known_image_urls("kuurth.com", url) == {"https://cdn/x.jpg"}
    assert cat.stored_image_count("kuurth.com") == 1


# --- the fleet view -----------------------------------------------------


@pytest.mark.unit
def test_status_rows_report_state_coverage_and_freshness(cat):
    run = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", run, rec(), None)
    cat.set_brand_state("kuurth.com", "active")
    cat.finalize_run(run, 0, COV)
    row = next(r for r in cat.status_rows() if r["domain"] == "kuurth.com")
    assert row["state"] == "active"
    assert row["products"] == 1
    assert row["verdict"] == "ok"
    assert row["freshness"] is not None


@pytest.mark.unit
def test_search_reads_the_slim_index_and_finds_by_any_field(cat):
    run = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", run, rec("wool-cap"), None)
    cat.record_product("kuurth.com", run, rec("cotton-tee"), None)
    cat.finalize_run(run, 0, COV)
    hits = cat.search_products(["kuurth.com"], "wool")
    assert [r["product_title"] for _, r in hits] == ["Wool-Cap"]
    assert cat.search_products(["kuurth.com"], "") == []


@pytest.mark.unit
def test_request_ledger_aggregates_by_host(cat):
    cat.record_requests([("cdn.x", 200, 120, None, "2026-09-12T10:00:00+00:00")])
    cat.record_requests([("cdn.x", 429, 90, 30, "2026-09-12T11:00:00+00:00")])
    row = next(r for r in cat.host_stats() if r["host"] == "cdn.x")
    assert (row["requests"], row["ok"], row["busy"]) == (2, 1, 1)
    assert row["max_retry_after"] == 30
    assert row["avg_ms"] == 105
    assert cat.host_stats(since="2026-09-12T10:30:00+00:00")[0]["requests"] == 1


@pytest.mark.unit
def test_scorecards_come_back_newest_first(cat):
    from backend.archive.score import score

    for _ in range(2):
        run = cat.open_run("kuurth.com", "full")
        cat.record_product("kuurth.com", run, rec(), None)
        cat.finalize_run(run, 0, COV)
        cat.save_scorecard(run, "kuurth.com", score([rec()]))
    cards = cat.scorecards("kuurth.com")
    assert len(cards) == 2
    assert cards[0]["run_id"] > cards[1]["run_id"]


@pytest.mark.unit
def test_extraction_version_round_trips(cat):
    assert cat.extraction_version_for("kuurth.com") is None
    cat.set_extraction_version("kuurth.com", "abc123")
    assert cat.extraction_version_for("kuurth.com") == "abc123"


@pytest.mark.unit
def test_the_search_index_survives_a_second_run(cat):
    """The index filters to the latest covered run. flush() happens before the run
    being finalised has its coverage written, so on run two the filter matched the
    previous run and the index came out empty."""
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec("wool-cap"), None)
    cat.finalize_run(r1, 0, COV)
    assert len(cat.search_products(["kuurth.com"], "wool")) == 1

    r2 = cat.open_run("kuurth.com", "delta")
    cat.record_product("kuurth.com", r2, rec("wool-cap", price=99.0), None)
    cat.finalize_run(r2, 0, COV)
    assert len(cat.search_products(["kuurth.com"], "wool")) == 1
