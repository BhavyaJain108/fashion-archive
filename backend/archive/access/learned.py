"""Corrections to what fingerprint.probe concluded about a brand.

Each is a small rule found on a real brand and verified on the ones that did not teach it.
The rules about reading a *page* — sizes from swatches, categories from breadcrumbs, one
product per country, landing pages — have graduated into the connectors themselves, since
they hold everywhere. What stays here is discovery: which sitemap to read and which URLs
in it are products. See LEARNINGS.md for where each came from.
"""

import re

from backend.archive.domain.brand import Capability
from backend.archive.fingerprint import probe

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_LD_BLOCKS = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)


def prober(domain: str, transport, retry_pause: float = 1.0) -> Capability:
    """fingerprint.probe, then every learning in turn."""
    cap = probe(domain, transport, retry_pause=retry_pause)
    cap = trust_a_named_product_sitemap(cap, transport)
    return widen_to_the_biggest_url_family(cap, transport)


def trust_a_named_product_sitemap(cap: Capability, transport) -> Capability:
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


def widen_to_the_biggest_url_family(cap: Capability, transport) -> Capability:
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
