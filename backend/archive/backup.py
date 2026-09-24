"""A nightly copy of what cannot be re-scraped.

The catalogue's rows live in Postgres on a plan with no point-in-time recovery, and
the scraper's control plane lives in R2 with no versioning. Until this file nothing
was backed up: a bad migration or a `DELETE` with the wrong WHERE clause would have
been the end of 25,000 rows and three weeks of learned rules.

What one day's backup holds, under `backups/<YYYY-MM-DD>/`:

  pg/<table>.ndjson.gz   the five catalogue tables (`schema.sql`), one gzip-compressed
                         object per table, one JSON object per line, `raw` included.
                         Rows stream out of Postgres through a server-side cursor and
                         into the gzip stream a line at a time, so a 25k-row table is
                         never held in memory as rows and as bytes at once; only the
                         compressed object is.
  r2/<key>               fleet.json, rules/*.json, plans/*.json and
                         control/schedule/*.json — the recipe books the finder paid
                         for, the plans, the schedule. Copied with the bucket's own
                         same-bucket CopyObject (`ObjectStore.copy`): the bytes never
                         leave R2, so this part costs no worker egress at all.
  manifest.json          row counts, bytes and timings, which is also what `backup()`
                         returns and what the log line says.

What is deliberately NOT copied:

  photographs (`archive/…`)  ~gigabytes, already the copy — each one was fetched
                             from a shop's CDN and can be fetched again from the
                             URL in `product_images.url`. Copying them daily would be
                             the whole bucket rewritten every night.
  run logs (`logs/…`)        the record of how a scrape went, written once and read
                             from the deck. Losing them loses history, not state;
                             nothing is rebuilt from them.
  runs, scores, evidence,    small, append-only, and every one is re-derived by the
  recommendations, progress  next pass of the brand. `runs/` is the one that would
                             be missed (the run ids products are stamped with), but
                             the stamps themselves are in the `products` dump.
  observation objects        `history/<domain>/<run>.json` are the r2 backend's
  (`history/…`)              frozen pre-migration copies of what `product_observations`
                             now holds; the table is dumped, the objects are not.

Bandwidth, since Render bills the worker's egress and the memory rule says compute
it first: the five tables are ~150–180 MB of JSON text a day (record ~60 MB, raw
~60 MB, images and observations the rest), which gzip brings to ~25–35 MB. That is
one upload a day of that size, ~1 GB a month — inside the plan's free allowance,
and a tenth of what one psylos1 pass used to upload rewriting its 35 MB object
forty times. The R2 copies are server-side and free. Pruning is a list plus
deletes, no bytes.

Retention is `KEEP_DAYS` days: fourteen days of daily copies is ~0.5 GB in R2 at
$0.015/GB-month.

One worker does it, once a day. `daily_backup` is the daemon's hook: the first worker
that sees the date change claims the day with a compare-and-swap on
`control/backup.json` and runs it; every other worker sees today's claim and moves on.
A claim whose worker died is retaken after `STALE_SECONDS`; a day that failed is
retried by the next worker to look.

Restoring is per brand: `restore(catalog, store, date, brand)` deletes the brand's
rows in all five tables and inserts the day's rows for it, in one transaction, so a
reader sees the old brand or the new one and never half of each.
"""

from __future__ import annotations

import gzip
import io
import json
import time
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads

# Insert order: a product must exist before its raw payload (foreign key). Deletes
# run in the reverse order; product_raw goes with its product by cascade.
TABLES = (
    "catalogue_brands",
    "products",
    "product_raw",
    "product_observations",
    "product_images",
)
# What is copied from the object store, by prefix (a bare key is copied as itself).
R2_KEYS = ("fleet.json", "rules/", "plans/", "control/schedule/")
KEEP_DAYS = 14
PREFIX = "backups/"
CONTROL = "control/backup.json"
# A claim without a finish after this long belongs to a worker that died mid-dump.
STALE_SECONDS = 3 * 3600
# Rows per round trip on the way out of Postgres, and per executemany on the way in.
BATCH = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def day_key(day: date | str) -> str:
    return f"{PREFIX}{day if isinstance(day, str) else day.isoformat()}/"


# --- the line format -------------------------------------------------------------


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"not JSON: {type(value).__name__}")


def dump_rows(rows: Iterable[dict]) -> bytes:
    """Rows to a gzip-compressed ndjson object, one row at a time through the
    compressor. The rows may be any iterable — a cursor, a generator — and are never
    collected into a list here."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for row in rows:
            gz.write(json.dumps(row, default=_json_default, ensure_ascii=False).encode("utf-8"))
            gz.write(b"\n")
    return buf.getvalue()


def load_rows(body: bytes) -> Iterator[dict]:
    """The inverse: the compressed object stays in memory once, lines come out one
    at a time."""
    with gzip.GzipFile(fileobj=io.BytesIO(body), mode="rb") as gz:
        for line in gz:
            if line.strip():
                yield json.loads(line)


# --- the Postgres half -----------------------------------------------------------


def _columns(conn, table: str) -> list[tuple[str, str]]:
    """(name, type) per column, in table order, from the catalogue rather than a list
    kept here, so a column added to schema.sql is in the next night's dump."""
    rows = conn.execute(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a
        WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (table,),
    ).fetchall()
    return [(name, typ) for name, typ in rows]


def _select_list(columns: list[tuple[str, str]]) -> str:
    # tsvector has no JSON form; its text form round-trips through ::tsvector.
    return ", ".join(f"{n}::text AS {n}" if t == "tsvector" else n for n, t in columns)


def _stream_table(conn, table: str, columns: list[tuple[str, str]]) -> Iterator[dict]:
    with conn.cursor(name=f"backup_{table}", row_factory=dict_row) as cur:
        cur.itersize = BATCH
        cur.execute(f"SELECT {_select_list(columns)} FROM {table} ORDER BY brand")  # noqa: S608
        yield from cur


def _counted(rows: Iterator[dict], tally: list[int]) -> Iterator[dict]:
    for row in rows:
        tally[0] += 1
        yield row


def _dump_tables(catalog, store: ObjectStore, day: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with catalog._pg() as conn:
        for table in TABLES:
            started = time.monotonic()
            tally = [0]
            body = dump_rows(_counted(_stream_table(conn, table, _columns(conn, table)), tally))
            store.put(f"{day_key(day)}pg/{table}.ndjson.gz", body)
            out[table] = {
                "rows": tally[0],
                "bytes": len(body),
                "seconds": round(time.monotonic() - started, 2),
            }
    return out


def _param(value: Any, typ: str) -> Any:
    if value is None:
        return None
    if typ == "jsonb":
        return Jsonb(value)
    return value


def _insert_sql(table: str, columns: list[tuple[str, str]]) -> str:
    # Every value is cast to the column's own type: the dump carries timestamps and
    # tsvectors as strings, and Postgres is told what they are rather than left to
    # guess from a text parameter.
    names = ", ".join(n for n, _ in columns)
    casts = ", ".join(f"%s::{t}" for _, t in columns)
    return f"INSERT INTO {table} ({names}) VALUES ({casts})"  # noqa: S608


def _load_table(conn, table: str, rows: Iterable[dict], brand: str) -> int:
    live = _columns(conn, table)
    present: list[tuple[str, str]] | None = None
    sql = ""
    batch: list[tuple] = []
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            if row.get("brand") != brand:
                continue
            if present is None:
                # Columns the table still has; one the dump lacks takes its default.
                present = [(c, t) for c, t in live if c in row]
                sql = _insert_sql(table, present)
            batch.append(tuple(_param(row[c], t) for c, t in present))
            if len(batch) >= BATCH:
                cur.executemany(sql, batch)
                n += len(batch)
                batch = []
        if batch:
            cur.executemany(sql, batch)
            n += len(batch)
    return n


# --- the object-store half -------------------------------------------------------


def copy_control_plane(store: ObjectStore, day: str) -> dict[str, int]:
    """fleet.json, rules, plans and the schedule, copied inside the store."""
    copied = 0
    absent = 0
    for spec in R2_KEYS:
        keys = store.list(spec) if spec.endswith("/") else [spec]
        for key in keys:
            if store.copy(key, f"{day_key(day)}r2/{key}"):
                copied += 1
            else:
                absent += 1
    return {"copied": copied, "absent": absent}


def days_held(store: ObjectStore) -> list[str]:
    """The days with a backup, oldest first."""
    days = {k[len(PREFIX) :].split("/", 1)[0] for k in store.list(PREFIX)}
    return sorted(d for d in days if d)


def prune(store: ObjectStore, now: datetime | None = None, keep_days: int = KEEP_DAYS) -> list[str]:
    """Delete every day older than `keep_days`. Returns the days removed."""
    cutoff = ((now or _now()) - timedelta(days=keep_days)).date().isoformat()
    removed = []
    for day in days_held(store):
        if day < cutoff:
            for key in store.list(day_key(day)):
                store.delete(key)
            removed.append(day)
    return removed


# --- the two entry points --------------------------------------------------------


def backup(catalog, store: ObjectStore, now: datetime | None = None) -> dict:
    """One day's backup: dump the tables, copy the control plane, prune, write the
    manifest. `catalog` must be the Postgres catalogue (it is asked for a
    connection); `store` is where the copies go — the same bucket the originals are
    in, so the R2 half is server-side."""
    if not hasattr(catalog, "_pg"):
        raise TypeError("backup needs the Postgres catalogue (CATALOG_BACKEND=pg)")
    now = now or _now()
    day = now.date().isoformat()
    started = time.monotonic()
    tables = _dump_tables(catalog, store, day)
    control = copy_control_plane(store, day)
    pruned = prune(store, now)
    manifest = {
        "day": day,
        "at": now.isoformat(),
        "tables": tables,
        "rows": sum(t["rows"] for t in tables.values()),
        "bytes": sum(t["bytes"] for t in tables.values()),
        "r2": control,
        "pruned": pruned,
        "seconds": round(time.monotonic() - started, 1),
    }
    store.put(f"{day_key(day)}manifest.json", dumps(manifest))
    return manifest


def manifest(store: ObjectStore, day: str) -> dict | None:
    found = store.get(f"{day_key(day)}manifest.json")
    return loads(found[0]) if found else None


def restore(catalog, store: ObjectStore, day: str, brand: str) -> dict[str, int]:
    """Put one brand back as it was on `day`. Delete-then-insert, one transaction:
    the brand is either wholly the day's copy or wholly untouched."""
    if not hasattr(catalog, "_pg"):
        raise TypeError("restore needs the Postgres catalogue (CATALOG_BACKEND=pg)")
    dumps_by_table: dict[str, bytes] = {}
    for table in TABLES:
        found = store.get(f"{day_key(day)}pg/{table}.ndjson.gz")
        if found is None:
            raise FileNotFoundError(f"no backup of {table} for {day}")
        dumps_by_table[table] = found[0]

    counts: dict[str, int] = {}
    with catalog._pg() as conn:
        with conn.transaction():
            for table in reversed(TABLES):
                if table == "product_raw":
                    continue  # goes with its product
                conn.execute(f"DELETE FROM {table} WHERE brand = %s", (brand,))  # noqa: S608
            for table in TABLES:
                counts[table] = _load_table(conn, table, load_rows(dumps_by_table[table]), brand)
            # The observations carry their ids; the sequence must not hand one out again.
            conn.execute(
                "SELECT setval('product_observations_id_seq', "
                "GREATEST((SELECT COALESCE(max(id), 1) FROM product_observations), 1))"
            )
    catalog.release_products(brand)
    catalog._watched_rows.pop(brand, None)
    catalog._open_images.pop(brand, None)
    return counts


# --- the daemon's hook ------------------------------------------------------------


def _claim(store: ObjectStore, day: str, worker_id: str, now: datetime) -> bool:
    """Take today's backup, or learn that someone has. One conditional write."""
    found = store.get(CONTROL)
    row = loads(found[0]) if found else {}
    etag = found[1] if found else None
    if row.get("day") == day:
        state = row.get("state")
        if state == "done":
            return False
        if state == "running":
            try:
                started = datetime.fromisoformat(row.get("started_at") or "")
            except ValueError:
                started = None  # unreadable is as good as dead
            if started is not None and (now - started).total_seconds() < STALE_SECONDS:
                return False
        # "failed", or a claim whose worker went quiet: try again.
    claim = {
        "day": day,
        "state": "running",
        "worker": worker_id,
        "started_at": now.isoformat(),
        "previous": {k: row.get(k) for k in ("day", "state", "finished_at", "rows", "error")},
    }
    try:
        if etag is None:
            store.put(CONTROL, dumps(claim), if_none_match=True)
        else:
            store.put(CONTROL, dumps(claim), if_match=etag)
    except Conflict:
        return False
    return True


def _finish(store: ObjectStore, day: str, worker_id: str, **fields) -> None:
    found = store.get(CONTROL)
    row = loads(found[0]) if found else {}
    if row.get("day") == day and row.get("worker") == worker_id:
        row.update(fields, finished_at=_now().isoformat())
        store.put(CONTROL, dumps(row))


def daily_backup(
    store: ObjectStore,
    catalog,
    worker_id: str,
    now: datetime | None = None,
    log=print,
    run=backup,
) -> dict | None:
    """Run today's backup if nobody has. Returns the manifest when this worker did
    it, None otherwise. Never raises: a backup that fails is logged and marked so the
    next worker to look retries it, and the scrape loop carries on either way."""
    now = now or _now()
    day = now.date().isoformat()
    if not hasattr(catalog, "_pg"):
        return None  # the r2 backend's rows are the objects themselves
    if not _claim(store, day, worker_id, now):
        return None
    log(f"{worker_id}: backing up {day}")
    try:
        result = run(catalog, store, now)
    except Exception as e:  # noqa: BLE001 — the loop must not die for a backup
        log(f"{worker_id}: backup {day} failed: {type(e).__name__}: {e}")
        _finish(store, day, worker_id, state="failed", error=f"{type(e).__name__}: {e}")
        return None
    _finish(
        store,
        day,
        worker_id,
        state="done",
        rows=result["rows"],
        bytes=result["bytes"],
        seconds=result["seconds"],
        pruned=result["pruned"],
    )
    log(
        f"{worker_id}: backup {day} done: {result['rows']} rows, "
        f"{result['bytes'] / 1e6:.1f} MB, {result['r2']['copied']} objects copied, "
        f"{len(result['pruned'])} old days pruned, {result['seconds']}s"
    )
    return result


def status(store: ObjectStore) -> dict:
    """What the deck and `archive backup --status` show."""
    found = store.get(CONTROL)
    row = loads(found[0]) if found else {}
    return {**row, "days": days_held(store)}
