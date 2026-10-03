"""The catalogue: what the shop shows, as six operations.

The logic for every answer lives here; the legacy /api/archive routes call these
same functions, so the old door and the new one cannot answer differently."""

from __future__ import annotations

from typing import Any

from backend.api.ops import Context, OpError, Param, op
from backend.archive import audience, storefront, storefront_sql
from backend.archive.store.catalog import has_photograph
from backend.archive.store.factory import backend_name

FIELDS = ("tiles", "records", "counts")


def _ar():
    # Imported late: archive_routes imports this module when it registers.
    from backend.api import archive_routes

    return archive_routes


def _entry_or_404(brand: str):
    entry = _ar()._entry(brand)
    if entry is None:
        raise OpError("Brand not shown by this archive", "NOT_FOUND", 404)
    return entry


def _warming(what: str):
    return OpError(f"The shop front is still being {what}", "WARMING", 503)


# --- the answers ---------------------------------------------------------------


def brands_answer() -> dict:
    ar = _ar()
    catalog = ar._catalog()
    try:
        # Three reads for the whole sidebar: the fleet object twice and the brand
        # list once. Per-brand it was 130 round trips and 21.6 seconds.
        status = {r["domain"]: r for r in catalog.status_rows()}
        live = catalog.live_product_counts()
        images = catalog.stored_image_counts()
        brands = [
            ar._brand_row(
                e, status.get(e.domain), catalog, live.get(e.domain, 0), images.get(e.domain, 0)
            )
            for e in ar.app_roster()
            if (status.get(e.domain) or {}).get("state") != "gated"
        ]
        return {"brands": brands, "total": len(brands)}
    finally:
        catalog.close()


def brand_answer(brand: str, include: list[str] | None = None) -> dict:
    ar = _ar()
    entry = _entry_or_404(brand)
    catalog = ar._catalog()
    try:
        status = next((r for r in catalog.status_rows() if r["domain"] == brand), None)
        records = ar._shop_products(brand, catalog)
        row = ar._brand_row(entry, status, catalog, len(records), catalog.stored_image_count(brand))
        row["field_fill"] = ar._field_fill(records)
        cards = catalog.scorecards(brand, limit=1)
        row["scorecard"] = cards[0] if cards else None
        if include and "hierarchy" in include:
            row["hierarchy"] = _hierarchy(records, ar._phrase_book(catalog))
        return row
    finally:
        catalog.close()


def _hierarchy(records: list[dict], book) -> list[dict]:
    ar = _ar()
    tree: dict[str, Any] = {}
    for record in records:
        for path in ar._category_paths(record, book):
            node = tree
            for level in path:
                node = node.setdefault(level, {})

    def build(node: dict, prefix: list[str]) -> list[dict]:
        out = []
        for name in sorted(node):
            path = [*prefix, name]
            out.append({"name": name, "url": "/".join(path), "children": build(node[name], path)})
        return out

    return [{"name": "all products", "url": ar.ALL, "children": []}, *build(tree, [])]


def hierarchy_answer(brand: str) -> dict:
    ar = _ar()
    _entry_or_404(brand)
    catalog = ar._catalog()
    try:
        records = ar._shop_products(brand, catalog)
        book = ar._phrase_book(catalog)
    finally:
        catalog.close()
    return {"hierarchy": _hierarchy(records, book)}


def records_answer(brand: str, category: str, limit: int, offset: int) -> dict:
    ar = _ar()
    _entry_or_404(brand)
    limit = min(max(1, limit), 2000)
    offset = max(0, offset)
    catalog = ar._catalog()
    try:
        book = ar._phrase_book(catalog)
        records = [r for r in ar._shop_products(brand, catalog) if ar._matches(r, category, book)]
        page = records[offset : offset + limit]
        return {
            "products": ar._decorate(page, brand, catalog),
            "total": len(records),
            "limit": limit,
            "offset": offset,
        }
    finally:
        catalog.close()


def counts_answer(brand: str) -> dict:
    ar = _ar()
    _entry_or_404(brand)
    catalog = ar._catalog()
    try:
        records = ar._shop_products(brand, catalog)
        book = ar._phrase_book(catalog)
    finally:
        catalog.close()
    counts: dict[str, int] = {ar.ALL: len(records)}
    for record in records:
        # A product in two places is counted in both, and once under "all" — the same
        # arithmetic a shop's own filter bar does. Every ancestor counts it too.
        for path in ar._category_paths(record, book):
            for depth in range(1, len(path) + 1):
                key = "/".join(path[:depth])
                counts[key] = counts.get(key, 0) + 1
    return {"counts": counts}


def search_answer(q: str, limit: int) -> dict:
    ar = _ar()
    q = (q or "").strip()
    limit = min(max(1, limit), 1000)
    if not q:
        return {"products": [], "total": 0}
    domains = [e.domain for e in ar.app_roster()]
    catalog = ar._catalog()
    try:
        by_domain: dict[str, list[dict]] = {}
        for domain, record in catalog.search_products(domains, q, limit):
            if not has_photograph(record) or not ar._open(domain, catalog):
                continue
            by_domain.setdefault(domain, []).append(record)
        out = []
        for domain, records in by_domain.items():
            out.extend(ar._decorate(records, domain, catalog))
        return {"products": out, "total": len(out)}
    finally:
        catalog.close()


def storefront_answer(args: dict) -> dict:
    """The tiles for one view of the grid and the counts every column shows."""
    ar = _ar()
    sort = args.get("sort") or "type"
    if sort not in storefront.SORTS:
        raise OpError(f"sort must be one of {', '.join(storefront.SORTS)}")
    brand = args.get("brand") or ""
    if brand:
        _entry_or_404(brand)
    view = dict(
        group=args.get("group") or "",
        bucket=args.get("bucket") or "",
        brand=brand,
        sale=bool(args.get("sale")),
        q=(args.get("q") or "").strip(),
        sort=sort,
        offset=max(0, int(args.get("offset") or 0)),
        limit=min(max(1, int(args.get("limit") or 60)), 240),
    )
    colour = args.get("colour") or ""
    gender = (args.get("gender") or "").strip().lower()
    if gender and gender not in audience.GENDERS:
        raise OpError(f"gender must be one of {', '.join(audience.GENDERS)}")
    # Sizes arrive as one comma-separated value ("M,L"): any of them, like a shop's own
    # size row. They are the shop's own spellings, matched as given.
    sizes = tuple(s.strip() for s in (args.get("size") or "").split(",") if s.strip())
    in_stock = bool(args.get("in_stock"))

    def _price(name: str) -> float | None:
        raw = args.get(name)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise OpError(f"{name} must be a number") from exc

    price_min, price_max = _price("price_min"), _price("price_max")
    if backend_name() == "pg":
        pg = ar._pg_view()
        if pg is None:
            raise _warming("filled")
        pool, roster, domains = pg
        return storefront_sql.query(
            pool,
            roster=roster,
            domains=domains,
            colour=colour,
            gender=gender,
            sizes=sizes,
            in_stock=in_stock,
            price_min=price_min,
            price_max=price_max,
            **view,
        )
    index = ar._index()
    if index is None:
        raise _warming("built")
    # The object-store backend is the fallback path and has no gender, size or price
    # filtering: those read columns the Postgres rows carry. It is told so rather than
    # quietly ignoring half the request.
    if gender or sizes or in_stock or price_min is not None or price_max is not None:
        raise OpError("gender, size, stock and price filters need the Postgres catalogue")
    return storefront.query(index, colour_=colour, **view)


def product_answer(brand: str, handle: str = "", url: str = "") -> dict:
    ar = _ar()
    if not ar._entry(brand) or not (url or handle):
        raise OpError("brand and handle (or url) are required")
    if backend_name() == "pg":
        pg = ar._pg_view()
        if pg is None:
            raise _warming("filled")
        pool, roster, domains = pg
        found = storefront_sql.product(
            pool, roster=roster, domains=domains, brand=brand, handle=handle, url=url
        )
        if found is None:
            raise OpError("No such product", "NOT_FOUND", 404)
        return found
    index = ar._index()
    if index is None:
        raise _warming("built")
    t = next(
        (
            t
            for t in index.tiles
            if t["brand_id"] == brand and (t["url"] == url if url else t["handle"] == handle)
        ),
        None,
    )
    if t is None:
        raise OpError("No such product", "NOT_FOUND", 404)
    more = [
        m for m in storefront.query(index, brand=brand, limit=9)["products"] if m["url"] != t["url"]
    ][:8]
    return {"tile": t, "more": more}


def health_answer() -> dict:
    ar = _ar()
    catalog = ar._catalog()  # raises NoCatalogue, which the app turns into a 503
    try:
        shown = [e.domain for e in ar.app_roster()]
        live = catalog.live_product_counts()
        counts = [live.get(domain, 0) for domain in shown]
        return {
            "ok": True,
            "store": type(ar.store()).__name__,
            "brands_shown": len(shown),
            "brands_with_products": sum(1 for n in counts if n),
            "products": sum(counts),
        }
    finally:
        catalog.close()


# --- the operations -----------------------------------------------------------

_PAGE = (
    Param("offset", "integer", "Skip this many; the next page starts here.", default=0),
    Param("limit", "integer", "How many; 60 by default, 240 at most for tiles.", default=60),
)


@op(
    name="catalogue_products",
    family="catalogue",
    summary="The products the shop shows, filtered and ordered, in one of three shapes.",
    method="GET",
    path="/api/catalogue/products",
    reads=("products", "product_tags", "brands.yml", "fleet.json"),
    replaces=("archive_storefront", "archive_products", "archive_search", "archive_counts"),
    params=(
        Param(
            "fields",
            "string",
            "tiles: the grid's tiles plus the counts every column shows. "
            "records: whole product records for one brand (or a search across all). "
            "counts: products per category path for one brand.",
            default="tiles",
            choices=FIELDS,
        ),
        Param("brand", "string", "One brand, by domain. Required for records and counts."),
        Param("group", "string", "A top-level group of the taxonomy (tiles)."),
        Param("bucket", "string", "A bucket inside the group (tiles)."),
        Param("colour", "string", "A colour from the palette (tiles)."),
        Param("sale", "boolean", "Only what is reduced (tiles).", default=False),
        Param(
            "gender",
            "string",
            "women or men. A product's own words decide where it has any; otherwise its "
            "brand's audience does. A brand that sells to everyone shows under both.",
            choices=audience.GENDERS,
        ),
        Param(
            "size",
            "string",
            "One size, or several separated by commas — any of them. A size counts only "
            "where the shop has not said it is out of stock.",
        ),
        Param(
            "in_stock",
            "boolean",
            "Only what the shop has not marked sold out.",
            default=False,
        ),
        Param("price_min", "number", "Lowest price, in the shop's own figures."),
        Param("price_max", "number", "Highest price, in the shop's own figures."),
        Param("q", "string", "Words to match in titles and descriptions."),
        Param("sort", "string", "Order of the tiles.", default="type", choices=storefront.SORTS),
        Param("category", "string", "A category path such as TOPS/TEES (records).", default="*"),
        *_PAGE,
    ),
    example={"fields": "tiles", "bucket": "jackets", "colour": "black", "limit": 12},
)
def catalogue_products(ctx: Context, a: dict) -> dict:
    """Three shapes because three pages need three things from the same table, and
    one route with a `fields` switch is one query grammar to learn rather than four.
    A filter that does not apply to a shape is ignored, not refused."""
    if a["fields"] == "counts":
        if not a["brand"]:
            raise OpError("brand is required for counts")
        return counts_answer(a["brand"])
    if a["fields"] == "records":
        if a["brand"]:
            return records_answer(a["brand"], a["category"] or "*", a["limit"], a["offset"])
        if a["q"]:
            return search_answer(a["q"], a["limit"])
        raise OpError("records need a brand, or q to search every brand")
    return storefront_answer(a)


@op(
    name="catalogue_product",
    family="catalogue",
    summary="One product with everything its page shows, and more from the same brand.",
    method="GET",
    path="/api/catalogue/products/{brand}/{handle}",
    reads=("products", "product_tags", "product_images"),
    replaces=("archive_product",),
    params=(
        Param("brand", "string", "The brand's domain.", required=True),
        Param(
            "handle",
            "string",
            "The product's handle: the last part of its shop URL.",
            required=True,
        ),
    ),
    example={"brand": "huelleyrose.com", "handle": "kira-skirt"},
)
def catalogue_product(ctx: Context, a: dict) -> dict:
    return product_answer(a["brand"], handle=a["handle"])


@op(
    name="catalogue_brands",
    family="catalogue",
    summary="Every brand the shop shows, with how much of it the archive holds.",
    method="GET",
    path="/api/catalogue/brands",
    reads=("brands.yml", "fleet.json", "products"),
    replaces=("archive_brands",),
)
def catalogue_brands(ctx: Context, a: dict) -> dict:
    return brands_answer()


@op(
    name="catalogue_brand",
    family="catalogue",
    summary="One brand: its roster entry, state, field fill and latest scorecard.",
    method="GET",
    path="/api/catalogue/brands/{brand}",
    reads=("brands.yml", "fleet.json", "products"),
    replaces=("archive_brand", "archive_hierarchy"),
    params=(
        Param("brand", "string", "The brand's domain.", required=True),
        Param("include", "array", "Extra sections: hierarchy (its category tree).", default=[]),
    ),
    example={"brand": "huelleyrose.com", "include": "hierarchy"},
)
def catalogue_brand(ctx: Context, a: dict) -> dict:
    return brand_answer(a["brand"], include=a["include"])


@op(
    name="catalogue_rates",
    family="catalogue",
    summary="Today's exchange rates against the dollar, for showing prices in one currency.",
    method="GET",
    path="/api/catalogue/rates",
    reads=("api.frankfurter.dev (ECB)", "open.er-api.com"),
    replaces=("archive_rates",),
)
def catalogue_rates(ctx: Context, a: dict) -> dict:
    return _ar().rates_answer()


@op(
    name="catalogue_health",
    family="catalogue",
    summary="Whether the catalogue is where the app thinks it is, and how big.",
    method="GET",
    path="/api/catalogue/health",
    reads=("fleet.json", "products"),
    replaces=("archive_health",),
)
def catalogue_health(ctx: Context, a: dict) -> dict:
    return health_answer()


OPS = [
    catalogue_products,
    catalogue_product,
    catalogue_brands,
    catalogue_brand,
    catalogue_rates,
    catalogue_health,
]
