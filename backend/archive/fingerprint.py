"""One polite HTTP round per brand → Capability (spec §4.0; ~4 GETs, seconds, $0)."""

import re
import time

from backend.archive.domain.brand import Capability, TransportLevel
from backend.archive.transport import Transport

# Interstitials say so in the body; block pages say so in the <title>.
_CHALLENGE_MARKERS = ("verifying your connection", "checking your browser")
_BLOCK_TITLES = ("access denied", "attention required", "just a moment", "forbidden")
_PASSWORD_MARKERS = ("password", "opening soon", "coming soon")
# Statuses that mean "the edge is deciding about you", not "no". Worth exactly one retry:
# gentlemonster served a sitemap on one probe and a challenge on the next (live, 2026-08-30).
_TRANSIENT = (202, 403, 429, 500, 502, 503, 504)


# A homepage link whose words or path say "shop": La Lune's site is a portfolio and its
# nav sends buyers to shop.laluneofficial.com, a WooCommerce store our probe of the
# bare domain never saw. Followed once, only when the brand's own host has no feed.
_ANCHOR = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_SHOP_WORDS = re.compile(r"\b(shop|store)\b", re.I)


def shop_link(body: str, domain: str) -> str | None:
    """The other host the homepage sends shoppers to, if there is one."""
    own = domain.removeprefix("www.")
    for href, text in _ANCHOR.findall(body):
        host = href.split("/", 3)[2].lower()
        if host.removeprefix("www.") == own:
            continue
        label = re.sub(r"<[^>]+>|\s+", " ", text)
        path = "/" + href.split("/", 3)[3] if href.count("/") >= 3 else "/"
        if _SHOP_WORDS.search(label) or _SHOP_WORDS.search(path.split("?")[0]):
            return host
    return None


def probe(
    domain: str, transport: Transport, retry_pause: float = 1.0, follow_shop: bool = True
) -> Capability:
    base = f"https://{domain}"
    evidence: dict[str, str] = {}

    def get(url: str):
        resp = transport.get(url)
        if resp.status_code in _TRANSIENT:
            if retry_pause:
                time.sleep(retry_pause)
            resp = transport.get(url)
        return resp

    sitemap_url = None
    robots = get(f"{base}/robots.txt")
    if robots.status_code == 200:
        m = re.search(r"(?im)^sitemap:\s*(\S+)", robots.text)
        if m:
            sitemap_url = m.group(1)
            evidence["robots"] = "sitemap"
    if sitemap_url is None:
        sm = get(f"{base}/sitemap.xml")
        if sm.status_code == 200 and "<" in sm.text[:200]:
            sitemap_url = f"{base}/sitemap.xml"
            evidence["robots"] = "direct-sitemap"

    pj = get(f"{base}/products.json?limit=1")
    bulk_json = pj.status_code == 200 and '"products"' in pj.text[:200]
    evidence["products_json"] = f"{pj.status_code}-{'open' if bulk_json else 'closed'}"

    # Shopify's product feed states prices without a currency; the store states it
    # once, for every product, at /meta.json. One request per brand, only on Shopify.
    currency = None
    if bulk_json:
        meta = get(f"{base}/meta.json")
        if meta.status_code == 200:
            try:
                currency = (meta.json() or {}).get("currency") or None
            except ValueError:
                currency = None
        evidence["meta_json"] = f"{meta.status_code}-{currency or 'no-currency'}"

    home = get(f"{base}/")
    evidence["homepage"] = str(home.status_code)
    # A block page still has a body, and its title is the clearest evidence we get
    # (outlw.xyz answers "access denied" under HTTP 401). Read it whatever the status;
    # only trust it for platform/password facts when the page was actually served.
    body = home.text.lower()
    served = home.status_code == 200

    password_gated = served and (
        "/password" in str(home.url) or any(m in _title(body) for m in _PASSWORD_MARKERS)
    )
    challenged = (
        home.status_code in (401, 403, 429)
        or pj.status_code in (401, 403, 429)
        or any(m in body for m in _CHALLENGE_MARKERS)
        or any(m in _title(body) for m in _BLOCK_TITLES)
    )

    platform = None
    if served and ("cdn.shopify" in body or "myshopify.com" in body):
        platform = "shopify"
    elif served and "woocommerce" in body:
        platform = "woocommerce"
    elif served and "wp-content" in body:
        platform = "wordpress"

    # Deep probes: only pay for them when the free Shopify feed is closed and the door is open.
    woo_api = False
    ldjson_product = False
    product_url_prefix = None
    # A challenged site is not worth extra plain-HTTP requests, but once a browser is
    # paying for the page anyway, look: that is the only way a blocked site's product
    # URL prefix is ever learned.
    level = getattr(transport, "level", TransportLevel.T0)
    if not bulk_json and not password_gated and (not challenged or level == TransportLevel.T2):
        woo_api = _probe_woo(base, transport, evidence)
        if not woo_api and sitemap_url:
            ldjson_product, product_url_prefix = _probe_ldjson(sitemap_url, transport, evidence)

    if password_gated:
        transport_level = TransportLevel.T4
    elif challenged:
        transport_level = TransportLevel.T2
    else:
        transport_level = TransportLevel.T0

    cap = Capability(
        domain=domain,
        platform=platform,
        transport=transport_level,
        bulk_json=bulk_json,
        woo_api=woo_api,
        ldjson_product=ldjson_product,
        product_url_prefix=product_url_prefix,
        sitemap_url=sitemap_url,
        password_gated=password_gated,
        challenged=challenged,
        currency=currency,
        evidence=evidence,
    )
    if (
        follow_shop
        and served
        and not password_gated
        and not any((bulk_json, woo_api, ldjson_product))
    ):
        host = shop_link(home.text, domain)
        if host:
            evidence["shop_link"] = cap.evidence["shop_link"] = host
            shop = probe(host, transport, retry_pause, follow_shop=False)
            if shop.bulk_json or shop.woo_api or shop.ldjson_product:
                return shop.model_copy(
                    update={
                        "domain": domain,
                        "shop_domain": host,
                        "evidence": {
                            **evidence,
                            **{f"shop.{k}": v for k, v in shop.evidence.items()},
                        },
                    }
                )
    return _sharpen_discovery(cap, transport)


def _sharpen_discovery(cap: Capability, transport: Transport) -> Capability:
    """Correct which sitemap to read and which of its URLs are products.

    The prefix is otherwise learned from one sampled page, which is wrong wherever a store
    gives each product its own folder: Vivienne Westwood matched 6 colour variants of one
    card holder, Gentle Monster matched one frame. Worse, leaving the sitemap as the index
    sends discovery walking the image sitemap, which is where a run goes quiet for ten
    minutes and spends bandwidth on nothing.
    """
    # A store with its own feed does not need its sitemap read: the product URLs come from
    # the feed. Sharpening it anyway would spend two requests per brand on the 23 that
    # already work, to change nothing.
    if cap.bulk_json or cap.woo_api:
        return cap
    if not cap.sitemap_url or cap.password_gated:
        return cap
    cap = _trust_a_named_product_sitemap(cap, transport)
    return _widen_to_the_biggest_url_family(cap, transport)


_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
# Which child of a multi-country sitemap index to read. We browse as a US visitor.
_LOCALE_PREFERENCE = ("/us/", "/en-us/", "/int/", "/en/")


def _trust_a_named_product_sitemap(cap: Capability, transport) -> Capability:
    """A sitemap index that names one child as the product sitemap has told us which URLs
    are products. Guessing a URL pattern from a sample is worse than believing it.

    Learned on Vivienne Westwood (2026-09-17): products live at
    /women/<category>/<subcategory>/<slug>/<SKU>.html, so the pattern learned from one
    sample was that one product's own folder, and discovery found 6 colour variants of a
    card holder. The index lists sitemap_0-product.xml.
    """
    if not cap.sitemap_url:
        return cap
    resp = transport.get(cap.sitemap_url)
    if resp.status_code != 200 or "<sitemapindex" not in resp.text:
        return cap
    named = [u for u in _LOC.findall(resp.text) if "product" in u.rsplit("/", 1)[-1].lower()]
    if len(named) != 1:
        return cap  # none, or several we cannot choose between
    evidence = {**cap.evidence, "learned": "named-product-sitemap"}
    return cap.model_copy(
        update={"sitemap_url": named[0], "product_url_prefix": "/", "evidence": evidence}
    )


# Which child of a multi-country sitemap index to read. We browse as a US visitor.
_LOCALE_PREFERENCE = ("/us/", "/en-us/", "/int/", "/en/")


def _widen_to_the_biggest_url_family(cap: Capability, transport) -> Capability:
    """Products are the biggest family of URLs in a store's sitemap.

    Learned on Gentle Monster (2026-09-17): products sit at /us/en/item/<code>/<slug>, one
    folder each, so the pattern learned from a sample was a single product's folder. And
    its sitemap index has one child per country, of which the probe happened to read Korea.
    Of 1,395 URLs in the US sitemap, 1,332 share /us/en/item/.

    Rule: read one sitemap (the named product one, else the US one, else the first), find
    the deepest folder that holds at least half its URLs, and use it if it matches more
    URLs than the pattern we had. A prefix of "/" means an earlier learning already found
    a sitemap of nothing but products, so there is nothing to widen.
    """
    if not cap.sitemap_url or cap.product_url_prefix == "/":
        return cap
    sitemap_url, urls = _one_sitemap(cap.sitemap_url, transport)
    if len(urls) < 20:
        return cap

    paths = ["/" + u.split("/", 3)[3] if u.count("/") >= 3 else "/" for u in urls]
    counts: dict[str, int] = {}
    for path in paths:
        segs = [s for s in path.split("/") if s]
        for depth in range(1, len(segs)):
            folder = "/" + "/".join(segs[:depth]) + "/"
            counts[folder] = counts.get(folder, 0) + 1
    family = [f for f, n in counts.items() if n * 2 >= len(urls)]
    if not family:
        return cap
    best = max(family, key=lambda f: (f.count("/"), counts[f]))

    current = sum(p.startswith(cap.product_url_prefix or "\0") for p in paths)
    if counts[best] <= current:
        return cap
    evidence = {**cap.evidence, "learned_family": f"{best} ({counts[best]} of {len(urls)})"}
    return cap.model_copy(
        update={"sitemap_url": sitemap_url, "product_url_prefix": best, "evidence": evidence}
    )


def _one_sitemap(url: str, transport, depth: int = 0) -> tuple[str, list[str]]:
    resp = transport.get(url)
    if resp.status_code != 200:
        return url, []
    locs = _LOC.findall(resp.text)
    if "<sitemapindex" not in resp.text or depth > 0:
        return url, [u for u in locs if not u.endswith(".xml")]
    named = [u for u in locs if "product" in u.rsplit("/", 1)[-1].lower()]
    by_locale = [u for pref in _LOCALE_PREFERENCE for u in locs if pref in u]
    chosen = (named or by_locale or locs or [None])[0]
    return _one_sitemap(chosen, transport, depth + 1) if chosen else (url, [])


def _probe_woo(base: str, transport: Transport, evidence: dict[str, str]) -> bool:
    for path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
        resp = transport.get(f"{base}{path}?per_page=1")
        if resp.status_code == 200 and resp.text.lstrip().startswith("["):
            evidence["woo_api"] = path
            return True
    return False


_LOC = re.compile(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", re.I)
_CHILD_SITEMAP = re.compile(r"<loc>\s*(https?://[^<]+\.xml[^<]*)\s*</loc>", re.I)
# Segment names that conventionally hold products — tried before bigger unknown clusters.
_CONVENTIONAL = ("products", "product", "shop", "item", "items", "p")


def _probe_ldjson(
    sitemap_url: str, transport: Transport, evidence: dict[str, str]
) -> tuple[bool, str | None]:
    """Learn this brand's product-URL shape, then confirm those pages carry Product JSON-LD.

    Sites put products wherever they like — outlw.xyz uses /assets/ (live bug 2026-08-30).
    So cluster the sitemap by first path segment and test the plausible clusters rather
    than assuming /products/. Costs at most 3 page fetches.
    """
    urls = _sitemap_urls(sitemap_url, transport)
    if not urls:
        return False, None

    # Cluster on the parent path, not the first segment: locale-prefixed sites put products
    # at /en/products/<slug>, so first-segment clustering groups the whole site under /en/
    # (regression found on psylos1, 2026-08-30).
    clusters: dict[str, list[str]] = {}
    for u in urls:
        segments = [x for x in u.split("/", 3)[-1].split("/") if x] if u.count("/") > 3 else []
        if len(segments) < 2:
            continue  # a top-level page has no parent path to learn from
        prefix = "/" + "/".join(segments[:-1]) + "/"
        clusters.setdefault(prefix, []).append(u)
    if not clusters:
        return False, None

    def conventional(prefix: str) -> bool:
        return any(seg in _CONVENTIONAL for seg in prefix.strip("/").split("/"))

    ranked = sorted(clusters.items(), key=lambda kv: (not conventional(kv[0]), -len(kv[1])))
    for prefix, members in ranked[:3]:
        page = transport.get(members[0])
        if page.status_code != 200:
            continue
        if "application/ld+json" in page.text and '"Product"' in page.text:
            evidence["ldjson_sample"] = members[0]
            return True, prefix
    return False, None


def _sitemap_urls(sitemap_url: str, transport: Transport, depth: int = 0) -> list[str]:
    resp = transport.get(sitemap_url)
    if resp.status_code != 200:
        return []
    text = resp.text
    if "<sitemapindex" in text and depth == 0:
        children = _CHILD_SITEMAP.findall(text)
        preferred = [c for c in children if "product" in c.lower()] or children[:2]
        out: list[str] = []
        for child in preferred:
            out.extend(_sitemap_urls(child, transport, depth + 1))
        return out
    return [u for u in _LOC.findall(text) if not u.endswith(".xml")]


def _title(body: str) -> str:
    m = re.search(r"<title>([^<]*)</title>", body)
    return m.group(1) if m else ""
