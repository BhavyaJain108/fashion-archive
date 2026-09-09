import pytest

from backend.archive.validate import check_axes, check_brand, check_field


def rows(field: str, values: list) -> list[dict]:
    return [{"itemurl": f"https://x.test/{i}", field: v} for i, v in enumerate(values)]


@pytest.mark.unit
def test_a_single_label_shop_is_the_normal_case():
    assert check_brand(["STAUD"] * 40) is None


@pytest.mark.unit
def test_a_retailer_carrying_many_labels_is_also_fine():
    """The Outnet sells hundreds of unrelated labels — that is what its brand field is for."""
    assert check_brand(["Gucci", "Balmain", "Givenchy", "Brunello Cucinelli"] * 10) is None


@pytest.mark.unit
def test_campaign_names_in_the_brand_field_are_caught():
    """staud.clothing publishes 41 of these; they all begin with the shop's own name."""
    values = ["STAUD FALL 2026"] * 20 + ["STAUD SUMMER 2026 SALE"] * 20 + ["STAUD RESORT 2026"] * 10
    problem = check_brand(values)
    assert problem and "campaigns" in problem


@pytest.mark.unit
def test_skus_in_the_brand_field_are_caught():
    """www.thesupermade.com stores one code per product where the brand should be."""
    problem = check_brand([f"SP2202{i:04d}KT-US" for i in range(40)])
    assert problem and "identify products" in problem


@pytest.mark.unit
def test_a_classifying_field_that_never_repeats_is_mis_mapped():
    """A category that is unique per product is not a category."""
    unique = rows("category1", [f"Look {i}" for i in range(40)])
    assert check_field("category1", unique)
    shared = rows("category1", ["Denim", "Tops"] * 20)
    assert check_field("category1", shared) is None


@pytest.mark.unit
def test_an_identifying_field_that_repeats_is_mis_mapped():
    """One image URL across a whole catalogue is a placeholder, not the product."""
    same = rows("main_image_url", ["https://x.test/logo.png"] * 40)
    problem = check_field("main_image_url", same)
    assert problem and "share" in problem


@pytest.mark.unit
def test_a_price_of_zero_is_reported():
    assert check_field("price", rows("price", [0.0] + [10.0] * 39))


@pytest.mark.unit
def test_sizes_and_colours_drawn_from_one_vocabulary_mean_swapped_axes():
    swapped = [
        {"itemurl": "https://x.test/1", "size_info": "Black, Cream", "color_info": "Black, Cream"}
    ]
    assert check_axes(swapped)
    proper = [{"itemurl": "https://x.test/1", "size_info": "S, M, L", "color_info": "Black, Cream"}]
    assert check_axes(proper) is None


@pytest.mark.unit
def test_the_campaign_names_carry_the_shops_own_spelling_of_itself():
    from backend.archive.validate import brand_name_for

    campaigns = ["STAUD FALL 2026", "STAUD SUMMER 2026 SALE", "STAUD RESORT 2026"]
    assert brand_name_for("staud.clothing", campaigns) == "STAUD"
    assert brand_name_for("www.kuurth.com", ["Kuurth", "Kuurth Archive"]) == "Kuurth"


@pytest.mark.unit
def test_a_prefix_that_is_not_the_shops_name_is_not_used_as_one():
    from backend.archive.validate import brand_name_for

    skus = [f"SP2202{i:03d}KT-US" for i in range(20)]
    assert brand_name_for("www.thesupermade.com", skus) == "thesupermade"
    # a truncation of the domain is not the domain
    assert brand_name_for("hip3399.com", ["HIP", "HIP SALE"]) == "hip3399"


@pytest.mark.unit
def test_an_explicit_display_name_always_wins():
    from backend.archive.validate import brand_name_for

    assert (
        brand_name_for("staud.clothing", ["STAUD FALL 2026"], "STAUD Clothing") == "STAUD Clothing"
    )
