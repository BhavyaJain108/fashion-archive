"""One shop front over every brand: the index behind the My Brands page.

The catalogue stores products one brand at a time, in the brand's own words. A
page laid out like SSENSE — every designer in one grid, one category column, one
sort — needs the opposite: everything at once, in one vocabulary. This module
builds that once, keeps it in memory for a while, and answers the page's
questions from it.

Two heuristics live here and are worth knowing about:

* `classify` folds a shop's category path and the product title into one
  taxonomy (Clothing / Shoes / Bags / Accessories, each with a few buckets).
  Keyword order is the whole algorithm: "denim jacket" must land in jackets,
  not jeans, so jackets are checked first.
* `colour` folds free-text colour into twelve names.

Both will be wrong for a few products. The page shows counts beside every
filter, so a wrong bucket is visible rather than silent.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from backend.archive.store.catalog import has_photograph

# --- taxonomy ---------------------------------------------------------------

# (group, bucket, keywords). First match wins, so specific before general.
_TAXONOMY: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "Clothing",
        "Jackets & coats",
        (
            "jacket",
            "coat",
            "blazer",
            "parka",
            "bomber",
            "puffer",
            "trench",
            "anorak",
            "windbreaker",
            "gilet",
            "overshirt",
            "blouson",
            "outerwear",
            "teddy",
            "shacket",
        ),
    ),
    (
        "Clothing",
        "Knitwear",
        (
            "sweater",
            "knit",
            "cardigan",
            "jumper",
            "pullover",
            "rollneck",
            "roll neck",
            "mockneck",
            "mock neck",
            "turtleneck",
            "quarter-zip",
            "quarter zip",
            "half-zip",
            "half zip",
        ),
    ),
    (
        "Clothing",
        "Hoodies & sweatshirts",
        ("hoodie", "hooded", "sweatshirt", "crewneck", "crew neck", "fleece", "zip-up", "zip up"),
    ),
    ("Clothing", "Tees", ("t-shirt", "t shirt", "tshirt", "tee", "tank", "singlet")),
    ("Clothing", "Shirts", ("shirt", "blouse", "polo")),
    ("Clothing", "Dresses", ("dress", "gown")),
    ("Clothing", "Skirts", ("skirt",)),
    (
        "Clothing",
        "Sets",
        (
            "jumpsuit",
            "romper",
            "overall",
            "tracksuit",
            "co-ord",
            "two piece",
            "2 piece",
            "set",
            "suit",
        ),
    ),
    ("Clothing", "Jeans", ("jean", "denim")),
    (
        "Clothing",
        "Pants",
        (
            "pant",
            "trouser",
            "chino",
            "cargo",
            "legging",
            "jogger",
            "sweatpant",
            "track pant",
            "bottoms",
            "bottom",
        ),
    ),
    ("Clothing", "Shorts", ("short", "sweatshort", "bermuda")),
    (
        "Clothing",
        "Underwear & swim",
        (
            "underwear",
            "brief",
            "boxer",
            "sock",
            "thong",
            "undies",
            "swim",
            "swimsuit",
            "bikini",
            "bra",
            "lingerie",
        ),
    ),
    (
        "Clothing",
        "Tops",
        ("top", "bodysuit", "corset", "camisole", "bralette", "vest", "tunic", "dickie"),
    ),
    (
        "Shoes",
        "Shoes",
        (
            "shoe",
            "sneaker",
            "boot",
            "loafer",
            "sandal",
            "derby",
            "derbies",
            "mule",
            "heel",
            "slipper",
            "slide",
            "trainer",
            "oxford",
            "clog",
            "footwear",
        ),
    ),
    (
        "Bags",
        "Bags",
        (
            "bag",
            "tote",
            "backpack",
            "pouch",
            "wallet",
            "cardholder",
            "card holder",
            "purse",
            "clutch",
            "baguette",
            "crossbody",
            "duffle",
            "duffel",
        ),
    ),
    (
        "Accessories",
        "Jewellery",
        (
            "ring",
            "necklace",
            "earring",
            "ear cuff",
            "bracelet",
            "brooch",
            "pendant",
            "chain",
            "anklet",
            "cuff",
            "cufflink",
            "charm",
            "jewel",
            "piercing",
            "choker",
            "stud",
        ),
    ),
    (
        "Accessories",
        "Hair",
        (
            "barrette",
            "hair clip",
            "hairclip",
            "headband",
            "scrunchie",
            "hair tie",
            "bow",
            "hair pin",
        ),
    ),
    ("Accessories", "Hats", ("hat", "cap", "beanie", "balaclava", "bucket")),
    ("Accessories", "Belts", ("belt",)),
    ("Accessories", "Watches", ("watch",)),
    ("Accessories", "Eyewear", ("sunglass", "glasses", "eyewear")),
    ("Accessories", "Scarves & gloves", ("scarf", "glove", "bandana", "mask", "mitten")),
    (
        "Accessories",
        "Accessories",
        ("accessor", "keychain", "keyring", "lighter", "pin", "patch", "phone case", "lanyard"),
    ),
    (
        "Everything else",
        "Home",
        (
            "throw",
            "pillow",
            "pillowcase",
            "napkin",
            "hanger",
            "candle",
            "blanket",
            "towel",
            "cushion",
            "tablecloth",
            "coaster",
            "mug",
            "vase",
            "rug",
            "apron",
            "bib",
        ),
    ),
    (
        "Everything else",
        "Everything else",
        (
            "gift card",
            "ebook",
            "e-book",
            "subscription",
            "insurance",
            "poster",
            "print",
            "book",
            "skateboard",
            "sticker",
        ),
    ),
]
GROUPS = ("Clothing", "Shoes", "Bags", "Accessories", "Everything else")
OTHER = ("Everything else", "Everything else")

_COLOURS: list[tuple[str, tuple[str, ...]]] = [
    ("Burgundy", ("burgundy", "wine", "maroon", "oxblood", "bordeaux")),
    ("Navy", ("navy", "midnight")),
    ("Black", ("black", "noir", "onyx", "jet")),
    ("White", ("white", "ivory", "ecru", "off-white", "off white", "bone")),
    ("Grey", ("grey", "gray", "charcoal", "silver", "heather", "ash", "slate")),
    ("Tan", ("tan", "beige", "cream", "khaki", "sand", "camel", "nude", "oat", "natural")),
    ("Brown", ("brown", "chocolate", "cognac", "tobacco", "mocha", "taupe", "coffee", "espresso")),
    ("Blue", ("blue", "denim", "indigo", "cobalt", "sky", "teal", "aqua")),
    ("Green", ("green", "olive", "sage", "forest", "mint", "lime", "moss", "emerald")),
    ("Red", ("red", "scarlet", "crimson", "cherry")),
    ("Pink", ("pink", "rose", "blush", "fuchsia", "magenta")),
    ("Purple", ("purple", "lavender", "lilac", "violet", "plum")),
    ("Orange", ("orange", "rust", "coral", "peach", "terracotta")),
    ("Yellow", ("yellow", "gold", "mustard", "lemon", "butter")),
]
COLOURS = tuple(name for name, _ in _COLOURS) + ("Multi",)

_MAX_LEVELS = 10


def _category_path(record: dict) -> list[str]:
    out = []
    for i in range(1, _MAX_LEVELS + 1):
        v = record.get(f"category{i}")
        if v in (None, "", "None"):
            break
        out.append(str(v))
    return out


def _has(text: str, word: str) -> bool:
    # Whole-word-ish: "set" must not match "sunset", "tee" must not match "steel".
    return re.search(rf"(?<![a-z]){re.escape(word)}(?:s|es)?(?![a-z])", text) is not None


def classify(record: dict) -> tuple[str, str]:
    """(group, bucket) for a product. The shop's own category outranks the title."""
    path = " ".join(_category_path(record)).lower()
    title = str(record.get("product_title") or "").lower()
    for text in (path, title):
        if not text:
            continue
        for group, bucket, words in _TAXONOMY:
            if any(_has(text, w) for w in words):
                return group, bucket
    return OTHER


def colour(record: dict) -> str | None:
    """color_info decides when it names one colour. Failing that, the title. Failing
    that, the tags — which list every colourway a shop sells, so they are read last
    and only when nothing else said anything."""
    for key in ("color_info", "product_title", "additional_tags"):
        text = str(record.get(key) or "").lower()
        if text in ("", "none"):
            continue
        if any(w in text for w in ("multi", "multicolor", "multicolour", "tie dye", "tie-dye")):
            return "Multi"
        hits = []
        for name, words in _COLOURS:
            positions = [
                m.start()
                for w in words
                for m in [re.search(rf"(?<![a-z]){re.escape(w)}(?:s|es)?(?![a-z])", text)]
                if m
            ]
            if positions:
                hits.append((min(positions), name))
        if len(hits) == 1:
            return hits[0][1]
        if len(hits) > 1:
            # color_info naming two colours is a two-tone product; a title or a tag
            # list naming several is read in order, and the first one wins.
            return "Multi" if key == "color_info" else min(hits)[1]
    return None


# Above this a "price" is a placeholder the shop uses for something unbuyable
# (99999 for a made-to-order set was the case that set it). Shown as no price.
_MAX_PRICE = 20000.0


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0 < f <= _MAX_PRICE else None


def _sizes(record: dict) -> list[dict]:
    avail = record.get("size_availability")
    if isinstance(avail, dict):
        return [{"size": str(k), "available": bool(v)} for k, v in avail.items()]
    if isinstance(avail, list):
        out = []
        for item in avail:
            if isinstance(item, dict):
                out.append(
                    {
                        "size": str(item.get("size") or item.get("name") or ""),
                        "available": bool(item.get("available", item.get("in_stock", True))),
                    }
                )
            else:
                out.append({"size": str(item), "available": True})
        return out
    info = record.get("size_info")
    if isinstance(info, list):
        return [{"size": str(s), "available": True} for s in info]
    if isinstance(info, str) and info not in ("", "None"):
        return [
            {"size": s.strip(), "available": True} for s in re.split(r"[,/|]", info) if s.strip()
        ]
    return []


def handle_of(url: str) -> str:
    """The last path segment of a product URL: what the page puts in its own URL.
    Shopify's /products/<handle> is the common case and is unique per shop."""
    return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] if url else ""


def _text(v: Any) -> str:
    return "" if v in (None, "None") else str(v)


def tile(
    record: dict,
    *,
    brand_id: str,
    brand_name: str,
    first_seen: str | None,
    archived: list[str],
    history: dict | None = None,
) -> dict:
    """One product as the page sees it. Carries everything the product page shows
    too (all images, description, material) so opening a product is answered
    from memory; `slim` strips those for the grid."""
    group, bucket = classify(record)
    price, full = _num(record.get("price")), _num(record.get("full_price"))
    sale = bool(price and full and full > price)
    images = record.get("all_images")
    if isinstance(images, str):
        images = [u.strip(" '\"") for u in images.strip("[]").split(",") if u.strip()]
    images = [u for u in (images or []) if isinstance(u, str) and u.startswith("http")]
    main = record.get("main_image_url") or (images[0] if images else None)
    second = next((u for u in images if u != main), None)
    url = record.get("itemurl") or ""
    return {
        "brand_id": brand_id,
        "brand": brand_name,
        "title": record.get("product_title") or "",
        "url": url,
        "handle": handle_of(url) or str(record.get("product_code") or ""),
        "code": record.get("product_code") or "",
        "price": price,
        "full_price": full if sale else None,
        "currency": record.get("currency") or "USD",
        "discount": (
            round((full - price) / full, 3) if sale and price is not None and full else 0.0
        ),
        "sale": sale,
        "in_stock": record.get("in_stock") in (True, 1, "True", "true"),
        "image": main,
        "image2": second,
        "archived": archived[:2],
        "group": group,
        "bucket": bucket,
        "colour": colour(record),
        "sizes": _sizes(record),
        "first_seen": first_seen or "",
        # --- product page only (see slim) ---
        "images": [main] + [u for u in images if u != main] if main else images,
        "description": _text(record.get("description")),
        "material": _text(record.get("material_info")),
        "colour_text": _text(record.get("color_info")),
        "last_seen": (history or {}).get("last_seen") or "",
        "last_on_site": (history or {}).get("last_on_site") or "",
    }


_DETAIL = ("images", "description", "material", "colour_text", "last_seen", "last_on_site")


def slim(t: dict) -> dict:
    """A tile without the product-page fields: what the grid gets."""
    return {k: v for k, v in t.items() if k not in _DETAIL}


# --- the index --------------------------------------------------------------


@dataclass
class Index:
    tiles: list[dict]
    brands: list[dict]  # [{brand_id, name, products}]
    built_at: float = field(default_factory=time.time)


def build(catalog, roster: Iterable) -> Index:
    tiles: list[dict] = []
    brands: list[dict] = []
    for entry in roster:
        domain = entry.domain
        # A password-gated brand keeps its old products in the archive and off the
        # shop front; a product with no photograph is not something anyone can buy.
        if catalog.get_brand_state(domain) == "gated":
            brands.append({"brand_id": domain, "name": entry.name, "products": 0})
            continue
        records = [r for r in catalog.current_products(domain) if has_photograph(r)]
        if not records:
            brands.append({"brand_id": domain, "name": entry.name, "products": 0})
            continue
        history = catalog.product_history(domain)
        archived = catalog.archived_images(domain)
        for r in records:
            url = r.get("itemurl", "")
            tiles.append(
                tile(
                    r,
                    brand_id=domain,
                    brand_name=entry.name,
                    first_seen=(history.get(url) or {}).get("first_seen"),
                    archived=archived.get(url, []),
                    history=history.get(url),
                )
            )
        brands.append({"brand_id": domain, "name": entry.name, "products": len(records)})
    return Index(tiles=tiles, brands=brands)


_TTL = 1800.0
_lock = threading.Lock()
_current: Index | None = None
_building = False


def _build_into_current(catalog_factory, roster_factory) -> None:
    global _current, _building
    started = time.time()
    catalog = catalog_factory()
    try:
        built = build(catalog, roster_factory())
    except Exception as error:  # noqa: BLE001 — a failed build must not kill the thread silently
        print(
            f"storefront: index build failed after {time.time() - started:.0f}s: {error!r}",
            flush=True,
        )
        return
    finally:
        catalog.close()
        _building = False
    _current = built
    print(
        f"storefront: index built — {len(built.tiles)} products from {len(built.brands)} brands in {time.time() - started:.0f}s",
        flush=True,
    )


def _start_build(catalog_factory, roster_factory) -> None:
    global _building
    with _lock:
        if _building:
            return
        _building = True
    threading.Thread(
        target=_build_into_current,
        args=(catalog_factory, roster_factory),
        name="storefront-index",
        daemon=True,
    ).start()


def get(catalog_factory, roster_factory, *, max_age: float = _TTL) -> Index | None:
    """The index if there is one. A stale index is served as-is while a fresh one
    builds in the background; None only before the first build has finished, which
    is why `warm` runs at boot. Building reads every brand's catalogue from the
    store and takes about a minute and a half, so no request ever waits on it."""
    if _current is None or time.time() - _current.built_at >= max_age:
        _start_build(catalog_factory, roster_factory)
    return _current


def warm(catalog_factory, roster_factory) -> None:
    """Kick off the first build. Call once, at boot."""
    _start_build(catalog_factory, roster_factory)


def reset() -> None:
    global _current, _building
    _current = None
    _building = False


# --- questions the page asks ------------------------------------------------

SORTS = ("latest", "price-asc", "price-desc", "discount")


def _matches(t: dict, *, group, bucket, brand, sale, colour_, q) -> bool:
    if group and t["group"] != group:
        return False
    if bucket and t["bucket"] != bucket:
        return False
    if brand and t["brand_id"] != brand:
        return False
    if sale and not t["sale"]:
        return False
    if colour_ and t["colour"] != colour_:
        return False
    if q:
        hay = f"{t['brand']} {t['title']} {t['bucket']}".lower()
        if not all(word in hay for word in q.lower().split()):
            return False
    return True


def query(
    index: Index,
    *,
    group: str = "",
    bucket: str = "",
    brand: str = "",
    sale: bool = False,
    colour_: str = "",
    q: str = "",
    sort: str = "latest",
    offset: int = 0,
    limit: int = 60,
) -> dict:
    f = dict(group=group, bucket=bucket, brand=brand, sale=sale, colour_=colour_, q=q)
    hits = [t for t in index.tiles if _matches(t, **f)]
    keys: dict[str, Callable[[dict], Any]] = {
        "latest": lambda t: (t["first_seen"], t["title"]),
        "price-asc": lambda t: (t["price"] is None, t["price"] or 0.0),
        "price-desc": lambda t: (t["price"] is None, -(t["price"] or 0.0)),
        "discount": lambda t: (-t["discount"], t["title"]),
    }
    key = keys.get(sort)
    if sort == "latest" and key is not None:
        hits.sort(key=key, reverse=True)
    elif key is not None:
        hits.sort(key=key)

    # Facets narrow like the page's other filters, except along their own axis.
    def count(axis: str, drop: dict) -> dict[str, int]:
        g = {**f, **drop}
        out: dict[str, int] = {}
        for t in index.tiles:
            if _matches(t, **g):
                k = t[axis]
                if k:
                    out[k] = out.get(k, 0) + 1
        return out

    groups = count("group", {"group": "", "bucket": ""})
    buckets = count("bucket", {"bucket": ""})
    tree = []
    for g in GROUPS:
        if not groups.get(g):
            continue
        subs: list[dict[str, Any]] = [
            {"bucket": b, "count": n}
            for b, n in buckets.items()
            if any(gg == g and bb == b for gg, bb, _ in _TAXONOMY)
            or (g == OTHER[0] and b == OTHER[1])
        ]
        subs.sort(key=lambda s: -int(s["count"]))
        tree.append({"group": g, "count": groups[g], "buckets": subs})
    brand_counts = count("brand_id", {"brand": ""})
    names = {b["brand_id"]: b["name"] for b in index.brands}
    designers = sorted(
        ({"brand_id": k, "name": names.get(k, k), "count": n} for k, n in brand_counts.items()),
        key=lambda d: d["name"].lower(),
    )
    colours = count("colour", {"colour_": ""})
    sale_count = sum(1 for t in index.tiles if _matches(t, **{**f, "sale": True}))
    return {
        "products": [slim(t) for t in hits[offset : offset + limit]],
        "total": len(hits),
        "offset": offset,
        "limit": limit,
        "facets": {
            "categories": tree,
            "designers": designers,
            "colours": [{"colour": c, "count": colours[c]} for c in COLOURS if colours.get(c)],
            "sale": sale_count,
        },
        "built_at": index.built_at,
    }
