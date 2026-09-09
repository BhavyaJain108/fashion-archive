import pytest

from backend.archive.domain.product import ProductRecord
from backend.archive.score import score


def rec(**kw) -> ProductRecord:
    base = dict(
        itemurl="https://x.test/p",
        product_title="Tee",
        price=40.0,
        in_stock=True,
        main_image_url="https://cdn.x/a.jpg",
        all_images='["https://cdn.x/a.jpg", "https://cdn.x/b.jpg"]',
    )
    base.update(kw)
    return ProductRecord(**base)


@pytest.mark.unit
def test_a_complete_run_passes_the_gate():
    card = score([rec(), rec()], seconds=10.0, cost_usd=0.5)
    assert card.required_ok is True
    assert card.required_gaps == {}
    assert card.products == 2
    assert card.images_per_product == 2.0
    assert card.seconds_per_product == 5.0
    assert card.cost_usd == 0.5


@pytest.mark.unit
def test_a_missing_price_fails_the_run_however_much_else_it_collected():
    """A shop cannot sell without one, so the blank is ours, not the brand's."""
    card = score([rec(), rec(price=None)])
    assert card.required_ok is False
    assert card.required_gaps == {"price": 0.5}


@pytest.mark.unit
def test_in_stock_false_is_a_value_not_a_gap():
    """False is falsy and still an answer: the shop told us it is sold out."""
    card = score([rec(in_stock=False)])
    assert card.required_ok is True


@pytest.mark.unit
def test_one_photograph_is_an_answer_and_no_photograph_is_not():
    """humanbynature publishes between 1 and 20 images per product and every count is
    the truth. The gate asks whether the shop showed us the garment."""
    one = score([rec(all_images='["https://cdn.x/a.jpg"]')])
    assert one.required_ok is True

    none = score([rec(all_images=None, main_image_url=None)])
    assert none.required_ok is False
    assert "all_images" in none.required_gaps
    assert none.products_without_image == 1


@pytest.mark.unit
def test_an_empty_run_scores_zero_and_fails():
    card = score([], seconds=30.0)
    assert card.products == 0 and card.required_ok is False
    assert card.seconds_per_product == 0.0


@pytest.mark.unit
def test_fields_filled_is_the_share_of_all_42():
    card = score([rec()])
    assert 0 < card.fields_filled < 1
    rich = score([rec(color_info="Black", material_info="Cotton", description="A tee")])
    assert rich.fields_filled > card.fields_filled


@pytest.mark.unit
def test_a_field_that_stopped_being_filled_is_a_regression():
    """Clearing wiacollections' rules lost its description rule with them: 98% to 0%,
    invisible in an aggregate that only moved two points."""
    from backend.archive.score import regressions

    before = score([rec(description="A tee") for _ in range(10)]).as_dict()
    after = score([rec() for _ in range(10)]).as_dict()
    lost = regressions(before, after)
    assert ("description", 1.0, 0.0) in lost


@pytest.mark.unit
def test_a_field_that_was_barely_filled_is_not_a_regression():
    """Losing a field that only ever worked on one product in ten is noise."""
    from backend.archive.score import regressions

    before = score([rec(description="A tee" if i == 0 else None) for i in range(10)]).as_dict()
    after = score([rec() for _ in range(10)]).as_dict()
    assert regressions(before, after) == []


@pytest.mark.unit
def test_a_small_movement_is_the_shop_not_us():
    from backend.archive.score import regressions

    before = score([rec(color_info="Black") for _ in range(20)]).as_dict()
    after = score([rec(color_info="Black" if i < 19 else None) for i in range(20)]).as_dict()
    assert regressions(before, after) == []
