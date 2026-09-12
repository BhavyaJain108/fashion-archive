"""Full-body test: CLI scrape of a mocked open-Shopify brand, then delta, then status."""

import json
from pathlib import Path

import httpx
import pytest

import backend.archive.runner.cli as cli
from backend.archive.transport import HttpxTransport

FIX = Path(__file__).parent / "fixtures"
YML = 'brands:\n  - {domain: kuurth.com, homepage_url: "https://kuurth.com"}\n'
HOME = (
    "<html><head><title>KUURTH</title></head>"
    '<body><script src="https://cdn.shopify.com/x"></script></body></html>'
)


def mock_transport() -> HttpxTransport:
    products = json.loads((FIX / "shopify_products_page1.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="Sitemap: https://kuurth.com/sitemap.xml\n")
        if path == "/":
            return httpx.Response(200, text=HOME)
        if path == "/products.json":
            page = request.url.params.get("page", "1")
            return httpx.Response(200, json=products if page == "1" else {"products": []})
        if path == "/sitemap.xml":
            return httpx.Response(200, text=(FIX / "sitemap_index.xml").read_text())
        if path == "/sitemap_products_1.xml":
            return httpx.Response(200, text=(FIX / "sitemap_products.xml").read_text())
        if path == "/sitemap_pages_1.xml":
            return httpx.Response(
                200,
                text='<?xml version="1.0"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',
            )
        return httpx.Response(404)

    return HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )


LD_PAGE = (
    '<html><head><script type="application/ld+json">'
    '{"@type":"Product","name":"Gale Coat","sku":"G1","offers":{"price":"420.00",'
    '"priceCurrency":"USD","availability":"InStock"},"image":"https://liniss.com/g.jpg"}'
    "</script></head><body>c</body></html>"
)
WP_SITEMAP = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://liniss.com/products/gale-coat</loc>"
    "<lastmod>2026-08-01T00:00:00Z</lastmod></url></urlset>"
)


def wp_structured_transport() -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="Sitemap: https://liniss.com/sitemap.xml\n")
        if path == "/sitemap.xml":
            return httpx.Response(200, text=WP_SITEMAP)
        if path == "/":
            return httpx.Response(
                200,
                text='<html><head><title>L</title></head><body><link href="/wp-content/a.css"></body></html>',
            )
        if path == "/products/gale-coat":
            return httpx.Response(200, text=LD_PAGE)
        return httpx.Response(404)

    return HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )


@pytest.mark.unit
def test_structured_lane_end_to_end_with_delta(tmp_path, capsys, monkeypatch):
    """WordPress brand, woo closed → sitemap×structured; delta re-run writes nothing."""
    monkeypatch.setattr(cli, "HttpxTransport", lambda *a, **k: wp_structured_transport())
    brands = tmp_path / "brands.yml"
    brands.write_text('brands:\n  - {domain: liniss.com, homepage_url: "https://liniss.com"}\n')
    db = tmp_path / "catalog.db"
    common = [
        "--db",
        str(db),
        "--brands",
        str(brands),
        "--locks",
        str(tmp_path / "locks"),
        "--logs",
        str(tmp_path / "logs"),
    ]
    assert cli.main(["scrape", "liniss.com", "--full", *common]) == 0
    assert cli.main(["scrape", "liniss.com", "--delta", *common]) == 0

    from backend.archive.store.catalog import Catalog

    cat = Catalog(db)
    assert cat.observation_count("liniss.com") == 1  # one product, one first-sight, no re-write
    plan = cat.load_plan("liniss.com")
    assert plan.composition == "t0×sitemap×structured_data×per_item"
    prod = cat.current_products("liniss.com")[0]
    assert prod["product_title"] == "Gale Coat" and prod["price"] == 420.0
    cat.close()


@pytest.mark.unit
def test_woo_lane_end_to_end(tmp_path, capsys, monkeypatch):
    import json as _json
    from pathlib import Path as _Path

    woo_products = _json.loads(
        (_Path(__file__).parent / "fixtures" / "woo_products_page1.json").read_text()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/sitemap.xml":
            return httpx.Response(404)
        if path == "/":
            return httpx.Response(
                200,
                text='<html><head><title>W</title></head><body><link href="/wp-content/a.css"></body></html>',
            )
        if path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
            page = request.url.params.get("page", "1")
            return httpx.Response(200, json=woo_products if page == "1" else [])
        return httpx.Response(404)

    monkeypatch.setattr(
        cli,
        "HttpxTransport",
        lambda *a, **k: HttpxTransport(
            client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        ),
    )
    brands = tmp_path / "brands.yml"
    brands.write_text(
        'brands:\n  - {domain: wiacollections.com, homepage_url: "https://wiacollections.com"}\n'
    )
    db = tmp_path / "catalog.db"
    assert (
        cli.main(
            [
                "scrape",
                "wiacollections.com",
                "--full",
                "--db",
                str(db),
                "--brands",
                str(brands),
                "--locks",
                str(tmp_path / "locks"),
                "--logs",
                str(tmp_path / "logs"),
            ]
        )
        == 0
    )
    from backend.archive.store.catalog import Catalog

    cat = Catalog(db)
    assert cat.load_plan("wiacollections.com").composition == "t0×woo_api×platform_json×per_item"
    prods = cat.current_products("wiacollections.com")
    assert {p["product_title"] for p in prods} == {"Wia Jacket", "Wia Tee"}
    assert next(p for p in prods if p["product_title"] == "Wia Jacket")["price"] == 199.0
    cat.close()


@pytest.mark.unit
def test_scrape_then_delta_then_status(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "HttpxTransport", lambda *a, **k: mock_transport())
    brands = tmp_path / "brands.yml"
    brands.write_text(YML)
    db = tmp_path / "catalog.db"
    common = [
        "--db",
        str(db),
        "--brands",
        str(brands),
        "--locks",
        str(tmp_path / "locks"),
        "--logs",
        str(tmp_path / "logs"),
        "--images-dir",
        str(tmp_path / "images"),
    ]

    assert cli.main(["scrape", "kuurth.com", "--full", *common]) == 0
    assert cli.main(["scrape", "kuurth.com", "--delta", *common]) == 0  # nothing changed → still ok
    assert cli.main(["status", "--db", str(db), "--brands", str(brands)]) == 0
    out = capsys.readouterr().out
    assert "kuurth.com" in out and "active" in out and "100%" in out
