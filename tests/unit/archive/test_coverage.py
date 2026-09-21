"""S7 — the measurement the improvement loop starts from."""

import httpx
import pytest

from backend.archive.coverage import field_coverage, format_coverage
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import E0005_FIELDS
from backend.archive.transport import HttpxTransport

SHOP = (
    "<html><head><title>KUURTH</title></head>"
    '<body><script src="https://cdn.shopify.com/x.js"></script></body></html>'
)
PRODUCT = {
    "products": [
        {
            "id": 1,
            "title": "Tee",
            "handle": "tee",
            "variants": [{"price": "20.00", "available": True, "title": "M"}],
            "images": [{"src": "https://kuurth.com/a.jpg"}],
        }
    ]
}


def transport_over(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404))

    return HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )


@pytest.mark.unit
def test_every_e0005_field_is_reported_not_just_the_ones_that_work():
    """The five-column matrix read 100% while 36 of 45 fields were empty."""
    routes = {
        "/robots.txt": httpx.Response(200, text="Sitemap: https://kuurth.com/sitemap.xml\n"),
        "/products.json": httpx.Response(200, json=PRODUCT),
        "/meta.json": httpx.Response(200, json={"currency": "USD"}),
        "/": httpx.Response(200, text=SHOP),
    }
    fill, size, note = field_coverage(
        Brand(domain="kuurth.com", homepage_url="https://kuurth.com"),
        transport_over(routes),
        sample=1,
    )
    assert set(fill) == set(E0005_FIELDS)
    assert fill["product_title"] == 1.0
    assert fill["promotion_type"] == 0.0
    assert size >= 1 and note == ""


@pytest.mark.unit
def test_a_brand_we_cannot_read_says_so_rather_than_reporting_every_field_empty():
    """A row of zeros would read as a brand that publishes nothing."""
    routes = {"/": httpx.Response(403, text="Access Denied")}
    fill, _, note = field_coverage(
        Brand(domain="blocked.com", homepage_url="https://blocked.com"),
        transport_over(routes),
        sample=1,
    )
    assert fill == {} and note


@pytest.mark.unit
def test_a_field_no_brand_fills_is_marked_so_it_can_be_picked_up():
    rows = {
        "a.com": ({f: (1.0 if f == "product_title" else 0.0) for f in E0005_FIELDS}, 10, ""),
        "b.com": ({f: (1.0 if f == "price" else 0.0) for f in E0005_FIELDS}, 20, ""),
    }
    out = format_coverage(rows)
    assert "no brand fills this" in out
    title_row = next(line for line in out.splitlines() if line.startswith("product_title"))
    assert "no brand fills this" not in title_row
    assert "catalogue" in out and "fields filled" in out


@pytest.mark.unit
def test_measuring_nothing_says_so():
    assert "nothing measured" in format_coverage({})
