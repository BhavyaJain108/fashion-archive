from pathlib import Path

import httpx
import pytest

from backend.archive.connectors.sitemap import SitemapConnector
from backend.archive.domain.brand import Brand
from backend.archive.transport import HttpxTransport

FIX = Path(__file__).parent / "fixtures"


def make_transport() -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, text=(FIX / "sitemap_index.xml").read_text())
        if request.url.path == "/sitemap_products_1.xml":
            return httpx.Response(200, text=(FIX / "sitemap_products.xml").read_text())
        if request.url.path == "/sitemap_pages_1.xml":
            return httpx.Response(
                200,
                text='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://kuurth.com/pages/faq</loc></url></urlset>",
            )
        return httpx.Response(404)

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


BRAND = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")


@pytest.mark.unit
def test_discover_walks_index_and_keeps_only_product_urls():
    refs = SitemapConnector("https://kuurth.com/sitemap.xml").discover(BRAND, make_transport())
    assert [r.url for r in refs] == [
        "https://kuurth.com/products/ring-one",
        "https://kuurth.com/products/cuff-two",
    ]
    assert refs[1].change_hint == "2026-08-20T09:30:00Z"


@pytest.mark.unit
def test_count_matches_discover():
    c = SitemapConnector("https://kuurth.com/sitemap.xml")
    assert c.count(BRAND, make_transport()) == 2


WEBFLOW = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://www.outlw.xyz/shop</loc></url>"
    "<url><loc>https://www.outlw.xyz/assets/ai-warrior-tee</loc><lastmod>2026-08-01</lastmod></url>"
    "<url><loc>https://www.outlw.xyz/assets/ameri-care-tee</loc></url>"
    "</urlset>"
)


@pytest.mark.unit
def test_learned_prefix_finds_products_a_generic_regex_would_miss():
    """outlw.xyz keeps products under /assets/ (live bug 2026-08-30)."""
    t = HttpxTransport(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text=WEBFLOW))
        )
    )
    brand = Brand(domain="www.outlw.xyz", homepage_url="https://www.outlw.xyz")
    generic = SitemapConnector("https://www.outlw.xyz/sitemap.xml")
    assert generic.discover(brand, t) == []  # the old behaviour: nothing found

    learned = SitemapConnector("https://www.outlw.xyz/sitemap.xml", url_prefix="/assets/")
    refs = learned.discover(brand, t)
    assert [r.url for r in refs] == [
        "https://www.outlw.xyz/assets/ai-warrior-tee",
        "https://www.outlw.xyz/assets/ameri-care-tee",
    ]
    assert refs[0].change_hint == "2026-08-01"


@pytest.mark.unit
def test_discovery_stops_at_the_limit_without_reading_the_rest():
    """The Outnet's index fans out to 80,048 URLs; the walk must stop early."""
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if request.url.path == "/sitemap.xml":
            children = "".join(
                f"<sitemap><loc>https://big.test/s{i}.xml</loc></sitemap>" for i in range(5)
            )
            return httpx.Response(
                200,
                text='<?xml version="1.0"?><sitemapindex '
                'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{children}</sitemapindex>",
            )
        n = request.url.path.strip("/s.xml")
        urls = "".join(
            f"<url><loc>https://big.test/products/{n}-{i}</loc></url>" for i in range(100)
        )
        return httpx.Response(
            200,
            text='<?xml version="1.0"?><urlset '
            f'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        )

    transport = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )
    refs = SitemapConnector("https://big.test/sitemap.xml", limit=30).discover(BRAND, transport)
    assert len(refs) == 30
    assert len(fetched) == 2  # the index and exactly one child sitemap


@pytest.mark.unit
def test_one_broken_child_sitemap_does_not_lose_the_catalogue():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            return httpx.Response(
                200,
                text='<?xml version="1.0"?><sitemapindex '
                'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<sitemap><loc>https://big.test/dead.xml</loc></sitemap>"
                "<sitemap><loc>https://big.test/good.xml</loc></sitemap></sitemapindex>",
            )
        if request.url.path == "/dead.xml":
            return httpx.Response(500)
        return httpx.Response(
            200,
            text='<?xml version="1.0"?><urlset '
            'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://big.test/products/alive</loc></url></urlset>",
        )

    transport = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )
    refs = SitemapConnector("https://big.test/sitemap.xml").discover(BRAND, transport)
    assert [r.url for r in refs] == ["https://big.test/products/alive"]
