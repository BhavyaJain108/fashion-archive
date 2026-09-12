"""The My Brands page, served from the archive.

Read-only, and deliberately so. The roster is brands.yml and the products are whatever
the scraper last wrote into the catalogue; the page shows that and changes none of it.
Scraping runs beside the app, not inside it — that separation is the point, so that a
code deploy and a running scrape do not have to agree about anything.

Everything lives under /api/archive/ so the older pipeline's /api/brands routes keep
working for the panels that still use them.
"""

import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from backend.archive.roster import RosterEntry, app_roster
from backend.archive.store.catalog import Catalog
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
    if not backing.list("brands/"):
        raise NoCatalogue("no archive in this store: nothing under brands/")
    return Catalog(backing)


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


def _leaf_key(record: dict) -> str:
    path = _category_path(record)
    return "/".join(path) if path else UNCATEGORISED


def _matches(record: dict, category: str) -> bool:
    """A product belongs to a category if that category is its path or a parent of it."""
    if category in ("", ALL):
        return True
    leaf = _leaf_key(record)
    return leaf == category or leaf.startswith(category + "/")


# ---------------------------------------------------------------------------
# brands
# ---------------------------------------------------------------------------


def _brand_row(
    entry: RosterEntry, status: dict | None, catalog: Catalog, live: int | None = None
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
        "images": catalog.stored_image_count(entry.domain) if products else 0,
        "coverage_pct": (status or {}).get("coverage_pct"),
        "verdict": (status or {}).get("verdict"),
        "last_run": (status or {}).get("freshness"),
        "mode": (status or {}).get("mode"),
    }


def get_brands():
    """GET /api/archive/brands — the roster the app shows, with what the archive holds."""
    catalog = _catalog()
    try:
        status = {r["domain"]: r for r in catalog.status_rows()}
        live = catalog.live_product_counts()
        brands = [
            _brand_row(e, status.get(e.domain), catalog, live.get(e.domain, 0))
            for e in app_roster()
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
        records = catalog.current_products(brand_id)
        row = _brand_row(entry, status, catalog, len(records))
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
    """GET /api/archive/brands/<brand_id>/categories/hierarchy — the brand's own taxonomy.

    Built from the category1..category10 columns rather than stored separately: those
    columns are what the scraper actually recorded, so the tree can never claim a
    category no product is in.
    """
    catalog = _catalog()
    try:
        records = catalog.current_products(brand_id)
    finally:
        catalog.close()

    tree: dict[str, Any] = {}
    for record in records:
        node = tree
        for level in _category_path(record) or [UNCATEGORISED]:
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


def _decorate(records: list[dict], domain: str, catalog: Catalog) -> list[dict]:
    archived = catalog.archived_images(domain)
    # The stored `brand` is whatever the shop published, which for most of these is the
    # domain — accurate, and not what anyone wants to read on a tile. The roster's name
    # travels alongside it rather than overwriting it.
    name = next((e.name for e in app_roster() if e.domain == domain), domain)
    out = []
    for record in records:
        slim = _slim(record)
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
        records = [r for r in catalog.current_products(brand_id) if _matches(r, category)]
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
        records = catalog.current_products(brand_id)
    finally:
        catalog.close()

    counts: dict[str, int] = {ALL: len(records)}
    for record in records:
        path = _category_path(record) or [UNCATEGORISED]
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
            by_domain.setdefault(domain, []).append(record)
        out = []
        for domain, records in by_domain.items():
            out.extend(_decorate(records, domain, catalog))
        return jsonify({"products": out, "total": len(out)})
    finally:
        catalog.close()


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


def _no_catalogue(error: NoCatalogue):
    return jsonify({"ok": False, "error": str(error), "code": "NO_CATALOGUE"}), 503


def register_archive_routes(app: Flask) -> None:
    app.register_error_handler(NoCatalogue, _no_catalogue)
    app.add_url_rule("/api/archive/health", "archive_health", get_health, methods=["GET"])
    app.add_url_rule("/api/archive/brands", "archive_brands", get_brands, methods=["GET"])
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
