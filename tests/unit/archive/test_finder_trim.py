"""What the finder shows the model, and what it must never lose.

The three *_product_page.html fixtures are synthetic: built to the proportions of a
Shopify (Dawn) page, a WooCommerce/Elementor page and a Next.js storefront — their
scripts, style blocks, icon SVGs, data-* blobs, mega-menus and srcsets — because no
captured page lives in the repo and the tests fetch nothing. The ratios are asserted
here so a change to the trimmer that quietly sends more is a failing test."""

import re
from pathlib import Path

import pytest

from backend.archive.finder_llm import _MAX_HTML, learn_recipes, prepare_page, trim_page

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = sorted(FIXTURES.glob("*_product_page.html"))
# What the finder sent before the trimmer: scripts/styles/svg/noscript out, then 220k.
_OLD = re.compile(r"<(script|style|svg|noscript)\b.*?</\1>", re.S | re.I)


def old_payload(html: str) -> str:
    return _OLD.sub(" ", html)[:220_000]


@pytest.mark.unit
@pytest.mark.parametrize("page", PAGES, ids=[p.stem for p in PAGES])
def test_each_fixture_is_at_most_half_and_under_the_cap(page):
    html = page.read_text()
    before, after = len(old_payload(html)), len(prepare_page(html))
    assert after <= _MAX_HTML
    assert after <= 0.55 * before, f"{page.name}: {after:,} of {before:,} = {after / before:.2f}"


@pytest.mark.unit
@pytest.mark.parametrize("page", PAGES, ids=[p.stem for p in PAGES])
def test_what_a_rule_points_at_survives(page):
    sent = prepare_page(page.read_text())
    assert "application/ld+json" in sent
    assert 'property="og:image"' in sent  # a meta rule for main_image_url is common
    assert "srcset" in sent
    # the sizes, on every platform's own markup
    assert any(s in sent for s in ('name="Size"', "EU 39", 'data-size="EU 39"'))
    # and what no rule reads is gone
    for noise in ("<svg", "<!--", " style=", " onclick=", "<noscript", "trekkie", "__NEXT_DATA__"):
        assert noise not in sent, noise
    for m in re.finditer(r"<script\b[^>]*>", sent):
        assert "ld+json" in m.group(0), m.group(0)


@pytest.mark.unit
def test_trim_keeps_json_ld_in_place_and_drops_the_rest():
    html = """<html><head><!-- theme 12 -->
    <link rel="stylesheet" href="a.css"><link rel="canonical" href="https://x.com/p/a">
    <script type="application/ld+json">{"@type":"Product","name":"Derby"}</script>
    <script>var tracking = "noise";</script><style>.x{}</style></head>
    <body><svg><path d="M0 0"/></svg><noscript><img src="n.jpg"></noscript>
    <div   class="col"   style="color:red" onclick="go()">Oxblood</div></body></html>"""
    out = trim_page(html)
    assert '<script type="application/ld+json">{"@type":"Product","name":"Derby"}</script>' in out
    assert out.index("ld+json") < out.index("Oxblood")  # where it was, not appended
    assert 'rel="canonical"' in out and "a.css" not in out
    for gone in ("theme 12", "tracking", ".x{}", "<svg", "<noscript", "n.jpg", "style=", "onclick"):
        assert gone not in out
    assert '<div class="col">Oxblood</div>' in out  # whitespace collapsed, attrs intact


@pytest.mark.unit
def test_long_data_attributes_stay_only_when_they_are_about_the_product():
    layout = (
        '{"_animation":"fadeIn","_margin":{"top":0},"motion_fx":"yes","padding":' + "0" * 200 + "}"
    )
    variations = (
        '[{"attributes":{"attribute_pa_size":"39"},"is_in_stock":true,' + '"x":0,' * 40 + "}]"
    )
    html = (
        f"<div data-settings='{layout}' data-id=\"7\" data-product_variations='{variations}' "
        f'data-blob="{"z" * 300}" data-hero="{"a" * 200},https://cdn.x/hero.jpg">'
    )
    out = trim_page(html)
    assert "data-settings" not in out and "data-blob" not in out  # long, about layout
    assert 'data-id="7"' in out  # short
    assert "data-product_variations" in out  # long, but the size table
    assert "data-hero" in out  # long, but carries an image URL


@pytest.mark.unit
def test_srcset_is_cut_to_its_first_two_candidates_and_sizes_is_dropped():
    html = (
        '<img src="a.jpg" sizes="(min-width: 990px) 50vw, 100vw" '
        'srcset="https://cdn/a.jpg?w=240 240w, https://cdn/a.jpg?w=480 480w, '
        'https://cdn/a.jpg?w=960 960w, https://cdn/a.jpg?w=1920 1920w">'
    )
    out = trim_page(html)
    assert 'srcset="https://cdn/a.jpg?w=240 240w, https://cdn/a.jpg?w=480 480w"' in out
    assert "960w" not in out and "sizes=" not in out
    assert trim_page('<img srcset="a.jpg 1x, b.jpg 2x">') == '<img srcset="a.jpg 1x, b.jpg 2x">'


@pytest.mark.unit
def test_the_product_region_is_preferred_when_the_page_marks_one():
    body = "<p>the product</p>" * 400
    html = (
        '<html><head><title>T</title><meta property="og:image" content="https://x/1.jpg">'
        '<script type="application/ld+json">{"@type":"Product"}</script></head>'
        "<body><header><nav>" + "<a href='/c'>menu</a>" * 100 + "</nav></header>"
        f'<main id="MainContent"><div class="pdp">{body}</div></main>'
        "<footer>" + "<a href='/f'>foot</a>" * 100 + "</footer></body></html>"
    )
    sent = prepare_page(html)
    assert sent.startswith("<title>T</title> <meta")
    assert "ld+json" in sent and "<main" in sent and "the product" in sent
    assert "menu" not in sent and "foot" not in sent


@pytest.mark.unit
def test_a_page_without_a_region_or_with_an_empty_shell_is_sent_whole():
    plain = "<html><body><div class='a'>" + "<span>sizes</span>" * 50 + "</div></body></html>"
    assert prepare_page(plain) == trim_page(plain)
    shell = (
        "<html><body><header>" + "<a href='/c'>menu</a>" * 100 + "</header>"
        '<main id="__next"></main>' + "<p>rendered later</p>" * 50 + "</body></html>"
    )
    assert "menu" in prepare_page(shell)  # an empty <main> is an app shell, not the product


@pytest.mark.unit
def test_region_by_itemtype_and_by_class_and_the_cap():
    product = "<li class='s'>EU 39</li>" * 300
    by_type = (
        "<body><nav>" + "<a>x</a>" * 50 + "</nav>"
        f'<div itemscope itemtype="https://schema.org/Product"><ul>{product}</ul></div></body>'
    )
    assert "<nav>" not in prepare_page(by_type) and "EU 39" in prepare_page(by_type)
    by_class = (
        "<body><nav>" + "<a>x</a>" * 50 + "</nav>"
        f'<section class="page product-single grid"><ul>{product}</ul></section></body>'
    )
    assert "<nav>" not in prepare_page(by_class)
    assert len(prepare_page(by_class, cap=500)) == 500


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.prompt = ""

    def propose(self, prompt):
        self.prompt = prompt
        return self.payload


@pytest.mark.unit
def test_rules_are_verified_on_the_page_as_fetched_not_on_what_the_model_saw():
    """The model never sees the <noscript> image or the header, but a rule that points
    there holds on the real page, and the real page is what every later product is
    read with — so it is kept."""
    html = (
        '<html><body><header><span class="brand-colour">Oxblood</span></header>'
        '<main><div class="p">' + "<i>x</i>" * 1500 + "</div>"
        '<noscript><img class="hero" src="https://cdn/hero.jpg"></noscript></main></body></html>'
    )
    rules = [
        {
            "field": "color_info",
            "kind": "css_text",
            "expression": "header .brand-colour",
            "expected": "Oxblood",
        },
        {
            "field": "main_image_url",
            "kind": "css_attr",
            "expression": "noscript img.hero",
            "attribute": "src",
            "expected": "https://cdn/hero.jpg",
        },
    ]
    client = FakeLLM({"recipes": rules})
    book = learn_recipes(html, "u", "x.com", ["color_info", "main_image_url"], client=client)
    assert "Oxblood" not in client.prompt and "hero.jpg" not in client.prompt
    assert book.fields() == {"color_info", "main_image_url"}
    assert "replayed on the WHOLE page" in client.prompt
