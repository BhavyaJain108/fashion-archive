import pytest

from backend.archive.domain.brand import (
    Capability,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    PlanAttempt,
    ScrapePlan,
    TransportLevel,
)
from backend.archive.domain.product import WATCHED_FIELDS, ProductRecord, ProductRef


@pytest.mark.unit
def test_scrape_plan_composition_string():
    plan = ScrapePlan(
        domain="kuurth.com",
        transport=TransportLevel.T0,
        discovery=DiscoveryChannel.BULK_JSON,
        fetch=FetchChannel.PLATFORM_JSON,
        change_signal=ChangeSignal.PER_ITEM,
        status="ready",
        fingerprinted_at="2026-08-27T00:00:00+00:00",
    )
    assert plan.composition == "t0×bulk_json×platform_json×per_item"
    assert plan.tried == [] and plan.stale is False


@pytest.mark.unit
def test_plan_round_trips_through_json():
    """Plans are persisted as JSON in SQLite — serialization must be lossless."""
    plan = ScrapePlan(
        domain="x.com",
        transport=TransportLevel.T4,
        discovery=DiscoveryChannel.BULK_JSON,
        fetch=FetchChannel.PLATFORM_JSON,
        change_signal=ChangeSignal.NONE,
        status="skip_gated",
        tried=[
            PlanAttempt(
                composition="t0×bulk_json×platform_json×per_item",
                failed_at="2026-08-27T00:00:00+00:00",
                reason="challenged",
            )
        ],
        fingerprinted_at="2026-08-27T00:00:00+00:00",
    )
    assert ScrapePlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.unit
def test_product_record_defaults_and_watched_fields():
    rec = ProductRecord(itemurl="https://kuurth.com/products/x", product_title="X")
    assert rec.size_info is None and rec.all_images is None and rec.raw == {}
    assert WATCHED_FIELDS == ("price", "full_price", "in_stock", "size_availability")


@pytest.mark.unit
def test_pack_helpers_build_the_aligned_e0005_strings():
    from backend.archive.domain.product import pack_categories, pack_images, pack_sizes

    packed = pack_sizes(
        [
            {"size": "S", "available": True, "count": 3},
            {"size": "M", "available": False, "count": 0},
        ]
    )
    assert packed["size_info"] == "S, M"
    assert packed["size_availability"] == "in_stock, out_of_stock"  # aligned 1:1
    assert packed["size_stock_counts"] == "3, 0"
    assert pack_sizes([])["size_info"] is None

    imgs = pack_images(["a.jpg", "b.jpg"])
    assert imgs["main_image_url"] == "a.jpg" and imgs["all_images"] == '["a.jpg", "b.jpg"]'

    cats = pack_categories(["Women", "Tops", "Shirts"])
    assert cats == {"category1": "Women", "category2": "Tops", "category3": "Shirts"}


@pytest.mark.unit
def test_capability_and_ref():
    cap = Capability(
        domain="kuurth.com",
        platform="shopify",
        transport=TransportLevel.T0,
        bulk_json=True,
        sitemap_url="https://kuurth.com/sitemap.xml",
        password_gated=False,
        challenged=False,
    )
    assert cap.evidence == {}
    assert ProductRef(url="https://kuurth.com/products/x").change_hint is None


@pytest.mark.unit
def test_one_measure_answers_two_different_questions():
    """"Do we have an answer" and "could there be more" are not the same question, and
    conflating them called 15 brands broken for photographing their stock as they chose."""
    from backend.archive.domain.product import (
        ProductRecord,
        completeness,
        is_complete,
        is_worth_chasing,
    )

    empty = ProductRecord(itemurl="https://x.test/p", product_title="Tee")
    assert completeness(empty, "color_info") == 0
    assert completeness(empty, "all_images") == 0
    assert is_complete(empty, "all_images") is False
    assert is_worth_chasing(empty, "all_images") is True

    one = empty.model_copy(update={"all_images": '["https://cdn.x/a.jpg"]'})
    assert completeness(one, "all_images") == 1
    # a shop with one photograph has answered the question ...
    assert is_complete(one, "all_images") is True
    # ... but it is still worth one look for a gallery the channel never mentioned
    assert is_worth_chasing(one, "all_images") is True

    many = empty.model_copy(
        update={"all_images": '["https://cdn.x/a.jpg", "https://cdn.x/b.jpg"]'}
    )
    assert completeness(many, "all_images") == 2
    assert is_complete(many, "all_images") is True
    assert is_worth_chasing(many, "all_images") is False

    # a scalar is complete as soon as it has any value
    colour = empty.model_copy(update={"color_info": "Black"})
    assert is_complete(colour, "color_info") is True

    # it reads a stored row as readily as a record
    assert completeness({"all_images": '["a", "b", "c"]'}, "all_images") == 3
