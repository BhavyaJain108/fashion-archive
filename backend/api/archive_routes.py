"""The My Brands page, served from the archive.

Read-only, and deliberately so. The roster is brands.yml and the products are whatever
the scraper last wrote into the catalogue; the page shows that and changes none of it.
Scraping runs beside the app, not inside it — that separation is the point, so that a
code deploy and a running scrape do not have to agree about anything.

Everything lives under /api/archive/ so the older pipeline's /api/brands routes keep
working for the panels that still use them.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from backend.archive import storefront, storefront_sql, taxonomy
from backend.archive.roster import RosterEntry, app_roster
from backend.archive.store.catalog import Catalog, has_photograph
from backend.archive.store.factory import backend_name, open_catalog
from backend.archive.store.objects import ObjectStore, object_store

_ROOT = Path(__file__).resolve().parents[2]
_MAX_CATEGORY_LEVELS = 10

# A record carries the connector's untouched payload so a mapping can be re-derived
# later. It is worth many times the rest of the record in bytes and means nothing to a
# browser, so it does not go over the wire.
_DROP = ("raw",)

# Not a category: the leaf every brand has, so a shop that publishes no taxonomy at all
# is still browsable. Products with no categories get their own leaf rather than being
# quietly dropped out of the tree.
ALL = "*"
UNCATEGORISED = "(uncategorised)"


def store() -> ObjectStore:
    """The archive's store. R2 in production; a directory when ARCHIVE_OBJECTS says so."""
    local = os.environ.get("ARCHIVE_OBJECTS")
    return object_store(Path(local) if local else None)


class NoCatalogue(RuntimeError):
    """There is no archive in this store.

    Worth its own error, because every read of an absent object answers "nothing"
    rather than failing. Without this check each endpoint would succeed, every brand
    would report zero products, and the page would look like an archive that had
    scraped nothing rather than one that is not there.
    """


def _catalog() -> Catalog:
    backing = store()
    # One GET rather than a LIST: fleet.json names every brand the archive knows.
    if backing.get("fleet.json") is None and not backing.list("brands/"):
        raise NoCatalogue("no archive in this store: no fleet.json and nothing under brands/")
    return open_catalog(backing)


# The phrase book is one small object shared by every brand; re-reading it on each
# request would be a round trip per page for something that changes when someone edits it.
BOOK_CACHE_SECONDS = 60
_book_cache: tuple[float, Any] | None = None


def _slim(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in _DROP}


def _category_path(record: dict) -> list[str]:
    levels = []
    for i in range(1, _MAX_CATEGORY_LEVELS + 1):
        value = record.get(f"category{i}")
        if value in (None, ""):
            break
        levels.append(str(value))
    return levels


def _category_paths(record: dict, book) -> list[list[str]]:
    """Where this product hangs in a brand's tree — one place, or several.

    The shop's own path wins wherever it published one. Where it published none, the
    archive's own word for the thing stands in: half the fleet publishes no categories
    at all, and before this psylos1's 7,939 products were one undifferentiated heap
    called (uncategorised). A product may answer to two types ("set" is a top and a
    bottom) and then hangs in both, which is what a shop's own filter does too.
    """
    shop = _category_path(record)
    if shop:
        return [shop]
    return [[t] for t in book.types_for(record)] or [[UNCATEGORISED]]


def _leaf_keys(record: dict, book) -> list[str]:
    return ["/".join(path) for path in _category_paths(record, book)]


def _matches(record: dict, category: str, book) -> bool:
    """A product belongs to a category if that category is one of its paths, or a
    parent of one."""
    if category in ("", ALL):
        return True
    return any(
        leaf == category or leaf.startswith(category + "/") for leaf in _leaf_keys(record, book)
    )


# ---------------------------------------------------------------------------
# what the site may show
# ---------------------------------------------------------------------------

# The site shows only what a person could go and buy: the products of the most
# recent run that read the whole shop, from brands that are open, with a photograph.
# A password-gated brand may still hold products from before its wall went up; those
# are the archive's memory, not the shop's window.


def _open(domain: str, catalog: Catalog) -> bool:
    return catalog.get_brand_state(domain) != "gated"


def _visible(records: list[dict]) -> list[dict]:
    return [r for r in records if has_photograph(r)]


def _shop_products(domain: str, catalog: Catalog) -> list[dict]:
    if not _open(domain, catalog):
        return []
    # A gift card, a shipping fee, a tax line and "Price difference" are real rows in a
    # shop's catalogue and not things anyone came here to look at. The archive keeps
    # them and the deck still shows them; the window does not.
    book = _phrase_book(catalog)
    return [r for r in _visible(catalog.current_products(domain)) if book.is_product(r)]


# ---------------------------------------------------------------------------
# brands
# ---------------------------------------------------------------------------


def _brand_row(
    entry: RosterEntry,
    status: dict | None,
    catalog: Catalog,
    live: int | None = None,
    images: int | None = None,
) -> dict:
    products = live if live is not None else (status["products"] if status else 0)
    return {
        "brand_id": entry.domain,
        "domain": entry.domain,
        "name": entry.name,
        "homepage_url": entry.homepage_url,
        "size": entry.size,
        "notes": entry.notes,
        "state": (status or {}).get("state", "new"),
        "products": products,
        "images": images if images is not None else 0,
        "coverage_pct": (status or {}).get("coverage_pct"),
        "verdict": (status or {}).get("verdict"),
        "last_run": (status or {}).get("freshness"),
        "mode": (status or {}).get("mode"),
    }


def get_brands():
    """GET /api/archive/brands — the roster the app shows, with what the archive holds."""
    catalog = _catalog()
    try:
        # Three reads for the whole sidebar: the fleet object twice and the brand
        # list once. Per-brand it was 130 round trips and 21.6 seconds.
        status = {r["domain"]: r for r in catalog.status_rows()}
        live = catalog.live_product_counts()
        images = catalog.stored_image_counts()
        brands = [
            _brand_row(
                e,
                status.get(e.domain),
                catalog,
                live.get(e.domain, 0),
                images.get(e.domain, 0),
            )
            for e in app_roster()
            if (status.get(e.domain) or {}).get("state") != "gated"
        ]
        return jsonify({"brands": brands, "total": len(brands)})
    finally:
        catalog.close()


def _entry(domain: str) -> RosterEntry | None:
    return next((e for e in app_roster() if e.domain == domain), None)


def get_brand(brand_id):
    """GET /api/archive/brands/<brand_id> — one brand, with how well it is filled in."""
    entry = _entry(brand_id)
    if not entry:
        return jsonify({"error": "Brand not shown by this archive"}), 404
    catalog = _catalog()
    try:
        status = next((r for r in catalog.status_rows() if r["domain"] == brand_id), None)
        records = _shop_products(brand_id, catalog)
        row = _brand_row(entry, status, catalog, len(records), catalog.stored_image_count(brand_id))
        row["field_fill"] = _field_fill(records)
        cards = catalog.scorecards(brand_id, limit=1)
        row["scorecard"] = cards[0] if cards else None
        return jsonify(row)
    finally:
        catalog.close()


def _field_fill(records: list[dict]) -> dict[str, float]:
    """Share of this brand's products that carry a value for each field.

    The page shows it so a brand whose catalogue looks complete but whose products are
    three-quarters blank cannot pass for a healthy one.
    """
    if not records:
        return {}
    keys: list[str] = []
    for record in records:
        for k in record:
            if k not in _DROP and k not in keys:
                keys.append(k)
    out = {}
    for key in keys:
        filled = sum(1 for r in records if r.get(key) not in (None, "", [], {}))
        if filled:
            out[key] = round(filled / len(records), 4)
    return out


def get_hierarchy(brand_id):
    """GET /api/archive/brands/<brand_id>/categories/hierarchy — how this brand is shelved.

    Built from the category1..category10 columns rather than stored separately: those
    columns are what the scraper actually recorded, so the tree can never claim a
    category no product is in. Where a shop published no columns at all, the archive's
    own word for each product stands in — otherwise half the fleet is one heap.
    """
    catalog = _catalog()
    try:
        records = _shop_products(brand_id, catalog)
        book = _phrase_book(catalog)
    finally:
        catalog.close()

    tree: dict[str, Any] = {}
    for record in records:
        for path in _category_paths(record, book):
            node = tree
            for level in path:
                node = node.setdefault(level, {})

    def build(node: dict, prefix: list[str]) -> list[dict]:
        out = []
        for name in sorted(node):
            path = [*prefix, name]
            out.append(
                {
                    "name": name,
                    "url": "/".join(path),
                    "children": build(node[name], path),
                }
            )
        return out

    hierarchy = [{"name": "all products", "url": ALL, "children": []}, *build(tree, [])]
    return jsonify({"hierarchy": hierarchy})


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------


def _phrase_book(catalog: Catalog):
    """The shared vocabulary, re-read at most once a minute.

    One small object, and the answer to "what is this product" for every brand. Reading
    it per request would be a round trip on every page; a minute stale is invisible to a
    reader and means a correction still lands within a minute.
    """
    global _book_cache
    now = time.time()
    if _book_cache and now - _book_cache[0] < BOOK_CACHE_SECONDS:
        return _book_cache[1]
    book = taxonomy.load(catalog.store)
    _book_cache = (now, book)
    return book


def _decorate(records: list[dict], domain: str, catalog: Catalog) -> list[dict]:
    archived = catalog.archived_images(domain)
    book = _phrase_book(catalog)
    # The stored `brand` is whatever the shop published, which for most of these is the
    # domain — accurate, and not what anyone wants to read on a tile. The roster's name
    # travels alongside it rather than overwriting it.
    name = next((e.name for e in app_roster() if e.domain == domain), domain)
    out = []
    for record in records:
        slim = _slim(record)
        # What this product answers to in the archive's own words, beside the shop's.
        types = book.types_for(record)
        slim[taxonomy.TYPE_FIELD] = ", ".join(types) if types else None
        slim["brand_id"] = domain
        slim["brand_name"] = name
        urls = archived.get(record.get("itemurl", ""), [])
        if urls:
            slim["archived_images"] = urls
        out.append(slim)
    return out


def get_products():
    """GET /api/archive/products?brand_id=&category=&limit=&offset="""
    brand_id = request.args.get("brand_id", "")
    if not _entry(brand_id):
        return jsonify({"error": "Brand not shown by this archive"}), 404
    category = request.args.get("category", ALL)
    limit = min(int(request.args.get("limit", 200)), 2000)
    offset = int(request.args.get("offset", 0))

    catalog = _catalog()
    try:
        book = _phrase_book(catalog)
        records = [r for r in _shop_products(brand_id, catalog) if _matches(r, category, book)]
        page = records[offset : offset + limit]
        return jsonify(
            {
                "products": _decorate(page, brand_id, catalog),
                "total": len(records),
                "limit": limit,
                "offset": offset,
            }
        )
    finally:
        catalog.close()


def get_counts():
    """GET /api/archive/products/counts?brand_id= — products per leaf category."""
    brand_id = request.args.get("brand_id", "")
    if not _entry(brand_id):
        return jsonify({"error": "Brand not shown by this archive"}), 404
    catalog = _catalog()
    try:
        records = _shop_products(brand_id, catalog)
        book = _phrase_book(catalog)
    finally:
        catalog.close()

    counts: dict[str, int] = {ALL: len(records)}
    for record in records:
        # A product in two places is counted in both, and once under "all" — the same
        # arithmetic a shop's own filter bar does.
        for path in _category_paths(record, book):
            # Every ancestor counts it too, so a collapsed parent still shows a total.
            for depth in range(1, len(path) + 1):
                key = "/".join(path[:depth])
                counts[key] = counts.get(key, 0) + 1
    return jsonify({"counts": counts})


def search_products():
    """GET /api/archive/products/search?q=&limit= — across every brand the app shows."""
    query = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 200)), 1000)
    if not query:
        return jsonify({"products": []})

    domains = [e.domain for e in app_roster()]
    catalog = _catalog()
    try:
        by_domain: dict[str, list[dict]] = {}
        for domain, record in catalog.search_products(domains, query, limit):
            if not has_photograph(record) or not _open(domain, catalog):
                continue
            by_domain.setdefault(domain, []).append(record)
        out = []
        for domain, records in by_domain.items():
            out.extend(_decorate(records, domain, catalog))
        return jsonify({"products": out, "total": len(out)})
    finally:
        catalog.close()


# ---------------------------------------------------------------------------
# the shop front: every brand in one grid
# ---------------------------------------------------------------------------


def _index() -> storefront.Index | None:
    return storefront.get(_catalog, app_roster)


def _pg_view():
    """(pool, roster, open domains) for the SQL shop front, or None while the first
    backfill is still filling the table."""
    from backend.archive.store import backfill

    catalog = _catalog()
    try:
        if backfill.in_progress():
            return None
        pool = catalog._pool
        domains = storefront_sql.open_domains(catalog, app_roster())
    finally:
        catalog.close()
    return pool, list(app_roster()), domains


def get_storefront():
    """GET /api/archive/storefront?group=&bucket=&brand=&sale=&colour=&q=&sort=&offset=&limit=

    One answer for the whole page: the tiles for this view, and the counts every
    column shows. On the Postgres backend this is six small queries; on the
    object-store backend it is served from an in-memory index built at boot.
    """
    a = request.args
    try:
        offset = max(0, int(a.get("offset", 0)))
        limit = min(max(1, int(a.get("limit", 60))), 240)
    except ValueError:
        return jsonify({"error": "offset and limit must be integers"}), 400
    sort = a.get("sort", "latest")
    if sort not in storefront.SORTS:
        return jsonify({"error": f"sort must be one of {', '.join(storefront.SORTS)}"}), 400
    brand = a.get("brand", "")
    if brand and not _entry(brand):
        return jsonify({"error": "Brand not shown by this archive"}), 404
    args = dict(
        group=a.get("group", ""),
        bucket=a.get("bucket", ""),
        brand=brand,
        sale=a.get("sale", "") in ("1", "true", "yes"),
        q=a.get("q", "").strip(),
        sort=sort,
        offset=offset,
        limit=limit,
    )
    if backend_name() == "pg":
        view = _pg_view()
        if view is None:
            return jsonify(
                {"error": "The shop front is still being filled", "code": "WARMING"}
            ), 503
        pool, roster, domains = view
        return jsonify(
            storefront_sql.query(
                pool, roster=roster, domains=domains, colour=a.get("colour", ""), **args
            )
        )
    index = _index()
    if index is None:
        return jsonify({"error": "The shop front is still being built", "code": "WARMING"}), 503
    return jsonify(storefront.query(index, colour_=a.get("colour", ""), **args))


def get_product():
    """GET /api/archive/product?brand_id=&handle= — one product with everything the
    page shows, and eight more from the same brand. One indexed lookup on the
    Postgres backend; on the object-store backend, a scan of the in-memory index."""
    brand_id = request.args.get("brand_id", "")
    url = request.args.get("url", "")
    handle = request.args.get("handle", "")
    if not _entry(brand_id) or not (url or handle):
        return jsonify({"error": "brand_id and url or handle are required"}), 400
    if backend_name() == "pg":
        view = _pg_view()
        if view is None:
            return jsonify(
                {"error": "The shop front is still being filled", "code": "WARMING"}
            ), 503
        pool, roster, domains = view
        found = storefront_sql.product(
            pool, roster=roster, domains=domains, brand=brand_id, handle=handle, url=url
        )
        if found is None:
            return jsonify({"error": "No such product"}), 404
        return jsonify(found)
    index = _index()
    if index is None:
        return jsonify({"error": "The shop front is still being built", "code": "WARMING"}), 503
    t = next(
        (
            t
            for t in index.tiles
            if t["brand_id"] == brand_id and (t["url"] == url if url else t["handle"] == handle)
        ),
        None,
    )
    if t is None:
        return jsonify({"error": "No such product"}), 404
    more = [
        m
        for m in storefront.query(index, brand=brand_id, limit=9)["products"]
        if m["url"] != t["url"]
    ][:8]
    return jsonify({"tile": t, "more": more})


# ---------------------------------------------------------------------------


def get_health():
    """GET /api/archive/health — whether the catalogue is where the app thinks it is."""
    catalog = _catalog()  # raises NoCatalogue, which the handler turns into a 503
    try:
        shown = [e.domain for e in app_roster()]
        live = catalog.live_product_counts()
        counts = [live.get(domain, 0) for domain in shown]
        return jsonify(
            {
                "ok": True,
                "store": type(store()).__name__,
                "brands_shown": len(shown),
                "brands_with_products": sum(1 for n in counts if n),
                "products": sum(counts),
            }
        )
    finally:
        catalog.close()


# ---------------------------------------------------------------------------
# money
# ---------------------------------------------------------------------------

# The shops price in their own currencies — dollars, euros, pounds, Australian
# dollars, roubles. A visitor reads prices in theirs. The rates come from the
# European Central Bank by way of frankfurter.dev, once a day, no key; a currency
# the ECB does not publish (the rouble, since 2022) is shown as the shop prints it.
RATES_URL = "https://api.frankfurter.dev/v1/latest?base=USD"
# The central bank publishes about thirty currencies and no rouble. A second feed
# fills in whatever the bank leaves out (RUB for xsai.vision); the bank's figure wins
# wherever both have one.
RATES_FALLBACK_URL = "https://open.er-api.com/v6/latest/USD"
RATES_TTL_SECONDS = 6 * 3600
_rates_cache: tuple[float, dict] | None = None
_rates_lock = threading.Lock()


def _fetch_json(url: str) -> dict:
    import urllib.request

    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 — fixed https URLs
        return json.loads(resp.read().decode("utf-8"))


def _fetch_rates() -> dict:
    body = _fetch_json(RATES_URL)
    rates = {k: float(v) for k, v in (body.get("rates") or {}).items()}
    rates["USD"] = 1.0
    try:
        extra = _fetch_json(RATES_FALLBACK_URL).get("rates") or {}
    except Exception:  # noqa: BLE001 — the second feed is a bonus, not a requirement
        extra = {}
    for code, value in extra.items():
        if code not in rates:
            try:
                rates[code] = float(value)
            except (TypeError, ValueError):
                continue
    return {"ok": True, "base": "USD", "date": body.get("date"), "rates": rates}


def get_rates():
    """GET /api/archive/rates — today's exchange rates against the dollar."""
    global _rates_cache
    with _rates_lock:
        if _rates_cache and time.monotonic() - _rates_cache[0] < RATES_TTL_SECONDS:
            return jsonify(_rates_cache[1])
        try:
            payload = _fetch_rates()
            _rates_cache = (time.monotonic(), payload)
        except Exception as e:  # noqa: BLE001 — the page shows shop prices when this fails
            payload = _rates_cache[1] if _rates_cache else {"ok": False, "error": str(e)[:160]}
        return jsonify(payload)


def _no_catalogue(error: NoCatalogue):
    return jsonify({"ok": False, "error": str(error), "code": "NO_CATALOGUE"}), 503


def register_archive_routes(app: Flask) -> None:
    app.register_error_handler(NoCatalogue, _no_catalogue)
    app.add_url_rule("/api/archive/health", "archive_health", get_health, methods=["GET"])
    app.add_url_rule("/api/archive/brands", "archive_brands", get_brands, methods=["GET"])
    app.add_url_rule("/api/archive/rates", "archive_rates", get_rates, methods=["GET"])
    app.add_url_rule("/api/archive/brands/<brand_id>", "archive_brand", get_brand, methods=["GET"])
    app.add_url_rule(
        "/api/archive/brands/<brand_id>/categories/hierarchy",
        "archive_hierarchy",
        get_hierarchy,
        methods=["GET"],
    )
    app.add_url_rule("/api/archive/products", "archive_products", get_products, methods=["GET"])
    app.add_url_rule("/api/archive/products/counts", "archive_counts", get_counts, methods=["GET"])
    app.add_url_rule(
        "/api/archive/products/search", "archive_search", search_products, methods=["GET"]
    )
    app.add_url_rule(
        "/api/archive/storefront", "archive_storefront", get_storefront, methods=["GET"]
    )
    app.add_url_rule("/api/archive/product", "archive_product", get_product, methods=["GET"])
