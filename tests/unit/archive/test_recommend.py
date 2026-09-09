from typing import Any, cast

import pytest

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.recommend import recommend
from backend.archive.score import score
from backend.archive.store.catalog import Catalog


def rec(n, **kw) -> ProductRecord:
    base = dict(
        itemurl=f"https://kuurth.com/products/{n}",
        product_title=f"Tee {n}",
        price=40.0,
        in_stock=True,
        main_image_url=f"https://cdn.x/{n}.jpg",
        all_images=f'["https://cdn.x/{n}.jpg", "https://cdn.x/{n}b.jpg"]',
    )
    base.update(kw)
    return ProductRecord(**cast(Any, base))


@pytest.fixture()
def cat(tmp_path):
    c = Catalog(tmp_path / "c.db")
    c.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    return c


def store(cat, records, **card_kw):
    run = cat.open_run("kuurth.com", "full")
    for r in records:
        cat.record_product("kuurth.com", run, r, None)
    from backend.archive.domain.run import Coverage

    cat.finalize_run(
        run,
        0,
        Coverage(
            extracted=len(records), channel_counts={}, coverage_pct=1.0, field_fill={}, verdict="ok"
        ),
    )
    cat.save_scorecard(run, "kuurth.com", score(records, **card_kw))
    return run


@pytest.mark.unit
def test_a_failed_gate_outranks_everything_else(cat):
    run = store(cat, [rec(i, price=None if i == 0 else 40.0) for i in range(25)])
    cat.record_evidence("kuurth.com", run, [("price", "channel", 25, 24)])
    top = recommend(cat, "kuurth.com")[0]
    assert top[0] == 1 and "price" in top[1]


@pytest.mark.unit
def test_a_field_holding_the_wrong_thing_is_reported_before_empty_ones(cat):
    """A wrong value is worse than a blank, because it is believed."""
    store(cat, [rec(i, color_info=f"Look number {i}") for i in range(25)])
    findings = recommend(cat, "kuurth.com")
    assert any(f[0] == 2 and "color_info" in f[1] for f in findings)


@pytest.mark.unit
def test_unsearched_fields_are_separated_from_dead_ends(cat):
    run = store(cat, [rec(i) for i in range(25)])
    # the model was handed a page and asked for material; it found nothing
    cat.record_evidence("kuurth.com", run, [("material_info", "page_llm", 3, 0)])
    findings = recommend(cat, "kuurth.com")
    dead = [f for f in findings if f[0] == 5]
    unsearched = [f for f in findings if f[0] == 4]
    assert dead and "material_info" in dead[0][2]
    assert unsearched and "material_info" not in unsearched[0][2]


@pytest.mark.unit
def test_a_brand_costing_too_much_per_product_is_flagged(cat):
    store(cat, [rec(i) for i in range(25)], cost_usd=5.0)
    assert any(f[0] == 6 for f in recommend(cat, "kuurth.com"))


@pytest.mark.unit
def test_a_brand_with_nothing_stored_says_so(cat):
    assert recommend(cat, "kuurth.com")[0][1] == "nothing stored"


@pytest.mark.unit
def test_a_rule_that_only_worked_on_its_own_page_is_flagged(cat):
    """wiacollections learned regex (\\d+%PES) — polyester only — beside a general one."""
    from backend.archive.domain.recipe import Recipe, RecipeBook

    store(cat, [rec(i, material_info="85%PES") for i in range(25)])
    cat.save_recipe_book(
        RecipeBook(
            domain="kuurth.com",
            learned_at="2026-09-09T00:00:00+00:00",
            recipes=[
                Recipe(field="material_info", kind="regex", expression=r"(\d+%PES)", hits=2),
                Recipe(
                    field="material_info",
                    kind="regex",
                    expression=r"(\d{1,3}%[A-Z]{2,3})",
                    hits=98,
                ),
            ],
        )
    )
    narrow = [f for f in recommend(cat, "kuurth.com") if "fires on" in f[1]]
    assert narrow and "PES" in narrow[0][2]


@pytest.mark.unit
def test_cost_is_judged_per_brand_not_per_product(cat):
    """A shop with 200 products should not cost more than one with 20 once its rules
    are learned, so the number that matters is what the brand cost."""
    store(cat, [rec(i) for i in range(200)], cost_usd=0.60)
    assert not [f for f in recommend(cat, "kuurth.com") if f[0] == 6]
    store(cat, [rec(i) for i in range(20)], cost_usd=4.00)
    assert [f for f in recommend(cat, "kuurth.com") if f[0] == 6]


@pytest.mark.unit
def test_a_field_that_stopped_working_outranks_everything(cat):
    """Clearing wiacollections' rules lost its description rule with them, and the
    aggregate barely moved."""
    store(cat, [rec(i, description="A tee") for i in range(25)])
    store(cat, [rec(i) for i in range(25)])
    top = recommend(cat, "kuurth.com")[0]
    assert top[0] == 1 and "description fell from 100% to 0%" in top[1]


@pytest.mark.unit
def test_a_gate_that_used_to_pass_and_now_fails_is_reported(cat):
    store(cat, [rec(i) for i in range(25)])
    store(cat, [rec(i, price=None) for i in range(25)])
    findings = recommend(cat, "kuurth.com")
    assert any("failed a gate the last one passed" in f[1] for f in findings)


@pytest.mark.unit
def test_a_first_run_has_nothing_to_regress_against(cat):
    store(cat, [rec(i) for i in range(25)])
    assert not [f for f in recommend(cat, "kuurth.com") if "fell from" in f[1]]
