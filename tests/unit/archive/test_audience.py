"""Who a product is for, from the shop's own words — and the brand's, where it is silent."""

import pytest

from backend.archive import audience


def rec(**f):
    return {"itemurl": "https://b.com/products/x", "product_title": "A Thing", **f}


# --- what the product itself says -------------------------------------------------


@pytest.mark.unit
def test_the_shops_category_says_it():
    """bode files 146 products under MENS TROUSERS and 61 under WOMENS TROUSERS."""
    assert audience.of_product(rec(category1="MENS TROUSERS")) == "men"
    assert audience.of_product(rec(category1="WOMENS TROUSERS")) == "women"


@pytest.mark.unit
def test_a_tag_says_it():
    assert audience.of_product(rec(additional_tags="CREAM, WOMENS, P26")) == "women"


@pytest.mark.unit
def test_the_url_says_it():
    assert audience.of_product(rec(itemurl="https://b.com/products/womens-jeans-black")) == "women"


@pytest.mark.unit
def test_a_deeper_level_outranks_a_shallower_one():
    """Vivienne Westwood's path is Women > Accessories > Wallets; a men's wallet in the
    women's gifting section is still the shop's own ordering, so the leaf wins."""
    got = audience.of_product(rec(category1="Women", category2="Mens Gifts"))
    assert got == "men"


@pytest.mark.unit
def test_a_product_that_says_both_says_nothing():
    """ "Men's and women's sizing" is not evidence for either."""
    assert (
        audience.of_product(rec(product_title="Unisex Tee", additional_tags="MENS, WOMENS")) is None
    )


@pytest.mark.unit
def test_a_product_that_says_nothing_says_nothing():
    assert audience.of_product(rec(category1="SHIRTS")) is None


@pytest.mark.unit
def test_a_word_inside_another_word_is_not_a_signal():
    """ "Women" must not be found in "womenswear"'s neighbours — management, humen."""
    assert audience.of_product(rec(product_title="Management Coat")) is None
    assert audience.of_product(rec(product_title="Mangrove Shirt")) is None


@pytest.mark.unit
def test_kids_are_not_a_gender_here():
    """The page offers Women and Men. A children's hat is neither, and saying "men"
    because the word "boys" appeared would be worse than saying nothing."""
    assert audience.of_product(rec(category1="KIDS TRUCKER HAT")) is None


# --- what the brand says, where the product is silent -----------------------------


@pytest.mark.unit
def test_the_brands_audience_answers_a_silent_product():
    """meshki, tigermist and iamgia never say "women" — the whole shop is."""
    assert audience.of("meshki.us", rec(category1="DRESSES"), {"meshki.us": "women"}) == "women"


@pytest.mark.unit
def test_the_product_outranks_the_brand():
    """bode is a mixed shop. Its own MENS tag decides, not the roster's word."""
    got = audience.of("bode.com", rec(category1="MENS SHIRTS"), {"bode.com": "women"})
    assert got == "men"


@pytest.mark.unit
def test_a_brand_marked_all_leaves_its_silent_products_unplaced():
    """An eyewear or jewellery shop is genuinely for everyone; the page shows those
    products under both Women and Men rather than inventing a gender for them."""
    assert audience.of("gentlemonster.com", rec(), {"gentlemonster.com": "all"}) is None


@pytest.mark.unit
def test_an_unknown_brand_is_not_guessed_at():
    assert audience.of("new.com", rec(), {}) is None


# --- which sizes can actually be bought -------------------------------------------


@pytest.mark.unit
def test_only_the_sizes_in_stock_are_listed():
    got = audience.sizes_in_stock(
        {
            "size_info": "XS, S, M, L",
            "size_availability": "out_of_stock, in_stock, in_stock, out_of_stock",
        }
    )
    assert got == ["S", "M"]


@pytest.mark.unit
def test_a_size_the_shop_never_ruled_out_counts_as_available():
    """The shop lists the size and has said nothing about stock. Hiding it would be a
    guess; 45% of the catalogue carries no availability line at all."""
    assert audience.sizes_in_stock({"size_info": "S, M, L"}) == ["S", "M", "L"]


@pytest.mark.unit
def test_lists_of_different_lengths_are_not_paired():
    """size_info and size_availability are parallel lists, and a mismatch means one of
    them is not what we think. Offering every size is the safe read."""
    got = audience.sizes_in_stock({"size_info": "S, M, L", "size_availability": "in_stock"})
    assert got == ["S", "M", "L"]


@pytest.mark.unit
def test_a_product_with_no_sizes_has_none():
    assert audience.sizes_in_stock({}) == []


@pytest.mark.unit
def test_sizes_lose_the_shops_whitespace_and_its_spelling():
    """This column is for filtering, so one size is one value. The shop's own words
    stay in size_info, which is what the product page shows."""
    got = audience.sizes_in_stock(
        {"size_info": " one size ,UK 10", "size_availability": "in_stock, in_stock"}
    )
    assert got == ["OS", "UK 10"]


@pytest.mark.unit
def test_a_scraped_size_chart_is_not_a_set_of_sizes():
    """rosier.com's size_info is its size-chart table, on all 7,827 of its products.
    The real sizes are in there; "chart", "bust" and "cm" are not sizes."""
    got = audience.sizes_in_stock(
        {"size_info": "measure, how, chart, shoes, rings, XXS, XS, S, M, cm, in, bust, waist"}
    )
    assert got == ["XXS", "XS", "S", "M"]


@pytest.mark.unit
def test_a_size_written_as_a_pair_survives():
    assert audience.sizes_in_stock({"size_info": "XS/S, M/L"}) == ["XS/S", "M/L"]


@pytest.mark.unit
def test_regional_and_numeric_sizes_survive():
    got = audience.sizes_in_stock({"size_info": "UK 10, EU 38, 4, one size"})
    assert got == ["UK 10", "EU 38", "4", "OS"]


@pytest.mark.unit
def test_one_spelling_per_size():
    """A shop writing "medium" and another writing "M" must not become two chips."""
    assert audience.sizes_in_stock({"size_info": "small, medium, large"}) == ["S", "M", "L"]
    assert audience.sizes_in_stock({"size_info": "2XL, 3XL, one size"}) == ["XXL", "XXXL", "OS"]


@pytest.mark.unit
def test_folding_does_not_invent_duplicates():
    assert audience.sizes_in_stock({"size_info": "M, medium"}) == ["M"]


@pytest.mark.unit
def test_a_shop_for_everyone_is_not_a_shop_nobody_judged():
    """`all` is a judgement — the shop dresses everyone, so its products belong under
    both Women and Men. An empty audience is the absence of a judgement, and those
    products belong under neither: 8,135 unsexed psylos1 products under Women would
    make the filter useless rather than generous."""
    assert audience.ALL == "all"
    assert audience.UNJUDGED == ""
    # of() answers for neither, in both cases — the brand-level rule lives in the query,
    # which is what keeps a roster edit from needing a rewrite of every row
    assert audience.of("x.com", rec(), {"x.com": "all"}) is None
    assert audience.of("x.com", rec(), {"x.com": ""}) is None
