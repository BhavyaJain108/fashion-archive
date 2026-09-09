"""Structured-data fetch: schema.org Product JSON-LD (Google Shopping makes it near-universal),
with OpenGraph fallback. Paired with sitemap discovery (M2 plan Task 3)."""

import json
import re

from backend.archive.connectors.base import SkipProduct
from backend.archive.connectors.sitemap import SitemapConnector
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import (
    ProductRecord,
    ProductRef,
    pack_categories,
    pack_images,
    pack_sizes,
)
from backend.archive.transport import Transport

_LD_BLOCK = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_OG = re.compile(r'<meta[^>]*property="og:(title|image)"[^>]*content="([^"]*)"', re.I)

# DOM size fallback: most storefronts render sizes as a <select> of options or a group of
# buttons/labels carrying a data-size/data-value attribute. Deliberately conservative —
# a wrong size list is worse than none.
_SIZE_SELECT = re.compile(
    r'<select[^>]*(?:name|id|class)="[^"]*siz[^"]*"[^>]*>(.*?)</select>', re.S | re.I
)
_OPTION = re.compile(r"<option[^>]*>(.*?)</option>", re.S | re.I)
_DATA_SIZE = re.compile(r'data-(?:size|option-value)="([^"]{1,12})"', re.I)
_PLACEHOLDER = re.compile(r"^\s*(select|choose|pick|please)\b|^\s*(size|sizes|--|-)?\s*$", re.I)


class StructuredConnector:
    kind = "structured"

    def __init__(self, sitemap_url: str, url_prefix: str | None = None, limit: int | None = None):
        self._sitemap = SitemapConnector(sitemap_url, url_prefix, limit)
        # The page just fetched, so learned rules can run without a second request.
        self.last_html: str | None = None

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        return self._sitemap.discover(brand, transport)

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord:
        resp = transport.get(ref.url)
        if resp.status_code != 200:
            self.last_html = None
            raise SkipProduct(f"{ref.url} → HTTP {resp.status_code}")
        self.last_html = resp.text
        return parse_ldjson_product(resp.text, ref.url)


def parse_ldjson_product(html: str, url: str) -> ProductRecord:
    node = _find_product_node(html)
    if node:
        return _map_product_node(node, url, html)
    og = dict(_OG.findall(html))
    if og.get("title"):
        return ProductRecord(
            itemurl=url,
            product_title=og["title"],
            **pack_images([og["image"]] if og.get("image") else []),
            **pack_sizes(sizes_from_dom(html)),
            raw={"source": "og_meta"},
        )
    raise SkipProduct(f"no Product JSON-LD or OG data on {url}")


def sizes_from_dom(html: str) -> list[dict]:
    """Last-resort size extraction from the rendered HTML."""
    m = _SIZE_SELECT.search(html)
    if m:
        labels = [re.sub(r"<[^>]+>", "", o).strip() for o in _OPTION.findall(m.group(1))]
        labels = [x for x in labels if x and not _PLACEHOLDER.match(x) and len(x) <= 12]
        if labels:
            return [{"size": x} for x in dict.fromkeys(labels)]
    attrs = [x.strip() for x in _DATA_SIZE.findall(html)]
    attrs = [x for x in attrs if x and not _PLACEHOLDER.match(x)]
    if 1 < len(set(attrs)) <= 30:
        return [{"size": x} for x in dict.fromkeys(attrs)]
    return []


def _find_product_node(html: str) -> dict | None:
    for block in _LD_BLOCK.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _iter_nodes(data):
            types = node.get("@type", "")
            types = types if isinstance(types, list) else [types]
            if "Product" in types or "ProductGroup" in types:
                return node
    return None


def _iter_nodes(data):
    if isinstance(data, dict):
        yield data
        yield from _iter_nodes(data.get("@graph", []))
    elif isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)


def _offers_of(node: dict) -> list[dict]:
    """Flatten schema.org's two offer shapes into one list.

    A store with many variants usually publishes one AggregateOffer holding the real
    per-variant offers (xsai.vision: 27 of them). Reading only the outer node found no
    price, no currency and no stock flag on a page that stated all three.
    """
    offers = node.get("offers", [])
    offers = offers if isinstance(offers, list) else [offers]
    out = []
    for o in offers:
        inner = o.get("offers") if isinstance(o, dict) else None
        if isinstance(inner, dict):
            inner = [inner]
        out.extend(inner if inner else [o])
    return out


def _aggregate_price(node: dict) -> float | None:
    """An AggregateOffer states its range instead of a price; the low end is the ask."""
    offers = node.get("offers")
    offers = offers if isinstance(offers, list) else [offers] if offers else []
    lows = [o.get("lowPrice") for o in offers if isinstance(o, dict) and o.get("lowPrice")]
    try:
        return min(float(x) for x in lows) if lows else None
    except (TypeError, ValueError):
        return None


def _sizes_from_node(node: dict) -> list[dict]:
    """schema.org exposes sizes two ways: named offers, or hasVariant ProductGroups."""
    variants = node.get("hasVariant") or []
    if isinstance(variants, dict):
        variants = [variants]
    out = []
    for v in variants:
        label = v.get("size") or v.get("name")
        if isinstance(label, dict):
            label = label.get("name")
        if not label:
            continue
        avail = " ".join(str(o.get("availability", "")) for o in _offers_of(v))
        out.append({"size": str(label), "available": "InStock" in avail})
    if out:
        return out

    named = [o for o in _offers_of(node) if o.get("name")]
    if len(named) >= 2:
        return [
            {"size": o["name"], "available": "InStock" in str(o.get("availability", ""))}
            for o in named
        ]
    return []


def _map_product_node(node: dict, url: str, html: str = "") -> ProductRecord:
    if not node.get("name"):
        raise SkipProduct(f"Product node without a name on {url}")
    offers = _offers_of(node)
    prices = [float(o["price"]) for o in offers if o.get("price") not in (None, "")]
    price = min(prices) if prices else _aggregate_price(node)
    currency = next((o["priceCurrency"] for o in offers if o.get("priceCurrency")), None)
    availabilities = [str(o.get("availability", "")) for o in offers]
    in_stock = any("InStock" in a for a in availabilities) if availabilities else None

    sizes = _sizes_from_node(node)
    if not sizes and html:
        sizes = sizes_from_dom(html)

    brand = node.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    color = node.get("color")
    material = node.get("material")
    if isinstance(material, dict):
        material = material.get("name")

    return ProductRecord(
        itemurl=url,
        product_title=node["name"],
        # E0005 separates the brand's own SKU from barcode-style identifiers, so an
        # mpn belongs in additional_code, never in product_code.
        product_code=node.get("sku") or None,
        **_codes(node),
        specifications=_specifications(node) or None,
        additional_tags=_keywords(node) or None,
        brand=brand,
        description=(node.get("description") or "").strip() or None,
        price=price,
        currency=currency,
        in_stock=in_stock,
        color_info=str(color) if color else None,
        material_info=str(material) if material else None,
        **pack_sizes(sizes),
        **pack_images(_images(node.get("image"))),
        **pack_categories(_categories(node.get("category"))),
        raw={"ldjson": node},
    )


def _categories(cat) -> list[str]:
    if not cat:
        return []
    if isinstance(cat, str):
        return [c.strip() for c in cat.split(">") if c.strip()]
    if isinstance(cat, list):
        return [str(c) for c in cat if c]
    return []


def _images(image) -> list[str]:
    if image is None:
        return []
    if isinstance(image, str):
        return [image]
    if isinstance(image, dict):
        return [image["url"]] if image.get("url") else []
    out = []
    for i in image:
        out.extend(_images(i))
    return out


# schema.org publishes several barcode-style identifiers, each already named by its own
# key — the one case where the type label needs no guessing.
_CODE_KEYS = ("gtin13", "gtin12", "gtin8", "gtin", "ean", "upc", "mpn", "isbn")


def _codes(node: dict) -> dict:
    found = [(k.upper(), str(node[k]).strip()) for k in _CODE_KEYS if node.get(k)]
    out = {}
    for i, (kind, value) in enumerate(found[:3], start=1):
        out[f"additional_code_{i}"] = value
        out[f"additional_code_{i}_type"] = kind
    return out


def _specifications(node: dict) -> str:
    """schema.org additionalProperty is a list of name/value pairs."""
    props = node.get("additionalProperty") or []
    if isinstance(props, dict):
        props = [props]
    pairs = [
        f"{p.get('name')}: {p.get('value')}"
        for p in props
        if isinstance(p, dict) and p.get("name") and p.get("value") not in (None, "")
    ]
    return "; ".join(pairs)


def _keywords(node: dict) -> str:
    words = node.get("keywords")
    if isinstance(words, list):
        return ", ".join(str(w) for w in words if w)
    return str(words).strip() if words else ""
