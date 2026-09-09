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
    assert rec.price is None  # honest: OG carries no price


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
                    {"@type": "Offer", "price": 12743, "priceCurrency": "RUB", "sku": "W03WP-S",
                     "availability": "https://schema.org/InStock"},
                    {"@type": "Offer", "price": 13900, "priceCurrency": "RUB", "sku": "W03WP-L",
                     "availability": "https://schema.org/OutOfStock"},
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
