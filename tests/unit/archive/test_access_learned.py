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


GM_INDEX = """<sitemapindex>
<sitemap><loc>https://gm.com/kr/static-publish/sitemap.xml</loc></sitemap>
<sitemap><loc>https://gm.com/us/static-publish/sitemap.xml</loc></sitemap>
</sitemapindex>"""
GM_US = (
    "<urlset>"
    + "".join(
        f"<url><loc>https://gm.com/us/en/item/CODE{i}/frame-{i}</loc></url>" for i in range(30)
    )
    + "<url><loc>https://gm.com/us/en/stores</loc></url></urlset>"
)


@pytest.mark.unit
def test_products_are_found_as_the_biggest_family_in_the_home_country_sitemap():
    from backend.archive.access.learned import widen_to_the_biggest_url_family

    def handler(r):
        return httpx.Response(200, text=GM_US if "/us/" in str(r.url) else GM_INDEX)

    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    one_folder = Capability(
        domain="gm.com",
        transport=TransportLevel.T0,
        sitemap_url="https://gm.com/legacy/sitemap-index.xml",
        product_url_prefix="/kr/ko/item/CODE1/",
    )
    got = widen_to_the_biggest_url_family(one_folder, t)
    assert got.sitemap_url == "https://gm.com/us/static-publish/sitemap.xml"
    assert got.product_url_prefix == "/us/en/item/"
