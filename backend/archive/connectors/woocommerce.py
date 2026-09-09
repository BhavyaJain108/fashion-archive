"""WooCommerce Store API: WordPress's public products.json equivalent (spec §4.2 / M2 plan)."""

import hashlib
import re

from backend.archive.connectors.base import ChannelBlocked, SkipProduct
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
_MAX_PAGES = 200
_PATHS = ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products")


class WooConnector:
    kind = "woo"

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        path = self._resolve_path(brand, transport)
        refs: list[ProductRef] = []
        for page in range(1, _MAX_PAGES + 1):
            url = f"https://{brand.domain}{path}?per_page=100&page={page}"
            resp = transport.get(url)
            if resp.status_code in (401, 403, 429):
                raise ChannelBlocked(f"{url} → HTTP {resp.status_code}")
            if resp.status_code != 200:
                raise ChannelBlocked(f"{url} → HTTP {resp.status_code}")
            products = resp.json()
            if not products:
                break
            for p in products:
                refs.append(ProductRef(url=p["permalink"], change_hint=_hint(p), payload=p))
            if len(products) < 100:
                break
        return refs

    def fetch(self, ref: ProductRef, transport: Transport | None) -> ProductRecord:
        if not ref.payload:
            raise SkipProduct(f"no payload on {ref.url}")
        return map_woo_product(ref.payload)

    def _resolve_path(self, brand: Brand, transport: Transport) -> str:
        for path in _PATHS:
            resp = transport.get(f"https://{brand.domain}{path}?per_page=1")
            if resp.status_code == 200 and resp.text.lstrip().startswith("["):
                return path
            if resp.status_code in (401, 403, 429):
                raise ChannelBlocked(f"{path} → HTTP {resp.status_code}")
        raise ChannelBlocked(f"no woo store api on {brand.domain}")


def _hint(p: dict) -> str:
    prices = p.get("prices") or {}
    basis = f"{p.get('name')}|{prices.get('price')}|{prices.get('regular_price')}|{p.get('is_in_stock')}"
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def map_woo_product(p: dict) -> ProductRecord:
    prices = p.get("prices") or {}
    unit = 10 ** int(prices.get("currency_minor_unit", 2))

    def money(v) -> float | None:
        return None if v in (None, "") else int(v) / unit

    price = money(prices.get("price"))
    full_price = money(prices.get("regular_price"))
    # A shop that marks a product unpurchasable and quotes 0 is not saying it is free,
    # it is declining to name a price. Storing 0.0 asserts something the shop did not:
    # wiacollections has three such rows, all variable products that are out of stock.
    if not p.get("is_purchasable", True):
        # Both of them: a shop declining to price a product declines the struck-through
        # one too, and fixing only `price` left full_price asserting the same falsehood.
        price = None if price == 0 else price
        full_price = None if full_price == 0 else full_price
    if full_price is not None and price is not None and full_price <= price:
        full_price = None
    sizes = []
    for attr in p.get("attributes", []):
        if (attr.get("name") or "").lower() == "size":
            sizes = [{"size": t["name"]} for t in attr.get("terms", []) if t.get("name")]
    return ProductRecord(
        itemurl=p["permalink"],
        product_title=p["name"],
        product_code=p.get("sku") or None,
        # A sale is the relation between the struck-through price and the asking one.
        promotion_type="sale" if full_price is not None else None,
        additional_tags=", ".join(
            t["name"] for t in (p.get("tags") or []) if isinstance(t, dict) and t.get("name")
        )
        or None,
        description=_TAG_RE.sub("", p.get("description") or "").strip() or None,
        price=price,
        full_price=full_price,
        currency=prices.get("currency_code"),
        in_stock=p.get("is_in_stock"),
        **pack_sizes(sizes),
        **pack_images([img["src"] for img in p.get("images", []) if img.get("src")]),
        **pack_categories([c["name"] for c in p.get("categories", []) if c.get("name")]),
        raw=p,
    )
