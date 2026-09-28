"""EQL's launch platform (runfair): a Gatsby site whose pages are JSON beside the page.

luar.runfair.com (2026-09-27): /page-data/index/page-data.json lists the retailer's
"draws" — each a product on sale for a window, with a country and a slug — and
/page-data/<country>/<slug>/page-data.json holds the whole draw: name, price, currency,
description, photographs, SKU, the window it sells in. There is no sitemap (the URL
answers with the app's HTML), no JSON-LD, and nothing on the page until the app runs, so
the page data is the one place the products exist for a reader without a browser.
"""

from datetime import datetime, timezone

from backend.archive.connectors.base import ChannelBlocked, SkipProduct
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord, ProductRef, pack_images
from backend.archive.transport import Transport


class RunfairConnector:
    kind = "runfair"

    def __init__(self, market: str | None = None, now: datetime | None = None):
        # A draw sells in one country. With a market set, the other countries' draws
        # are left out; without one, every draw is read.
        self.market = market
        self._now = now  # injected in tests; the window test needs a clock

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        url = f"https://{brand.domain}/page-data/index/page-data.json"
        resp = transport.get(url)
        if resp.status_code != 200:
            raise ChannelBlocked(f"{url} → HTTP {resp.status_code}")
        try:
            retailers = resp.json()["result"]["pageContext"]["retailers"]
        except (ValueError, KeyError, TypeError):
            raise ChannelBlocked(f"{url}: no retailers in the page data") from None
        refs: list[ProductRef] = []
        for retailer in retailers or []:
            for draw in retailer.get("draws") or []:
                country = (draw.get("country") or "").lower()
                slug = draw.get("slug")
                if not slug or not country:
                    continue
                if self.market and country != self.market.lower():
                    continue
                refs.append(
                    ProductRef(
                        url=f"https://{brand.domain}/{country}/{slug}",
                        # The window is what changes about a draw; a re-listed product
                        # is a new draw with new dates.
                        change_hint=draw.get("end") or draw.get("start"),
                        payload={"country": country, "slug": slug},
                    )
                )
        return refs

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord:
        domain = ref.url.split("/")[2]
        payload = ref.payload or {}
        country, slug = payload.get("country"), payload.get("slug")
        if not slug:
            rest = ref.url.split("/", 3)[3] if ref.url.count("/") >= 3 else ""
            country, _, slug = rest.partition("/")
        url = f"https://{domain}/page-data/{country}/{slug}/page-data.json"
        resp = transport.get(url)
        if resp.status_code != 200:
            raise SkipProduct(f"{url} → HTTP {resp.status_code}")
        try:
            draw = resp.json()["result"]["pageContext"]["draw"]
        except (ValueError, KeyError, TypeError):
            raise SkipProduct(f"{url}: no draw in the page data") from None
        return map_draw(draw, ref.url, now=self._now)


def map_draw(draw: dict, url: str, now: datetime | None = None) -> ProductRecord:
    title = draw.get("product") or draw.get("name")
    if not title:
        raise SkipProduct(f"draw without a product name at {url}")
    price = draw.get("price")
    images: list[str] = []
    for item in [draw.get("hero"), *(draw.get("gallery") or [])]:
        link = (item or {}).get("url") if isinstance(item, dict) else None
        if link and link not in images:
            images.append(link)
    # The inventory names the variants (one draw sold "Snake"); which axis they are
    # is not stated, so they go in the field for axes that are neither size nor colour.
    variants = [i.get("name") for i in draw.get("inventory") or [] if i.get("name")]
    # A draw names its brand as an object or a string; a store that does not is one
    # brand's own subdomain, and the subdomain is the brand.
    raw_brand = draw.get("brand")
    brand = raw_brand.get("name") if isinstance(raw_brand, dict) else raw_brand
    if not brand:
        host = url.split("/")[2] if url.count("/") >= 2 else ""
        brand = host.split(".")[0].upper() if host.endswith(".runfair.com") else None
    return ProductRecord(
        itemurl=url,
        product_title=title,
        brand=brand or None,
        product_code=draw.get("sku") or None,
        description=(draw.get("description") or "").strip() or None,
        price=float(price) if price is not None else None,
        currency=draw.get("currency") or None,
        market=(draw.get("country") or "").upper() or None,
        in_stock=selling(draw, now),
        variant_info=", ".join(variants) or None,
        additional_content=(draw.get("extraDescription") or "").strip() or None,
        **pack_images(images),
        platform="runfair",
        raw=draw,
    )


def selling(draw: dict, now: datetime | None = None) -> bool | None:
    """A draw sells between its start and its end; outside the window nothing can be
    bought, however published the page. None when the dates cannot be read."""
    if draw.get("isPublished") is False:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        start, end = _aware(draw.get("start")), _aware(draw.get("end"))
    except ValueError:
        return None
    if start and start > now:
        return False
    if end and end < now:
        return False
    return True


def _aware(iso: str | None) -> datetime | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
