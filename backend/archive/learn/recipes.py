"""A lane described as data, so the model can propose one without writing code.

Every fix of 2026-09-27 but two was a parameter to a connector that already existed:
which sitemap, which alternate, which JSON endpoint, which path in it. A lane recipe
is those parameters written down — where the list of products is, how one product is
fetched, and where each field sits in what comes back — and `RecipeConnector` runs it
through the same discover/fetch seam every other connector uses.

Recipes land on their own once the gate has proved them. Code does not. That is the
line between what the loop may do unattended and what leaves a diff behind.

Templates take {domain}, {url} (the product's URL), {handle} (its last path segment),
and any key of the item the discovery step found it in ({slug}, {country}, {id}).
Paths are dotted, with [n] for an index and [*] to fan out: "result.pageContext.draw",
"products[*].handle", "hasVariant[*].offers.price".
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.archive.connectors.base import ChannelBlocked, NotAProduct, SkipProduct
from backend.archive.connectors.sitemap import SitemapConnector
from backend.archive.connectors.structured import _find_product_node, page_images
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import (
    ProductRecord,
    ProductRef,
    pack_categories,
    pack_images,
    pack_sizes,
)
from backend.archive.transport import Transport

DISCOVER_KINDS = ("sitemap", "json_list", "listing")
FETCH_KINDS = ("json", "jsonld", "og", "regex", "payload")
# The record fields a recipe may fill, and how each is read.
FIELDS = (
    "product_title",
    "price",
    "full_price",
    "currency",
    "description",
    "product_code",
    "brand",
    "in_stock",
    "images",  # a list, or one URL
    "sizes",  # a list of labels, or of {label, available}
    "color_info",
    "material_info",
    "categories",  # a list, or "a > b"
    "additional_tags",
)


# The catalogue's own names for the same things, so a proposal written in E0005 words is
# not refused over a name. Unknown names are still refused: they are not read by anything.
ALIASES = {
    "all_images": "images",
    "main_image_url": "images",
    "image": "images",
    "size_info": "sizes",
    "size_availability": "sizes",
    "category1": "categories",
    "category": "categories",
    "color": "color_info",
    "colour": "color_info",
    "colour_info": "color_info",
    "material": "material_info",
    "tags": "additional_tags",
    "title": "product_title",
    "name": "product_title",
    "sku": "product_code",
    "code": "product_code",
    "url": "itemurl",
    "itemurl": "itemurl",
    "availability": "in_stock",
    "stock": "in_stock",
}


def _canonical_fields(fields: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, path in fields.items():
        canon = ALIASES.get(name, name)
        if canon == "itemurl":
            continue  # the URL is the ref's; never a field to read
        out.setdefault(canon, path)  # the first spelling wins (all_images before image)
    return out


class Discover(BaseModel):
    kind: str
    url: str | None = None  # the list endpoint or sitemap; may carry {page}
    items: str | None = None  # json_list: path to the array of items
    url_template: str | None = None  # how an item becomes a product URL
    prefix: str | None = None  # sitemap: the product URL prefix
    page_param: str | None = None  # json_list: query parameter to page with, until empty
    max_pages: int = 200
    link_pattern: str | None = None  # listing: regex with one group over the page
    filter: dict[str, str] = Field(default_factory=dict)  # json_list: item path -> required value


class Fetch(BaseModel):
    kind: str
    url_template: str | None = None  # json: where the product's data is
    root: str | None = None  # json: path to the product object
    fields: dict[str, str] = Field(default_factory=dict)  # FIELDS -> path or regex

    @field_validator("fields", mode="before")
    @classmethod
    def _aliases(cls, v: Any) -> Any:
        if isinstance(v, list):  # the tool's shape: [{name, path}, ...]
            v = {
                str(e.get("name")): str(e.get("path"))
                for e in v
                if isinstance(e, dict) and e.get("name") and e.get("path")
            }
        return _canonical_fields(v) if isinstance(v, dict) else v

    in_stock_when: str | None = None  # a value of the in_stock path that means in stock
    currency: str | None = None  # a fixed currency, when the data states none


class LaneRecipe(BaseModel):
    id: str
    signature: str
    description: str
    discover: Discover
    fetch: Fetch
    learned_from: str | None = None  # the brand that taught it
    at: str | None = None
    status: str = "provisional"  # provisional | confirmed | retired
    brands: list[str] = Field(default_factory=list)  # where it has read products

    def check(self) -> list[str]:
        """What is wrong with this recipe, as a list; empty when it is well formed."""
        out = []
        if self.discover.kind not in DISCOVER_KINDS:
            out.append(f"discover.kind {self.discover.kind!r} is not one of {DISCOVER_KINDS}")
        if self.fetch.kind not in FETCH_KINDS:
            out.append(f"fetch.kind {self.fetch.kind!r} is not one of {FETCH_KINDS}")
        if self.discover.kind == "sitemap" and not self.discover.url:
            out.append("a sitemap discovery needs a url")
        if self.discover.kind == "json_list" and not (self.discover.url and self.discover.items):
            out.append("a json_list discovery needs a url and an items path")
        if self.discover.kind == "listing" and not (
            self.discover.url and self.discover.link_pattern
        ):
            out.append("a listing discovery needs a url and a link_pattern")
        if self.fetch.kind in ("json", "regex") and "product_title" not in self.fetch.fields:
            out.append(f"a {self.fetch.kind} fetch must say where product_title is")
        for f in self.fetch.fields:
            if f not in FIELDS:
                out.append(f"unknown field {f!r}")
        return out


# --- paths and templates ---------------------------------------------------------------

_STEP = re.compile(r"([^.\[\]]+)|\[(\*|-?\d+)\]|\[([^=\]]+)=([^\]]*)\]")


def path_get(data: Any, path: str | None) -> Any:
    """Walk a dotted path. [*] fans out into a list; a missing step is None."""
    if not path:
        return data
    current: Any = data
    for m in _STEP.finditer(path):
        key, index, pick_key, pick_value = m.group(1), m.group(2), m.group(3), m.group(4)
        if pick_key is not None:
            # [name=Tags]: the first item of a list whose key reads that value
            items = current if isinstance(current, list) else [current]
            current = next(
                (
                    c
                    for c in items
                    if isinstance(c, dict) and str(c.get(pick_key.strip())) == pick_value.strip()
                ),
                None,
            )
        elif key is not None:
            if isinstance(current, list):
                picked: list[Any] = [c.get(key) if isinstance(c, dict) else None for c in current]
                # A key read across a fanned-out list of lists flattens one level:
                # retailers[*].draws is every draw, not a list per retailer.
                if picked and all(isinstance(x, list) for x in picked):
                    picked = [x for sub in picked for x in list(sub)]
                current = picked
            elif isinstance(current, dict):
                current = current.get(key)
            else:
                return None
        elif index == "*":
            if isinstance(current, dict):
                current = list(current.values())
            elif not isinstance(current, list):
                return None
            # flatten one level when the previous step already fanned out
            if current and all(isinstance(c, list) for c in current):
                current = [x for c in current for x in c]
        else:
            i = int(index)
            if isinstance(current, list) and -len(current) <= i < len(current):
                current = current[i]
            else:
                return None
        if current is None:
            return None
    return current


def _find_typed_node(html: str, root: str) -> dict | None:
    """The first JSON-LD node of the type a recipe names ("@type==ProductGroup" or just
    "ProductGroup"); a dotted root instead walks the first Product node found."""
    from backend.archive.connectors.structured import _LD_BLOCK, _iter_nodes

    want = root.split("==", 1)[1].strip() if "==" in root else root.strip()
    if "." in want or "[" in want:
        node = _find_product_node(html)
        got = path_get(node, want) if node else None
        return got if isinstance(got, dict) else node
    for block in _LD_BLOCK.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _iter_nodes(data):
            types = node.get("@type", "")
            types = types if isinstance(types, list) else [types]
            if want in types:
                return node
    return None


def render(template: str, **values: Any) -> str:
    out = template
    for k, v in values.items():
        if v is None:
            continue
        out = out.replace("{" + k + "}", str(v))
    return out


def _handle(url: str) -> str:
    return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


# --- the connector -------------------------------------------------------------------


class RecipeConnector:
    kind = "recipe"

    def __init__(self, recipe: LaneRecipe, limit: int | None = None, currency: str | None = None):
        problems = recipe.check()
        if problems:
            raise ValueError("; ".join(problems))
        self.recipe = recipe
        self.limit = limit
        self.currency = recipe.fetch.currency or currency

    # -- discover --

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        d = self.recipe.discover
        if d.kind == "sitemap":
            url = render(d.url or "", domain=brand.domain)
            prefix = render(d.prefix, domain=brand.domain) if d.prefix else None
            if prefix and "://" in prefix:
                # the connector filters on the path; a recipe may say the whole URL
                prefix = (
                    "/" + prefix.split("://", 1)[1].split("/", 1)[1]
                    if "/" in prefix.split("://", 1)[1]
                    else None
                )
            # A regex beside a sitemap filters its URLs (Gentle Monster's model-written
            # recipe named the product URL shape as a pattern, not a prefix). The walk
            # then needs headroom past the limit: landing pages sort first in a sitemap.
            keep = re.compile(d.link_pattern, re.I) if d.link_pattern and not prefix else None
            walk = (
                None if self.limit is None else (max(self.limit * 20, 500) if keep else self.limit)
            )
            try:
                refs = SitemapConnector(url, prefix, walk).discover(brand, transport)
                if keep:
                    refs = [r for r in refs if keep.search(r.url)]
                    refs = refs[: self.limit] if self.limit is not None else refs
                return refs
            except ChannelBlocked:
                # A child sitemap named without the query its index gives it (Shopify's
                # sitemap_products_1.xml?from=..&to=..) refuses; the index never does.
                root = f"https://{brand.domain}/sitemap.xml"
                if url == root:
                    raise
                return SitemapConnector(root, prefix, self.limit).discover(brand, transport)
        if d.kind == "json_list":
            return self._json_list(brand, transport)
        if d.kind == "listing":
            return self._listing(brand, transport)
        raise ValueError(d.kind)

    def _json_list(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        d = self.recipe.discover
        refs: list[ProductRef] = []
        seen: set[str] = set()
        page = 1
        while page <= d.max_pages:
            url = render(d.url or "", domain=brand.domain, page=page)
            if d.page_param and "{page}" not in (d.url or ""):
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{d.page_param}={page}"
            resp = transport.get(url)
            if resp.status_code != 200:
                if page == 1:
                    raise ChannelBlocked(f"{url} → HTTP {resp.status_code}")
                break
            try:
                data = resp.json()
            except ValueError:
                raise ChannelBlocked(f"{url}: not JSON") from None
            found = path_get(data, d.items)
            items: list = found if isinstance(found, list) else []
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                if any(str(path_get(item, k)) != v for k, v in d.filter.items()):
                    continue
                values = {k: v for k, v in item.items() if isinstance(v, (str, int, float))}
                link = render(d.url_template or "{url}", domain=brand.domain, **values)
                if "{" in link or link in seen:
                    continue
                seen.add(link)
                refs.append(ProductRef(url=link, change_hint=_hint(item), payload=item))
                if self.limit is not None and len(refs) >= self.limit:
                    return refs
            if not d.page_param and "{page}" not in (d.url or ""):
                break
            page += 1
        return refs

    def _listing(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        d = self.recipe.discover
        url = render(d.url or "", domain=brand.domain)
        resp = transport.get(url)
        if resp.status_code != 200:
            raise ChannelBlocked(f"{url} → HTTP {resp.status_code}")
        pattern = re.compile(d.link_pattern or "", re.I)
        refs: list[ProductRef] = []
        seen: set[str] = set()
        for m in pattern.finditer(resp.text or ""):
            got = m.group(1) if m.groups() else m.group(0)
            payload: dict[str, Any] = {"match": got, "id": got, "handle": got}
            if got.startswith("/"):
                link = f"https://{brand.domain}{got}"
            elif "://" in got:
                link = got
            else:
                # A bare id or handle (YEEZY's Swell object ids): the template says
                # where it lives; without one it is a path off the root.
                link = render(
                    d.url_template or "https://{domain}/{match}", domain=brand.domain, **payload
                )
            if link in seen:
                continue
            seen.add(link)
            refs.append(ProductRef(url=link, payload=payload))
            if self.limit is not None and len(refs) >= self.limit:
                break
        return refs

    # -- fetch --

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord:
        f = self.recipe.fetch
        parts = ref.url.split("/")
        if len(parts) < 3 or not parts[2]:
            raise SkipProduct(f"{ref.url!r} is not a URL")
        domain = parts[2]
        values = {k: v for k, v in (ref.payload or {}).items() if isinstance(v, (str, int, float))}
        if f.kind == "payload":
            return self._from_values(ref.url, ref.payload or {})
        words: dict[str, Any] = {"domain": domain, "url": ref.url, "handle": _handle(ref.url)}
        words.update(values)  # what discovery found the product in wins over the URL's tail
        url = render(f.url_template or "{url}", **words)
        resp = transport.get(url)
        if resp.status_code == 404:
            raise NotAProduct(f"{url}: gone")
        if resp.status_code != 200:
            raise SkipProduct(f"{url} → HTTP {resp.status_code}")
        if f.kind == "json":
            try:
                data = resp.json()
            except ValueError:
                raise SkipProduct(f"{url}: not JSON") from None
            root = path_get(data, f.root)
            if root is None:
                raise SkipProduct(f"{url}: nothing at {f.root!r}")
            return self._from_values(ref.url, root)
        if f.kind == "jsonld":
            node = _find_typed_node(resp.text, f.root) if f.root else _find_product_node(resp.text)
            if not node:
                raise NotAProduct(f"{url}: no Product JSON-LD")
            merged = {**node}
            return self._from_values(ref.url, merged, html=resp.text)
        if f.kind == "og":
            og = dict(
                re.findall(
                    r'<meta[^>]*property="og:([a-z:_]+)"[^>]*content="([^"]*)"', resp.text, re.I
                )
            )
            data = {"og": og, "html": ""}
            values2 = {
                "product_title": og.get("title"),
                "price": og.get("price:amount") or og.get("product:price:amount"),
                "currency": og.get("price:currency") or og.get("product:price:currency"),
                "images": page_images(resp.text),
            }
            return self._record(ref.url, values2)
        if f.kind == "regex":
            out: dict[str, Any] = {}
            for field, pattern in f.fields.items():
                m = re.search(pattern, resp.text, re.S | re.I)
                if m:
                    out[field] = m.group(1) if m.groups() else m.group(0)
            if "images" not in out:
                out["images"] = page_images(resp.text)
            return self._record(ref.url, out)
        raise ValueError(f.kind)

    def _from_values(self, url: str, data: Any, html: str = "") -> ProductRecord:
        f = self.recipe.fetch
        out: dict[str, Any] = {}
        for field, path in f.fields.items():
            out[field] = path_get(data, path)
        if "images" not in out and html:
            out["images"] = page_images(html)
        return self._record(url, out)

    def _record(self, url: str, v: dict[str, Any]) -> ProductRecord:
        f = self.recipe.fetch
        title = _text(v.get("product_title"))
        if not title:
            raise SkipProduct(f"{url}: no product_title")
        price = _money(v.get("price"))
        full = _money(v.get("full_price"))
        if full is not None and price is not None and full <= price:
            full = None
        images = _list(v.get("images"))
        images = [str(i) for i in images if isinstance(i, (str,)) and i]
        if price is None and not images:
            raise NotAProduct(f"{url}: no price and no photograph")
        sizes = _sizes(v.get("sizes"))
        cats = v.get("categories")
        if isinstance(cats, str):
            cats = [c.strip() for c in cats.split(">") if c.strip()]
        cats = [str(c) for c in _list(cats) if c]
        stock = v.get("in_stock")
        if f.in_stock_when is not None and stock is not None:
            want = f.in_stock_when.strip().lower()
            quoted = re.findall(r"['\"]([^'\"]+)['\"]", want)
            if quoted:  # a sentence with the word in quotes: the last quoted word is it
                want = quoted[-1].lower()
            values = stock if isinstance(stock, list) else [stock]
            in_stock: bool | None = any(want in str(v).lower() for v in values if v is not None)
        elif isinstance(stock, bool):
            in_stock = stock
        elif isinstance(stock, str):
            s = stock.lower()
            in_stock = ("instock" in s.replace(" ", "")) or s in ("true", "1", "yes", "available")
        elif isinstance(stock, (int, float)):
            in_stock = stock > 0
        elif stock is None and sizes:
            in_stock = (
                any(s.get("available") for s in sizes)
                if any("available" in s for s in sizes)
                else None
            )
        else:
            in_stock = None
        currency = _text(v.get("currency")) or self.currency
        tags = v.get("additional_tags")
        tags = ", ".join(str(t) for t in _list(tags) if t) if tags else None
        return ProductRecord(
            itemurl=url,
            product_title=title,
            product_code=_text(v.get("product_code")),
            brand=_text(v.get("brand")),
            description=_text(v.get("description")),
            price=price,
            full_price=full,
            currency=currency.upper() if currency else None,
            in_stock=in_stock,
            color_info=_text(v.get("color_info")),
            material_info=_text(v.get("material_info")),
            promotion_type="sale" if full is not None else None,
            additional_tags=tags or None,
            **pack_sizes(sizes),
            **pack_images(images),
            **pack_categories(cats),
            platform="recipe",
            raw={"recipe": self.recipe.id},
        )


def _hint(item: dict) -> str | None:
    for k in ("updated_at", "updatedAt", "modified", "lastmod", "end", "start"):
        if item.get(k):
            return str(item[k])
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = next((x for x in value if x), None)
        if value is None:
            return None
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or value.get("text")
    s = re.sub(r"<[^>]+>", "", str(value)).strip()
    return s or None


def _money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, list):
        nums = [n for n in (_money(x) for x in value) if n is not None]
        return min(nums) if nums else None
    if isinstance(value, dict):
        return _money(value.get("amount") or value.get("value") or value.get("price"))
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.startswith("["):
        try:
            got = json.loads(value)
            return got if isinstance(got, list) else [value]
        except ValueError:
            return [value]
    return [value]


def _sizes(value: Any) -> list[dict]:
    out: list[dict] = []
    for item in _list(value):
        if isinstance(item, dict):
            label = item.get("label") or item.get("size") or item.get("name") or item.get("title")
            if not label:
                continue
            entry: dict[str, Any] = {"size": str(label)}
            if "available" in item:
                entry["available"] = bool(item["available"])
            out.append(entry)
        elif item is not None and str(item).strip():
            out.append({"size": str(item).strip()})
    return out
