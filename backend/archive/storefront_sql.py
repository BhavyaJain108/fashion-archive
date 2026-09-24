"""The shop front as queries, for the Postgres catalogue.

Same answers as `storefront.query` and the product route, but each page is six
small queries over `products` instead of a scan of an in-memory index that
took a minute and a half to build. The vocabulary (groups, buckets, colours) is
written into the rows at scrape time by `storefront.classify` and
`storefront.colour`, so the columns are already what the page filters on.

What counts as "in the shop" is the same three rules the index applied: the
brand is in the roster and not gated, the product belongs to the brand's live
run, and it has a photograph.
"""

from __future__ import annotations

import time
from typing import Any

from backend.archive import storefront as shop
from backend.archive.storefront import _TAXONOMY, COLOURS, GROUPS, OTHER, slim

_MAX_PRICE = 20000.0  # above this a "price" is a placeholder; see storefront._num

_OPEN_TTL = 120.0
_open_cache: tuple[float, list[str]] = (0.0, [])


def open_domains(catalog, roster) -> list[str]:
    """Roster brands that are not gated. Brand state lives in the object store, one
    small read per brand, so it is remembered for two minutes."""
    global _open_cache
    at, held = _open_cache
    if time.time() - at < _OPEN_TTL and held:
        return held
    out = [e.domain for e in roster if catalog.get_brand_state(e.domain) != "gated"]
    _open_cache = (time.time(), out)
    return out


def forget_open_domains() -> None:
    global _open_cache
    _open_cache = (0.0, [])


# The rows the page can show at all. `%(domains)s` is the open roster.
_BASE = """
FROM products p
JOIN catalogue_brands b ON b.brand = p.brand AND b.live_run = p.last_covered_run
WHERE p.brand = ANY(%(domains)s)
  AND (p.main_image_url IS NOT NULL OR jsonb_array_length(p.all_images) > 0)
"""

_PRICE = "CASE WHEN p.price > %(max_price)s THEN NULL ELSE p.price END"
_FULL = "CASE WHEN p.full_price > %(max_price)s THEN NULL ELSE p.full_price END"
_SALE = f"({_PRICE} IS NOT NULL AND {_FULL} IS NOT NULL AND {_FULL} > {_PRICE})"
_DISCOUNT = f"CASE WHEN {_SALE} THEN ({_FULL} - {_PRICE}) / {_FULL} ELSE 0 END"

_ORDER = {
    "latest": "p.first_seen_run DESC, p.title",
    "price-asc": f"{_PRICE} ASC NULLS LAST, p.title",
    "price-desc": f"{_PRICE} DESC NULLS LAST, p.title",
    "discount": f"{_DISCOUNT} DESC, p.title",
}

_TILE_COLS = """
p.brand, p.record, p.first_seen_run, p.last_seen_run, p.last_covered_run,
(SELECT array_agg(i.stored_url ORDER BY i.updated_at) FROM product_images i
   WHERE i.brand = p.brand AND i.itemurl = p.itemurl AND i.stored_url IS NOT NULL) AS archived
"""


def _where(f: dict, *, skip: tuple[str, ...] = ()) -> tuple[str, dict]:
    clauses, params = [], {}
    if f.get("group") and "group" not in skip:
        clauses.append("p.shop_group = %(group)s")
        params["group"] = f["group"]
    if f.get("bucket") and "bucket" not in skip:
        clauses.append("p.shop_bucket = %(bucket)s")
        params["bucket"] = f["bucket"]
    if f.get("brand") and "brand" not in skip:
        clauses.append("p.brand = %(brand)s")
        params["brand"] = f["brand"]
    if f.get("sale") and "sale" not in skip:
        clauses.append(_SALE)
    if f.get("colour") and "colour" not in skip:
        clauses.append("p.shop_colour = %(colour)s")
        params["colour"] = f["colour"]
    if f.get("q") and "q" not in skip:
        clauses.append("(p.search @@ plainto_tsquery('simple', %(q)s) OR p.title ILIKE %(q_like)s)")
        params["q"] = f["q"]
        params["q_like"] = f"%{f['q']}%"
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _stamp(run_id: str | None) -> str:
    return run_id.rsplit("-", 1)[0] if run_id else ""


def _tile(row, names: dict[str, str]) -> dict:
    brand, record, first, seen, covered, archived = row
    t = shop.tile(
        record,
        brand_id=brand,
        brand_name=names.get(brand, brand),
        first_seen=_stamp(first),
        archived=list(archived or []),
        history={"last_seen": _stamp(seen), "last_on_site": _stamp(covered)},
    )
    return t


def query(
    pool,
    *,
    roster,
    domains: list[str],
    group: str = "",
    bucket: str = "",
    brand: str = "",
    sale: bool = False,
    colour: str = "",
    q: str = "",
    sort: str = "latest",
    offset: int = 0,
    limit: int = 60,
) -> dict:
    names = {e.domain: e.name for e in roster}
    f = dict(group=group, bucket=bucket, brand=brand, sale=sale, colour=colour, q=q)
    base_params: dict[str, Any] = {"domains": list(domains), "max_price": _MAX_PRICE}
    order = _ORDER.get(sort, _ORDER["latest"])

    with pool.connection() as conn:
        w, prm = _where(f)
        total = conn.execute(f"SELECT count(*) {_BASE}{w}", {**base_params, **prm}).fetchone()[0]
        rows = conn.execute(
            f"SELECT {_TILE_COLS} {_BASE}{w} ORDER BY {order} LIMIT %(limit)s OFFSET %(offset)s",
            {**base_params, **prm, "limit": limit, "offset": offset},
        ).fetchall()
        w, prm = _where(f, skip=("group", "bucket"))
        gb = conn.execute(
            f"SELECT p.shop_group, p.shop_bucket, count(*) {_BASE}{w} GROUP BY 1, 2",
            {**base_params, **prm},
        ).fetchall()
        w, prm = _where(f, skip=("brand",))
        by_brand = conn.execute(
            f"SELECT p.brand, count(*) {_BASE}{w} GROUP BY 1", {**base_params, **prm}
        ).fetchall()
        w, prm = _where(f, skip=("colour",))
        by_colour = dict(
            conn.execute(
                f"SELECT p.shop_colour, count(*) {_BASE}{w} AND p.shop_colour IS NOT NULL GROUP BY 1",
                {**base_params, **prm},
            ).fetchall()
        )
        w, prm = _where({**f, "sale": True})
        sale_count = conn.execute(f"SELECT count(*) {_BASE}{w}", {**base_params, **prm}).fetchone()[
            0
        ]

    groups: dict[str, int] = {}
    buckets: dict[str, int] = {}
    for g, b, n in gb:
        groups[g] = groups.get(g, 0) + n
        if not group or g == group:
            buckets[b] = buckets.get(b, 0) + n
    tree = []
    for g in GROUPS:
        if not groups.get(g):
            continue
        subs = [
            {"bucket": b, "count": n}
            for b, n in buckets.items()
            if any(gg == g and bb == b for gg, bb, _ in _TAXONOMY)
            or (g == OTHER[0] and b == OTHER[1])
        ]
        subs.sort(key=lambda s: -int(s["count"]))
        tree.append({"group": g, "count": groups[g], "buckets": subs})
    designers = sorted(
        ({"brand_id": d, "name": names.get(d, d), "count": n} for d, n in by_brand),
        key=lambda d: d["name"].lower(),
    )
    return {
        "products": [slim(_tile(r, names)) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "facets": {
            "categories": tree,
            "designers": designers,
            "colours": [{"colour": c, "count": by_colour[c]} for c in COLOURS if by_colour.get(c)],
            "sale": sale_count,
        },
        "built_at": None,
    }


def product(
    pool, *, roster, domains: list[str], brand: str, handle: str = "", url: str = ""
) -> dict | None:
    names = {e.domain: e.name for e in roster}
    if brand not in domains:
        return None
    key = "p.itemurl = %(url)s" if url else "p.handle = %(handle)s"
    with pool.connection() as conn:
        row = conn.execute(
            f"SELECT {_TILE_COLS} {_BASE} AND p.brand = %(brand)s AND {key} LIMIT 1",
            {"domains": list(domains), "brand": brand, "handle": handle, "url": url},
        ).fetchone()
    if row is None:
        return None
    t = _tile(row, names)
    more = [
        m
        for m in query(pool, roster=roster, domains=domains, brand=brand, limit=9)["products"]
        if m["url"] != t["url"]
    ][:8]
    return {"tile": t, "more": more}
