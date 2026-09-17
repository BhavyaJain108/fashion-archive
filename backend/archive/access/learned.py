"""What the access rounds taught us about reading a brand, applied on top of the pipeline.

Each learning is a small correction to what fingerprint.probe concluded, found on a real
brand and kept here rather than in the production fingerprint code: this package is
research, and a learning earns its way into the pipeline only after it holds on more than
the brand that taught it. See LEARNINGS.md for the record of where each one came from.
"""

import re

from backend.archive.connectors import get_connector
from backend.archive.domain.brand import Capability
from backend.archive.domain.product import pack_sizes
from backend.archive.fingerprint import probe

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


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


# A size swatch names its size in an attribute whose name contains "size", and says
# whether you can buy it in the neighbouring title/aria-label. Deliberately narrow on the
# value: a wrong size list is worse than none.
# Lookahead for the trailing context: capturing it consumed the next swatch and only the
# first size of each page was ever seen.
_SIZE_ATTR = re.compile(r'data-[\w-]*size[\w-]*="([^"{}]{1,12})"(?=(.{0,160}))', re.I | re.S)
_TITLE = re.compile(r'(?:title|aria-label)="([^"]{0,60})"', re.I)
_SOLD_OUT = ("not available", "out of stock", "sold out", "unavailable")


def sizes_from_swatches(html: str) -> list[dict]:
    """Sizes and their availability, read from variation swatches.

    Learned on Vivienne Westwood (2026-09-17), which runs Salesforce Commerce Cloud and
    renders every size as a swatch:

        data-tau-size-id="XXS" title="XXS (not available)"
        data-tau-size-id="S"   title="S "

    The shared DOM fallback only looks for `data-size` and `data-option-value`, so every
    size on the site was invisible — and with them the per-size stock, which is the whole
    point of re-scraping a fashion catalogue.
    """
    out: dict[str, dict] = {}
    for value, tail in _SIZE_ATTR.findall(html):
        label = value.strip()
        if not label or label in out:
            continue
        title = _TITLE.search(tail)
        available = None
        if title:
            available = not any(s in title.group(1).lower() for s in _SOLD_OUT)
        out[label] = {"size": label, "available": available}
    return list(out.values())


_LOCALE_IN_PATH = re.compile(r"^(https?://[^/]+)/[a-z]{2}-[a-z]{2}/", re.I)


def dedupe_locale_copies(refs: list) -> list:
    """One entry per product, not one per country it is sold in.

    Learned on Vivienne Westwood (2026-09-17): its product sitemap lists every product
    once per locale (/en-fr/, /en-de/, …), so a catalogue of 544 products counted as
    4,352. An inflated count is worse than a wrong one — it reads as success.
    """
    seen: set[str] = set()
    kept = []
    for ref in refs:
        key = _LOCALE_IN_PATH.sub(r"\1/", ref.url)
        if key in seen:
            continue
        seen.add(key)
        kept.append(ref)
    return kept


def drop_landing_pages(refs: list) -> list:
    """Products in one family sit at one depth. Anything shallower is a listing.

    Learned on Van Cleef & Arpels (2026-09-17): its product family /us/en/collections/
    also holds the collection landing pages — /collections/jewelry.html and
    /collections/jewelry/alhambra.html. Those pages carry several Product blocks of their
    own, so the extractor read one happily and produced a "product" named "Jewelry
    collections" priced at whatever was featured that day. They were also the first URLs
    in the sitemap, so they were exactly what the samples measured.

    Of 1,333 URLs, 34 are landings at depth 6-7 and 1,299 are products at depth 8-10.
    Keeping everything at or below the most common depth drops the landings and costs no
    requests. Where every product sits at the same depth this changes nothing.
    """
    if len(refs) < 20:
        return refs
    depths = [ref.url.count("/") for ref in refs]
    modal = max(set(depths), key=depths.count)
    return [ref for ref in refs if ref.url.count("/") >= modal]


class LearnedConnector:
    """Wraps a real connector and applies what later rounds taught us about reading pages."""

    def __init__(self, inner):
        self._inner = inner
        self.kind = getattr(inner, "kind", "learned")

    def discover(self, brand, transport):
        refs = dedupe_locale_copies(self._inner.discover(brand, transport))
        return drop_landing_pages(refs)

    def count(self, brand, transport) -> int:
        return len(self.discover(brand, transport))

    def fetch(self, ref, transport):
        record = self._inner.fetch(ref, transport)
        html = getattr(self._inner, "last_html", None)
        if not record.size_info and html:
            sizes = sizes_from_swatches(html)
            if sizes:
                record = record.model_copy(update=pack_sizes(sizes))
        return record


def connector_factory(plan, sitemap_url=None, limit=None):
    return LearnedConnector(get_connector(plan, sitemap_url=sitemap_url, limit=limit))
