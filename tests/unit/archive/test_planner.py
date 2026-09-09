import pytest

from backend.archive.connectors import get_connector
from backend.archive.connectors.shopify import ShopifyConnector
from backend.archive.domain.brand import Capability, PlanAttempt, TransportLevel
from backend.archive.planner import compose_plan

NOW = "2026-08-27T00:00:00+00:00"


def cap(**kw) -> Capability:
    base = dict(
        domain="x.com",
        transport=TransportLevel.T0,
        bulk_json=False,
        password_gated=False,
        challenged=False,
    )
    base.update(kw)
    return Capability(**base)


@pytest.mark.unit
def test_open_shopify_composes_bulk_plan():
    plan = compose_plan(cap(platform="shopify", bulk_json=True), now=NOW)
    assert plan.status == "ready"
    assert plan.composition == "t0×bulk_json×platform_json×per_item"
    assert isinstance(get_connector(plan), ShopifyConnector)


@pytest.mark.unit
def test_password_gate_skips():
    plan = compose_plan(cap(password_gated=True, transport=TransportLevel.T4), now=NOW)
    assert plan.status == "skip_gated"


@pytest.mark.unit
def test_challenged_lands_in_needs_attention_in_m1():
    plan = compose_plan(
        cap(platform="shopify", challenged=True, transport=TransportLevel.T2), now=NOW
    )
    assert plan.status == "needs_attention"


@pytest.mark.unit
def test_woo_capability_composes_woo_plan():
    from backend.archive.connectors.woocommerce import WooConnector

    plan = compose_plan(cap(platform="wordpress", woo_api=True), now=NOW)
    assert plan.status == "ready"
    assert plan.composition == "t0×woo_api×platform_json×per_item"
    assert isinstance(get_connector(plan), WooConnector)


@pytest.mark.unit
def test_ldjson_capability_composes_structured_plan():
    from backend.archive.connectors.structured import StructuredConnector

    plan = compose_plan(
        cap(ldjson_product=True, sitemap_url="https://liniss.com/sitemap.xml"), now=NOW
    )
    assert plan.status == "ready"
    assert plan.composition == "t0×sitemap×structured_data×per_item"
    assert plan.sitemap_url == "https://liniss.com/sitemap.xml"
    assert isinstance(get_connector(plan), StructuredConnector)


@pytest.mark.unit
def test_ladder_falls_through_failed_rungs():
    """Brand has woo AND ldjson; woo already failed → structured is chosen; both failed → attention."""
    woo_failed = PlanAttempt(
        composition="t0×woo_api×platform_json×per_item", failed_at=NOW, reason="calibration"
    )
    c = cap(woo_api=True, ldjson_product=True, sitemap_url="https://x.com/sitemap.xml")
    plan = compose_plan(c, tried=[woo_failed], now=NOW)
    assert plan.composition == "t0×sitemap×structured_data×per_item"

    both = [
        woo_failed,
        PlanAttempt(
            composition="t0×sitemap×structured_data×per_item", failed_at=NOW, reason="calibration"
        ),
    ]
    assert compose_plan(c, tried=both, now=NOW).status == "needs_attention"


@pytest.mark.unit
def test_no_browser_rungs_without_opt_in():
    """HTTP-only runs must never produce a T2 plan they can't execute."""
    c = cap(
        platform="shopify",
        challenged=True,
        transport=TransportLevel.T2,
        sitemap_url="https://gm.com/sitemap.xml",
    )
    assert compose_plan(c, now=NOW).status == "needs_attention"


@pytest.mark.unit
def test_browser_opt_in_composes_t2_plan():
    c = cap(
        platform="shopify",
        challenged=True,
        transport=TransportLevel.T2,
        sitemap_url="https://gm.com/sitemap.xml",
    )
    plan = compose_plan(c, now=NOW, browser=True)
    assert plan.status == "ready" and plan.transport == TransportLevel.T2
    assert plan.composition == "t2×bulk_json×platform_json×per_item"


@pytest.mark.unit
def test_browser_falls_through_to_structured_when_bulk_tried():
    c = cap(challenged=True, transport=TransportLevel.T2, sitemap_url="https://vw.com/sitemap.xml")
    tried = [
        PlanAttempt(composition="t2×bulk_json×platform_json×per_item", failed_at=NOW, reason="x")
    ]
    plan = compose_plan(c, tried=tried, now=NOW, browser=True)
    assert plan.composition == "t2×sitemap×structured_data×per_item"


@pytest.mark.unit
def test_replan_does_not_repeat_a_failed_composition():
    """Re-entry carries memory (spec §4.3b): a failed t0×bulk_json attempt is not retried."""
    failed = PlanAttempt(
        composition="t0×bulk_json×platform_json×per_item",
        failed_at=NOW,
        reason="calibration failed",
    )
    plan = compose_plan(cap(platform="shopify", bulk_json=True), tried=[failed], now=NOW)
    assert plan.status == "needs_attention"
    assert plan.tried == [failed]


@pytest.mark.unit
def test_browser_bulk_rung_requires_evidence_not_a_platform_guess():
    """Live bug (theoutnet, 2026-08-30): the homepage carried a stray 'shopify' marketing
    pixel, so the planner guessed Shopify and burned a run on a 404 products.json.
    A browser bulk rung is only justified when HTTP was actually blocked."""
    unchallenged = cap(
        platform="shopify",  # false positive from a third-party script
        challenged=False,
        bulk_json=False,  # a true negative: the endpoint answered 404, not a challenge
        transport=TransportLevel.T0,
        sitemap_url="https://www.theoutnet.com/sitemap.xml",
    )
    plan = compose_plan(unchallenged, now=NOW, browser=True)
    assert plan.composition == "t2×sitemap×structured_data×per_item"


@pytest.mark.unit
def test_browser_bulk_rung_kept_for_genuinely_challenged_shopify():
    challenged = cap(
        platform="shopify", challenged=True, bulk_json=False, transport=TransportLevel.T2
    )
    plan = compose_plan(challenged, now=NOW, browser=True)
    assert plan.composition == "t2×bulk_json×platform_json×per_item"
