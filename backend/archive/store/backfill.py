"""Copy the catalogue from the object store into Postgres.

Reads every catalogue/<domain>.json, images/<domain>.json and
history/<domain>/<run>.json and upserts the rows. Idempotent: run it twice and
the second pass changes nothing. Prints a reconciliation per brand — rows in the
object against rows in the table — which is the acceptance check.

    python -m backend.archive.store.backfill            # every brand
    python -m backend.archive.store.backfill bode.com   # one

The API also runs this once at boot, in the background, when it is on the
Postgres backend and the products table is empty (see backend/app.py).
"""

from __future__ import annotations

import sys
import time

from psycopg.types.json import Jsonb

from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import ObjectStore, loads
from backend.archive.store.pg_catalog import (
    _UPSERT,
    _UPSERT_RAW,
    PgCatalog,
    _bool,
    _num,
    _text,
    row_params,
    run_when,
)


def _domains(store: ObjectStore) -> list[str]:
    return sorted(
        k[len("catalogue/") : -len(".json")]
        for k in store.list("catalogue/")
        if k.endswith(".json") and not k.endswith(".meta.json")
    )


def backfill_brand(store: ObjectStore, pg: PgCatalog, domain: str, log=print) -> dict:
    r2 = Catalog(store)  # the object-store reader, for the run bookkeeping and the objects
    started = time.time()
    found = store.get(f"catalogue/{domain}.json")
    products = (loads(found[0]) if found else {"products": {}}).get("products", {})
    live_run = r2._latest_covered_run(domain)

    rows, raws = [], []
    for itemurl, entry in products.items():
        record = dict(entry.get("record") or {})
        record.setdefault("itemurl", itemurl)
        raw = record.get("raw") or {}
        rows.append(
            {
                **row_params(
                    domain,
                    record,
                    change_hint=entry.get("change_hint"),
                    first_seen_run=entry.get("first_seen_run") or entry.get("last_seen_run") or "",
                    last_seen_run=entry.get("last_seen_run") or entry.get("first_seen_run") or "",
                ),
                "last_covered_run": entry.get("last_covered_run"),
            }
        )
        if raw:
            raws.append((domain, itemurl, Jsonb(raw)))

    imgs = (
        loads(store.get(f"images/{domain}.json")[0]) if store.get(f"images/{domain}.json") else {}
    ) or {}
    image_rows = [
        (
            domain,
            itemurl,
            r.get("url"),
            r.get("content_hash"),
            r.get("stored_url"),
            int(r.get("misses") or 0),
        )
        for itemurl, lst in imgs.items()
        for r in (lst or [])
        if r.get("url")
    ]

    obs_rows = []
    for key in store.list(f"history/{domain}/"):
        run_id = key.rsplit("/", 1)[-1][: -len(".json")]
        held = loads(store.get(key)[0])
        when = run_when(run_id)
        for o in held.get("observations", []):
            obs_rows.append(
                (
                    domain,
                    o.get("itemurl"),
                    run_id,
                    when,
                    _num(o.get("price")),
                    _num(o.get("full_price")),
                    _bool(o.get("in_stock")),
                    _text(o.get("size_availability")),
                )
            )

    with pg._pg() as conn:
        with conn.cursor() as cur:
            if rows:
                cur.executemany(_UPSERT, rows)
                # The stamp the upsert deliberately leaves alone, set from the object.
                cur.executemany(
                    "UPDATE products SET last_covered_run = %(last_covered_run)s, "
                    "first_seen_run = %(first_seen_run)s WHERE brand = %(brand)s AND itemurl = %(itemurl)s",
                    rows,
                )
            if raws:
                cur.executemany(_UPSERT_RAW, raws)
            if image_rows:
                cur.executemany(
                    "INSERT INTO product_images (brand, itemurl, url, content_hash, stored_url, misses) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (brand, itemurl, url) DO UPDATE SET "
                    "content_hash = EXCLUDED.content_hash, stored_url = EXCLUDED.stored_url, misses = EXCLUDED.misses",
                    image_rows,
                )
            if obs_rows:
                # Observations have no natural key; wipe the brand's and rewrite, so a
                # second pass does not double them.
                cur.execute("DELETE FROM product_observations WHERE brand = %s", (domain,))
                cur.executemany(
                    "INSERT INTO product_observations (brand, itemurl, run_id, observed_at, price, full_price, in_stock, size_availability) "
                    "VALUES (%s, %s, %s, COALESCE(%s, now()), %s, %s, %s, %s)",
                    obs_rows,
                )
            cur.execute(
                "INSERT INTO catalogue_brands (brand, live_run) VALUES (%s, %s) "
                "ON CONFLICT (brand) DO UPDATE SET live_run = EXCLUDED.live_run, updated_at = now()",
                (domain, live_run),
            )
            in_db, live_db = cur.execute(
                "SELECT count(*), count(*) FILTER (WHERE last_covered_run = %s) FROM products WHERE brand = %s",
                (live_run, domain),
            ).fetchone()
            raw_db = cur.execute(
                "SELECT count(*) FROM product_raw WHERE brand = %s", (domain,)
            ).fetchone()[0]
            img_db = cur.execute(
                "SELECT count(*) FROM product_images WHERE brand = %s", (domain,)
            ).fetchone()[0]
            obs_db = cur.execute(
                "SELECT count(*) FROM product_observations WHERE brand = %s", (domain,)
            ).fetchone()[0]
    pg._refresh_meta(domain)

    live_obj = sum(
        1 for e in products.values() if live_run and e.get("last_covered_run") == live_run
    )
    result = {
        "domain": domain,
        "rows_object": len(products),
        "rows_db": in_db,
        "live_object": live_obj,
        "live_db": live_db,
        "raw_db": raw_db,
        "images_object": len(image_rows),
        "images_db": img_db,
        "observations_object": len(obs_rows),
        "observations_db": obs_db,
        "seconds": round(time.time() - started, 1),
    }
    ok = (
        in_db == len(products)
        and live_db == live_obj
        and img_db == len(image_rows)
        and obs_db == len(obs_rows)
    )
    log(
        f"backfill {domain:32s} rows {in_db}/{len(products)}  live {live_db}/{live_obj}  "
        f"raw {raw_db}  images {img_db}/{len(image_rows)}  observations {obs_db}/{len(obs_rows)}  "
        f"{'ok' if ok else 'MISMATCH'}  {result['seconds']}s"
    )
    result["ok"] = ok
    return result


def backfill(
    store: ObjectStore, pg: PgCatalog, domains: list[str] | None = None, log=print
) -> list[dict]:
    out = []
    for domain in domains or _domains(store):
        try:
            out.append(backfill_brand(store, pg, domain, log=log))
        except Exception as error:  # noqa: BLE001 — one brand must not stop the rest
            log(f"backfill {domain}: FAILED {error!r}")
            out.append({"domain": domain, "ok": False, "error": repr(error)})
    good = sum(1 for r in out if r.get("ok"))
    log(
        f"backfill done: {good}/{len(out)} brands reconciled, {sum(r.get('rows_db', 0) for r in out)} rows"
    )
    return out


_running = False


def in_progress() -> bool:
    return _running


def backfill_if_empty(store: ObjectStore, log=print) -> None:
    """At boot on the Postgres backend: if nothing has been copied yet, copy
    everything, in the background, once. The shop answers 503 WARMING meanwhile."""
    global _running
    pg = PgCatalog(store)
    if not products_table_is_empty(pg):
        pg.close()
        return
    import threading

    def run() -> None:
        global _running
        try:
            backfill(store, pg, log=log)
        finally:
            _running = False
            pg.close()

    _running = True
    threading.Thread(target=run, name="catalogue-backfill", daemon=True).start()


def products_table_is_empty(pg: PgCatalog) -> bool:
    with pg._pg() as conn:
        return conn.execute("SELECT NOT EXISTS (SELECT 1 FROM products)").fetchone()[0]


if __name__ == "__main__":
    from backend.archive.store.objects import object_store

    store = object_store()
    pg = PgCatalog(store)
    results = backfill(store, pg, sys.argv[1:] or None)
    pg.close()
    sys.exit(0 if all(r.get("ok") for r in results) else 1)
