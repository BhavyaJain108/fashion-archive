"""What the access rounds taught us about reading a brand, applied on top of the pipeline.

Each learning is a small correction to what fingerprint.probe concluded, found on a real
brand and kept here rather than in the production fingerprint code: this package is
research, and a learning earns its way into the pipeline only after it holds on more than
the brand that taught it. See LEARNINGS.md for the record of where each one came from.
"""

import re

from backend.archive.domain.brand import Capability
from backend.archive.fingerprint import probe

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def prober(domain: str, transport, retry_pause: float = 1.0) -> Capability:
    """fingerprint.probe, then every learning in turn."""
    cap = probe(domain, transport, retry_pause=retry_pause)
    return trust_a_named_product_sitemap(cap, transport)


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
