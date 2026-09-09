"""Bulk Shopify catalog: /products.json is discovery AND fetch in one channel (spec §4.2)."""

import re
import time

from backend.archive.connectors.base import ChannelBlocked, ChannelBusy, SkipProduct
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import (
    ProductRecord,
    ProductRef,
    pack_categories,
    pack_images,
    pack_sizes,
)
from backend.archive.transport import Transport

_TAG_RE = re.compile(r"<[^>]+>")

# A Shopify variant's option1/2/3 line up with the product's own options list, and a
# store chooses that order freely: 437 products in a five-brand sample are laid out
# ("Color", "Size"), so reading option1 as the size stored colours as sizes. A
# single-variant product's one option is "Title" with the value "Default Title", which
# is not a size either. Match on the option's NAME, whatever position it is in.
_SIZE_WORDS = ("size", "taille", "größe", "grösse", "talla", "taglia", "размер")
_COLOR_WORDS = ("color", "colour", "couleur", "farbe", "цвет")
_MATERIAL_WORDS = ("material", "fabric", "matiere", "matière", "stoff")


def _option_index(options: list[str], words: tuple[str, ...]) -> int | None:
    for i, name in enumerate(options[:3]):  # Shopify allows three
        lowered = name.lower()
        if any(w in lowered for w in words):
            return i
    # A feed that names no options at all: its one axis is conventionally the size.
    if not options and words is _SIZE_WORDS:
        return 0
    return None


def _option_values(variants: list[dict], options: list[str], words: tuple[str, ...]) -> list[str]:
    index = _option_index(options, words)
    if index is None:
        return []
    key = f"option{index + 1}"
    seen = {}
    for v in variants:
        value = (v.get(key) or "").strip()
        if value and value.lower() != "default title":
            seen[value] = None
    return list(seen)


def _sizes_from_variants(variants: list[dict], options: list[str]) -> list[dict]:
    """One entry per size, with stock rolled up across the other options.

    With a ("Color", "Size") layout the same size appears once per colour, so a size is
    in stock when any variant carrying it is.
    """
    index = _option_index(options, _SIZE_WORDS)
    if index is None:
        return []
    key = f"option{index + 1}"
    out: dict[str, dict] = {}
    for v in variants:
        label = (v.get(key) or "").strip()
        if not label or label.lower() == "default title":
            continue
        entry = out.setdefault(label, {"size": label, "available": False, "count": 0})
        entry["available"] = entry["available"] or bool(v.get("available"))
        count = v.get("inventory_quantity")
        if isinstance(count, int) and count > 0:
            entry["count"] += count
    for entry in out.values():
        entry["count"] = entry["count"] or None
    return list(out.values())


_MAX_PAGES = 200  # 200 × 250 = 50k products; loop guard, not a coverage cap
_BUSY = (429, 503)  # the store is fine, it wants us to slow down


class ShopifyConnector:
    kind = "shopify"

    def __init__(self, currency: str | None = None, retry_pause: float = 2.0):
        # /products.json states prices with no currency; the store states it once.
        self.currency = currency
        self.retry_pause = retry_pause

    def _page(self, url: str, transport: Transport):
        """One page of the feed, with one patient retry when the store says slow down."""
        resp = transport.get(url)
        if resp.status_code in _BUSY:
            time.sleep(self.retry_pause)
            resp = transport.get(url)
        if resp.status_code in _BUSY:
            raise ChannelBusy(f"{url} → HTTP {resp.status_code}")
        if resp.status_code != 200 or "/password" in str(resp.url):
            raise ChannelBlocked(f"{url} → HTTP {resp.status_code}")
        return resp

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        refs: list[ProductRef] = []
        for page in range(1, _MAX_PAGES + 1):
            url = f"https://{brand.domain}/products.json?limit=250&page={page}"
            products = self._page(url, transport).json().get("products", [])
            if not products:
                break
            for p in products:
                refs.append(
                    ProductRef(
                        url=f"https://{brand.domain}/products/{p['handle']}",
                        change_hint=p.get("updated_at"),
                        payload=p,
                    )
                )
        return refs

    def fetch(self, ref: ProductRef, transport: Transport | None) -> ProductRecord:
        if not ref.payload:
            raise SkipProduct(f"no payload on {ref.url}")
        domain = ref.url.split("/")[2]
        return map_product(ref.payload, domain, self.currency)


def map_product(p: dict, domain: str, currency: str | None = None) -> ProductRecord:
    variants = p.get("variants", [])
    prices = [float(v["price"]) for v in variants if v.get("price") is not None]
    compare = [float(v["compare_at_price"]) for v in variants if v.get("compare_at_price")]
    price = min(prices) if prices else None
    full_price = min(compare) if compare else None
    if full_price is not None and price is not None and full_price <= price:
        full_price = None  # compare_at_price equal/below price is not a sale
    options = [str(o.get("name") or "") for o in p.get("options", [])]
    sizes = _sizes_from_variants(variants, options)
    colors = _option_values(variants, options, _COLOR_WORDS)
    materials = _option_values(variants, options, _MATERIAL_WORDS)
    tags = [t for t in p.get("tags", []) if t]
    # category1..10 is a navigation path, root to leaf. Shopify's tags are a flat,
    # unordered set — appending them here manufactured a hierarchy that does not exist
    # ("Hoodies > unisex > fleece" was never a path the shop published). Tags have their
    # own field. product_type is the one category Shopify actually states.
    categories = [p["product_type"]] if p.get("product_type") else []
    return ProductRecord(
        itemurl=f"https://{domain}/products/{p['handle']}",
        product_title=p["title"],
        # E0005's product_code is the brand's own SKU, not the URL slug. Every Shopify
        # brand was reporting 100% on this field while holding a handle like
        # "ollie-bag-black-croc-embossed" instead of the SKU "12-9383-BLFC-OS".
        product_code=_first(variants, "sku"),
        brand=p.get("vendor"),
        description=_TAG_RE.sub("", p.get("body_html") or "").strip() or None,
        price=price,
        full_price=full_price,
        currency=currency,
        in_stock=any(v.get("available") for v in variants) if variants else None,
        color_info=", ".join(colors) or None,
        material_info=", ".join(materials) or None,
        variant_info=_other_axes(variants, options) or None,
        # A barcode is only usable when it says which kind of barcode it is.
        **_barcode(variants),
        # A sale exists exactly when the struck-through price is above the asking one;
        # there is nothing on the page to extract, it is a relation between two numbers.
        promotion_type="sale" if full_price is not None else None,
        additional_tags=", ".join(tags) or None,
        **pack_sizes(sizes),
        **pack_images([img["src"] for img in p.get("images", []) if img.get("src")]),
        **pack_categories(categories),
        raw=p,
    )


def _first(variants: list[dict], key: str) -> str | None:
    for v in variants:
        value = (v.get(key) or "").strip() if isinstance(v.get(key), str) else v.get(key)
        if value:
            return str(value)
    return None


def _barcode(variants: list[dict]) -> dict:
    """Shopify publishes one barcode field whose kind it does not state.

    Length is the only signal available: GTIN-13/EAN and UPC-A have fixed widths, and
    anything else is a manufacturer code. Guessing beyond that would put a wrong label
    on a real number, which is worse than a general one.
    """
    code = _first(variants, "barcode")
    if not code:
        return {}
    digits = code.isdigit()
    kind = "EAN" if digits and len(code) == 13 else "UPC" if digits and len(code) == 12 else "MPN"
    return {"additional_code_1": code, "additional_code_1_type": kind}


def _other_axes(variants: list[dict], options: list[str]) -> str:
    """The variant axes that are neither size, colour nor material.

    Shoes are sold by width, jewellery by stone, prints by length. E0005 keeps those
    here so the size and colour fields stay comparable across brands.
    """
    claimed = {
        _option_index(options, words) for words in (_SIZE_WORDS, _COLOR_WORDS, _MATERIAL_WORDS)
    } - {None}
    out = []
    for i, name in enumerate(options[:3]):
        if i in claimed or name.lower() in ("title", ""):
            continue
        values = list(
            dict.fromkeys(
                (v.get(f"option{i + 1}") or "").strip()
                for v in variants
                if (v.get(f"option{i + 1}") or "").strip().lower() not in ("", "default title")
            )
        )
        if values:
            out.append(f"{name}: {', '.join(values)}")
    return "; ".join(out)
