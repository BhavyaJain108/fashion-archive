"""A lane as data: today's fixes, expressed as recipes, read the same products."""

import json

import httpx
import pytest

from backend.archive.connectors.base import ChannelBlocked, NotAProduct
from backend.archive.domain.brand import Brand
from backend.archive.learn.recipes import (
    Discover,
    Fetch,
    LaneRecipe,
    RecipeConnector,
    path_get,
    render,
)
from backend.archive.transport import HttpxTransport


def transport(routes: dict[str, httpx.Response]) -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        return routes.get(key, routes.get(request.url.path, httpx.Response(404)))

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.unit
def test_paths_walk_dots_indexes_and_fan_out():
    data = {
        "result": {
            "pageContext": {
                "retailers": [{"draws": [{"slug": "a"}, {"slug": "b"}]}, {"draws": [{"slug": "c"}]}]
            }
        }
    }
    assert path_get(data, "result.pageContext.retailers[0].draws[1].slug") == "b"
    assert path_get(data, "result.pageContext.retailers[*].draws") == [
        {"slug": "a"},
        {"slug": "b"},
        {"slug": "c"},
    ]
    assert path_get(data, "result.pageContext.retailers[*].draws[*].slug") == ["a", "b", "c"]
    assert path_get(data, "result.nothing.here") is None
    assert path_get({"a": [1, 2]}, "a[-1]") == 2
    props = {
        "additionalProperty": [{"name": "Tags", "value": ["x", "y"]}, {"name": "Size", "value": 8}]
    }
    assert path_get(props, "additionalProperty[name=Size].value") == 8
    assert path_get(props, "additionalProperty[name=Tags].value[*]") == ["x", "y"]
    assert path_get(props, "additionalProperty[name=Colour].value") is None
    assert (
        render(
            "https://{domain}/page-data/{country}/{slug}/page-data.json",
            domain="x",
            country="us",
            slug="ana",
            missing=None,
        )
        == "https://x/page-data/us/ana/page-data.json"
    )


@pytest.mark.unit
def test_a_recipe_says_what_is_wrong_with_it():
    r = LaneRecipe(
        id="r",
        signature="s",
        description="d",
        discover=Discover(kind="json_list"),
        fetch=Fetch(kind="json", fields={"nope": "x"}),
    )
    problems = r.check()
    assert any("items path" in p for p in problems)
    assert any("product_title" in p for p in problems)
    assert any("unknown field" in p for p in problems)
    with pytest.raises(ValueError):
        RecipeConnector(r)


LUAR_INDEX = {
    "result": {
        "pageContext": {
            "retailers": [
                {
                    "draws": [
                        {"slug": "mini-ana", "country": "US", "end": "2026-09-01"},
                        {"slug": "bag", "country": "GB"},
                    ]
                }
            ]
        }
    }
}
LUAR_DRAW = {
    "result": {
        "pageContext": {
            "draw": {
                "product": "Mini Ana",
                "price": 185,
                "currency": "USD",
                "sku": "LUAR1",
                "description": "A bag.",
                "gallery": [{"url": "https://cdn/a.jpg"}],
                "isPublished": True,
            }
        }
    }
}


@pytest.mark.unit
def test_luar_as_a_recipe_json_list_then_json():
    recipe = LaneRecipe(
        id="gatsby-runfair",
        signature="gatsby·page-data·none·none·none·none",
        description="EQL launch pages: draws in the index page-data, one page-data per draw",
        discover=Discover(
            kind="json_list",
            url="https://{domain}/page-data/index/page-data.json",
            items="result.pageContext.retailers[*].draws",
            url_template="https://{domain}/{country}/{slug}",
            filter={"country": "US"},
        ),
        fetch=Fetch(
            kind="json",
            url_template="https://{domain}/page-data/{country}/{slug}/page-data.json",
            root="result.pageContext.draw",
            fields={
                "product_title": "product",
                "price": "price",
                "currency": "currency",
                "product_code": "sku",
                "description": "description",
                "images": "gallery[*].url",
                "in_stock": "isPublished",
            },
        ),
    )
    t = transport(
        {
            "/page-data/index/page-data.json": httpx.Response(200, json=LUAR_INDEX),
            "/page-data/US/mini-ana/page-data.json": httpx.Response(200, json=LUAR_DRAW),
        }
    )
    c = RecipeConnector(recipe)
    refs = c.discover(Brand(domain="luar.runfair.com", homepage_url="https://luar.runfair.com"), t)
    assert [r.url for r in refs] == [
        "https://luar.runfair.com/US/mini-ana"
    ]  # the GB draw is filtered
    assert refs[0].change_hint == "2026-09-01"
    rec = c.fetch(refs[0], t)
    assert rec.product_title == "Mini Ana" and rec.price == 185.0 and rec.currency == "USD"
    assert rec.main_image_url == "https://cdn/a.jpg" and rec.in_stock is True
    assert rec.platform == "recipe" and rec.raw == {"recipe": "gatsby-runfair"}


FENG_SITEMAP = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://feng.com/</loc></url><url><loc>https://feng.com/products/vest</loc></url>"
    "<url><loc>https://feng.com/products/gone</loc></url></urlset>"
)
FENG_PRODUCT = {
    "product": {
        "title": "Napo Vest",
        "variants": [
            {"price": "9180000", "available": True, "option1": "1"},
            {"price": "9180000", "available": False, "option1": "2"},
        ],
        "images": [{"src": "https://cdn.hstatic.net/v.jpg"}],
        "options": [{"name": "Kích thước"}],
        "body_html": "<p>Vest</p>",
    }
}


@pytest.mark.unit
def test_feng_as_a_recipe_sitemap_then_per_handle_json():
    recipe = LaneRecipe(
        id="haravan-per-product",
        signature="haravan·per-product·named-product·none·none·none",
        description="the product sitemap, then /products/<handle>.json",
        discover=Discover(
            kind="sitemap", url="https://{domain}/sitemap_products_1.xml", prefix="/"
        ),
        fetch=Fetch(
            kind="json",
            url_template="{url}.json",
            root="product",
            fields={
                "product_title": "title",
                "price": "variants[*].price",
                "images": "images[*].src",
                "description": "body_html",
                "sizes": "variants[*].option1",
                "in_stock": "variants[0].available",
            },
            currency="VND",
        ),
    )
    t = transport(
        {
            "/sitemap_products_1.xml": httpx.Response(200, text=FENG_SITEMAP),
            "/products/vest.json": httpx.Response(200, json=FENG_PRODUCT),
        }
    )
    c = RecipeConnector(recipe)
    refs = c.discover(Brand(domain="feng.com", homepage_url="https://feng.com"), t)
    assert [r.url for r in refs] == [
        "https://feng.com/products/vest",
        "https://feng.com/products/gone",
    ]
    rec = c.fetch(refs[0], t)
    assert rec.product_title == "Napo Vest" and rec.price == 9180000.0 and rec.currency == "VND"
    assert rec.description == "Vest" and rec.size_info == "1, 2" and rec.in_stock is True
    assert rec.all_images == json.dumps(["https://cdn.hstatic.net/v.jpg"])
    with pytest.raises(NotAProduct):
        c.fetch(refs[1], t)  # 404: gone


@pytest.mark.unit
def test_a_jsonld_recipe_reads_the_page_and_a_listing_finds_links():
    page = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"Product","name":"Coat","offers":{"price":"420","priceCurrency":"EUR","availability":"https://schema.org/InStock"},"image":["https://x/c.jpg"]}'
        "</script></head><body></body></html>"
    )
    listing = '<html><a href="/products/coat">Coat</a><a href="/products/coat">again</a><a href="/about">x</a></html>'
    recipe = LaneRecipe(
        id="listing-jsonld",
        signature="custom·closed·none·jsonld·none·none",
        description="a listing page, then JSON-LD",
        discover=Discover(
            kind="listing", url="https://{domain}/shop", link_pattern=r'href="(/products/[^"]+)"'
        ),
        fetch=Fetch(
            kind="jsonld",
            fields={
                "product_title": "name",
                "price": "offers.price",
                "currency": "offers.priceCurrency",
                "in_stock": "offers.availability",
            },
        ),
    )
    t = transport(
        {
            "/shop": httpx.Response(200, text=listing),
            "/products/coat": httpx.Response(200, text=page),
        }
    )
    c = RecipeConnector(recipe)
    refs = c.discover(Brand(domain="x.com", homepage_url="https://x.com"), t)
    assert [r.url for r in refs] == ["https://x.com/products/coat"]
    rec = c.fetch(refs[0], t)
    assert (
        rec.product_title == "Coat"
        and rec.price == 420.0
        and rec.currency == "EUR"
        and rec.in_stock is True
    )
    assert rec.main_image_url == "https://x/c.jpg"


@pytest.mark.unit
def test_a_list_endpoint_that_refuses_is_a_blocked_channel():
    recipe = LaneRecipe(
        id="r",
        signature="s",
        description="d",
        discover=Discover(
            kind="json_list",
            url="https://{domain}/api",
            items="items",
            url_template="https://{domain}/p/{id}",
        ),
        fetch=Fetch(kind="payload", fields={"product_title": "name"}),
    )
    with pytest.raises(ChannelBlocked):
        RecipeConnector(recipe).discover(
            Brand(domain="x.com", homepage_url="https://x.com"),
            transport({"/api": httpx.Response(403)}),
        )


@pytest.mark.unit
def test_a_paged_list_walks_until_empty_and_a_payload_fetch_needs_no_request():
    pages = {
        "/api?page=1": httpx.Response(
            200, json={"items": [{"id": 1, "name": "A", "price": 5, "image": "https://x/a.jpg"}]}
        ),
        "/api?page=2": httpx.Response(
            200, json={"items": [{"id": 2, "name": "B", "price": 6, "image": "https://x/b.jpg"}]}
        ),
        "/api?page=3": httpx.Response(200, json={"items": []}),
    }
    recipe = LaneRecipe(
        id="r",
        signature="s",
        description="d",
        discover=Discover(
            kind="json_list",
            url="https://{domain}/api",
            items="items",
            url_template="https://{domain}/p/{id}",
            page_param="page",
        ),
        fetch=Fetch(
            kind="payload", fields={"product_title": "name", "price": "price", "images": "image"}
        ),
    )
    c = RecipeConnector(recipe)
    t = transport(pages)
    refs = c.discover(Brand(domain="x.com", homepage_url="https://x.com"), t)
    assert [r.url for r in refs] == ["https://x.com/p/1", "https://x.com/p/2"]
    rec = c.fetch(refs[1], None)  # payload: no HTTP
    assert rec.product_title == "B" and rec.price == 6.0 and rec.main_image_url == "https://x/b.jpg"


@pytest.mark.unit
def test_a_recipe_written_in_the_catalogues_field_names_is_read_as_ours():
    from backend.archive.learn.recipes import Fetch

    f = Fetch(kind="json", fields={"all_images": "image[*]", "size_info": "sizes", "sku": "id"})
    assert f.fields == {"images": "image[*]", "sizes": "sizes", "product_code": "id"}
    as_list = Fetch(
        kind="json", fields=[{"name": "title", "path": "name"}, {"name": "price", "path": "p"}]
    )
    assert as_list.fields == {"product_title": "name", "price": "p"}


@pytest.mark.unit
def test_a_listing_that_captures_bare_ids_places_them_with_the_template():
    from backend.archive.domain.brand import Brand
    from backend.archive.learn.recipes import Discover, Fetch, LaneRecipe, RecipeConnector

    class T:
        def get(self, url):
            class R:
                status_code = 200
                text = 'x data-id="6904bd75cf2f2e0012ba2388" y data-id="6904bd75cf2f2e0012ba2399"'

            return R()

    r = LaneRecipe(
        id="t",
        signature="s",
        description="",
        discover=Discover(
            kind="listing",
            url="https://{domain}/",
            link_pattern=r'data-id="([0-9a-f]{24})"',
            url_template="https://{domain}/api/products/{id}",
        ),
        fetch=Fetch(kind="json", fields={"product_title": "name"}),
    )
    refs = RecipeConnector(r, limit=None).discover(
        Brand(domain="y.com", homepage_url="https://y.com"), T()
    )
    assert [x.url for x in refs] == [
        "https://y.com/api/products/6904bd75cf2f2e0012ba2388",
        "https://y.com/api/products/6904bd75cf2f2e0012ba2399",
    ]
    assert refs[0].payload["id"] == "6904bd75cf2f2e0012ba2388"


@pytest.mark.unit
def test_a_sitemap_recipe_may_filter_its_urls_with_a_pattern(monkeypatch):
    from backend.archive.domain.brand import Brand
    from backend.archive.domain.product import ProductRef
    from backend.archive.learn import recipes as mod
    from backend.archive.learn.recipes import Discover, Fetch, LaneRecipe, RecipeConnector

    def fake_discover(self, brand, transport):
        found = [
            ProductRef(url="https://g.com/us/en/stores"),
            ProductRef(url="https://g.com/us/en/item/ABC/jennie"),
            ProductRef(url="https://g.com/us/en/item/DEF/zen"),
        ]
        kept = [x for x in found if self._is_product(x.url)]
        return kept[: self.limit] if self.limit else kept

    monkeypatch.setattr(mod._PatternSitemap, "discover", fake_discover)
    r = LaneRecipe(
        id="t",
        signature="s",
        description="",
        discover=Discover(
            kind="sitemap", url="https://{domain}/sitemap.xml", link_pattern=r"/item/([A-Z0-9]+)/"
        ),
        fetch=Fetch(kind="jsonld"),
    )
    refs = RecipeConnector(r, limit=1).discover(
        Brand(domain="g.com", homepage_url="https://g.com"), None
    )
    assert [x.url for x in refs] == ["https://g.com/us/en/item/ABC/jennie"]
