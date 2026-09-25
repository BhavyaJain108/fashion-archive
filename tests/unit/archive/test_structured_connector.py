import httpx
import pytest

from backend.archive.connectors.base import SkipProduct
from backend.archive.connectors.structured import StructuredConnector, parse_ldjson_product
from backend.archive.domain.product import ProductRef
from backend.archive.transport import HttpxTransport

FULL_LD = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Gale Coat",
 "sku":"LIN-GALE","description":"Wool coat.","brand":{"@type":"Brand","name":"Liniss"},
 "image":["https://liniss.com/i/gale-1.jpg","https://liniss.com/i/gale-2.jpg"],
 "offers":[
   {"@type":"Offer","name":"S","price":"420.00","priceCurrency":"USD","availability":"https://schema.org/InStock"},
   {"@type":"Offer","name":"M","price":"420.00","priceCurrency":"USD","availability":"https://schema.org/OutOfStock"}]}
</script></head><body>x</body></html>"""

GRAPH_LD = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"WebPage","name":"page"},
  {"@type":"Product","name":"Toe Derby","offers":{"@type":"Offer","price":250,
   "priceCurrency":"EUR","availability":"InStock"},
   "image":{"@type":"ImageObject","url":"https://psylos1.com/d.jpg"}}]}
</script></head><body>y</body></html>"""

OG_ONLY = """<html><head><title>t</title>
<meta property="og:title" content="Silver Ring"/>
<meta property="og:image" content="https://xsai.vision/r.jpg"/>
<meta property="product:price:amount" content="5990"/>
<meta property="product:price:currency" content="RUB"/>
</head><body>z</body></html>"""


def page_transport(html: str) -> HttpxTransport:
    return HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html)))
    )


@pytest.mark.unit
def test_full_ldjson_product_with_offer_sizes():
    rec = StructuredConnector("https://liniss.com/sitemap.xml").fetch(
        ProductRef(url="https://liniss.com/products/gale-coat"), page_transport(FULL_LD)
    )
    assert rec.product_title == "Gale Coat" and rec.product_code == "LIN-GALE"
    assert rec.brand == "Liniss" and rec.price == 420.0 and rec.currency == "USD"
    assert rec.in_stock is True  # at least one offer in stock
    assert rec.size_info == "S, M"
    assert rec.size_availability == "in_stock, out_of_stock"
    assert rec.all_images == (
        '["https://liniss.com/i/gale-1.jpg", "https://liniss.com/i/gale-2.jpg"]'
    )


@pytest.mark.unit
def test_graph_wrapped_product_and_image_object():
    rec = parse_ldjson_product(GRAPH_LD, "https://psylos1.com/en/products/toe-derby")
    assert rec.product_title == "Toe Derby" and rec.price == 250.0
    assert rec.main_image_url == "https://psylos1.com/d.jpg"
    assert rec.size_info is None  # single unnamed offer → no size claims


@pytest.mark.unit
def test_og_fallback_when_no_ldjson():
    rec = StructuredConnector("https://xsai.vision/sitemap.xml").fetch(
        ProductRef(url="https://xsai.vision/products/ring"), page_transport(OG_ONLY)
    )
    assert rec.product_title == "Silver Ring"
    assert rec.main_image_url == "https://xsai.vision/r.jpg"
    assert (rec.price, rec.currency) == (5990.0, "RUB")  # Open Graph's commerce tags


@pytest.mark.unit
def test_no_data_at_all_skips_product():
    with pytest.raises(SkipProduct):
        StructuredConnector("https://x.com/sitemap.xml").fetch(
            ProductRef(url="https://x.com/products/a"),
            page_transport("<html><head><title>t</title></head><body>nothing</body></html>"),
        )


HAS_VARIANT_LD = """<html><head>
<script type="application/ld+json">
{"@type":"ProductGroup","name":"Wide Pants","hasVariant":[
  {"@type":"Product","size":"S","offers":{"availability":"https://schema.org/InStock"}},
  {"@type":"Product","size":"M","offers":{"availability":"https://schema.org/OutOfStock"}}]}
</script></head><body>p</body></html>"""

SELECT_DOM = """<html><head>
<script type="application/ld+json">{"@type":"Product","name":"Gale Coat"}</script>
</head><body>
<select name="product-size"><option>Select size</option><option>XS</option>
<option>S</option><option>M</option></select></body></html>"""

DATA_ATTR_DOM = """<html><head>
<script type="application/ld+json">{"@type":"Product","name":"Derby"}</script>
</head><body>
<button data-size="40">40</button><button data-size="41">41</button>
<button data-size="42">42</button></body></html>"""


@pytest.mark.unit
def test_sizes_from_hasvariant_product_group():
    """schema.org's other size idiom — a ProductGroup with hasVariant."""
    rec = parse_ldjson_product(HAS_VARIANT_LD, "https://xsai.vision/products/wide-pants")
    assert rec.size_info == "S, M"
    assert rec.size_availability == "in_stock, out_of_stock"


@pytest.mark.unit
def test_sizes_fall_back_to_a_size_select_in_the_dom():
    """Live gap (psylos1/theoutnet 2026-08-30): JSON-LD carries no sizes at all."""
    rec = parse_ldjson_product(SELECT_DOM, "https://liniss.com/products/gale-coat")
    assert rec.size_info == "XS, S, M"  # placeholder option dropped


@pytest.mark.unit
def test_sizes_fall_back_to_data_size_attributes():
    rec = parse_ldjson_product(DATA_ATTR_DOM, "https://psylos1.com/products/derby")
    assert rec.size_info == "40, 41, 42"


@pytest.mark.unit
def test_dom_size_fallback_stays_quiet_when_it_finds_nothing_credible():
    """A wrong size list is worse than none — no guessing from arbitrary markup."""
    from backend.archive.connectors.structured import sizes_from_dom

    assert sizes_from_dom("<html><body><div>no sizes here</div></body></html>") == []
    assert sizes_from_dom('<button data-size="one-size">x</button>') == []  # single value


def _ldjson(node: dict) -> str:
    import json

    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(node)
        + "</script></head><body>x</body></html>"
    )


@pytest.mark.unit
def test_aggregate_offer_yields_price_currency_and_stock():
    """xsai.vision publishes one AggregateOffer wrapping the per-variant offers."""
    html = _ldjson(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "WIDE PANTS",
            "offers": {
                "@type": "AggregateOffer",
                "priceCurrency": "RUB",
                "lowPrice": 12743,
                "highPrice": 13900,
                "offers": [
                    {
                        "@type": "Offer",
                        "price": 12743,
                        "priceCurrency": "RUB",
                        "sku": "W03WP-S",
                        "availability": "https://schema.org/InStock",
                    },
                    {
                        "@type": "Offer",
                        "price": 13900,
                        "priceCurrency": "RUB",
                        "sku": "W03WP-L",
                        "availability": "https://schema.org/OutOfStock",
                    },
                ],
            },
        }
    )
    rec = parse_ldjson_product(html, "https://xsai.vision/products/wide-pants-13")
    assert rec.price == 12743.0
    assert rec.currency == "RUB"
    assert rec.in_stock is True


@pytest.mark.unit
def test_aggregate_offer_without_inner_offers_still_prices():
    html = _ldjson(
        {
            "@type": "Product",
            "name": "Tee",
            "offers": {"@type": "AggregateOffer", "lowPrice": "49.00", "priceCurrency": "EUR"},
        }
    )
    rec = parse_ldjson_product(html, "https://x.test/p/tee")
    assert rec.price == 49.0 and rec.currency == "EUR"


@pytest.mark.unit
def test_the_brands_sku_and_the_barcodes_go_to_different_fields():
    """E0005's product_code is the brand's own SKU; an mpn is a barcode-style code."""
    html = _ldjson(
        {
            "@type": "Product",
            "name": "Gale Coat",
            "sku": "LIN-GALE",
            "gtin13": "4901234567894",
            "mpn": "GALE-2026",
            "offers": {"price": "420.00", "priceCurrency": "USD"},
        }
    )
    rec = parse_ldjson_product(html, "https://liniss.com/products/gale")
    assert rec.product_code == "LIN-GALE"
    assert (rec.additional_code_1, rec.additional_code_1_type) == ("4901234567894", "GTIN13")
    assert (rec.additional_code_2, rec.additional_code_2_type) == ("GALE-2026", "MPN")


@pytest.mark.unit
def test_a_numeric_sku_is_kept_as_its_digits():
    """WIA Collections' JSON-LD prints "sku": 10442 — a number. The whole run died on
    it ('int' object has no attribute 'strip') and the brand was marked needs_attention
    for a template choice, not a fault of the site (2026-09-22)."""
    html = _ldjson(
        {
            "@type": "Product",
            "name": "Sable Dress",
            "sku": 10442,
            "offers": {"price": "180.00", "priceCurrency": "USD"},
        }
    )
    rec = parse_ldjson_product(html, "https://wiacollections.com/products/sable")
    assert rec.product_code == "10442" and rec.color_info is None


@pytest.mark.unit
def test_additional_properties_become_specifications():
    html = _ldjson(
        {
            "@type": "Product",
            "name": "Gale Coat",
            "additionalProperty": [
                {"name": "Fit", "value": "Oversized"},
                {"name": "Length", "value": "Midi"},
                {"name": "Empty", "value": ""},
            ],
            "keywords": ["outerwear", "wool"],
            "offers": {"price": "420.00"},
        }
    )
    rec = parse_ldjson_product(html, "https://liniss.com/products/gale")
    assert rec.specifications == "Fit: Oversized; Length: Midi"
    assert rec.additional_tags == "outerwear, wool"


@pytest.mark.unit
def test_the_priced_product_wins_over_the_style_it_belongs_to():
    """A page can publish the ProductGroup first — the style, with no price — and the
    Product actually being viewed second. Taking the first gave a title and nothing else."""
    from backend.archive.connectors.structured import _find_product_node

    html = """<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
      {"@type":"ProductGroup","name":"Zen","productGroupID":"15000387"},
      {"@type":"Product","name":"Jennie - Zen C1","image":["https://x/1.jpg"],
       "offers":{"@type":"Offer","price":"330","priceCurrency":"USD",
                 "availability":"https://schema.org/InStock"}}]}</script>"""
    node = _find_product_node(html)
    assert node["name"] == "Jennie - Zen C1"


@pytest.mark.unit
def test_a_lone_product_group_is_still_used_when_it_is_all_there_is():
    from backend.archive.connectors.structured import _find_product_node

    html = '<script type="application/ld+json">{"@type":"ProductGroup","name":"Zen"}</script>'
    assert _find_product_node(html)["name"] == "Zen"


# The JSON-LD block from https://www.entirestudios.com/product/adidas-x-entire-studios-ace-black
# as stored on 2026-09-23, cut to two of its sixteen variants and with the return policy
# and seller trimmed. The group states no offers; each variant states its own.
ENTIRE_PRODUCT_GROUP = """<html><head>
<script type="application/ld+json">{"@context": "https://schema.org/", "@type": "ProductGroup",
 "brand": {"@type": "Brand", "name": "Entire Studios"}, "name": "Ace Black",
 "description": "Regular fit Laces Leather and synthetic upper",
 "image": ["https://cdn.shopify.com/s/files/1/0111/8054/0000/files/entire-studios-ace-black.webp?v=1775503517"],
 "url": "https://www.entirestudios.com/product/adidas-x-entire-studios-ace-black",
 "variesBy": ["https://schema.org/size"],
 "hasVariant": [
  {"@type": "Product", "brand": {"@type": "Brand", "name": "Entire Studios"}, "gtin": "198321694357",
   "mpn": "KI57014-", "name": "Ace Black \\u2014 4.5", "size": "4.5",
   "offers": {"@type": "Offer", "availability": "https://schema.org/InStock",
              "itemCondition": "https://schema.org/NewCondition", "price": "220.00",
              "priceCurrency": "USD", "priceValidUntil": "2026-12-31",
              "url": "https://www.entirestudios.com/product/adidas-x-entire-studios-ace-black"}},
  {"@type": "Product", "brand": {"@type": "Brand", "name": "Entire Studios"}, "gtin": "198321694364",
   "mpn": "KI57014-", "name": "Ace Black \\u2014 5", "size": "5",
   "offers": {"@type": "Offer", "availability": "https://schema.org/OutOfStock",
              "itemCondition": "https://schema.org/NewCondition", "price": "220.00",
              "priceCurrency": "USD", "priceValidUntil": "2026-12-31",
              "url": "https://www.entirestudios.com/product/adidas-x-entire-studios-ace-black"}}
 ]}</script></head><body>x</body></html>"""


@pytest.mark.unit
def test_a_product_group_is_priced_from_its_variants_offers():
    """Entire Studios (2026-09-24): 384 of 1,377 pages publish a ProductGroup with no
    offers of its own, each hasVariant Product carrying the price, currency and stock
    flag. Reading only the group stored all 384 with price None, currency None,
    in_stock None."""
    rec = parse_ldjson_product(
        ENTIRE_PRODUCT_GROUP,
        "https://www.entirestudios.com/product/adidas-x-entire-studios-ace-black",
    )
    assert rec.product_title == "Ace Black"
    assert rec.price == 220.0
    assert rec.currency == "USD"
    assert rec.in_stock is True
    assert rec.size_info == "4.5, 5"
    assert rec.size_availability == "in_stock, out_of_stock"


@pytest.mark.unit
def test_a_group_listing_its_variants_offers_does_not_outrank_the_product_on_the_page():
    """Gentle Monster's guard, kept: the Product being viewed wins over the style it
    belongs to, even when that style now yields offers through its variants."""
    from backend.archive.connectors.structured import _find_product_node

    html = """<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
      {"@type":"ProductGroup","name":"Zen","hasVariant":[
        {"@type":"Product","name":"Jennie - Zen C2",
         "offers":{"@type":"Offer","price":"310","priceCurrency":"USD"}}]},
      {"@type":"Product","name":"Jennie - Zen C1","image":["https://x/1.jpg"],
       "offers":{"@type":"Offer","price":"330","priceCurrency":"USD",
                 "availability":"https://schema.org/InStock"}}]}</script>"""
    assert _find_product_node(html)["name"] == "Jennie - Zen C1"


SWATCHES = """
<a href="/x?size=XXS" data-tau-size-id="XXS" title="XXS (not available)"><span>XXS</span></a>
<a href="/x?size=S" data-tau-size-id="S" title="S "><span>S</span></a>
<a href="/x?size=M" data-tau-size-id="M" title="M "><span>M</span></a>
<a data-tau-size-id="{{id}}" title="template"></a>
"""


@pytest.mark.unit
def test_sizes_and_their_availability_are_read_from_swatches():
    from backend.archive.connectors.structured import sizes_from_swatches

    assert sizes_from_swatches(SWATCHES) == [
        {"size": "XXS", "available": False},
        {"size": "S", "available": True},
        {"size": "M", "available": True},
    ]


@pytest.mark.unit
def test_a_page_with_no_swatches_yields_no_sizes():
    from backend.archive.connectors.structured import sizes_from_swatches

    assert sizes_from_swatches("<p>no sizes here</p>") == []


def crumbs(*names):
    items = ",".join(
        f'{{"@type":"ListItem","position":{i},"name":"{n}"}}' for i, n in enumerate(names, 1)
    )
    return f'<script type="application/ld+json">{{"@type":"BreadcrumbList","itemListElement":[{items}]}}</script>'


@pytest.mark.unit
def test_the_category_path_is_the_breadcrumbs_without_the_root_or_the_product():
    from backend.archive.connectors.structured import categories_from_breadcrumbs

    html = crumbs("Home", "Women", "Clothing", "Skirts", "Scribble Check Skirt")
    assert categories_from_breadcrumbs(html, "Scribble Check Skirt") == [
        "Women",
        "Clothing",
        "Skirts",
    ]


@pytest.mark.unit
def test_a_truncated_last_crumb_is_still_recognised_as_the_product():
    from backend.archive.connectors.structured import categories_from_breadcrumbs

    html = crumbs("Homepage", "Jewelry", "Alhambra - Jewelry", "Magic Alhambra long neck")
    got = categories_from_breadcrumbs(html, "Magic Alhambra long necklace, 1 motif 18K gold")
    assert got == ["Jewelry", "Alhambra - Jewelry"]


@pytest.mark.unit
def test_a_shop_with_no_category_level_gets_no_invented_one():
    """XSAI's breadcrumbs are brand then product. There is no category to record."""
    from backend.archive.connectors.structured import categories_from_breadcrumbs

    assert categories_from_breadcrumbs(crumbs("XSAI", "WIDE PANTS"), "WIDE PANTS") == []


@pytest.mark.unit
def test_a_page_without_breadcrumbs_yields_nothing():
    from backend.archive.connectors.structured import categories_from_breadcrumbs

    assert categories_from_breadcrumbs("<p>nothing</p>", "x") == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("sku", "expected"),
    [
        ("1802002B-C00A1--RED", "RED"),
        ("1802002B-C00A1--LIME-GREEN", "LIME GREEN"),
        ("54030004W-L0098--PEARL-WHITE", "PEARL WHITE"),
        ("VCARPQZH00", None),  # no variant named
        ("1802002B-C00A1", None),  # a plain sku is not a colour
        ("ABC--C00A1", None),  # digits mean it is another sku segment, not a colour
        (None, None),
        (10442, None),  # WIA Collections prints its SKUs as numbers (2026-09-22)
    ],
)
def test_a_variant_sku_names_its_variant_after_the_double_dash(sku, expected):
    from backend.archive.connectors.structured import variant_from_sku

    assert variant_from_sku(sku) == expected


@pytest.mark.unit
def test_a_colour_the_page_states_outright_beats_the_sku():
    html = """<script type="application/ld+json">{"@type":"Product","name":"Zen",
      "sku":"15680--BLACK","color":"Clear Acetate",
      "offers":{"@type":"Offer","price":"330"}}</script>"""
    from backend.archive.connectors.structured import parse_ldjson_product

    assert parse_ldjson_product(html, "https://x/p").color_info == "Clear Acetate"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("RED", "RED"),
        ("PEARL WHITE", "PEARL WHITE"),
        ("BLACK PU GRAIN", "BLACK PU GRAIN"),
        ("SEX", None),  # a Vivienne Westwood print, not a colour
        ("PRIMAVERA CHERUBS", None),
        (None, None),
    ],
)
def test_only_a_variant_that_names_a_colour_becomes_one(variant, expected):
    from backend.archive.connectors.structured import color_from_variant

    assert color_from_variant(variant) == expected


@pytest.mark.unit
def test_a_variant_that_is_not_a_colour_is_still_recorded_as_a_variant():
    html = """<script type="application/ld+json">{"@type":"Product",
      "name":"Worlds End Swing Dress","sku":"3101000H-C006D--SEX",
      "offers":{"@type":"Offer","price":"975"}}</script>"""
    from backend.archive.connectors.structured import parse_ldjson_product

    rec = parse_ldjson_product(html, "https://x/p")
    assert rec.variant_info == "SEX"
    assert rec.color_info is None


@pytest.mark.unit
def test_a_page_with_only_a_title_is_not_a_product():
    # entirestudios.com/product/a-4-bomber-army: 200, og:title, "currently
    # unavailable", no price. A record with a name and no price is not kept — with or
    # without a photograph (the 2026-09-25 full run kept all 987 because they had one).
    html = '<html><head><meta property="og:title" content="A-4 Bomber Army"><meta property="og:image" content="https://cdn.sanity.io/x.jpg"></head><body>This product is currently unavailable.</body></html>'
    with pytest.raises(SkipProduct) as e:
        parse_ldjson_product(html, "https://www.entirestudios.com/products/a-4-bomber-army")
    assert "no product data" in str(e.value)
