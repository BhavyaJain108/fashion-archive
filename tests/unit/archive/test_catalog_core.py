import pytest

from backend.archive.domain.brand import (
    Brand,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    ScrapePlan,
    TransportLevel,
)
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import Catalog


def make_plan(domain="kuurth.com") -> ScrapePlan:
    return ScrapePlan(
        domain=domain,
        transport=TransportLevel.T0,
        discovery=DiscoveryChannel.BULK_JSON,
        fetch=FetchChannel.PLATFORM_JSON,
        change_signal=ChangeSignal.PER_ITEM,
        status="ready",
        fingerprinted_at="2026-08-27T00:00:00+00:00",
    )


@pytest.mark.unit
def test_brand_and_state_round_trip(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    assert cat.get_brand("kuurth.com").homepage_url == "https://kuurth.com"
    assert cat.get_brand_state("kuurth.com") == "new"
    cat.set_brand_state("kuurth.com", "active")
    assert cat.get_brand_state("kuurth.com") == "active"


@pytest.mark.unit
def test_plan_round_trip_and_upsert(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    cat.save_plan(make_plan())
    assert cat.load_plan("kuurth.com").status == "ready"
    stale = make_plan()
    stale.stale = True
    cat.save_plan(stale)  # upsert, not insert
    assert cat.load_plan("kuurth.com").stale is True


@pytest.mark.unit
def test_runs_are_append_only_and_crash_visible(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    run1 = cat.open_run("kuurth.com", "full")
    assert cat.latest_run("kuurth.com")["exit_status"] is None  # open run is visible immediately
    cov = Coverage(
        extracted=2,
        channel_counts={"bulk_json": 2},
        coverage_pct=1.0,
        field_fill={"product_title": 1.0},
        verdict="ok",
    )
    cat.finalize_run(run1, 0, cov)
    run2 = cat.open_run("kuurth.com", "delta")
    assert run2 != run1
    latest = cat.latest_run("kuurth.com")
    assert latest["id"] == run2 and latest["mode"] == "delta"


@pytest.mark.unit
def test_recipe_book_round_trip(tmp_path):
    from backend.archive.domain.recipe import Recipe, RecipeBook

    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="psylos1.com", homepage_url="https://psylos1.com"))
    assert cat.load_recipe_book("psylos1.com") is None
    book = RecipeBook(
        domain="psylos1.com",
        learned_at="2026-08-30T00:00:00+00:00",
        learned_from_url="https://psylos1.com/en/products/x",
        recipes=[Recipe(field="size_info", kind="css_all_text", expression="li.sz")],
    )
    cat.save_recipe_book(book)
    assert cat.load_recipe_book("psylos1.com") == book
