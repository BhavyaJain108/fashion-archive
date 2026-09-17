import httpx
import pytest

from backend.archive.access.learned import trust_a_named_product_sitemap
from backend.archive.domain.brand import Capability, TransportLevel
from backend.archive.transport import HttpxTransport

INDEX = """<sitemapindex>
<sitemap><loc>https://vw.com/sitemap_0-product.xml</loc></sitemap>
<sitemap><loc>https://vw.com/sitemap_1-image.xml</loc></sitemap>
</sitemapindex>"""


def cap(**kw):
    return Capability(
        domain="vw.com",
        transport=TransportLevel.T0,
        sitemap_url="https://vw.com/sitemap_index.xml",
        product_url_prefix="/women/wallets/flat-card-holder-black/",
        **kw,
    )


def over(body):
    handler = lambda r: httpx.Response(200, text=body)  # noqa: E731
    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.unit
def test_a_named_product_sitemap_replaces_a_guessed_url_pattern():
    got = trust_a_named_product_sitemap(cap(), over(INDEX))
    assert got.sitemap_url == "https://vw.com/sitemap_0-product.xml"
    assert got.product_url_prefix == "/"


@pytest.mark.unit
def test_without_a_named_product_sitemap_nothing_changes():
    plain = "<sitemapindex><sitemap><loc>https://vw.com/a.xml</loc></sitemap></sitemapindex>"
    assert trust_a_named_product_sitemap(cap(), over(plain)) == cap()
