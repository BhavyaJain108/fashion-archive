import pytest

from backend.archive.domain.recipe import Recipe, RecipeBook
from backend.archive.finder import apply_recipes, verify_recipe

PAGE = """<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"Derby Shoes","color":"Silver",
 "material":"Calf leather","offers":{"price":"420.00"}}
</script></head><body>
  <div class="pdp">
    <ul class="size-list">
      <li class="sz">EU 39</li><li class="sz">EU 40</li><li class="sz sold">EU 41</li>
    </ul>
    <span class="colour-name">Oxblood</span>
    <div class="composition">100% wool, made in Italy</div>
    <button data-variant-size="S"></button><button data-variant-size="M"></button>
  </div>
</body></html>"""


@pytest.mark.unit
def test_css_all_text_collects_a_size_list():
    r = Recipe(field="size_info", kind="css_all_text", expression="ul.size-list li.sz")
    assert apply_recipes(PAGE, [r]) == {"size_info": "EU 39, EU 40, EU 41"}


@pytest.mark.unit
def test_css_all_attr_collects_sizes_from_attributes():
    r = Recipe(
        field="size_info",
        kind="css_all_attr",
        expression="button[data-variant-size]",
        attribute="data-variant-size",
    )
    assert apply_recipes(PAGE, [r]) == {"size_info": "S, M"}


@pytest.mark.unit
def test_css_text_and_regex_pull_single_values():
    colour = Recipe(field="color_info", kind="css_text", expression="span.colour-name")
    material = Recipe(field="material_info", kind="regex", expression=r'composition">([^<]+)<')
    got = apply_recipes(PAGE, [colour, material])
    assert got["color_info"] == "Oxblood"
    assert got["material_info"] == "100% wool, made in Italy"


@pytest.mark.unit
def test_json_ld_path_reads_the_product_node():
    r = Recipe(field="material_info", kind="json_ld_path", expression="material")
    assert apply_recipes(PAGE, [r]) == {"material_info": "Calf leather"}


@pytest.mark.unit
def test_a_rule_that_matches_nothing_is_simply_absent():
    r = Recipe(field="size_info", kind="css_text", expression=".does-not-exist")
    assert apply_recipes(PAGE, [r]) == {}


@pytest.mark.unit
def test_a_broken_rule_never_raises():
    """One bad selector must not take down a 7,000-product scrape."""
    bad = Recipe(field="size_info", kind="css_text", expression="[[[not a selector")
    ok = Recipe(field="color_info", kind="css_text", expression="span.colour-name")
    assert apply_recipes(PAGE, [bad, ok]) == {"color_info": "Oxblood"}


@pytest.mark.unit
def test_verify_keeps_a_rule_that_reproduces_the_predicted_value():
    r = Recipe(
        field="size_info",
        kind="css_all_text",
        expression="ul.size-list li.sz",
        expected="EU 39, EU 40, EU 41",
    )
    assert verify_recipe(r, PAGE) is True


@pytest.mark.unit
def test_verify_rejects_an_invented_selector():
    """The LLM claims a value; if replaying the rule does not produce it, the rule dies."""
    invented = Recipe(
        field="size_info",
        kind="css_text",
        expression="div.sizes-wrapper",
        expected="XS, S, M, L",
    )
    assert verify_recipe(invented, PAGE) is False


@pytest.mark.unit
def test_verify_rejects_a_rule_that_finds_the_wrong_thing():
    wrong = Recipe(
        field="color_info",
        kind="css_text",
        expression="div.composition",
        expected="Oxblood",
    )
    assert verify_recipe(wrong, PAGE) is False


@pytest.mark.unit
def test_recipe_book_round_trips_and_reports_its_fields():
    book = RecipeBook(
        domain="psylos1.com",
        learned_at="2026-08-30T00:00:00+00:00",
        recipes=[Recipe(field="size_info", kind="css_text", expression="a")],
    )
    assert RecipeBook.model_validate_json(book.model_dump_json()) == book
    assert book.fields() == {"size_info"}


@pytest.mark.unit
def test_interface_copy_is_not_a_value():
    from backend.archive.finder import is_plausible

    assert is_plausible("size_info", "S, M, L") is True
    assert is_plausible("size_info", "One Size") is True
    assert is_plausible("size_info", "Sold out") is False
    assert is_plausible("size_info", "SOLD OUT") is False
    assert is_plausible("color_info", "Add to cart") is False
    assert is_plausible("description", "") is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "S, M, L",
        "38, 39, 40, 41",
        "US 3.5 MEN / US 5 WOMEN=IT 35, US 4.5 MEN / US 6 WOMEN =IT 36",  # psylos1, real
        "One Size",
        "XS, S (2), M, L",  # xsai, real
    ],
)
def test_real_size_lists_fit_the_size_shape(value):
    from backend.archive.finder import is_plausible

    assert is_plausible("size_info", value) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "Sold out",  # theoutnet's learned rule read the sold-out badge
        "Polo, Crew Neck",  # psylos1: necklines, not sizes
        "Lavanda bikini set.",  # wiacollections: the short description
        "Free shipping on all orders over 100",
    ],
)
def test_text_that_is_not_a_size_list_is_rejected(value):
    from backend.archive.finder import is_plausible

    assert is_plausible("size_info", value) is False


@pytest.mark.unit
def test_availability_takes_stock_words_the_other_fields_reject():
    from backend.archive.finder import is_plausible

    assert is_plausible("size_availability", "In stock, Sold out, In stock") is True
    assert is_plausible("size_availability", "true, false") is True
    assert is_plausible("size_availability", "Lavanda bikini set.") is False
    assert is_plausible("color_info", "Sold out") is False


@pytest.mark.unit
def test_colour_and_material_shapes():
    from backend.archive.finder import is_plausible

    assert is_plausible("color_info", "Gray, Apricot, Coffee") is True
    assert is_plausible("color_info", "#2D2D2D, #8F847E") is True
    assert is_plausible("color_info", "A soft knit made in Italy from recycled wool.") is False
    assert is_plausible("material_info", "75% ХЛОПОК 25% ПОЛИАМИД") is True
    assert is_plausible("material_info", "100% cotton") is True
    assert (
        is_plausible(
            "material_info",
            "Elevate your wardrobe with this piece. Crafted in Italy, it is defined "
            "by a fluid drape and a relaxed shape that works day to night.",
        )
        is False
    )


@pytest.mark.unit
def test_a_value_that_is_really_the_title_is_rejected():
    """wiacollections learned a colour rule that returned the product's own title."""
    from backend.archive.finder import is_plausible

    context = {"product_title": "Lucky Pink Big White T-shirt", "description": None}
    assert is_plausible("color_info", "Pink heavyweight T-shirt", context) is False
    assert is_plausible("color_info", "Pink", context) is True  # a real colour still passes
    # a description is meant to read like the product
    assert is_plausible("description", "Lucky Pink Big White T-shirt in cotton", context) is True


@pytest.mark.unit
def test_product_code_shape():
    from backend.archive.finder import is_plausible

    assert is_plausible("product_code", "W03WP-S190-KH") is True
    assert is_plausible("product_code", "MSCDAR097C9447---") is True
    assert is_plausible("product_code", "This product is made to order. Ships in 2 weeks.") is False


@pytest.mark.unit
@pytest.mark.parametrize("value", ["XS/S, M/L", "MEDIUM, SMALL", "Small, Medium, Large"])
def test_sizes_written_as_words_or_pairs_are_still_sizes(value):
    """Real values from xsai.vision and wiacollections.com."""
    from backend.archive.finder import is_plausible

    assert is_plausible("size_info", value) is True


@pytest.mark.unit
def test_availability_must_be_stock_words_not_a_copy_of_the_sizes():
    """Every brand had learned an availability rule that just repeated the sizes."""
    from backend.archive.finder import is_plausible

    assert is_plausible("size_availability", "S, M, L, XL") is False


@pytest.mark.unit
def test_the_heading_above_a_value_is_not_the_value():
    """psylos1 learned a material rule that returned the accordion button's text."""
    from backend.archive.finder import is_plausible

    assert is_plausible("material_info", "Fabrics & Materials") is False
    assert is_plausible("material_info", "Composition and care") is False
    assert is_plausible("size_info", "Select size") is False
    assert is_plausible("color_info", "Colour") is False
    assert is_plausible("material_info", "Cotton") is True  # a real one-word material


@pytest.mark.unit
def test_an_image_field_must_hold_urls():
    from backend.archive.finder import is_plausible

    assert is_plausible("main_image_url", "https://cdn.shopify.com/x/a.jpg") is True
    assert is_plausible("all_images", "https://cdn.x/a.jpg, https://cdn.x/b.jpg") is True
    assert is_plausible("main_image_url", "Product photo") is False
    assert is_plausible("all_images", "img-1, img-2") is False


@pytest.mark.unit
def test_a_list_rule_may_be_verified_by_its_first_entries():
    """psylos1's gallery holds 18 URLs — ~1,800 characters the model would have to
    reproduce exactly, so it proposed nothing at all rather than risk a wrong rule."""
    from backend.archive.domain.recipe import Recipe
    from backend.archive.finder import verify_recipe

    html = (
        "<html><body><div class='mosaic'>"
        + "".join(f"<img src='https://cdn.x/{i}.jpg'>" for i in range(18))
        + "</div></body></html>"
    )
    first_two = Recipe(
        field="all_images",
        kind="css_all_attr",
        expression=".mosaic img",
        attribute="src",
        expected="https://cdn.x/0.jpg, https://cdn.x/1.jpg",
    )
    assert verify_recipe(first_two, html) is True

    # an invented selector still cannot pass: it matches nothing, so there is no prefix
    invented = first_two.model_copy(update={"expression": ".gallery-not-here img"})
    assert verify_recipe(invented, html) is False

    # a wrong first entry is still a wrong rule
    wrong = first_two.model_copy(update={"expected": "https://cdn.x/99.jpg"})
    assert verify_recipe(wrong, html) is False

    # single-value rules are unchanged: they must match in full
    single = Recipe(
        field="main_image_url", kind="css_attr", expression=".mosaic img",
        attribute="src", expected="https://cdn.x/0",
    )
    assert verify_recipe(single, html) is False


@pytest.mark.unit
def test_a_regex_with_no_pattern_in_it_is_a_memorised_value():
    """theoutnet learned material rules reading "Kaschmirmischung" — a value copied off
    one page, which then matched 1% of the catalogue."""
    from backend.archive.domain.recipe import Recipe
    from backend.archive.finder import verify_recipe

    html = "<html><body>Kaschmirmischung</body></html>"
    literal = Recipe(
        field="material_info", kind="regex",
        expression="Kaschmirmischung", expected="Kaschmirmischung",
    )
    assert verify_recipe(literal, html) is False

    real = Recipe(
        field="material_info", kind="regex",
        expression=r"([\w-]+mischung)", expected="Kaschmirmischung",
    )
    assert verify_recipe(real, html) is True
