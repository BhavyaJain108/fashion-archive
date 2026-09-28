"""What kind of shop this is, in six words.

Every rule the loop learns is about a *shape*, not a brand: "Salesforce Commerce with
hreflang alternates inline", "Shopify-shaped index with the feed off". The signature
is that shape written down, computed by the probe from what it already saw, so a rule
can say which brands it applies to, a regression set can be listed rather than guessed,
and the roster can be read as clusters — which is how the space organises itself.

Coarse on purpose. A signature that matches exactly one brand for ever is a brand name
wearing a disguise, and the loop flags it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from backend.archive.domain.brand import Capability, TransportLevel

PLATFORMS = (
    "shopify",
    "swell",
    "haravan",
    "woocommerce",
    "wordpress",
    "sfcc",
    "squarespace",
    "cargo",
    "gatsby",
    "nextjs",
    "webflow",
    "custom",
)
FEEDS = ("open", "per-product", "woo", "page-data", "api", "closed")
SITEMAPS = ("none", "flat", "index", "named-product", "multi-locale", "alternates")
PAGES = ("jsonld", "productgroup", "og", "none")
DEFENCES = ("none", "rate", "tls", "address", "challenge", "geo", "password")
LOCALES = ("none", "path", "country-path")

_LOCALE_PATH = re.compile(r"^/[a-z]{2}-[a-z]{2}/", re.I)
_COUNTRY_PATH = re.compile(r"^/[a-z]{2}/[a-z]{2}/", re.I)


class Signature(BaseModel):
    platform: str = "custom"
    feed: str = "closed"
    sitemap: str = "none"
    page: str = "none"
    defence: str = "none"
    locale: str = "none"

    @property
    def key(self) -> str:
        return "·".join(
            (self.platform, self.feed, self.sitemap, self.page, self.defence, self.locale)
        )

    @classmethod
    def parse(cls, key: str) -> Signature:
        parts = key.split("·")
        if len(parts) != 6:
            raise ValueError(f"not a signature: {key!r}")
        return cls(
            platform=parts[0],
            feed=parts[1],
            sitemap=parts[2],
            page=parts[3],
            defence=parts[4],
            locale=parts[5],
        )

    def likeness(self, other: Signature) -> int:
        """How many of the six words two shops share. Platform and feed count double:
        they decide the lane; the rest decide how hard it is to walk."""
        score = 0
        score += 2 if self.platform == other.platform else 0
        score += 2 if self.feed == other.feed else 0
        score += int(self.sitemap == other.sitemap)
        score += int(self.page == other.page)
        score += int(self.defence == other.defence)
        score += int(self.locale == other.locale)
        return score


def signature_of(cap: Capability, ladder: list[dict] | None = None) -> Signature:
    """The signature the probe's own evidence supports. `ladder` is the dossier's
    rung history (outcome per level), which says what the defence is when the
    Capability alone only says "challenged"."""
    ev = cap.evidence or {}
    platform = (
        cap.platform if cap.platform in PLATFORMS else ("custom" if cap.platform else "custom")
    )

    if cap.swell_store and cap.swell_key:
        feed = "api"
    elif cap.bulk_json:
        feed = "open"
    elif cap.product_json:
        feed = "per-product"
    elif cap.woo_api:
        feed = "woo"
    elif cap.page_data:
        feed = "page-data"
    else:
        feed = "closed"

    if not cap.sitemap_url:
        sitemap = "none"
    elif ev.get("learned") == "named-product-sitemap" or "sitemap_products_" in (
        cap.sitemap_url or ""
    ):
        sitemap = "named-product"
    elif ev.get("sitemap_alternates"):
        sitemap = "alternates"
    elif ev.get("sitemap_locales"):
        sitemap = "multi-locale"
    elif ev.get("sitemap_shape") == "index":
        sitemap = "index"
    else:
        sitemap = "flat"

    kind = ev.get("ldjson_kind")
    if cap.ldjson_product and kind in ("jsonld", "productgroup", "og"):
        page = kind
    elif cap.ldjson_product:
        page = "jsonld"
    elif ev.get("ldjson_kind") == "og":
        page = "og"
    else:
        page = "none"

    defence = _defence(cap, ladder or [])

    prefix = cap.product_url_prefix or ""
    loc_ev = ev.get("sitemap_locale") or ""
    if _COUNTRY_PATH.match(prefix):
        locale = "country-path"
    elif _LOCALE_PATH.match(prefix) or loc_ev:
        locale = "path"
    else:
        locale = "none"

    return Signature(
        platform=platform, feed=feed, sitemap=sitemap, page=page, defence=defence, locale=locale
    )


def _defence(cap: Capability, ladder: list[dict]) -> str:
    if cap.password_gated:
        return "password"
    latest: dict[str, str] = {}
    for rung in ladder:
        level = str(rung.get("level") or rung.get("strategy") or "")
        if level:
            latest[level] = str(rung.get("outcome") or "")
    outcomes = set(latest.values())
    if "geo" in outcomes:
        return "geo"
    if outcomes and outcomes <= {"waf_403", "unreachable", "tls_blocked"} and len(latest) >= 2:
        # Refused at every rung that changes the handshake: the address is what is judged.
        return "address"
    if "tls_blocked" in outcomes:
        return "tls"
    if "rate_429" in outcomes:
        return "rate"
    if "challenge" in outcomes:
        return "challenge"
    if cap.challenged and cap.transport in (TransportLevel.T2,):
        return "challenge"
    if cap.challenged:
        return "rate" if cap.evidence.get("products_json", "").startswith("429") else "challenge"
    return "none"
