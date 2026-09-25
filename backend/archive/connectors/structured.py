"""Structured-data fetch: schema.org Product JSON-LD (Google Shopping makes it near-universal),
with OpenGraph fallback. Paired with sitemap discovery (M2 plan Task 3)."""

import json
import re

from backend.archive.connectors.base import NotAProduct, SkipProduct
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
# Open Graph's commerce extension: the one place a page without JSON-LD states a price.
_OG_PRICE = re.compile(
    r'<meta[^>]*property="(?:product|og):price:(amount|currency)"[^>]*content="([^"]*)"', re.I
)

# DOM size fallback: most storefronts render sizes as a <select> of options or a group of
# buttons/labels carrying a data-size/data-value attribute. Deliberately conservative —
# a wrong size list is worse than none.
_SIZE_SELECT = re.compile(
    r'<select[^>]*(?:name|id|class)="[^"]*siz[^"]*"[^>]*>(.*?)</select>', re.S | re.I
)
_OPTION = re.compile(r"<option[^>]*>(.*?)</option>", re.S | re.I)
_DATA_SIZE = re.compile(r'data-(?:size|option-value)="([^"]{1,12})"', re.I)
# A variation swatch names its size in an attribute whose name contains "size" — the name
# itself varies by platform (Salesforce Commerce Cloud writes data-tau-size-id) — and says
# whether you can buy it in the neighbouring title. Matching only data-size missed every
# size on Vivienne Westwood, and with them the per-size stock. Lookahead on the tail, or
# each match eats the next swatch.
_SWATCH_SIZE = re.compile(r'data-[\w-]*size[\w-]*="([^"{}]{1,12})"(?=(.{0,160}))', re.I | re.S)
_SWATCH_TITLE = re.compile(r'(?:title|aria-label)="([^"]{0,60})"', re.I)
_SOLD_OUT = ("not available", "out of stock", "sold out", "unavailable")
# A variant SKU says what the variant is after a double dash: 1802002B-C00A1--RED.
# Letters and hyphens only, so a plain SKU segment cannot pass itself off as a colour.
_VARIANT_SUFFIX = re.compile(r"--([A-Za-z][A-Za-z -]{1,23})$")
# Colour words, so a variant that names a print or a material does not become a colour.
# Deliberately a short list of plain words: the point is to recognise the common case and
# abstain on the rest, not to catalogue every shade a fashion house invents.
_COLOUR_WORDS = frozenset(
    """
black white red blue green navy gold silver platinum ivory cream beige brown grey gray
pink purple violet yellow orange multi tan burgundy khaki olive lime teal charcoal bronze
nude camel rose copper sand stone ecru taupe aubergine mustard turquoise
""".split()
)
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
    money = dict(_OG_PRICE.findall(html))
    # A page with no Product JSON-LD is a product only if it at least names a price.
    # Entire Studios' sitemap lists 987 retired pages that say "currently unavailable"
    # and carry og:title, sometimes a photograph, and never a price; stored, they were
    # 72% of the brand's live count and nothing on them could be bought. Skipped, a page
    # is picked up the day it comes back with data.
    price = _money(money.get("amount"))
    if og.get("title") and price is not None:
        return ProductRecord(
            itemurl=url,
            product_title=og["title"],
            price=price,
            currency=(money.get("currency") or "").strip().upper() or None,
            **pack_images([og["image"]] if og.get("image") else []),
            **pack_sizes(sizes_from_dom(html)),
            raw={"source": "og_meta"},
        )
    raise NotAProduct(f"no product data on {url} (no JSON-LD Product, no price)")


def _money(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


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
    return sizes_from_swatches(html)


def sizes_from_swatches(html: str) -> list[dict]:
    """Sizes and their availability, from variation swatches under any attribute name."""
    out: dict[str, dict] = {}
    for value, tail in _SWATCH_SIZE.findall(html):
        label = value.strip()
        if not label or label in out or _PLACEHOLDER.match(label):
            continue
        title = _SWATCH_TITLE.search(tail)
        available = None
        if title:
            available = not any(s in title.group(1).lower() for s in _SOLD_OUT)
        out[label] = {"size": label, "available": available}
    return list(out.values()) if len(out) > 1 else []


def _text_or_none(value) -> str | None:
    """A JSON-LD scalar as text, or None when the shop left it out. Numbers are
    kept as their digits; an empty string is an absence, not a code."""
    if value is None or isinstance(value, (list, dict)):
        return None
    text = str(value).strip()
    return text or None


def variant_from_sku(sku: str | int | None) -> str | None:
    """What a variant SKU names after its double dash.

    Vivienne Westwood publishes no `color` in its JSON-LD and the page's only other
    colour markup is a swatch id, but its SKUs carry the variant: of 4,336 products,
    2,576 end in a suffix like --BLACK, --LIME-GREEN, --PRIMAVERA-CHERUBS. The rest name
    no variant and get nothing, which is the honest answer rather than a guess.

    Deliberately not read from `data-*color*` attributes, the shape that worked for
    sizes: Van Cleef's pages carry data-affirm-color="black" on a financing widget, and
    that rule would have recorded a gold necklace as black.
    """
    if sku is None or sku == "":
        return None
    # JSON-LD carries whatever the shop's template printed: WIA Collections
    # publishes its SKUs as bare numbers, and a number has nothing to strip.
    m = _VARIANT_SUFFIX.search(str(sku).strip())
    return m.group(1).replace("-", " ").strip() if m else None


def color_from_variant(variant: str | None) -> str | None:
    """The variant, when it actually names a colour.

    A variant is usually a colourway and sometimes not: Vivienne Westwood's Worlds End
    Swing Dress is --SEX, after the shop, and others are prints (PRIMAVERA CHERUBS) or
    materials (BLACK PU GRAIN). Recording those as colours would be confidently wrong in
    a field a shopper filters on, so a variant reaches color_info only when one of its
    words is a colour.
    """
    if not variant:
        return None
    words = {w.lower() for w in variant.replace("/", " ").split()}
    return variant if words & _COLOUR_WORDS else None


def categories_from_breadcrumbs(html: str, product_title: str | None = None) -> list[str]:
    """The category path, from BreadcrumbList JSON-LD.

    The shape is the same on every storefront that publishes it: the first crumb is the
    site root, the last is the product itself, and what is left is the path a shopper
    walked to reach it. A shop whose breadcrumbs are only brand then product has no
    category level, and gets none — inventing one would be worse than the blank.
    """
    crumbs = _breadcrumb_names(html)
    if len(crumbs) < 2:
        return []
    names = crumbs[1:]
    if names and _is_the_product(names[-1], product_title):
        names = names[:-1]
    return [n for n in names if n]


def _breadcrumb_names(html: str) -> list[str]:
    for block in _LD_BLOCK.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _iter_nodes(data):
            if isinstance(node, dict) and node.get("@type") == "BreadcrumbList":
                items = node.get("itemListElement") or []
                ordered = sorted(items, key=lambda i: i.get("position", 0))
                return [_crumb_name(i) for i in ordered]
    return []


def _crumb_name(item: dict) -> str:
    name = item.get("name")
    if not name and isinstance(item.get("item"), dict):
        name = item["item"].get("name")
    return (name or "").strip()


def _is_the_product(crumb: str, title: str | None) -> bool:
    """Sites truncate the last crumb, so compare loosely."""
    if not title:
        return True
    a, b = crumb.strip().lower(), title.strip().lower()
    return a.startswith(b[:20]) or b.startswith(a[:20])


def _find_product_node(html: str) -> dict | None:
    """The product node, preferring one that states a price.

    A page may publish both a ProductGroup (the style: name, description, the list of
    colours) and the Product actually on the page (the price, the images, the stock).
    Taking whichever came first gave a title and nothing else on the pages that put the
    group first — Gentle Monster, where it cost us price, stock and images on 3 of every
    5 products (2026-09-17).
    """
    candidates = []
    for block in _LD_BLOCK.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _iter_nodes(data):
            types = node.get("@type", "")
            types = types if isinstance(types, list) else [types]
            if "Product" in types or "ProductGroup" in types:
                candidates.append(node)
    if not candidates:
        return None
    # A node's own offers, not its variants': a ProductGroup that lists its variants'
    # offers must not outrank the Product actually on the page.
    return next((n for n in candidates if _own_offers(n)), candidates[0])


def _iter_nodes(data):
    if isinstance(data, dict):
        yield data
        yield from _iter_nodes(data.get("@graph", []))
    elif isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)


def _own_offers(node: dict) -> list[dict]:
    """Flatten schema.org's two offer shapes into one list.

    A store with many variants usually publishes one AggregateOffer holding the real
    per-variant offers (xsai.vision: 27 of them). Reading only the outer node found no
    price, no currency and no stock flag on a page that stated all three.
    """
    offers = node.get("offers", [])
    offers = offers if isinstance(offers, list) else [offers]
    out: list[dict] = []
    for o in offers:
        inner = o.get("offers") if isinstance(o, dict) else None
        if isinstance(inner, dict):
            inner = [inner]
        out.extend(inner if inner else [o])
    return out


def _offers_of(node: dict) -> list[dict]:
    """The node's offers, or its variants' when it states none of its own.

    schema.org's third shape: a ProductGroup with no `offers` at all, each
    `hasVariant` Product carrying its own. Entire Studios publishes 384 of its 1,377
    pages this way (2026-09-24) — one price and one stock flag per size, and nothing
    on the group — and reading only the group left every one of them without a price,
    a currency or a stock flag.
    """
    own = _own_offers(node)
    if own:
        return own
    variants = node.get("hasVariant") or []
    if isinstance(variants, dict):
        variants = [variants]
    out: list[dict] = []
    for v in variants:
        if isinstance(v, dict):
            out.extend(_own_offers(v))
    return out


def _aggregate_price(node: dict) -> float | None:
    """An AggregateOffer states its range instead of a price; the low end is the ask."""
    offers = node.get("offers")
    offers = offers if isinstance(offers, list) else [offers] if offers else []
    lows = [o.get("lowPrice") for o in offers if isinstance(o, dict) and o.get("lowPrice")]
    try:
        return min(float(x) for x in lows if x is not None) if lows else None
    except (TypeError, ValueError):
        return None


def _sizes_from_node(node: dict) -> list[dict]:
    """schema.org exposes sizes two ways: named offers, or hasVariant ProductGroups."""
    variants = node.get("hasVariant") or []
    if isinstance(variants, dict):
        variants = [variants]
    out: list[dict] = []
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
    variant = variant_from_sku(node.get("sku"))
    color = node.get("color") or color_from_variant(variant)
    material = node.get("material")
    if isinstance(material, dict):
        material = material.get("name")

    return ProductRecord(
        itemurl=url,
        product_title=node["name"],
        # E0005 separates the brand's own SKU from barcode-style identifiers, so an
        # mpn belongs in additional_code, never in product_code.
        product_code=_text_or_none(node.get("sku")),
        **_codes(node),
        specifications=_specifications(node) or None,
        additional_tags=_keywords(node) or None,
        brand=brand,
        description=(node.get("description") or "").strip() or None,
        price=price,
        currency=currency,
        in_stock=in_stock,
        color_info=str(color) if color else None,
        variant_info=variant,
        material_info=str(material) if material else None,
        **pack_sizes(sizes),
        **pack_images(_images(node.get("image"))),
        **pack_categories(
            _categories(node.get("category")) or categories_from_breadcrumbs(html, node["name"])
        ),
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
