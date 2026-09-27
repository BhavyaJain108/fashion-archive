"""Bulk Shopify catalog: /products.json is discovery AND fetch in one channel (spec §4.2)."""

import re
import time

from backend.archive.connectors.base import ChannelBlocked, ChannelBusy, NotAProduct, SkipProduct
from backend.archive.connectors.sitemap import SitemapConnector
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import (
    ProductRecord,
    ProductRef,
    pack_categories,
    pack_images,
    pack_offers,
    pack_sizes,
)
from backend.archive.transport import Transport

_TAG_RE = re.compile(r"<[^>]+>")

# A Shopify variant's option1/2/3 line up with the product's own options list, and a
# store chooses that order freely: 437 products in a five-brand sample are laid out
# ("Color", "Size"), so reading option1 as the size stored colours as sizes. A
# single-variant product's one option is "Title" with the value "Default Title", which
# is not a size either. Match on the option's NAME, whatever position it is in.
_SIZE_WORDS = ("size", "taille", "größe", "grösse", "talla", "taglia", "размер", "kích thước")
_COLOR_WORDS = ("color", "colour", "couleur", "farbe", "цвет", "màu sắc")
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
    seen: dict[str, None] = {}
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


def _offers_from_variants(variants: list[dict], options: list[str]) -> list[dict]:
    """One entry per variant — the id /cart/<id>:<qty> takes — with the size read
    from the same option `_sizes_from_variants` reads. A ("Color", "Size") layout
    yields several entries per size; the bag picks by variant id, not by label."""
    index = _option_index(options, _SIZE_WORDS)
    key = f"option{index + 1}" if index is not None else None
    out = []
    for v in variants:
        if v.get("id") in (None, ""):
            continue
        label = (v.get(key) or "").strip() if key else ""
        out.append(
            {
                "size": None if not label or label.lower() == "default title" else label,
                "variant_id": v["id"],
                "available": v.get("available"),
                "price": v.get("price"),
            }
        )
    return out


_MAX_PAGES = 200  # 200 × 250 = 50k products; loop guard, not a coverage cap
_BUSY = (429, 503)  # the store is fine, it wants us to slow down

# The market whose prices the catalogue holds. A Shopify store with Markets enabled
# prices each country itself — kuurth.com asks 34.95 EUR at home and 52.00 USD in the
# US, which is a decision, not a conversion — and `?country=US` on the feed returns
# that market's figures. A store without a US market ignores the parameter and serves
# its own currency (marrknull.com, EUR), which the response cookie then says.
DEFAULT_MARKET = "US"
_CART_CURRENCY = re.compile(r"cart_currency=([A-Z]{3})")


def served_currency(resp) -> str | None:
    """The currency the store priced this response in, read off its cookie.

    Shopify sets `cart_currency` on every storefront response, the feed included,
    and it names the currency of the prices in the body — so it is the one source
    that agrees with the numbers whether or not the market switch took.
    """
    headers = resp.headers
    try:
        raw = headers.get_list("set-cookie")
    except AttributeError:
        value = headers.get("set-cookie") if headers is not None else None
        raw = [value] if value else []
    for line in raw:
        m = _CART_CURRENCY.search(line or "")
        if m:
            return m.group(1)
    return None


class ShopifyConnector:
    kind = "shopify"

    def __init__(
        self,
        currency: str | None = None,
        retry_pause: float = 2.0,
        market: str | None = DEFAULT_MARKET,
    ):
        # /products.json states prices with no currency; the store states it once
        # (meta.json), and the response cookie says which market's prices came back.
        self.currency = currency
        self.retry_pause = retry_pause
        self.market = market

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
        country = f"&country={self.market}" if self.market else ""
        for page in range(1, _MAX_PAGES + 1):
            url = f"https://{brand.domain}/products.json?limit=250&page={page}{country}"
            resp = self._page(url, transport)
            if page == 1:
                # Whatever the store priced the feed in wins over what meta.json said:
                # the two differ exactly when the market switch took.
                self.currency = served_currency(resp) or self.currency
            products = resp.json().get("products", [])
            if not products:
                break
            for p in products:
                refs.append(
                    ProductRef(
                        url=f"https://{brand.domain}/products/{p['handle']}",
                        # The market is part of the hint: switching it re-records
                        # every product once, which is how the old currency leaves.
                        change_hint=_hint(p.get("updated_at"), self.market),
                        payload=p,
                    )
                )
        return refs

    def fetch(self, ref: ProductRef, transport: Transport | None) -> ProductRecord:
        if not ref.payload:
            raise SkipProduct(f"no payload on {ref.url}")
        domain = ref.url.split("/")[2]
        record = map_product(ref.payload, domain, self.currency, self.market)
        if record.main_image_url is None and transport is not None:
            record = with_page_images(record, transport)
        return record


class ShopifyPageConnector:
    """A Shopify store with its bulk feed switched off, read one product at a time.

    fengofficiel.com answers 404 at /products.json and the whole product record at
    /products/<handle>.json (2026-09-27) — the same shape the feed carries, so the same
    mapping applies. Discovery is the store's own product sitemap. The per-product
    endpoint takes no market, so the prices are the shop's own, and `market` is left
    unset to say so.
    """

    kind = "shopify_page"

    def __init__(
        self,
        sitemap_url: str,
        url_prefix: str | None = None,
        limit: int | None = None,
        currency: str | None = None,
        retry_pause: float = 2.0,
    ):
        self._sitemap = SitemapConnector(sitemap_url, url_prefix, limit)
        self.currency = currency
        self.retry_pause = retry_pause

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        return self._sitemap.discover(brand, transport)

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord:
        url = ref.url.split("?")[0].rstrip("/") + ".json"
        resp = transport.get(url)
        if resp.status_code in _BUSY:
            time.sleep(self.retry_pause)
            resp = transport.get(url)
        if resp.status_code in _BUSY:
            raise ChannelBusy(f"{url} → HTTP {resp.status_code}")
        if resp.status_code == 404:
            # The sitemap is regenerated on a schedule; a handle it still lists can be
            # gone. That says nothing about our access.
            raise NotAProduct(f"{ref.url}: no such product any more")
        if resp.status_code != 200 or "/password" in str(resp.url):
            raise SkipProduct(f"{url} → HTTP {resp.status_code}")
        try:
            product = resp.json().get("product")
        except ValueError:
            product = None
        if not product:
            raise SkipProduct(f"no product in {url}")
        domain = ref.url.split("/")[2]
        return map_product(product, domain, served_currency(resp) or self.currency, market=None)


def with_page_images(record: ProductRecord, transport: Transport) -> ProductRecord:
    """The page's photographs, for a feed product that lists none.

    cooperativeshop.us publishes 529 products whose feed entries carry `images: []`
    and `image: null`, while every product page states its photographs in og:image
    (2026-09-27). One extra request, only for a product the feed shows no picture of.
    """
    from backend.archive.connectors.structured import page_images

    resp = transport.get(record.itemurl)
    if resp.status_code != 200:
        return record
    images = page_images(resp.text)
    if not images:
        return record
    return record.model_copy(update=pack_images(images))


def _hint(updated_at: str | None, market: str | None) -> str | None:
    if updated_at is None:
        return None
    return f"{updated_at}|{market}" if market else updated_at


def map_product(
    p: dict, domain: str, currency: str | None = None, market: str | None = None
) -> ProductRecord:
    variants = p.get("variants") or []
    prices = [float(v["price"]) for v in variants if v.get("price") is not None]
    compare = [float(v["compare_at_price"]) for v in variants if v.get("compare_at_price")]
    price = min(prices) if prices else None
    full_price = min(compare) if compare else None
    if full_price is not None and price is not None and full_price <= price:
        full_price = None  # compare_at_price equal/below price is not a sale
    images = [img["src"] for img in p.get("images") or [] if img.get("src")]
    # A record priced at nothing with nothing to show is a placeholder, not a product:
    # fengofficiel.com keeps 8 of its 43 handles that way, every variant at 0 and
    # unavailable (2026-09-27). Stored, they would be half the brand at no price.
    if price == 0 and not images and not any(v.get("available") for v in variants):
        raise NotAProduct(f"{p.get('handle')}: no price, no photograph, nothing to buy")
    options = [str(o.get("name") or "") for o in p.get("options") or []]
    sizes = _sizes_from_variants(variants, options)
    colors = _option_values(variants, options, _COLOR_WORDS)
    materials = _option_values(variants, options, _MATERIAL_WORDS)
    # The feed lists tags; the per-product endpoint writes them as one string, or null
    # (fengofficiel.com, 2026-09-27).
    raw_tags = p.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",")]
    tags = [t for t in raw_tags if t]
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
        market=market,
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
        **pack_images(images),
        **pack_categories(categories),
        **pack_offers(_offers_from_variants(variants, options)),
        platform="shopify",
        handle=p.get("handle") or None,
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
