"""The gate, the analyst's answer, and the tick — hermetic, with a scripted model."""

from datetime import datetime, timezone

import httpx
import pytest

from backend.archive.domain.brand import Brand, DiscoveryChannel, FetchChannel, TransportLevel
from backend.archive.learn import gate
from backend.archive.learn.analyst import Analysis, analyse
from backend.archive.learn.dossier import DossierStore
from backend.archive.learn.loop import Loop, gaps_from_fill, recipe_plan
from backend.archive.learn.recipes import Discover, Fetch, LaneRecipe
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import DirectoryObjectStore
from backend.archive.transport import HttpxTransport

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

SITEMAP = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    + "".join(f"<url><loc>https://x.com/products/p{i}</loc></url>" for i in range(6))
    + "</urlset>"
)


def product_json(i: int) -> dict:
    return {
        "product": {
            "title": f"Item {i}",
            "variants": [{"price": "10.00", "available": True}],
            "images": [{"src": f"https://x/{i}.jpg"}],
        }
    }


def recipe() -> LaneRecipe:
    return LaneRecipe(
        id="test-recipe",
        signature="custom·closed·flat·none·none·none",
        description="sitemap then per-handle json",
        discover=Discover(kind="sitemap", url="https://{domain}/sitemap.xml", prefix="/products/"),
        fetch=Fetch(
            kind="json",
            url_template="{url}.json",
            root="product",
            fields={
                "product_title": "title",
                "price": "variants[*].price",
                "images": "images[*].src",
                "in_stock": "variants[0].available",
            },
            currency="USD",
        ),
    )


def routes(domain: str = "x.com", broken: bool = False) -> dict:
    out = {"/sitemap.xml": httpx.Response(200, text=SITEMAP.replace("x.com", domain))}
    for i in range(6):
        out[f"/products/p{i}.json"] = (
            httpx.Response(500) if broken else httpx.Response(200, json=product_json(i))
        )
    return out


def transport(table: dict) -> HttpxTransport:
    return HttpxTransport(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: table.get(r.url.path, httpx.Response(404)))
        )
    )


BRAND = Brand(domain="x.com", homepage_url="https://x.com")


# --- gate ----------------------------------------------------------------------------


@pytest.mark.unit
def test_the_gate_replays_then_reads_live_then_asks_the_neighbours():
    pages = {
        "https://x.com/sitemap.xml": SITEMAP,
        **{
            f"https://x.com/products/p{i}.json": httpx.Response(200, json=product_json(i)).text
            for i in range(6)
        },
    }
    result = gate.prove(
        recipe(),
        BRAND,
        transport(routes()),
        pages=pages,
        neighbour_brands=[Brand(domain="y.com", homepage_url="https://y.com")],
        transport_factory=lambda: transport(routes("y.com")),
    )
    assert result.passed and [s["step"] for s in result.steps] == ["replay", "live", "neighbours"]
    assert result.scope == "signature"
    assert result.products == 6 and result.verdict in ("full", "partial")


@pytest.mark.unit
def test_the_gate_stops_at_the_first_proof_that_fails():
    result = gate.prove(recipe(), BRAND, transport(routes(broken=True)), pages={})
    assert not result.passed
    assert result.steps[0]["passed"] is None  # nothing to replay
    assert result.steps[1]["step"] == "live" and result.steps[1]["passed"] is False


@pytest.mark.unit
def test_a_neighbour_the_recipe_cannot_read_keeps_it_a_lane_for_its_brand():
    result = gate.prove(
        recipe(),
        BRAND,
        transport(routes()),
        pages={},
        neighbour_brands=[Brand(domain="z.com", homepage_url="https://z.com")],
        transport_factory=lambda: transport(routes("z.com", broken=True)),
    )
    assert result.passed and result.scope == "brand"
    assert result.steps[-1]["step"] == "neighbours" and result.steps[-1]["passed"] is False


@pytest.mark.unit
def test_the_baseline_notices_a_drop(tmp_path):
    b = gate.Baseline(DirectoryObjectStore(tmp_path))
    b.record(
        "x.com",
        "full",
        {"product_title": 1.0, "price": 1.0, "in_stock": 1.0, "all_images": 1.0},
        "t0×a×b×c",
    )
    assert (
        b.regressed(
            "x.com",
            "full",
            {"product_title": 1.0, "price": 1.0, "in_stock": 1.0, "all_images": 0.98},
        )
        is None
    )
    assert b.regressed("x.com", "partial", {}) == "verdict full → partial"
    assert "core fill" in (
        b.regressed(
            "x.com",
            "full",
            {"product_title": 1.0, "price": 0.5, "in_stock": 1.0, "all_images": 1.0},
        )
        or ""
    )


# --- analyst -------------------------------------------------------------------------


class ScriptedModel:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def propose(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        return self.answer


def proposal(kind="recipe"):
    return {
        "signature": {
            "platform": "custom",
            "feed": "per-product",
            "sitemap": "flat",
            "page": "none",
            "defence": "none",
            "locale": "none",
        },
        "wall": "unreadable",
        "reasoning": "The sitemap lists /products/<handle>; each handle answers .json with a product object.",
        "confidence": 0.9,
        "lane": {
            "kind": kind,
            "recipe": {
                "description": "sitemap then per-handle json",
                "discover": recipe().discover.model_dump(),
                "fetch": recipe().fetch.model_dump(),
            }
            if kind == "recipe"
            else None,
            "code": {
                "summary": "a connector",
                "files": [{"path": "backend/archive/connectors/x.py", "content": "# x\n"}],
                "test": {"path": "tests/unit/archive/test_x.py", "content": "def test_x(): pass\n"},
            }
            if kind == "code"
            else None,
            "why_not_cheaper": "the feed is closed",
        },
        "gaps": [{"field": "size_info", "state": "absent", "why": "no sizes anywhere on the page"}],
        "learning": "x.com: the sitemap lists handles and each answers .json.",
    }


@pytest.mark.unit
def test_the_analyst_returns_a_proposal_and_records_its_cost(tmp_path):
    ds = DossierStore(DirectoryObjectStore(tmp_path))
    d = ds.open("x.com")
    model = ScriptedModel(proposal())
    a = analyse("brand", d, {"https://x.com/": "<html>home</html>"}, [], [], client=model)
    assert a.status == "proposed" and a.proposal["lane"]["kind"] == "recipe"
    assert "PAGE https://x.com/" in model.prompts[0] and "BRAND: x.com" in model.prompts[0]
    bad = analyse("brand", d, {}, [], [], client=ScriptedModel({}))
    assert bad.status == "failed"


# --- the loop --------------------------------------------------------------------------


@pytest.fixture()
def world(tmp_path):
    store = DirectoryObjectStore(tmp_path / "store")
    catalog = Catalog(store)
    catalog.upsert_brand(BRAND)
    brands = tmp_path / "brands.yml"
    brands.write_text(
        'brands:\n  - {domain: x.com, homepage_url: "https://x.com", display_name: "X", size: small}\n'
    )
    return store, catalog, brands


@pytest.mark.unit
def test_an_analysis_that_passes_the_gate_lands_a_recipe_and_a_plan(world, monkeypatch):
    store, catalog, brands = world
    monkeypatch.setenv("ARCHIVE_BUDGET_FLOOR_USD", "5")
    loop = Loop(
        store,
        catalog,
        brands_path=brands,
        analyst=ScriptedModel(proposal()),
        transport_factory=lambda level: transport(routes()),
        log=lambda *a: None,
        clock=lambda: T0,
    )
    ds = loop.dossiers
    ds.open("x.com", name="X")
    ds.rung("x.com", "t0", "ok_thin")
    ds.set_signature("x.com", "custom·closed·flat·none·none·none")
    a = loop.analyse("x.com")
    assert a.status == "landed", a.gate
    plan = catalog.load_plan("x.com")
    assert (
        plan.discovery == DiscoveryChannel.RECIPE
        and plan.fetch == FetchChannel.RECIPES
        and plan.recipe["id"].endswith(a.id)
    )
    d = ds.load("x.com")
    assert d.rules and d.rules[0].kind == "recipe"
    assert d.gaps["size_info"]["state"] == "absent"
    assert d.best_lane().verdict in ("full", "partial") and d.best_lane().products == 6
    assert loop._recipes()[0].learned_from == "x.com"
    assert loop.baseline.get("x.com")["composition"] == plan.composition
    # the learning went to the notebook
    assert b"x.com: the sitemap lists handles" in store.get("learn/learnings.jsonl")[0]


@pytest.mark.unit
def test_an_analysis_that_fails_the_gate_is_rejected_and_lands_nothing(world, monkeypatch):
    store, catalog, brands = world
    monkeypatch.setenv("ARCHIVE_BUDGET_FLOOR_USD", "5")
    loop = Loop(
        store,
        catalog,
        brands_path=brands,
        analyst=ScriptedModel(proposal()),
        transport_factory=lambda level: transport(routes(broken=True)),
        log=lambda *a: None,
        clock=lambda: T0,
    )
    loop.dossiers.open("x.com")
    a = loop.analyse("x.com")
    assert a.status == "rejected" and a.gate["passed"] is False
    assert catalog.load_plan("x.com") is None and loop._recipes() == []


@pytest.mark.unit
def test_a_code_proposal_is_filed_for_a_person_when_the_worker_cannot_push(
    world, monkeypatch, tmp_path
):
    store, catalog, brands = world
    monkeypatch.setenv("ARCHIVE_BUDGET_FLOOR_USD", "5")
    loop = Loop(
        store,
        catalog,
        brands_path=brands,
        analyst=ScriptedModel(proposal("code")),
        transport_factory=lambda level: transport(routes()),
        log=lambda *a: None,
        clock=lambda: T0,
    )
    loop.dossiers.open("x.com")
    a = loop.analyse("x.com")
    assert a.status == "proposed" and a.gate["passed"] is None
    filed = loop.proposals()
    assert (
        filed[0]["id"] == a.id and filed[0]["files"][0]["path"] == "backend/archive/connectors/x.py"
    )
    written = loop.apply_code(a.id, tmp_path / "tree")
    assert (tmp_path / "tree" / "backend/archive/connectors/x.py").read_text() == "# x\n"
    assert len(written) == 2


@pytest.mark.unit
def test_a_tick_onboards_classifies_and_writes_the_map_and_the_budget(world, monkeypatch):
    store, catalog, brands = world
    monkeypatch.setenv("ARCHIVE_BUDGET_FLOOR_USD", "5")
    monkeypatch.delenv("ARCHIVE_PROXY_URL", raising=False)
    loop = Loop(
        store,
        catalog,
        brands_path=brands,
        analyst=None,
        transport_factory=lambda level: transport(routes()),
        log=lambda *a: None,
        clock=lambda: T0,
    )

    # The sweep is the probe up the ladder; scripted so no network is touched.
    from backend.archive.access.outcome import Outcome
    from backend.archive.access.probe import AccessResult
    from backend.archive.domain.brand import Capability

    cap = Capability(
        domain="x.com",
        transport=TransportLevel.T0,
        evidence={"products_json": "404-closed", "homepage": "200"},
    )

    def fake_sweep(domains, strategies, **kw):
        return [
            AccessResult(
                domain=domains[0],
                strategy="httpx",
                outcome=Outcome.OK_THIN,
                seconds=0.1,
                requests=4,
                statuses=[200, 404, 200],
                capability=cap,
            )
        ]

    monkeypatch.setattr("backend.archive.learn.loop.sweep", fake_sweep)
    summary = loop.tick()
    assert summary["onboarded"] == ["x.com"]
    d = loop.dossiers.load("x.com")
    assert d.onboarding.finished_at is not None
    steps = {s.name: s.status for s in d.onboarding.steps}
    assert (
        steps["probe"] == "done"
        and steps["signature"] == "done"
        and steps["first-read"] == "skipped"
    )
    assert d.rung_outcomes() == {"t0": "ok_thin"}
    assert d.wall["type"] == "unreadable" and d.wall["action"] == "analyse"
    # no model: the action is recorded as wanted, not taken
    assert any(a["did"].startswith("analysis wanted") for a in summary["actions"])
    smap = store.get("control/signatures.json")
    assert smap and b"x.com" in smap[0]
    assert loop.budget.summary()["brands"] == 1
    assert loop.status()["last"]["onboarded"] == ["x.com"]


@pytest.mark.unit
def test_a_recipe_plan_carries_the_recipe_and_gaps_read_the_fill():
    plan = recipe_plan("x.com", recipe(), TransportLevel.T2)
    assert (
        plan.transport == TransportLevel.T1
        and plan.recipe["id"] == "test-recipe"
        and plan.currency == "USD"
    )
    gaps = gaps_from_fill({"product_title": 1.0, "price": 0.0})
    assert gaps["product_title"]["state"] == "read"
    assert gaps["price"]["state"] == "unread", "a guaranteed field blank is ours"
    assert gaps["size_info"]["state"] == "unsought", "a variant field blank is worth a look"
    assert gaps["additional_code_1"]["state"] == "absent", "a barcode blank is not a wall"


@pytest.mark.unit
def test_an_analysis_object_round_trips_through_the_dossier(tmp_path):
    ds = DossierStore(DirectoryObjectStore(tmp_path))
    a = Analysis(id="a1", at=T0.isoformat(), kind="brand", reasoning="r", proposal={"x": 1})
    ds.analysis("x.com", a)
    ds.analysis("x.com", a.model_copy(update={"status": "landed"}))
    d = ds.load("x.com")
    assert len(d.analyses) == 1 and d.analyses[0].status == "landed"
    assert [e.kind for e in d.events] == ["opened", "analysis"]
