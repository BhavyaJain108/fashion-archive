import httpx
import pytest

from backend.archive.domain.brand import Capability, TransportLevel
from backend.archive.fingerprint import (
    _trust_a_named_product_sitemap as trust_a_named_product_sitemap,
)
from backend.archive.fingerprint import (
    _widen_to_the_biggest_url_family as widen_to_the_biggest_url_family,
)
from backend.archive.fingerprint import probe
from backend.archive.transport import HttpxTransport

SHOP_HOME = (
    "<html><head><title>KUURTH</title></head>"
    '<body><script src="https://cdn.shopify.com/x.js"></script></body></html>'
)
PW_HOME = "<html><head><title>Password – colt</title></head><body>opening soon</body></html>"


def make_transport(routes: dict[str, httpx.Response]) -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404))

    return HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )


@pytest.mark.unit
def test_open_shopify_capability():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(
                200, text="User-agent: *\nSitemap: https://kuurth.com/sitemap.xml\n"
            ),
            "/products.json": httpx.Response(200, json={"products": [{"id": 1}]}),
            "/": httpx.Response(200, text=SHOP_HOME),
        }
    )
    cap = probe("kuurth.com", t, retry_pause=0)
    assert cap.platform == "shopify" and cap.bulk_json is True
    assert cap.sitemap_url == "https://kuurth.com/sitemap.xml"
    assert cap.transport == TransportLevel.T0
    assert not cap.password_gated and not cap.challenged


@pytest.mark.unit
def test_password_gated_store():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(404),
            "/products.json": httpx.Response(
                302, headers={"location": "https://coltmcr.com/password"}
            ),
            "/password": httpx.Response(200, text=PW_HOME),
            "/": httpx.Response(302, headers={"location": "https://coltmcr.com/password"}),
            "/sitemap.xml": httpx.Response(404),
        }
    )
    cap = probe("coltmcr.com", t, retry_pause=0)
    assert cap.password_gated is True and cap.transport == TransportLevel.T4


WP_HOME = (
    '<html><head><title>Lalune</title></head><body><link href="/wp-content/x.css"></body></html>'
)
LD_PRODUCT_PAGE = (
    '<html><head><script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"Product","name":"Gale Coat"}'
    "</script></head><body>coat</body></html>"
)
SITEMAP = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://liniss.com/products/gale-coat</loc></url></urlset>"
)


@pytest.mark.unit
def test_open_shopify_probe_pays_no_extra_requests():
    """Deep probes (woo, ld+json) only run when the bulk feed is closed."""
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="Sitemap: https://kuurth.com/sitemap.xml\n"),
            "/products.json": httpx.Response(200, json={"products": [{"id": 1}]}),
            "/meta.json": httpx.Response(200, json={"currency": "USD"}),
            "/": httpx.Response(200, text=SHOP_HOME),
        }
    )
    probe("kuurth.com", t, retry_pause=0)
    # robots, products.json, meta.json (the store currency), homepage — nothing more
    assert len(t.ledger) == 4


@pytest.mark.unit
def test_wordpress_with_open_woo_store_api():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(404),
            "/sitemap.xml": httpx.Response(200, text=SITEMAP),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(200, text=WP_HOME),
            "/wp-json/wc/store/v1/products": httpx.Response(200, json=[{"id": 1, "name": "x"}]),
        }
    )
    cap = probe("wiacollections.com", t, retry_pause=0)
    assert cap.platform == "wordpress" and cap.woo_api is True


@pytest.mark.unit
def test_ldjson_product_detected_via_sitemap_sample():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="Sitemap: https://liniss.com/sitemap.xml\n"),
            "/sitemap.xml": httpx.Response(200, text=SITEMAP),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(
                200, text="<html><head><title>L</title></head><body></body></html>"
            ),
            "/wp-json/wc/store/v1/products": httpx.Response(404),
            "/wp-json/wc/store/products": httpx.Response(404),
            "/products/gale-coat": httpx.Response(200, text=LD_PRODUCT_PAGE),
        }
    )
    cap = probe("liniss.com", t, retry_pause=0)
    assert cap.woo_api is False and cap.ldjson_product is True


@pytest.mark.unit
def test_challenged_store_needs_browser():
    """staud.clothing-style: every plain-HTTP request 429s (probe of 2026-08-26)."""
    t = make_transport(
        {
            "/robots.txt": httpx.Response(429),
            "/products.json": httpx.Response(429),
            "/": httpx.Response(429),
            "/sitemap.xml": httpx.Response(429),
        }
    )
    cap = probe("staud.clothing", t, retry_pause=0)
    assert cap.challenged is True and cap.bulk_json is False
    assert cap.transport == TransportLevel.T2


WEBFLOW_SITEMAP = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://www.outlw.xyz/shop</loc></url>"
    "<url><loc>https://www.outlw.xyz/shipping</loc></url>"
    "<url><loc>https://www.outlw.xyz/assets/ai-warrior-tee</loc></url>"
    "<url><loc>https://www.outlw.xyz/assets/ameri-care-tee</loc></url>"
    "<url><loc>https://www.outlw.xyz/assets/american-chopper</loc></url>"
    "<url><loc>https://www.outlw.xyz/archive/2023</loc></url>"
    "</urlset>"
)


@pytest.mark.unit
def test_learns_an_unconventional_product_url_prefix():
    """Live bug (outlw.xyz, 2026-08-30): 140 products live under /assets/, so a hardcoded
    /products/ regex found none — even though the pages carry Product JSON-LD."""
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="Sitemap: https://www.outlw.xyz/sitemap.xml\n"),
            "/sitemap.xml": httpx.Response(200, text=WEBFLOW_SITEMAP),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(
                200, text="<html><head><title>OUTLW</title></head><body></body></html>"
            ),
            "/wp-json/wc/store/v1/products": httpx.Response(404),
            "/wp-json/wc/store/products": httpx.Response(404),
            "/assets/ai-warrior-tee": httpx.Response(200, text=LD_PRODUCT_PAGE),
        }
    )
    cap = probe("www.outlw.xyz", t, retry_pause=0)
    assert cap.ldjson_product is True
    assert cap.product_url_prefix == "/assets/"


@pytest.mark.unit
def test_conventional_products_prefix_is_tried_first():
    """A /products/ cluster should win without spending probes on other segments."""
    sm = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://liniss.com/blog/a</loc></url>"
        "<url><loc>https://liniss.com/blog/b</loc></url>"
        "<url><loc>https://liniss.com/blog/c</loc></url>"
        "<url><loc>https://liniss.com/products/gale-coat</loc></url>"
        "</urlset>"
    )
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="Sitemap: https://liniss.com/sitemap.xml\n"),
            "/sitemap.xml": httpx.Response(200, text=sm),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(
                200, text="<html><head><title>L</title></head><body></body></html>"
            ),
            "/wp-json/wc/store/v1/products": httpx.Response(404),
            "/wp-json/wc/store/products": httpx.Response(404),
            "/products/gale-coat": httpx.Response(200, text=LD_PRODUCT_PAGE),
        }
    )
    cap = probe("liniss.com", t, retry_pause=0)
    assert cap.product_url_prefix == "/products/"
    assert "/blog/" not in str(t.ledger)  # never wasted a probe on the bigger blog cluster


@pytest.mark.unit
def test_no_product_pages_anywhere_reports_no_lane():
    """laluneofficial.com: an editorial WordPress sitemap with no products at all."""
    sm = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://lalune.com/blog/</loc></url>"
        "<url><loc>https://lalune.com/press-1/</loc></url>"
        "<url><loc>https://lalune.com/lookbook/</loc></url>"
        "</urlset>"
    )
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="Sitemap: https://lalune.com/sitemap.xml\n"),
            "/sitemap.xml": httpx.Response(200, text=sm),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(
                200, text="<html><head><title>L</title></head><body></body></html>"
            ),
            "/wp-json/wc/store/v1/products": httpx.Response(404),
            "/wp-json/wc/store/products": httpx.Response(404),
            "/blog/": httpx.Response(200, text="<html><body>a blog post</body></html>"),
        }
    )
    cap = probe("lalune.com", t, retry_pause=0)
    assert cap.ldjson_product is False and cap.product_url_prefix is None


@pytest.mark.unit
def test_transient_challenge_on_robots_is_retried():
    """Live bug (gentlemonster, 2026-08-30): robots.txt served a sitemap on one probe and a
    challenge 20 minutes later, so the brand's classification was a coin flip."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(202, text="")  # challenge in progress
            return httpx.Response(200, text="Sitemap: https://gm.com/sitemap.xml\n")
        if request.url.path == "/products.json":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(
                200, text="<html><head><title>GM</title></head><body></body></html>"
            )
        return httpx.Response(404)

    t = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )
    cap = probe("gm.com", t, retry_pause=0)
    assert cap.sitemap_url == "https://gm.com/sitemap.xml"  # the retry recovered it
    assert calls["n"] == 2


@pytest.mark.unit
def test_persistent_challenge_is_not_retried_forever():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403)

    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    cap = probe("hard.com", t, retry_pause=0)
    assert cap.challenged is True
    assert calls["n"] <= 10  # one retry per probe, not a loop


@pytest.mark.unit
def test_locale_prefixed_product_urls_are_clustered_correctly():
    """Regression (psylos1, 2026-08-30): clustering on the FIRST path segment grouped
    everything under the locale '/en/', sampled a non-product page, and lost a working brand."""
    sm = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://psylos1.com/en/about</loc></url>"
        "<url><loc>https://psylos1.com/en/contact</loc></url>"
        "<url><loc>https://psylos1.com/en/products/derby-shoes</loc></url>"
        "<url><loc>https://psylos1.com/en/products/silver-ring</loc></url>"
        "</urlset>"
    )
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="Sitemap: https://psylos1.com/sitemap.xml\n"),
            "/sitemap.xml": httpx.Response(200, text=sm),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(
                200, text="<html><head><title>P</title></head><body></body></html>"
            ),
            "/wp-json/wc/store/v1/products": httpx.Response(404),
            "/wp-json/wc/store/products": httpx.Response(404),
            "/en/products/derby-shoes": httpx.Response(200, text=LD_PRODUCT_PAGE),
        }
    )
    cap = probe("psylos1.com", t, retry_pause=0)
    assert cap.ldjson_product is True
    assert cap.product_url_prefix == "/en/products/"


@pytest.mark.unit
def test_a_401_access_denied_page_counts_as_a_block():
    """outlw.xyz answers every URL with HTTP 401 and <title>access denied</title>."""

    denied = httpx.Response(401, text="<html><head><title>access denied</title></head></html>")
    cap = probe(
        "www.outlw.xyz",
        make_transport(
            {
                "/robots.txt": httpx.Response(
                    200, text="Sitemap: https://www.outlw.xyz/sitemap.xml"
                ),
                "/": denied,
                "/products.json": denied,
            }
        ),
    )
    assert cap.challenged is True
    assert cap.password_gated is False
    assert cap.platform is None


@pytest.mark.unit
def test_a_browser_probe_still_looks_for_the_product_prefix_on_a_blocked_site():
    """Over HTTP a block ends the probe; on a browser the deep steps are worth trying."""
    product = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"Product","name":"Tee","offers":{"price":"10"}}'
        "</script></head><body>x</body></html>"
    )
    routes = {
        "/": httpx.Response(403, text="<html><head><title>blocked</title></head></html>"),
        "/products.json": httpx.Response(403),
        "/robots.txt": httpx.Response(200, text="Sitemap: https://b.test/sitemap.xml"),
        "/sitemap.xml": httpx.Response(
            200,
            text='<?xml version="1.0"?><urlset '
            'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://b.test/assets/tee</loc></url>"
            "<url><loc>https://b.test/assets/cap</loc></url></urlset>",
        ),
        "/assets/tee": httpx.Response(200, text=product),
        "/assets/cap": httpx.Response(200, text=product),
    }
    http = make_transport(routes)
    assert probe("b.test", http).product_url_prefix is None  # HTTP gives up, as before

    browser = make_transport(routes)
    browser.level = TransportLevel.T2
    assert probe("b.test", browser).product_url_prefix == "/assets/"


@pytest.mark.unit
def test_a_shopify_store_states_its_currency_at_meta_json():
    cap = probe(
        "kuurth.com",
        make_transport(
            {
                "/products.json": httpx.Response(200, text='{"products":[{"id":1}]}'),
                "/meta.json": httpx.Response(200, json={"currency": "USD", "name": "KUURTH"}),
                "/": httpx.Response(200, text=SHOP_HOME),
                "/robots.txt": httpx.Response(200, text=""),
            }
        ),
    )
    assert cap.currency == "USD"


@pytest.mark.unit
def test_no_meta_json_request_when_there_is_no_bulk_feed():
    """Only Shopify publishes it; other platforms must not pay for the request."""
    asked = []

    class Recording(HttpxTransport):
        def get(self, url, **kw):
            asked.append(url)
            return super().get(url, **kw)

    routes = {
        "/products.json": httpx.Response(404),
        "/": httpx.Response(200, text="<html><head><title>x</title></head></html>"),
        "/robots.txt": httpx.Response(200, text=""),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404))

    t = Recording(client=httpx.Client(transport=httpx.MockTransport(handler)))
    probe("kuurth.com", t)
    assert not any("meta.json" in u for u in asked)


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


PORTFOLIO_HOME = (
    "<html><head><title>La Lune</title></head><body>"
    '<a href="https://laluneofficial.com/category/collections/">Collections</a>'
    '<a href="https://shop.laluneofficial.com/product-category/all-products/">Shop</a>'
    '<link rel="stylesheet" href="/wp-content/themes/portra/style.css"></body></html>'
)


def make_host_transport(routes: dict[tuple[str, str], httpx.Response]) -> HttpxTransport:
    """Routes keyed by (host, path): a probe that crosses hosts needs to tell them apart."""

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get((request.url.host, request.url.path), httpx.Response(404))

    return HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )


@pytest.mark.unit
def test_a_portfolio_site_with_a_shop_link_is_read_at_the_shop():
    # laluneofficial.com is WordPress with no feed; its nav says Shop and points at a
    # subdomain running WooCommerce. The capability is the shop's, keyed on the brand.
    t = make_host_transport(
        {
            ("laluneofficial.com", "/"): httpx.Response(200, text=PORTFOLIO_HOME),
            ("shop.laluneofficial.com", "/"): httpx.Response(
                200, text="<html><body class='woocommerce'></body></html>"
            ),
            ("shop.laluneofficial.com", "/wp-json/wc/store/v1/products"): httpx.Response(
                200, text='[{"id": 1}]'
            ),
        }
    )
    cap = probe("laluneofficial.com", t, retry_pause=0)
    assert (cap.domain, cap.shop_domain) == ("laluneofficial.com", "shop.laluneofficial.com")
    assert cap.woo_api is True and cap.platform == "woocommerce"
    assert cap.evidence["shop_link"] == "shop.laluneofficial.com"
    assert cap.evidence["shop.woo_api"] == "/wp-json/wc/store/v1/products"


@pytest.mark.unit
def test_a_shop_link_that_leads_nowhere_changes_nothing():
    t = make_host_transport({("laluneofficial.com", "/"): httpx.Response(200, text=PORTFOLIO_HOME)})
    cap = probe("laluneofficial.com", t, retry_pause=0)
    assert cap.shop_domain is None and cap.woo_api is False
    assert cap.evidence["shop_link"] == "shop.laluneofficial.com"  # tried, and said so


@pytest.mark.unit
def test_a_link_back_to_the_brands_own_host_is_not_a_shop_link():
    from backend.archive.fingerprint import shop_link

    body = '<a href="https://www.kuurth.com/collections/all">Shop</a>'
    assert shop_link(body, "kuurth.com") is None
    assert (
        shop_link('<a href="https://shop.kuurth.com/">Shop</a>', "kuurth.com") == "shop.kuurth.com"
    )
    assert (
        shop_link('<a href="https://kuurth.bigcartel.com/store">buy here</a>', "kuurth.com")
        == "kuurth.bigcartel.com"
    )


# --- 2026-09-27: Salesforce Commerce houses, Shopify with the feed off, runfair ---

PRODUCT_PAGE = (
    '<html><head><script type="application/ld+json">'
    '{"@type":"Product","name":"Jacket","offers":{"price":"730.00","priceCurrency":"USD"}}'
    "</script></head><body>p</body></html>"
)
PLAIN_HOME = "<html><head><title>P</title></head><body></body></html>"
NO_WOO = {
    "/wp-json/wc/store/v1/products": httpx.Response(404),
    "/wp-json/wc/store/products": httpx.Response(404),
}


def urlset(urls):
    return (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        + "</urlset>"
    )


def index(children):
    return (
        "<sitemapindex>"
        + "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
        + "</sitemapindex>"
    )


@pytest.mark.unit
def test_robots_naming_another_countrys_sitemap_is_answered_with_ours():
    """Marni: robots.txt names /en-ca/sitemap_index.xml; /en-us/ has the same index."""
    t = make_transport(
        {
            "/robots.txt": httpx.Response(
                200, text="Sitemap: https://marni.com/en-ca/sitemap_index.xml\n"
            ),
            "/en-us/sitemap_index.xml": httpx.Response(200, text=index([])),
            "/en-ca/sitemap_index.xml": httpx.Response(200, text=index([])),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(200, text=PLAIN_HOME),
            **NO_WOO,
        }
    )
    cap = probe("marni.com", t, retry_pause=0)
    assert cap.sitemap_url == "https://marni.com/en-us/sitemap_index.xml"
    assert cap.evidence["sitemap_locale"] == "en-ca→en-us"


@pytest.mark.unit
def test_a_country_sitemap_we_cannot_get_keeps_the_one_robots_named():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(
                200, text="Sitemap: https://marni.com/en-ca/sitemap_index.xml\n"
            ),
            "/en-ca/sitemap_index.xml": httpx.Response(200, text=index([])),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(200, text=PLAIN_HOME),
            **NO_WOO,
        }
    )
    cap = probe("marni.com", t, retry_pause=0)
    assert cap.sitemap_url == "https://marni.com/en-ca/sitemap_index.xml"
    assert "sitemap_locale" not in cap.evidence


@pytest.mark.unit
def test_of_two_unnamed_children_the_bigger_sitemap_is_the_products():
    """Marni's index: 72 looks and editorials in one child, 1,838 products in the other,
    every URL under /en-us/. The family cannot tell them apart; the size can."""
    looks = [f"https://marni.com/en-us/look_{i}.html" for i in range(25)]
    products = [f"https://marni.com/en-us/jackets-CODE{i}.html" for i in range(40)]
    routes = {
        "/en-us/sitemap_index.xml": httpx.Response(
            200,
            text=index(
                [
                    "https://marni.com/en-us/sitemap_0.xml",
                    "https://marni.com/en-us/sitemap-en-us.xml",
                ]
            ),
        ),
        "/en-us/sitemap_0.xml": httpx.Response(200, text=urlset(looks)),
        "/en-us/sitemap-en-us.xml": httpx.Response(200, text=urlset(products)),
    }
    t = make_transport(routes)
    had = Capability(
        domain="marni.com",
        transport=TransportLevel.T0,
        sitemap_url="https://marni.com/en-us/sitemap_index.xml",
        product_url_prefix="/en-us/",
    )
    got = widen_to_the_biggest_url_family(had, t)
    assert got.sitemap_url == "https://marni.com/en-us/sitemap-en-us.xml"
    assert got.product_url_prefix == "/en-us/"


ACNE_LOCALES = ("it/it", "tw/zh", "us/en")


def acne_sitemap():
    urls = []
    for loc in ACNE_LOCALES:
        urls.append(f"https://acne.com/{loc}/woman/new-arrivals/")
        urls.append(f"https://acne.com/{loc}/woman/clothing/")
        urls += [f"https://acne.com/{loc}/cardigan-{i}/CI{i:04d}-DXT.html" for i in range(30)]
    return urlset(urls)


@pytest.mark.unit
def test_products_in_their_own_folders_are_found_as_the_home_countrys_family():
    """Acne Studios: forty locales in one sitemap, every product in a folder of its own,
    so no parent path is shared and the biggest clusters are the category pages."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sitemap.xml":
            return httpx.Response(200, text=acne_sitemap())
        if path.startswith("/us/en/cardigan-"):
            return httpx.Response(200, text=PRODUCT_PAGE)
        return httpx.Response(200, text=PLAIN_HOME)  # a category page, or another country

    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    from backend.archive.fingerprint import _probe_ldjson

    evidence: dict[str, str] = {}
    found, prefix = _probe_ldjson("https://acne.com/sitemap.xml", t, evidence)
    assert found and prefix == "/us/en/"
    assert evidence["ldjson_sample"].startswith("https://acne.com/us/en/cardigan-")


@pytest.mark.unit
def test_widening_keeps_our_country_of_a_mixed_sitemap():
    t = make_transport({"/sitemap.xml": httpx.Response(200, text=acne_sitemap())})
    had = Capability(
        domain="acne.com",
        transport=TransportLevel.T0,
        sitemap_url="https://acne.com/sitemap.xml",
        product_url_prefix="/us/en/cardigan-1/",
    )
    got = widen_to_the_biggest_url_family(had, t)
    assert got.product_url_prefix == "/us/en/"
    assert got.sitemap_url == "https://acne.com/sitemap.xml"


@pytest.mark.unit
def test_a_sitemap_of_one_country_is_left_alone():
    from backend.archive.fingerprint import _one_market

    urls = [f"https://psylos1.com/en/products/p{i}" for i in range(5)]
    assert _one_market(urls) == urls
    mixed = [f"https://a.com/{loc}/x" for loc in ("fr-fr", "en-us", "de-de")]
    assert _one_market(mixed) == ["https://a.com/en-us/x"]


@pytest.mark.unit
def test_shopify_with_the_feed_off_still_answers_per_product():
    """fengofficiel.com: /products.json is 404, /products/<handle>.json is the product."""
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="Sitemap: https://feng.com/sitemap.xml\n"),
            "/sitemap.xml": httpx.Response(
                200, text=index(["https://feng.com/sitemap_products_1.xml"])
            ),
            "/sitemap_products_1.xml": httpx.Response(
                200, text=urlset(["https://feng.com/", "https://feng.com/products/tights"])
            ),
            "/products.json": httpx.Response(404),
            "/products/tights.json": httpx.Response(200, json={"product": {"handle": "tights"}}),
            "/": httpx.Response(200, text=PLAIN_HOME),
            **NO_WOO,
        }
    )
    cap = probe("feng.com", t, retry_pause=0)
    assert cap.product_json is True and cap.bulk_json is False
    assert cap.evidence["product_json"] == "200-open"
    # The product sitemap is trusted as the list of products, as for any Shopify index.
    assert cap.sitemap_url == "https://feng.com/sitemap_products_1.xml"
    assert cap.product_url_prefix == "/"
    assert "woo_api" not in cap.evidence  # nothing further was asked


@pytest.mark.unit
def test_a_store_that_is_not_shopify_is_not_asked_for_product_json():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="Sitemap: https://x.com/sitemap.xml\n"),
            "/sitemap.xml": httpx.Response(200, text=urlset(["https://x.com/about"])),
            "/products.json": httpx.Response(404),
            "/": httpx.Response(200, text=PLAIN_HOME),
            **NO_WOO,
        }
    )
    cap = probe("x.com", t, retry_pause=0)
    assert cap.product_json is False and "product_json" not in cap.evidence


GATSBY_HOME = (
    '<html><head><link as="fetch" rel="preload" href="/page-data/index/page-data.json">'
    '</head><body><div id="___gatsby"></div></body></html>'
)
DRAWS = {"result": {"pageContext": {"retailers": [{"draws": [{"slug": "ana", "country": "US"}]}]}}}


@pytest.mark.unit
def test_a_gatsby_site_whose_page_data_lists_draws_is_readable():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
            "/sitemap.xml": httpx.Response(200, text=GATSBY_HOME),  # the app's HTML
            "/products.json": httpx.Response(404),
            "/": httpx.Response(200, text=GATSBY_HOME),
            "/page-data/index/page-data.json": httpx.Response(200, json=DRAWS),
            **NO_WOO,
        }
    )
    cap = probe("luar.runfair.com", t, retry_pause=0)
    assert cap.page_data is True and cap.readable()
    assert cap.evidence["page_data"] == "200-draws"
    assert "woo_api" not in cap.evidence


ACNE_ALTERNATES = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
    'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
    + "".join(
        f"<url><loc>https://acne.com/it/it/cardigan-{i}/CI{i:04d}.html</loc>"
        f'<xhtml:link rel="alternate" hreflang="en-us" href="https://acne.com/us/en/cardigan-{i}/CI{i:04d}.html"/>'
        "</url>"
        for i in range(30)
    )
    + "<url><loc>https://acne.com/it/it/only-in-italy/CI9999.html</loc></url></urlset>"
)


@pytest.mark.unit
def test_probing_reads_the_markets_alternate_of_every_entry():
    """Acne Studios: 500 entries per sitemap, canonical in any country, en-us inline."""
    from backend.archive.fingerprint import _entries, _one_sitemap

    urls = _entries(ACNE_ALTERNATES)
    assert len(urls) == 31 and urls[0] == "https://acne.com/us/en/cardigan-0/CI0000.html"
    assert urls[-1] == "https://acne.com/it/it/only-in-italy/CI9999.html"
    t = make_transport({"/sitemap_1.xml": httpx.Response(200, text=ACNE_ALTERNATES)})
    assert _one_sitemap("https://acne.com/sitemap_1.xml", t)[1] == urls


@pytest.mark.unit
def test_an_index_of_many_unnamed_children_stays_the_sitemap_to_read():
    """Acne splits one catalogue over sitemap_1..5.xml; the first is a sample of the
    family, and adopting it would drop four fifths of the products."""
    children = [f"https://acne.com/sitemap_{i}.xml" for i in range(1, 6)]
    routes = {"/sitemap_index.xml": httpx.Response(200, text=index(children))}
    for c in children:
        routes[c.split("acne.com")[1]] = httpx.Response(200, text=ACNE_ALTERNATES)
    t = make_transport(routes)
    had = Capability(
        domain="acne.com",
        transport=TransportLevel.T0,
        sitemap_url="https://acne.com/sitemap_index.xml",
        product_url_prefix="/us/en/cardigan-1/",
    )
    got = widen_to_the_biggest_url_family(had, t)
    assert got.product_url_prefix == "/us/en/"
    assert got.sitemap_url == "https://acne.com/sitemap_index.xml"


SG_WALL = (
    '<html><head><link rel="icon" href="data:;"><meta http-equiv="refresh" '
    'content="0;/.well-known/sgcaptcha/?r=%2F&y=ipr:1.2.3.4:1790541378"></meta></head></html>'
)


@pytest.mark.unit
def test_a_sitegrounds_captcha_wall_is_a_challenge_not_an_empty_room():
    t = make_transport(
        {
            "/robots.txt": httpx.Response(202, text=SG_WALL),
            "/sitemap.xml": httpx.Response(202, text=SG_WALL),
            "/products.json": httpx.Response(202, text=SG_WALL),
            "/": httpx.Response(202, text=SG_WALL),
            **NO_WOO,
        }
    )
    cap = probe("wiacollections.com", t, retry_pause=0)
    assert cap.challenged is True and cap.transport == TransportLevel.T2
    assert not cap.readable()
