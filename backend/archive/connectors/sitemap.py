"""Sitemap discovery: product URLs + lastmod change hints, any platform (spec §4.2)."""

import re
import xml.etree.ElementTree as ET

from backend.archive.connectors.base import ChannelBlocked
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.transport import Transport

_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
# /products/ (Shopify, custom) and /product/ (WooCommerce permalinks), optional locale prefix
_PRODUCT_URL = re.compile(r"^https?://[^/]+(/[a-z]{2}(-[a-z]{2})?)?/products?/[^?#]+/?$", re.I)


class SitemapConnector:
    kind = "sitemap"

    def __init__(self, sitemap_url: str, url_prefix: str | None = None, limit: int | None = None):
        self.sitemap_url = sitemap_url
        # A prefix learned at SCOPE time (e.g. "/assets/" on Webflow) beats guessing.
        self.url_prefix = url_prefix
        # Stop walking once this many product URLs are in hand. The Outnet's index
        # fans out to 80,048 URLs and the walk timed out before the run could start.
        self.limit = limit

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        refs: list[ProductRef] = []
        self._collect(self.sitemap_url, transport, depth=0, refs=refs)
        return refs

    def _collect(self, url: str, transport: Transport, depth: int, refs: list[ProductRef]) -> None:
        if depth > 2 or (self.limit is not None and len(refs) >= self.limit):
            return
        resp = transport.get(url)
        if resp.status_code != 200:
            if depth == 0:
                raise ChannelBlocked(f"sitemap {url} → HTTP {resp.status_code}")
            return  # one unreadable child sitemap must not lose the whole catalogue
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            if depth == 0:
                raise ChannelBlocked(f"sitemap {url} is not XML") from None
            return
        if root.tag.endswith("sitemapindex"):
            for sm in root.findall("sm:sitemap/sm:loc", _NS):
                self._collect((sm.text or "").strip(), transport, depth + 1, refs)
                if self.limit is not None and len(refs) >= self.limit:
                    return
            return
        for u in root.findall("sm:url", _NS):
            loc = u.find("sm:loc", _NS)
            if loc is None or not loc.text:
                continue
            link = loc.text.strip()
            if not self._is_product(link):
                continue
            lastmod = u.find("sm:lastmod", _NS)
            refs.append(
                ProductRef(
                    url=link,
                    change_hint=lastmod.text.strip()
                    if lastmod is not None and lastmod.text
                    else None,
                )
            )
            if self.limit is not None and len(refs) >= self.limit:
                return

    def _is_product(self, url: str) -> bool:
        if self.url_prefix:
            path = "/" + url.split("/", 3)[3] if len(url.split("/", 3)) > 3 else "/"
            return path.startswith(self.url_prefix) and len(path) > len(self.url_prefix)
        return bool(_PRODUCT_URL.match(url))

    def count(self, brand: Brand, transport: Transport) -> int:
        return len(self.discover(brand, transport))

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord:
        raise NotImplementedError("structured-data fetch arrives in milestone 2")
