"""Swell (swell.is), a headless commerce platform: the catalogue behind a storefront API.

yeezy.com (2026-09-27): a Svelte app whose product tiles are buttons carrying Swell
object ids, whose images all resolve to cdn.swell.store/<store>/, and whose HTML embeds
the store's publishable key (pk_...) beside the Google Pay config. The page has no
JSON-LD, no feed, no sitemap, and Cloudflare blocks our address on every path but the
root. The storefront API on <store>.swell.store is a different host under no such rule:
/api/products lists every product with price, sale price, SKU, stock, options, images
and description, paginated, authenticated with the publishable key as HTTP basic auth
(store:key) — the same call the site's own JavaScript makes. One request per hundred
products, plus one per product for its variants (which size is in stock).
"""

from typing import Any

from backend.archive.connectors.base import ChannelBlocked, SkipProduct
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord, ProductRef, pack_categories, pack_images
from backend.archive.transport import Transport

PAGE = 100


def api_url(store: str, key: str, path: str) -> str:
    """The storefront API with the publishable key as basic auth in the URL: every
    transport we own sends it, and the key is public by design (it is in the page)."""
    return f"https://{store}:{key}@{store}.swell.store/api/{path}"


class SwellConnector:
    kind = "swell"

    def __init__(self, store: str, key: str, currency: str | None = None, limit: int | None = None):
        self.store = store
        self.key = key
        self.currency = currency
        self.limit = limit

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        refs: list[ProductRef] = []
        page = 1
        while True:
            url = api_url(self.store, self.key, f"products?limit={PAGE}&page={page}")
            resp = transport.get(url)
            if resp.status_code != 200:
                raise ChannelBlocked(
                    f"swell {self.store} products page {page} → HTTP {resp.status_code}"
                )
            try:
                data = resp.json()
            except ValueError:
                raise ChannelBlocked(
                    f"swell {self.store}: products page {page} is not JSON"
                ) from None
            results = data.get("results") or []
            for p in results:
                if not isinstance(p, dict) or not p.get("slug"):
                    continue
                refs.append(
                    ProductRef(
                        url=f"https://{brand.domain}/products/{p['slug']}",
                        change_hint=p.get("date_updated"),
                        payload=p,
                    )
                )
                if self.limit is not None and len(refs) >= self.limit:
                    return refs
            total = int(data.get("count") or 0)
            if len(results) < PAGE or page * PAGE >= total:
                return refs
            page += 1

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord:
        p = ref.payload or {}
        if not p:
            raise SkipProduct(f"{ref.url}: no product in the payload")
        variants = self._variants(p, transport)
        return map_product(
            p, ref.url, variants, brand_name=_brand_name(ref.url), currency=self.currency
        )

    def _variants(self, p: dict, transport: Transport) -> list[dict]:
        pid = p.get("id")
        if not pid or not (p.get("options") or []):
            return []
        resp = transport.get(api_url(self.store, self.key, f"products/{pid}/variants?limit={PAGE}"))
        if resp.status_code != 200:
            return []
        try:
            return [v for v in (resp.json().get("results") or []) if isinstance(v, dict)]
        except ValueError:
            return []


def map_product(
    p: dict, url: str, variants: list[dict], brand_name: str | None, currency: str | None
) -> ProductRecord:
    title = (p.get("name") or "").strip()
    if not title:
        raise SkipProduct(f"{url}: product without a name")
    price = _money(p.get("sale_price") if p.get("sale") else p.get("price"))
    full = _money(p.get("orig_price")) if p.get("sale") else None
    if full is not None and price is not None and full <= price:
        full = None
    images: list[str] = [
        str(u)
        for u in (((i or {}).get("file") or {}).get("url") for i in (p.get("images") or []))
        if u
    ]
    if price is None and not images:
        raise SkipProduct(f"{url}: no price and no photograph, nothing to buy")
    options = {
        (o.get("name") or "").strip().lower(): [
            v.get("name") for v in (o.get("values") or []) if v.get("name")
        ]
        for o in (p.get("options") or [])
        if isinstance(o, dict)
    }
    sizes = options.get("size") or []
    colours = options.get("color") or options.get("colour") or []
    other = {k: v for k, v in options.items() if k not in ("size", "color", "colour") and v}
    # Per-size stock from the variants: a variant is named "Colour, Size" or "Size".
    avail: dict[str, bool] = {}
    for v in variants:
        name = str(v.get("name") or "")
        size = name.split(",")[-1].strip() if name else ""
        if size in sizes:
            ok = v.get("stock_status") in (None, "in_stock") and (
                v.get("stock_level") is None or v.get("stock_level", 0) > 0
            )
            avail[size] = avail.get(size, False) or bool(ok)
    attrs = p.get("attributes") or {}
    collection = (
        (attrs.get("collection") or {}).get("value")
        if isinstance(attrs.get("collection"), dict)
        else None
    )
    in_stock = p.get("stock_status") == "in_stock" or bool(p.get("stock_purchasable"))
    return ProductRecord(
        itemurl=url,
        product_title=title,
        product_code=p.get("sku") or None,
        brand=brand_name,
        description=_text(p.get("description")) or None,
        price=price,
        full_price=full,
        currency=p.get("currency") or currency or None,
        in_stock=in_stock,
        quantity=int(p["stock_level"]) if isinstance(p.get("stock_level"), (int, float)) else None,
        size_info=", ".join(sizes) or None,
        size_availability=", ".join("in_stock" if avail.get(s) else "out_of_stock" for s in sizes)
        if sizes and avail
        else None,
        color_info=", ".join(colours) or None,
        variant_info="; ".join(f"{k}: {', '.join(v)}" for k, v in other.items()) or None,
        additional_tags=", ".join(t for t in (p.get("tags") or []) if t) or None,
        **pack_images(images),
        **pack_categories([collection] if collection else []),
        platform="swell",
    )


def _money(v: Any) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _text(html: Any) -> str:
    import re

    if not html:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html))).strip()


def _brand_name(url: str) -> str | None:
    host = url.split("/")[2] if url.count("/") >= 2 else ""
    host = host.removeprefix("www.")
    return host.split(".")[0].upper() if host else None
