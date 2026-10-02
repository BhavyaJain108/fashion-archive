"""What 2026-10-02's audit of the live catalogue asked of the system, one test each:
line items never stored, every run saying where its products went, missed fields acted
on, the fleet's neighbours used as evidence, no recipe that loses products, and the
photographs counted per product, per brand and in bytes."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from backend.archive.domain.brand import (
    Brand,
    Capability,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    ScrapePlan,
    TransportLevel,
)
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.image_stats import (
    brand_totals,
    flagged,
    load_storage,
    measure_storage,
    product_line,
)
from backend.archive.learn import gate
from backend.archive.learn.dossier import Dossier, DossierStore, Lane, now_iso
from backend.archive.learn.loop import (
    Loop,
    _better,
    gaps_from_fill,
    neighbour_evidence,
    refresh_gaps,
    upgraded_gaps,
)
from backend.archive.learn.walls import Action, Wall, classify
from backend.archive.runner.cli import _lane_note
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import DirectoryObjectStore

from .test_learn_loop import BRAND, recipe, routes, transport


def _lane(
    products: int,
    verdict: str = "ok",
    composition: str = "t0×bulk_json×platform_json×per_item",
    fill=None,
) -> Lane:
    return Lane(
        at=now_iso(),
        composition=composition,
        verdict=verdict,
        products=products,
        fill=fill or {"product_title": 1.0, "price": 1.0, "in_stock": 1.0, "all_images": 1.0},
    )


def _dossier(
    domain: str = "x.com", signature: str = "shopify·open·flat·none·none·none", **kw
) -> Dossier:
    return Dossier(
        domain=domain, signature=signature, created_at=now_iso(), updated_at=now_iso(), **kw
    )


# --- a run: line items declined, and where every discovered product went -------------


@pytest.mark.unit
def test_a_run_declines_a_gift_card_on_any_lane_and_says_where_its_products_went(tmp_path):
    from backend.archive.planner import compose_plan
    from backend.archive.runner.run import run_brand

    brand = Brand(domain="shop.com", homepage_url="https://shop.com")
    cap = Capability(
        domain="shop.com",
        platform="custom",
        transport=TransportLevel.T0,
        ldjson_product=True,
        sitemap_url="https://shop.com/sitemap.xml",
    )
    titles = {
        "a": "Silk Slip Dress",
        "b": "Shop Digital Gift Card",
        "c": "Blouse &amp;amp; Skirt Set",
    }

    class Conn:
        kind = "structured"

        def discover(self, b, t):
            return [
                ProductRef(url=f"https://shop.com/products/{k}", change_hint=k) for k in titles
            ] + [ProductRef(url="https://shop.com/collections/new", change_hint="n")]

        def fetch(self, r, t):
            from backend.archive.connectors.base import NotAProduct

            key = r.url.rsplit("/", 1)[-1]
            if key not in titles:
                raise NotAProduct(f"no product data on {r.url} (no JSON-LD Product, no price)")
            return ProductRecord(
                itemurl=r.url, product_title=titles[key], price=10.0, in_stock=True
            )

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
    )
    stored = {r["product_title"] for r in cat.current_products("shop.com")}
    assert stored == {"Silk Slip Dress", "Blouse & Skirt Set"}  # entities read as text
    run = cat.latest_run("shop.com")
    b = run["breakdown"]
    assert (b["discovered"], b["stored"], b["not_products"]) == (4, 2, 2)
    assert any("gift" in k.lower() for k in b["why"]) and any("JSON-LD" in k for k in b["why"])
    # The URL is taken out of the reason, so many category pages count as one kind.
    assert not any("https://" in k for k in b["why"])
    assert _lane_note(run).startswith("stored 2 of 4 discovered: 2 not products")


# --- gaps: from every run, kept where the model decided ------------------------------


@pytest.mark.unit
def test_gaps_come_from_the_run_and_a_partly_missing_guaranteed_field_is_ours():
    gaps = gaps_from_fill(
        {"product_title": 1.0, "price": 0.98, "all_images": 0.9, "category1": 0.2, "size_info": 0.9}
    )
    assert gaps["price"]["state"] == "read"
    assert gaps["all_images"]["state"] == "unread" and "10%" in gaps["all_images"]["why"]
    assert gaps["category1"]["state"] == "unsought"
    assert gaps["size_info"]["state"] == "read"


@pytest.mark.unit
def test_a_field_the_model_called_absent_stays_absent_until_a_run_reads_it():
    held = {"material_info": {"state": "absent", "why": "the shop never says", "source": "model"}}
    assert refresh_gaps(held, {"material_info": 0.0})["material_info"]["source"] == "model"
    assert refresh_gaps(held, {"material_info": 0.8})["material_info"]["state"] == "read"


@pytest.mark.unit
def test_an_ok_read_with_a_guaranteed_field_blank_on_some_products_is_a_field_gap():
    d = _dossier(
        lanes=[_lane(695)],
        gaps={"all_images": {"state": "unread", "why": "blank on 2% of products"}},
    )
    v = classify(d)
    assert (v.wall, v.action) == (Wall.FIELD_GAP, Action.ANALYSE) and "all_images" in v.why
    d.gaps = {"all_images": {"state": "read"}, "category1": {"state": "unsought"}}
    assert classify(d).wall == Wall.OPEN  # unsought alone is not a wall


@pytest.mark.unit
def test_a_field_most_of_a_platforms_shops_read_is_unread_where_one_leaves_it_blank():
    def shop(domain, cat):
        fill = {"product_title": 1.0, "category1": cat}
        return _dossier(
            domain,
            lanes=[_lane(50, fill=fill)],
            gaps={"category1": {"state": "unsought" if not cat else "read"}},
        )

    fleet = [shop("a.com", 1.0), shop("b.com", 0.9), shop("c.com", 0.8), shop("blank.com", 0.0)]
    evidence = neighbour_evidence(fleet)
    up = upgraded_gaps(fleet[-1], evidence)
    assert (
        up["category1"]["state"] == "unread"
        and up["category1"]["why"] == "3 of 3 other shopify shops publish it"
    )
    # Two neighbours are not enough to call it the platform's.
    assert upgraded_gaps(fleet[-1], neighbour_evidence(fleet[1:])) == {}


# --- recipes: never land one that loses products, and back one out that did ---------


@pytest.mark.unit
def test_a_recipe_that_reads_fewer_products_than_the_lane_it_replaces_does_not_land():
    d = _dossier(lanes=[_lane(37, "partial")])
    fewer = gate.GateResult(
        True, products=13, verdict="full", fill={"product_title": 1.0, "categories": 1.0}
    )
    same = gate.GateResult(
        True,
        products=37,
        verdict="full",
        fill={
            "product_title": 1.0,
            "price": 1.0,
            "in_stock": 1.0,
            "all_images": 1.0,
            "categories": 1.0,
        },
    )
    assert not _better(d, fewer)
    assert _better(d, same)


@pytest.mark.unit
def test_the_gate_expects_what_a_run_would_store_not_only_what_it_finds():
    table = routes()
    for i in (1, 3, 5):
        table[f"/products/p{i}.json"] = httpx.Response(404)
    step = gate.live(recipe(), BRAND, transport(table), sample=6)
    assert step["found"] == 6 and step["read"] == 3 and step["expected"] == 3


@pytest.mark.unit
def test_a_landed_recipe_that_reads_far_fewer_products_is_backed_out(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    cat = Catalog(store)
    plan = ScrapePlan(
        domain="vereya.com",
        transport=TransportLevel.T0,
        discovery=DiscoveryChannel.RECIPE,
        fetch=FetchChannel.RECIPES,
        change_signal=ChangeSignal.PER_ITEM,
        fingerprinted_at=datetime.now(timezone.utc).isoformat(),
        status="ready",
    )
    cat.save_plan(plan)
    ds = DossierStore(store)
    ds.open("vereya.com")
    ds.lane("vereya.com", "t0×bulk_json×platform_json×per_item", "partial", 37)
    ds.lane("vereya.com", "t0×recipe×recipes×per_item", "ok", 11)
    loop = Loop(store, cat, analyst=None, log=lambda *a: None)
    said = loop._undo_regression(ds.load("vereya.com"))
    assert said and "11" in said and "37" in said
    assert cat.load_plan("vereya.com").stale is True
    assert loop._undo_regression(ds.load("vereya.com")) is None  # once


# --- photographs: per product, per brand, in bytes ------------------------------------


@pytest.mark.unit
def test_a_product_says_what_it_names_keeps_gave_up_on_and_waits_for():
    record = {
        "itemurl": "u",
        "product_title": "Dress",
        "all_images": json.dumps(["a", "b", "c", "d"]),
    }
    rows = [
        {"url": "a", "stored_url": "https://img/a"},
        {"url": "b", "stored_url": None, "misses": 3},
        {"url": "c", "stored_url": None, "misses": 1},
    ]
    line = product_line(record, rows, give_up_after=3)
    assert (line["named"], line["kept"], line["given_up"], line["waiting"]) == (4, 1, 1, 2)


@pytest.mark.unit
def test_a_brand_counts_its_products_by_how_much_of_them_is_held_and_flags_the_empty():
    lines = [
        {"itemurl": "1", "title": "kept", "named": 2, "kept": 2, "given_up": 0, "waiting": 0},
        {"itemurl": "2", "title": "half", "named": 2, "kept": 1, "given_up": 0, "waiting": 1},
        {"itemurl": "3", "title": "waiting", "named": 3, "kept": 0, "given_up": 0, "waiting": 3},
        {"itemurl": "4", "title": "dead", "named": 1, "kept": 0, "given_up": 1, "waiting": 0},
        {"itemurl": "5", "title": "none", "named": 0, "kept": 0, "given_up": 0, "waiting": 0},
    ]
    t = brand_totals("x.com", lines)
    assert (t["complete"], t["partial"], t["none_kept"], t["none_named"]) == (1, 1, 2, 1)
    why = {f["title"]: f["why"] for f in flagged(lines)}
    assert set(why) == {"waiting", "dead", "none"}
    assert why["none"] == "the shop names no photograph"
    assert why["dead"].startswith("every photograph")


@pytest.mark.unit
def test_the_catalogue_reports_photographs_per_brand_and_the_bucket_weighs_them(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="x.com", homepage_url="https://x.com"))
    run = cat.open_run("x.com", "full")
    for i, images in enumerate((["https://cdn/a.jpg"], [])):
        cat.record_product(
            "x.com",
            run,
            ProductRecord(
                itemurl=f"https://x.com/p{i}", product_title=f"P{i}", all_images=json.dumps(images)
            ),
            None,
        )
    cat.record_image(
        "x.com", "https://x.com/p0", "https://cdn/a.jpg", "abc", stored_url="https://img/abc.jpg"
    )
    from backend.archive.domain.run import Coverage

    cat.finalize_run(run, 0, Coverage(extracted=2, coverage_pct=1.0, verdict="ok"))
    (stats,) = cat.image_stats("x.com")
    assert (stats["products"], stats["complete"], stats["none_named"], stats["kept"]) == (
        2,
        1,
        1,
        1,
    )
    assert [f["itemurl"] for f in flagged(cat.photograph_lines("x.com"))] == ["https://x.com/p1"]

    (tmp_path / "archive" / "x.com" / "ab").mkdir(parents=True)
    (tmp_path / "archive" / "x.com" / "ab" / "abc.jpg").write_bytes(b"x" * 1000)
    row = measure_storage(store)
    assert row["objects"] == 1 and row["by_brand"]["x.com"]["bytes"] == 1000
    assert load_storage(store)["bytes"] == 1000


@pytest.mark.unit
def test_a_size_guide_and_layout_attributes_are_not_sizes():
    """Rosier's measuring widget and picker: 4,263 products read "measure, how, chart,
    bust, waist…" and then "medium, 2, 4" as their sizes."""
    from backend.archive.connectors.structured import sizes_from_dom

    page = (
        '<div data-mr-size-guide-v1-item="measure"></div><div data-mr-size-guide-v1-item="chart"></div>'
        '<div data-mr-size-guide-v1-view-button="bust"></div>'
        '<picker data-size="medium" data-variant-size="2" data-page-size="4"></picker>'
    )
    assert sizes_from_dom(page) == []
    swatches = '<a data-tau-size-id="S" title="S"></a><a data-tau-size-id="M" title="M (not available)"></a>'
    assert [s["size"] for s in sizes_from_dom(page + swatches)] == ["S", "M"]


@pytest.mark.unit
def test_a_photograph_is_asked_for_with_its_product_page_as_referer(tmp_path):
    """Van Cleef's image server answers 403 to a bare request and the photograph to one
    that names the page it is on, as every browser does."""
    from backend.archive.images import ImageStore
    from backend.archive.transport import HttpxTransport
    from backend.storage.images import LocalImageStore

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64

    def answer(request: httpx.Request) -> httpx.Response:
        if request.headers.get("referer") != "https://vca.com/p/ring":
            return httpx.Response(403, text="denied")
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    transport = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(answer)))
    cat = Catalog(DirectoryObjectStore(tmp_path))
    images = ImageStore(LocalImageStore(root=tmp_path / "img", api_base="http://api.test"))
    assert images.archive_one(
        transport, cat, "https://vca.com/p/ring", "vca.com", "https://vca.com/i/1.png"
    )
    assert cat.stored_image_urls("vca.com", "https://vca.com/p/ring") == {"https://vca.com/i/1.png"}
