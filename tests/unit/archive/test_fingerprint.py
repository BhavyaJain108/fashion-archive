import httpx
import pytest

from backend.archive.domain.brand import TransportLevel
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
