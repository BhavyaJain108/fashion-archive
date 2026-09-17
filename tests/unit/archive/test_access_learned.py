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


SWATCHES = """
<a href="/x?size=XXS" data-tau-size-id="XXS" title="XXS (not available)"><span>XXS</span></a>
<a href="/x?size=S" data-tau-size-id="S" title="S "><span>S</span></a>
<a href="/x?size=M" data-tau-size-id="M" title="M "><span>M</span></a>
<a data-tau-size-id="{{id}}" title="template"></a>
"""


@pytest.mark.unit
def test_sizes_and_their_availability_are_read_from_swatches():
    from backend.archive.access.learned import sizes_from_swatches

    assert sizes_from_swatches(SWATCHES) == [
        {"size": "XXS", "available": False},
        {"size": "S", "available": True},
        {"size": "M", "available": True},
    ]


@pytest.mark.unit
def test_a_page_with_no_swatches_yields_no_sizes():
    from backend.archive.access.learned import sizes_from_swatches

    assert sizes_from_swatches("<p>no sizes here</p>") == []


@pytest.mark.unit
def test_the_same_product_in_eight_countries_is_one_product():
    from backend.archive.access.learned import dedupe_locale_copies
    from backend.archive.domain.product import ProductRef

    refs = [
        ProductRef(url="https://vw.com/women/a/b/cardigan/1.html"),
        ProductRef(url="https://vw.com/en-fr/women/a/b/cardigan/1.html"),
        ProductRef(url="https://vw.com/en-de/women/a/b/cardigan/1.html"),
        ProductRef(url="https://vw.com/women/a/b/skirt/2.html"),
    ]
    kept = dedupe_locale_copies(refs)
    assert [r.url for r in kept] == [
        "https://vw.com/women/a/b/cardigan/1.html",
        "https://vw.com/women/a/b/skirt/2.html",
    ]


@pytest.mark.unit
def test_collection_landing_pages_are_dropped_from_a_product_family():
    """Van Cleef keeps /collections/jewelry.html beside its products, and that page has
    Product blocks of its own — so it read as a product called "Jewelry collections"."""
    from backend.archive.access.learned import drop_landing_pages
    from backend.archive.domain.product import ProductRef

    base = "https://vca.com/us/en/collections/jewelry"
    refs = [ProductRef(url=f"{base}.html"), ProductRef(url=f"{base}/alhambra.html")]
    refs += [ProductRef(url=f"{base}/alhambra/vca{i}-bracelet.html") for i in range(30)]
    kept = drop_landing_pages(refs)
    assert len(kept) == 30
    assert all("/alhambra/" in r.url for r in kept)


@pytest.mark.unit
def test_a_catalogue_where_every_product_sits_at_one_depth_is_untouched():
    from backend.archive.access.learned import drop_landing_pages
    from backend.archive.domain.product import ProductRef

    refs = [ProductRef(url=f"https://gm.com/us/en/item/C{i}/frame-{i}") for i in range(30)]
    assert drop_landing_pages(refs) == refs
