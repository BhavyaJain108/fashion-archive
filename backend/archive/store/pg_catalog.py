"""The catalogue on Postgres.

`Catalog` keeps every product of a brand in one JSON object and reads or rewrites
the whole thing for any product. This subclass keeps the same interface and the
same run bookkeeping (runs, plans, logs, scorecards stay in the object store) but
stores products, their photographs and their price observations as rows, so a
product is an index lookup and a brand is a query.

What is inherited unchanged: everything under "runs", "plans", "logs",
"scorecards", "evidence", "recommendations", "attention", "progress", host
stats, and the fleet object. Those read and write small objects and are the
scraper's control plane.

What is overridden: `_catalogue` (materialises a brand's rows for the read-only
history views), `record_product`, `mark_seen`, `finalize_run`, `flush`,
`current_products`, `search_products`, `observation_count`, `rewrite_field`,
`release_products`, the image index, `_refresh_meta`, and `_latest_covered_run`
(read from `catalogue_brands` rather than by listing runs).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from backend.archive import storefront as shop
from backend.archive.domain.product import WATCHED_FIELDS
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import FLUSH_EVERY, Catalog, _now
from backend.archive.store.objects import ObjectStore

_MAX_LEVELS = 10

_TYPED = (
    "product_code",
    "title",
    "description",
    "price",
    "full_price",
    "currency",
    "in_stock",
    "size_info",
    "size_availability",
    "size_stock_counts",
    "color_info",
    "material_info",
    "variant_info",
    "main_image_url",
    "additional_tags",
    "specifications",
)

_UPSERT = """
INSERT INTO products (
    brand, itemurl, handle, product_code, title, description, price, full_price, currency,
    in_stock, size_info, size_availability, size_stock_counts, color_info, material_info,
    variant_info, categories, main_image_url, all_images, additional_tags, specifications,
    shop_group, shop_bucket, shop_colour, record, change_hint,
    first_seen_run, last_seen_run, search
) VALUES (
    %(brand)s, %(itemurl)s, %(handle)s, %(product_code)s, %(title)s, %(description)s,
    %(price)s, %(full_price)s, %(currency)s, %(in_stock)s, %(size_info)s,
    %(size_availability)s, %(size_stock_counts)s, %(color_info)s, %(material_info)s,
    %(variant_info)s, %(categories)s, %(main_image_url)s, %(all_images)s,
    %(additional_tags)s, %(specifications)s, %(shop_group)s, %(shop_bucket)s,
    %(shop_colour)s, %(record)s, %(change_hint)s, %(first_seen_run)s, %(last_seen_run)s,
    to_tsvector('simple', %(search_text)s)
)
ON CONFLICT (brand, itemurl) DO UPDATE SET
    handle = EXCLUDED.handle, product_code = EXCLUDED.product_code, title = EXCLUDED.title,
    description = EXCLUDED.description, price = EXCLUDED.price,
    full_price = EXCLUDED.full_price, currency = EXCLUDED.currency,
    in_stock = EXCLUDED.in_stock, size_info = EXCLUDED.size_info,
    size_availability = EXCLUDED.size_availability,
    size_stock_counts = EXCLUDED.size_stock_counts, color_info = EXCLUDED.color_info,
    material_info = EXCLUDED.material_info, variant_info = EXCLUDED.variant_info,
    categories = EXCLUDED.categories, main_image_url = EXCLUDED.main_image_url,
    all_images = EXCLUDED.all_images, additional_tags = EXCLUDED.additional_tags,
    specifications = EXCLUDED.specifications, shop_group = EXCLUDED.shop_group,
    shop_bucket = EXCLUDED.shop_bucket, shop_colour = EXCLUDED.shop_colour,
    record = EXCLUDED.record, change_hint = EXCLUDED.change_hint,
    last_seen_run = EXCLUDED.last_seen_run, search = EXCLUDED.search, updated_at = now()
"""

_UPSERT_RAW = """
INSERT INTO product_raw (brand, itemurl, raw) VALUES (%s, %s, %s)
ON CONFLICT (brand, itemurl) DO UPDATE SET raw = EXCLUDED.raw
"""

_ROW_COLS = (
    "itemurl, product_code, change_hint, first_seen_run, last_seen_run, last_covered_run, record"
)


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    return None if s in ("", "None") else s


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _bool(v: Any) -> bool | None:
    if v in (None, "", "None"):
        return None
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes")


def _categories(record: dict) -> list[str]:
    out = []
    for i in range(1, _MAX_LEVELS + 1):
        v = _text(record.get(f"category{i}"))
        if not v:
            break
        out.append(v)
    return out


def _images_of(record: dict) -> list[str]:
    raw = record.get("all_images")
    urls: Any = raw
    if isinstance(raw, str):
        try:
            urls = json.loads(raw)
        except json.JSONDecodeError:
            urls = [u.strip(" '\"") for u in raw.strip("[]").split(",") if u.strip()]
    return [u for u in (urls or []) if isinstance(u, str) and u.startswith("http")]


def row_params(
    brand: str, record: dict, *, change_hint: str | None, first_seen_run: str, last_seen_run: str
) -> dict:
    """The upsert's parameters for one record. `record` is stored without `raw`."""
    record = {k: v for k, v in record.items() if k != "raw"}
    group, bucket = shop.classify(record)
    itemurl = record.get("itemurl") or ""
    return {
        "brand": brand,
        "itemurl": itemurl,
        "handle": shop.handle_of(itemurl) or _text(record.get("product_code")) or itemurl,
        "product_code": _text(record.get("product_code")),
        "title": _text(record.get("product_title")) or "",
        "description": _text(record.get("description")),
        "price": _num(record.get("price")),
        "full_price": _num(record.get("full_price")),
        "currency": _text(record.get("currency")),
        "in_stock": _bool(record.get("in_stock")),
        "size_info": _text(record.get("size_info")),
        "size_availability": _text(record.get("size_availability")),
        "size_stock_counts": _text(record.get("size_stock_counts")),
        "color_info": _text(record.get("color_info")),
        "material_info": _text(record.get("material_info")),
        "variant_info": _text(record.get("variant_info")),
        "categories": _categories(record),
        "main_image_url": _text(record.get("main_image_url")),
        "all_images": Jsonb(_images_of(record)),
        "additional_tags": _text(record.get("additional_tags")),
        "specifications": _text(record.get("specifications")),
        "shop_group": group,
        "shop_bucket": bucket,
        "shop_colour": shop.colour(record),
        "record": Jsonb(record),
        "change_hint": change_hint,
        "first_seen_run": first_seen_run,
        "last_seen_run": last_seen_run,
        "search_text": " ".join(
            filter(
                None,
                [
                    _text(record.get("product_title")),
                    _text(record.get("description")),
                    _text(record.get("material_info")),
                    _text(record.get("color_info")),
                    _text(record.get("product_code")),
                    " ".join(_categories(record)),
                    _text(record.get("additional_tags")),
                ],
            )
        ),
    }


def _watched(record: dict) -> dict:
    return {
        "price": _num(record.get("price")),
        "full_price": _num(record.get("full_price")),
        "in_stock": _bool(record.get("in_stock")),
        "size_availability": _text(record.get("size_availability")),
    }


_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def shared_pool(dsn: str | None = None) -> ConnectionPool:
    """One pool per database URL for the whole process. The API builds a catalogue
    per request; a pool per request would open a connection per request."""
    url = dsn or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("CATALOG_BACKEND=pg needs DATABASE_URL")
    with _pools_lock:
        pool = _pools.get(url)
        if pool is None:
            # Small: the scraper's image pass runs a handful of threads, and the API
            # has its own pool for user data.
            pool = ConnectionPool(url, min_size=1, max_size=6, open=True)
            pool.wait(timeout=15)
            from backend.auth.migrate import apply_schema

            with pool.connection() as conn:
                apply_schema(conn)
            _pools[url] = pool
        return pool


class PgCatalog(Catalog):
    def __init__(
        self, store: ObjectStore, *, dsn: str | None = None, pool: ConnectionPool | None = None
    ):
        super().__init__(store)
        self._pool = pool or shared_pool(dsn)
        self._pg_lock = threading.RLock()
        self._pending: list[dict] = []
        self._pending_raw: list[tuple] = []
        self._watched_rows: dict[str, dict[str, dict]] = {}

    def _pg(self):
        return self._pool.connection()

    # --- reads -------------------------------------------------------------

    def _latest_covered_run(self, domain: str) -> str | None:
        with self._pg() as conn:
            row = conn.execute(
                "SELECT live_run FROM catalogue_brands WHERE brand = %s", (domain,)
            ).fetchone()
        if row and row[0]:
            return row[0]
        # No row yet (a brand that never finished a run here): the runs decide.
        return super()._latest_covered_run(domain)

    def _catalogue(self, domain: str) -> dict[str, Any]:
        """A brand's rows in the shape the JSON object had, for the read-only history
        views (`product_history`, `products_at_run`, `catalogue_changes`). Never
        written back; the writers below go straight to the tables."""
        if domain not in self._open:
            with self._pg() as conn:
                rows = conn.execute(
                    f"SELECT {_ROW_COLS} FROM products WHERE brand = %s", (domain,)
                ).fetchall()
            self._open[domain] = {
                "products": {
                    r[0]: {
                        "record": r[6],
                        "product_code": r[1],
                        "change_hint": r[2],
                        "first_seen_run": r[3],
                        "last_seen_run": r[4],
                        "last_covered_run": r[5],
                    }
                    for r in rows
                }
            }
        return self._open[domain]

    def current_products(
        self, domain: str, live_only: bool = True, with_raw: bool = True
    ) -> list[dict]:
        self.flush()
        sql = (
            "SELECT p.record, r.raw FROM products p LEFT JOIN product_raw r USING (brand, itemurl) "
            "WHERE p.brand = %s"
        )
        params: list[Any] = [domain]
        if live_only:
            live = self._latest_covered_run(domain)
            if live is None:
                return []
            sql += " AND p.last_covered_run = %s"
            params.append(live)
        with self._pg() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for record, raw in rows:
            if with_raw and raw is not None:
                record = {**record, "raw": raw}
            out.append(record)
        return out

    def search_products(
        self, domains: list[str], needle: str, limit: int = 200
    ) -> list[tuple[str, dict]]:
        if not domains or not needle:
            return []
        self.flush()
        with self._pg() as conn:
            rows = conn.execute(
                """
                SELECT p.brand, p.record FROM products p
                JOIN catalogue_brands b ON b.brand = p.brand AND b.live_run = p.last_covered_run
                WHERE p.brand = ANY(%s)
                  AND (p.search @@ plainto_tsquery('simple', %s) OR p.title ILIKE %s)
                LIMIT %s
                """,
                (list(domains), needle, f"%{needle}%", limit),
            ).fetchall()
        return [(brand, record) for brand, record in rows]

    def observation_count(self, domain: str) -> int:
        self.flush()
        with self._pg() as conn:
            return conn.execute(
                "SELECT count(*) FROM product_observations WHERE brand = %s", (domain,)
            ).fetchone()[0]

    def get_change_hints(self, domain: str) -> dict[str, str]:
        with self._pg() as conn:
            rows = conn.execute(
                "SELECT itemurl, change_hint FROM products WHERE brand = %s AND change_hint IS NOT NULL",
                (domain,),
            ).fetchall()
        return dict(rows)

    # --- writes ------------------------------------------------------------

    def _watched_map(self, domain: str) -> dict[str, dict]:
        if domain not in self._watched_rows:
            with self._pg() as conn:
                rows = conn.execute(
                    "SELECT itemurl, price, full_price, in_stock, size_availability, first_seen_run "
                    "FROM products WHERE brand = %s",
                    (domain,),
                ).fetchall()
            self._watched_rows[domain] = {
                r[0]: {
                    "price": r[1],
                    "full_price": r[2],
                    "in_stock": r[3],
                    "size_availability": r[4],
                    "first_seen_run": r[5],
                }
                for r in rows
            }
        return self._watched_rows[domain]

    def record_product(self, domain: str, run_id: str, record, change_hint: str | None) -> bool:
        current = json.loads(record.model_dump_json())
        raw = current.get("raw") or {}
        with self._pg_lock:
            known = self._watched_map(domain)
            previous = known.get(record.itemurl)
            now_w = _watched(current)
            changed = True
            if previous:
                changed = any(previous.get(f) != now_w.get(f) for f in WATCHED_FIELDS)
            first_seen = previous["first_seen_run"] if previous else run_id
            self._pending.append(
                row_params(
                    domain,
                    current,
                    change_hint=change_hint,
                    first_seen_run=first_seen,
                    last_seen_run=run_id,
                )
            )
            if raw:
                self._pending_raw.append((domain, record.itemurl, Jsonb(raw)))
            known[record.itemurl] = {**now_w, "first_seen_run": first_seen}
            if changed:
                self._pending_observations.setdefault((domain, run_id), []).append(
                    {
                        "itemurl": record.itemurl,
                        "price": record.price,
                        "full_price": record.full_price,
                        "in_stock": None if record.in_stock is None else int(record.in_stock),
                        "size_availability": record.size_availability,
                    }
                )
            self._dirty.add(domain)
            self._since_flush += 1
            due = self._since_flush >= FLUSH_EVERY
        if due:
            self.flush()
        return changed

    def mark_seen(self, domain: str, run_id: str, urls: list[str]) -> None:
        self.flush()
        if not urls:
            return
        with self._pg() as conn:
            conn.execute(
                "UPDATE products SET last_seen_run = %s WHERE brand = %s AND itemurl = ANY(%s)",
                (run_id, domain, list(urls)),
            )
        self._open.pop(domain, None)

    def rewrite_field(self, domain: str, field: str, value) -> int:
        self.flush()
        with self._pg() as conn:
            n = conn.execute(
                "UPDATE products SET record = jsonb_set(record, %s, %s, true), updated_at = now() "
                "WHERE brand = %s",
                ([field], Jsonb(value), domain),
            ).rowcount
            if field in _TYPED and field != "title":
                col = field
                conn.execute(f"UPDATE products SET {col} = %s WHERE brand = %s", (value, domain))
            elif field == "product_title":
                conn.execute(
                    "UPDATE products SET title = %s WHERE brand = %s", (value or "", domain)
                )
        self._open.pop(domain, None)
        return n

    def release_products(self, domain: str) -> bool:
        self._open.pop(domain, None)
        return True

    def _flush_locked(self) -> None:
        with self._pg_lock:
            pending, self._pending = self._pending, []
            pending_raw, self._pending_raw = self._pending_raw, []
            observations, self._pending_observations = self._pending_observations, {}
            self._dirty.clear()
            self._since_flush = 0
        if pending or pending_raw or observations:
            with self._pg() as conn:
                with conn.cursor() as cur:
                    if pending:
                        cur.executemany(_UPSERT, pending)
                    if pending_raw:
                        cur.executemany(_UPSERT_RAW, pending_raw)
                    for (domain, run_id), rows in sorted(observations.items()):
                        cur.executemany(
                            "INSERT INTO product_observations "
                            "(brand, itemurl, run_id, price, full_price, in_stock, size_availability) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            [
                                (
                                    domain,
                                    r["itemurl"],
                                    run_id,
                                    _num(r["price"]),
                                    _num(r["full_price"]),
                                    None if r["in_stock"] is None else bool(r["in_stock"]),
                                    _text(r["size_availability"]),
                                )
                                for r in rows
                            ],
                        )
        # The materialised copies are read-only snapshots; drop them so the next
        # history view sees the rows just written.
        self._open.clear()
        self.flush_images()

    def finalize_run(
        self, run_id: str, exit_status: int, coverage: Coverage | None, domain: str | None = None
    ) -> None:
        domain = domain or self._domain_of_run(run_id)
        if domain is None:
            return
        row = self._run(domain, run_id) or {}
        row["finished_at"] = _now()
        row["exit_status"] = exit_status
        row["coverage"] = json.loads(coverage.model_dump_json()) if coverage else None
        self._write(f"runs/{domain}/{run_id}.json", row)
        if row.get("mode") == "learn":
            return
        self.flush()
        if coverage is not None and exit_status in (0, 1):
            with self._pg() as conn:
                conn.execute(
                    "UPDATE products SET last_covered_run = %s WHERE brand = %s AND last_seen_run = %s",
                    (run_id, domain, run_id),
                )
                conn.execute(
                    "INSERT INTO catalogue_brands (brand, live_run) VALUES (%s, %s) "
                    "ON CONFLICT (brand) DO UPDATE SET live_run = EXCLUDED.live_run, updated_at = now()",
                    (domain, run_id),
                )
        self._open.pop(domain, None)
        self._watched_rows.pop(domain, None)
        self._refresh_meta(domain)

    def _write_search_index(self, domain: str) -> None:
        return  # the `search` column is generated

    def _refresh_meta(self, domain: str) -> None:
        live = self._latest_covered_run(domain)
        with self._pg() as conn:
            total, live_n = conn.execute(
                "SELECT count(*), count(*) FILTER (WHERE last_covered_run = %s) FROM products WHERE brand = %s",
                (live, domain),
            ).fetchone()
            images = conn.execute(
                "SELECT count(*) FROM product_images WHERE brand = %s AND stored_url IS NOT NULL",
                (domain,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO catalogue_brands (brand, live_run, products, live_products, images) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (brand) DO UPDATE SET "
                "live_run = COALESCE(EXCLUDED.live_run, catalogue_brands.live_run), products = EXCLUDED.products, "
                "live_products = EXCLUDED.live_products, images = EXCLUDED.images, updated_at = now()",
                (domain, live, total, live_n, images),
            )
        latest = self.latest_run(domain)
        coverage = (latest or {}).get("coverage") or {}
        meta = {
            "domain": domain,
            "products": total,
            "live_products": live_n,
            "images": images,
            "state": self.get_brand_state(domain),
            "freshness": (latest or {}).get("finished_at"),
            "mode": (latest or {}).get("mode"),
            "coverage_pct": coverage.get("coverage_pct"),
            "verdict": coverage.get("verdict"),
        }
        self._write(f"catalogue/{domain}.meta.json", meta)
        self._merge_into_fleet(domain, meta)

    # --- images ------------------------------------------------------------

    def _images(self, domain: str) -> dict[str, list[dict]]:
        if domain not in self._open_images:
            with self._pg() as conn:
                rows = conn.execute(
                    "SELECT itemurl, url, content_hash, stored_url, misses FROM product_images WHERE brand = %s",
                    (domain,),
                ).fetchall()
            held: dict[str, list[dict]] = {}
            for itemurl, url, h, stored, misses in rows:
                held.setdefault(itemurl, []).append(
                    {"url": url, "content_hash": h, "stored_url": stored, "misses": misses}
                )
            self._open_images[domain] = held
        return self._open_images[domain]

    def record_image(
        self, domain: str, itemurl: str, url: str, content_hash: str, stored_url: str | None = None
    ) -> None:
        with self._pg() as conn:
            conn.execute(
                "INSERT INTO product_images (brand, itemurl, url, content_hash, stored_url) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (brand, itemurl, url) DO UPDATE SET content_hash = EXCLUDED.content_hash, "
                "stored_url = COALESCE(EXCLUDED.stored_url, product_images.stored_url), updated_at = now()",
                (domain, itemurl, url, content_hash, stored_url),
            )
        with self._images_lock:
            held = self._open_images.get(domain)
            if held is not None:
                rows = held.setdefault(itemurl, [])
                for row in rows:
                    if row["url"] == url:
                        row["content_hash"] = content_hash
                        row["stored_url"] = stored_url or row.get("stored_url")
                        break
                else:
                    rows.append(
                        {
                            "url": url,
                            "content_hash": content_hash,
                            "stored_url": stored_url,
                            "misses": 0,
                        }
                    )

    def record_image_miss(self, domain: str, itemurl: str, url: str) -> None:
        with self._pg() as conn:
            conn.execute(
                "INSERT INTO product_images (brand, itemurl, url, misses) VALUES (%s, %s, %s, 1) "
                "ON CONFLICT (brand, itemurl, url) DO UPDATE SET misses = product_images.misses + 1, updated_at = now()",
                (domain, itemurl, url),
            )
        with self._images_lock:
            held = self._open_images.get(domain)
            if held is not None:
                rows = held.setdefault(itemurl, [])
                for row in rows:
                    if row["url"] == url:
                        row["misses"] = (row.get("misses") or 0) + 1
                        break
                else:
                    rows.append({"url": url, "content_hash": None, "stored_url": None, "misses": 1})

    def flush_images(self) -> None:
        return  # every photograph is its own row, written as it lands

    def stored_image_count(self, domain: str) -> int:
        with self._pg() as conn:
            return conn.execute(
                "SELECT count(*) FROM product_images WHERE brand = %s AND stored_url IS NOT NULL",
                (domain,),
            ).fetchone()[0]

    # --- fleet views: the table, not fleet.json ------------------------------

    def live_product_counts(self) -> dict[str, int]:
        with self._pg() as conn:
            rows = conn.execute(
                "SELECT brand, live_products FROM catalogue_brands WHERE live_products > 0"
            ).fetchall()
        return dict(rows)

    def stored_image_counts(self) -> dict[str, int]:
        with self._pg() as conn:
            rows = conn.execute("SELECT brand, images FROM catalogue_brands").fetchall()
        return dict(rows)

    def close(self) -> None:
        self.flush()
        with self._images_lock:
            self._open_images.clear()


def run_when(run_id: str | None) -> datetime | None:
    """A run id is a timestamp plus six hex characters; the timestamp part."""
    if not run_id:
        return None
    stamp = run_id.rsplit("-", 1)[0]
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
