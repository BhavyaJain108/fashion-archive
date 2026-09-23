"""Filtering a catalogue by what the brand offers."""

import pytest

from backend.archive import facets

ROWS = [
    {
        "itemurl": "u1",
        "color_info": "Black, Off White",
        "size_info": "S, M, L",
        "size_availability": "in_stock, out_of_stock, in_stock",
        "material_info": "100% wool",
        "category1": "Women",
        "category2": "Coats",
        "additional_tags": "New in",
        "in_stock": True,
        "price": 320.0,
        "full_price": 400.0,
    },
    {
        "itemurl": "u2",
        "color_info": "black",
        "size_info": "M, L, XL",
        "size_availability": "in_stock, in_stock, out_of_stock",
        "material_info": "Cotton",
        "category1": "Women",
        "category2": "Tops",
        "in_stock": True,
        "price": 80.0,
    },
    {
        "itemurl": "u3",
        "color_info": "Red",
        "size_info": "38, 40, 42",
        "size_availability": "out_of_stock, out_of_stock, in_stock",
        "category1": "Men",
        "in_stock": False,
        "price": 150.0,
    },
    {"itemurl": "u4", "in_stock": None},  # a product that says nothing
]


@pytest.mark.unit
def test_values_are_the_brands_words_grouped_without_regard_to_case():
    c = facets.counts(ROWS, {})
    colours = {i["value"]: i["count"] for i in c["colour"]}
    assert colours == {"Black": 2, "Off White": 1, "Red": 1}  # "black" joins "Black"
    assert [i["value"] for i in c["size"]] == ["S", "M", "L", "XL", "38", "40", "42"]
    assert {i["value"]: i["count"] for i in c["category"]} == {
        "Women": 2,
        "Women / Coats": 1,
        "Women / Tops": 1,
        "Men": 1,
    }
    assert {i["value"]: i["count"] for i in c["stock"]} == {"in stock": 2, "out of stock": 1}
    assert [i["value"] for i in c["sale"]] == ["on sale"] and c["sale"][0]["count"] == 1
    assert facets.price_range(ROWS) == {"min": 80.0, "max": 320.0}


@pytest.mark.unit
def test_any_within_a_facet_all_across_facets_and_counts_follow_the_other_choices():
    chosen = {"colour": {"black"}, "size": {"L"}}
    left = facets.apply(ROWS, chosen)
    assert [r["itemurl"] for r in left] == ["u1", "u2"]
    c = facets.counts(ROWS, chosen)
    # The colour chips are counted under the size choice only, so "Red" (no L) is gone
    # and "Black" still shows what clicking it would leave.
    assert {i["value"]: i["count"] for i in c["colour"]} == {"Black": 2, "Off White": 1}
    assert next(i for i in c["colour"] if i["value"] == "Black")["selected"] is True
    # Size chips are counted under the colour choice: the numeric sizes are gone.
    assert [i["value"] for i in c["size"]] == ["S", "M", "L", "XL"]
    assert facets.apply(ROWS, {"colour": {"Red", "Off White"}}) == [ROWS[0], ROWS[2]]


@pytest.mark.unit
def test_a_chosen_size_can_be_required_in_stock():
    assert [r["itemurl"] for r in facets.apply(ROWS, {"size": {"M"}})] == ["u1", "u2"]
    assert [r["itemurl"] for r in facets.apply(ROWS, {"size": {"M"}}, sized_in_stock=True)] == [
        "u2"
    ]
    m = next(i for i in facets.counts(ROWS, {})["size"] if i["value"] == "M")
    assert m["count"] == 2 and m["in_stock"] == 1
    assert facets.size_in_stock({"size_info": "S, M", "size_availability": "in_stock"}, "M") is None


@pytest.mark.unit
def test_price_bounds_cut_without_touching_the_chip_counts():
    assert [r["itemurl"] for r in facets.within_price(ROWS, 100, None)] == ["u1", "u3"]
    assert [r["itemurl"] for r in facets.within_price(ROWS, None, 100)] == ["u2"]
    assert facets.within_price(ROWS, None, None) is ROWS
