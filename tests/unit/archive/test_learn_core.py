"""The learning harness's foundations: signature, dossier, walls, meter, budget."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.archive.domain.brand import Capability, TransportLevel
from backend.archive.learn.budget import BudgetSpent, FleetBudget
from backend.archive.learn.dossier import DossierStore, RuleApplied
from backend.archive.learn.meter import Meter, Prices, cost_usd, predict, requests_per_check
from backend.archive.learn.signature import Signature, signature_of
from backend.archive.learn.walls import Action, Wall, classify
from backend.archive.store.objects import DirectoryObjectStore

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def cap(**kw: Any) -> Capability:
    base: dict[str, Any] = dict(domain="x.com", transport=TransportLevel.T0)
    base.update(kw)
    return Capability(**base)


# --- signature -------------------------------------------------------------------------


@pytest.mark.unit
def test_a_signature_is_six_words_and_round_trips():
    s = Signature(
        platform="sfcc",
        feed="closed",
        sitemap="alternates",
        page="productgroup",
        defence="none",
        locale="country-path",
    )
    assert s.key == "sfcc·closed·alternates·productgroup·none·country-path"
    assert Signature.parse(s.key) == s
    with pytest.raises(ValueError):
        Signature.parse("not a key")


@pytest.mark.unit
def test_the_probe_evidence_names_the_shape():
    acne = cap(
        platform="sfcc",
        sitemap_url="https://acne.com/sitemap_index.xml",
        ldjson_product=True,
        product_url_prefix="/us/en/",
        evidence={
            "sitemap_shape": "index",
            "sitemap_alternates": "275",
            "ldjson_kind": "productgroup",
        },
    )
    assert signature_of(acne).key == "sfcc·closed·alternates·productgroup·none·country-path"
    feng = cap(
        platform="haravan",
        product_json=True,
        sitemap_url="https://feng.com/sitemap_products_1.xml",
        product_url_prefix="/",
    )
    assert signature_of(feng).key == "haravan·per-product·named-product·none·none·none"
    luar = cap(platform="gatsby", page_data=True)
    assert signature_of(luar).key == "gatsby·page-data·none·none·none·none"
    shop = cap(
        platform="shopify",
        bulk_json=True,
        sitemap_url="https://s.com/sitemap.xml",
        evidence={"sitemap_shape": "index"},
    )
    assert signature_of(shop).feed == "open" and signature_of(shop).sitemap == "index"


@pytest.mark.unit
def test_the_ladder_says_what_the_defence_is():
    refused = cap(challenged=True, transport=TransportLevel.T2)
    ladder = [{"level": "t0", "outcome": "waf_403"}, {"level": "t1", "outcome": "waf_403"}]
    assert signature_of(refused, ladder).defence == "address"
    assert signature_of(refused, [{"level": "t0", "outcome": "tls_blocked"}]).defence == "tls"
    assert signature_of(refused, [{"level": "t0", "outcome": "challenge"}]).defence == "challenge"
    assert signature_of(cap(password_gated=True)).defence == "password"


@pytest.mark.unit
def test_likeness_weighs_platform_and_feed_double():
    a = Signature.parse("shopify·open·index·jsonld·none·none")
    b = Signature.parse("shopify·open·flat·og·rate·none")
    c = Signature.parse("sfcc·closed·index·jsonld·none·none")
    assert a.likeness(b) == 2 + 2 + 1  # platform, feed, locale
    assert a.likeness(c) == 1 + 1 + 1 + 1  # sitemap, page, defence, locale
    assert a.likeness(b) > a.likeness(c)


# --- dossier -----------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    return DirectoryObjectStore(tmp_path)


@pytest.mark.unit
def test_a_dossier_is_opened_once_and_appended_to(store):
    ds = DossierStore(store)
    d = ds.open("acne.com", name="Acne Studios")
    assert d.name == "Acne Studios" and d.events[0].kind == "opened"
    ds.rung("acne.com", "t0", "ok_thin", [200, 404], 1.2)
    ds.lane("acne.com", "t0×sitemap×structured_data×per_item", "full", 598, {"price": 1.0})
    ds.set_signature(
        "acne.com", "sfcc·closed·alternates·productgroup·none·country-path", why="probe"
    )
    ds.set_signature(
        "acne.com", "sfcc·closed·alternates·productgroup·none·country-path", why="again"
    )
    ds.set_wall("acne.com", "open", "none", "reads")
    d = ds.load("acne.com")
    assert d.rung_outcomes() == {"t0": "ok_thin"}
    assert d.best_lane().products == 598
    assert len(d.signature_history) == 1  # the same signature twice is one change
    assert d.wall["type"] == "open"
    assert [e.kind for e in d.events] == ["opened", "rung", "lane", "signature", "wall"]
    assert ds.domains() == ["acne.com"]


@pytest.mark.unit
def test_the_meter_adds_up_by_day(store):
    ds = DossierStore(store)
    ds.meter_add(
        "x.com",
        "2026-09-27",
        {"requests": {"t0": 10}, "bytes": {"t0": 5000}, "usd": 0.01, "runs": 1},
    )
    ds.meter_add(
        "x.com",
        "2026-09-27",
        {"requests": {"t0": 5, "t1p": 3}, "proxy_requests": 3, "usd": 0.02, "runs": 1},
    )
    d = ds.load("x.com")
    line = d.meter["2026-09-27"]
    assert line.requests == {"t0": 15, "t1p": 3} and line.proxy_requests == 3
    assert line.usd == 0.03 and line.runs == 2
    assert d.cost(days=1) == 0.03


@pytest.mark.unit
def test_onboarding_steps_are_written_as_they_happen(store):
    ds = DossierStore(store)
    ds.onboarding_start("x.com", name="X")
    ds.onboarding_step("x.com", "probe", "running")
    ds.onboarding_step("x.com", "probe", "done", "t0 ok")
    d = ds.load("x.com")
    steps = {s.name: s.status for s in d.onboarding.steps}
    assert steps["probe"] == "done" and steps["signature"] == "pending"
    assert d.onboarding.finished_at is None
    ds.onboarding_step("x.com", "verdict", "done", "open")
    assert ds.load("x.com").onboarding.finished_at is not None


@pytest.mark.unit
def test_pages_are_kept_beside_the_dossier(store):
    ds = DossierStore(store)
    sha = ds.save_page("x.com", "https://x.com/p/1", "<html>p</html>", kind="product")
    assert ds.load_page("x.com", sha) == "<html>p</html>"
    assert ds.load("x.com").pages[sha]["url"] == "https://x.com/p/1"


@pytest.mark.unit
def test_rules_applied_are_recorded_once(store):
    ds = DossierStore(store)
    r = RuleApplied(
        id="r1",
        signature="a·b·c·d·e·f",
        kind="recipe",
        description="d",
        at="2026-09-27T00:00:00+00:00",
    )
    ds.rule("x.com", r)
    ds.rule("x.com", r.model_copy(update={"status": "confirmed"}))
    d = ds.load("x.com")
    assert len(d.rules) == 1 and d.rules[0].status == "confirmed"


# --- walls -------------------------------------------------------------------------------


def dossier_with(store, domain="x.com", rungs=(), lanes=(), gaps=None, predicted=None, notes=None):
    ds = DossierStore(store)
    ds.open(domain)
    for level, outcome in rungs:
        ds.rung(domain, level, outcome)
    for comp, verdict, products, fill in lanes:
        ds.lane(domain, comp, verdict, products, fill)
    if gaps:
        ds.set_gaps(domain, gaps)
    if predicted:
        ds.set_predicted(domain, predicted)
    if notes:
        ds.update(domain, lambda d: setattr(d, "notes", notes))
    return ds.load(domain)


@pytest.mark.unit
def test_walls_read_the_dossier_together(store):
    v = classify(dossier_with(store))
    assert (v.wall, v.action) == (Wall.UNKNOWN, Action.ONBOARD)

    v = classify(
        dossier_with(
            store,
            "a.com",
            rungs=[("t0", "ok")],
            lanes=[("t0×bulk_json×platform_json×per_item", "full", 300, {})],
        )
    )
    assert (v.wall, v.action) == (Wall.OPEN, Action.NONE)

    v = classify(dossier_with(store, "b.com", rungs=[("t0", "waf_403")]))
    assert (v.wall, v.action) == (Wall.TLS, Action.CLIMB_T1)

    v = classify(
        dossier_with(store, "c.com", rungs=[("t0", "waf_403"), ("t1", "waf_403")]),
        proxy_available=False,
    )
    assert (v.wall, v.action) == (Wall.ADDRESS, Action.WATCH)
    v = classify(
        dossier_with(store, "c2.com", rungs=[("t0", "waf_403"), ("t1", "waf_403")]),
        proxy_available=True,
    )
    assert (v.wall, v.action) == (Wall.ADDRESS, Action.CLIMB_T1P)

    v = classify(dossier_with(store, "d.com", rungs=[("t0", "challenge")]), browser_available=True)
    assert (v.wall, v.action) == (Wall.CHALLENGE, Action.CLIMB_T2)

    v = classify(dossier_with(store, "e.com", rungs=[("t0", "ok_thin"), ("t1", "ok_thin")]))
    assert (v.wall, v.action) == (Wall.UNREADABLE, Action.ANALYSE)

    v = classify(dossier_with(store, "f.com", rungs=[("t0", "gated")]))
    assert (v.wall, v.action) == (Wall.GATED, Action.WATCH)

    v = classify(
        dossier_with(
            store,
            "g.com",
            rungs=[("t0", "ok")],
            lanes=[("t0×sitemap×structured_data×per_item", "busy", None, {})],
        )
    )
    assert (v.wall, v.action) == (Wall.BUSY, Action.PACE)

    v = classify(dossier_with(store, "h.com", notes="not a shop: a portfolio"))
    assert (v.wall, v.action) == (Wall.NOT_A_SHOP, Action.NONE)


@pytest.mark.unit
def test_a_partial_read_with_an_unread_field_asks_the_model_and_an_absent_one_does_not(store):
    lanes = [("t0×sitemap×structured_data×per_item", "partial", 900, {"price": 1.0})]
    v = classify(
        dossier_with(
            store,
            "m.com",
            rungs=[("t0", "ok")],
            lanes=lanes,
            gaps={"size_info": {"state": "unread"}},
        )
    )
    assert (v.wall, v.action) == (Wall.FIELD_GAP, Action.ANALYSE)
    v = classify(
        dossier_with(
            store,
            "n.com",
            rungs=[("t0", "ok")],
            lanes=lanes,
            gaps={"size_info": {"state": "absent"}},
        )
    )
    assert (v.wall, v.action) == (Wall.OPEN, Action.NONE)


@pytest.mark.unit
def test_a_brand_far_dearer_than_its_neighbours_is_asked_to_be_cheapened(store):
    lanes = [("t2×sitemap×structured_data×per_item", "full", 100, {})]
    d = dossier_with(
        store, "p.com", rungs=[("t0", "ok")], lanes=lanes, predicted={"per_product_usd": 0.01}
    )
    assert classify(d, median_cost_per_product=0.001).action == Action.CHEAPEN
    assert classify(d, median_cost_per_product=0.008).action == Action.NONE


# --- meter -------------------------------------------------------------------------------


class FakeTransport:
    def __init__(self, level, rows):
        self.level = level
        self.ledger = rows


@pytest.mark.unit
def test_the_meter_counts_by_rung_and_prices_it():
    prices = Prices(
        proxy_usd_per_1k=2.0,
        browser_usd_per_second=0.001,
        usd_per_gb=0.0,
        worker_usd_per_second=0.0,
    )
    m = Meter(prices=prices)
    m.track(FakeTransport(TransportLevel.T0, [{"url": "a", "status": 200, "bytes": 1000}] * 4))
    m.track(FakeTransport(TransportLevel.T1P, [{"url": "b", "status": 200, "bytes": 500}] * 10))
    m.track(
        FakeTransport(
            TransportLevel.T2, [{"url": "c", "status": 200, "bytes": 5, "seconds": 3.0}] * 2
        )
    )
    m.note_llm(0.5, calls=1, tokens=1000)
    s = m.snapshot()
    assert s["requests"] == {"t0": 4, "t1p": 10, "t2": 2}
    assert s["proxy_requests"] == 10 and s["browser_seconds"] == 6.0
    # 10 proxy requests at $2/1k = $0.02; 6 browser seconds at $0.001 = $0.006; llm $0.5
    assert s["usd"] == round(0.5 + 0.02 + 0.006, 6)
    assert cost_usd(s, Prices()) == 0.5  # unpriced, only the model costs anything


@pytest.mark.unit
def test_predictions_follow_the_lane_and_the_cadence():
    feed_reqs, _ = requests_per_check("bulk_json", "platform_json", 3600, full=True)
    page_reqs, _ = requests_per_check("sitemap", "structured_data", 3600, full=True)
    assert feed_reqs == 16 and page_reqs > 3600  # a feed is two orders cheaper
    prices = Prices(proxy_usd_per_1k=2.0)
    p = predict(
        3600,
        "t1p×sitemap×structured_data×per_item",
        cadence_seconds=86_400,
        sweep_seconds=None,
        prices=prices,
    )
    assert p["per_check_requests"] == 362 and p["per_check_usd"] == round(362 * 2.0 / 1000, 6)
    assert p["per_day_usd"] == p["per_check_usd"]
    measured = predict(
        3600,
        "t1p×sitemap×structured_data×per_item",
        43_200,
        None,
        prices,
        measured_per_check_usd=0.1,
    )
    assert (
        measured["per_check_usd"] == 0.1 and measured["per_day_usd"] == 0.2 and measured["measured"]
    )


# --- budget ------------------------------------------------------------------------------


@pytest.mark.unit
def test_the_ceiling_is_a_multiple_of_the_baseline_and_the_pools_split_it(store, monkeypatch):
    monkeypatch.setenv("ARCHIVE_BUDGET_MULTIPLIER", "2.0")
    monkeypatch.setenv("ARCHIVE_BUDGET_FLOOR_USD", "0")
    b = FleetBudget(store, clock=lambda: T0)
    row = b.refresh({"a.com": 1.0, "b.com": 3.0})
    assert row["baseline_usd_day"] == 4.0 and row["ceiling_usd_day"] == 8.0
    assert row["pools"]["recurring"]["cap"] == 4.0 and row["pools"]["discretionary"]["cap"] == 4.0
    b.charge("a.com", "recurring", 0.5)
    b.charge("a.com", "discretionary", 3.9)
    assert b.allow("discretionary", 0.05) and not b.allow("discretionary", 0.2)
    with pytest.raises(BudgetSpent):
        b.check("discretionary", 0.2)
    s = b.summary()
    assert s["spent_usd"] == 4.4 and s["by_brand"]["a.com"]["discretionary"] == 3.9


@pytest.mark.unit
def test_the_day_rolls_into_history(store, monkeypatch):
    monkeypatch.setenv("ARCHIVE_BUDGET_FLOOR_USD", "0")
    day = {"now": T0}
    b = FleetBudget(store, clock=lambda: day["now"])
    b.refresh({"a.com": 1.0})
    b.charge("a.com", "recurring", 0.25)
    day["now"] = T0 + timedelta(days=1)
    s = b.summary()
    assert s["day"] == "2026-09-28" and s["spent_usd"] == 0.0
    assert s["history"]["2026-09-27"]["recurring"] == 0.25


@pytest.mark.unit
def test_the_stretch_is_how_far_the_recurring_day_overshoots_its_pool(store, monkeypatch):
    monkeypatch.setenv("ARCHIVE_BUDGET_MULTIPLIER", "1.5")
    monkeypatch.setenv("ARCHIVE_BUDGET_FLOOR_USD", "0")
    b = FleetBudget(store, clock=lambda: T0)
    b.refresh({"a.com": 2.0})  # recurring cap 2.0
    assert b.stretch_factor(1.5) == 1.0
    assert b.stretch_factor(3.0) == 1.5


# --- the onboarding pool ---------------------------------------------------------------


@pytest.mark.unit
def test_a_first_read_is_paid_from_the_onboarding_pool_beside_the_ceiling(store, monkeypatch):
    """A wave of new brands must neither drain the day's recurring allowance nor be
    stopped by it: onboarding has its own number, outside the ceiling."""
    from backend.archive.learn.budget import BudgetSpent, FleetBudget

    monkeypatch.setenv("ONBOARD_DAILY_USD", "1.0")
    b = FleetBudget(store)
    b.refresh({"a.com": 2.0})
    b.charge("new.com", "onboarding", 0.6)
    s = b.summary()
    assert s["pools"]["onboarding"] == {"spent": 0.6, "cap": 1.0}
    assert s["spent_usd"] == 0.0  # the ceiling's pools are untouched
    assert s["by_brand"]["new.com"]["onboarding"] == 0.6
    assert b.allow("onboarding", 0.3) and not b.allow("onboarding", 0.5)
    with pytest.raises(BudgetSpent):
        b.check("onboarding", 0.5)
    # Still charged to the brand's line and the pool the next day rolls into history.
    later = FleetBudget(store, clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc))
    assert later.summary()["history"][s["day"]]["onboarding"] == 0.6


@pytest.mark.unit
def test_the_daily_cap_keeps_a_first_reads_day_apart_from_the_finders(store):
    from backend.archive.spend_cap import ONBOARD_KEY, DailyCap, FinderBudgetSpent

    finder = DailyCap(store, 10.0)
    onboard = DailyCap(store, 1.0, key=ONBOARD_KEY)
    onboard.charge(0.95)
    assert finder.spent_today() == 0.0 and onboard.spent_today() == 0.95
    assert finder.allow(0.1)
    with pytest.raises(FinderBudgetSpent):
        onboard.check(0.1)


@pytest.mark.unit
def test_a_runs_verdict_is_written_in_the_lanes_words():
    """Van Cleef read 1,258 products in a run called "ok" while its dossier called it
    walled: the run's words and the probe's must classify alike."""
    from backend.archive.learn.dossier import lane_verdict

    assert lane_verdict("ok", 1258) == "ok"
    assert lane_verdict("degraded", 40) == "partial"
    assert lane_verdict("degraded", 0) == "failed"
    assert lane_verdict("failed", None) == "failed"
