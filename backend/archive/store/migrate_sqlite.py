"""Move a SQLite catalogue into objects, once.

Reads the tables the old store wrote and writes the objects the new one reads. It does
not delete the database: the file stays until the objects have been read back and
checked, because a migration that removes its own source leaves nothing to compare
against.

Idempotent — every write is a whole object keyed by brand, so running it twice leaves
the same result.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from backend.archive.store.objects import DirectoryObjectStore, ObjectStore, dumps


def _run_key(run_id: int, started_at: str) -> str:
    """A migrated run's id, sorting by when it started.

    New ids are `<iso-8601>-<6 hex>` and the store orders runs lexically, so a
    migrated id has to begin with a timestamp too. The first attempt was
    `legacy-00000042`, and 'l' (108) sorts after '2' (50) — every migrated run
    outranked every new one, `_latest_covered_run` always returned an old one, and
    a brand that had just been re-scraped showed zero products. The padded integer
    stays as a tiebreak for runs that share a start time.
    """
    return f"{started_at}-legacy{run_id:06d}"


def migrate(db_path: Path, store: ObjectStore) -> dict[str, int]:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    counts: dict[str, int] = {}

    def put(key: str, value) -> None:
        store.put(key, dumps(value))

    # --- brands
    brands = db.execute("SELECT * FROM brands").fetchall()
    for row in brands:
        put(
            f"brands/{row['domain']}.json",
            {
                "domain": row["domain"],
                "homepage_url": row["homepage_url"],
                "display_name": row["display_name"],
                "notes": row["notes"],
                "state": row["state"],
            },
        )
    counts["brands"] = len(brands)

    # --- plans
    plans = db.execute("SELECT * FROM scrape_plans").fetchall()
    for row in plans:
        put(
            f"plans/{row['domain']}.json",
            {"plan": json.loads(row["plan_json"]), "fingerprinted_at": row["fingerprinted_at"]},
        )
    counts["plans"] = len(plans)

    # --- runs
    runs = db.execute("SELECT * FROM runs ORDER BY id").fetchall()
    per_brand: dict[str, list[str]] = {}
    # id -> key, because products, history, evidence and scorecards all refer to runs
    # by integer and every one of them has to agree on the new name.
    run_keys: dict[int, str] = {r["id"]: _run_key(r["id"], r["started_at"]) for r in runs}
    for row in runs:
        key = _run_key(row["id"], row["started_at"])
        put(
            f"runs/{row['domain']}/{key}.json",
            {
                "id": key,
                "domain": row["domain"],
                "mode": row["mode"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "exit_status": row["exit_status"],
                "coverage": json.loads(row["coverage_json"]) if row["coverage_json"] else None,
            },
        )
        per_brand.setdefault(row["domain"], []).append(key)
    for domain, ids in per_brand.items():
        put(f"runs/{domain}/index.json", {"runs": ids})
    counts["runs"] = len(runs)

    # --- products, and the history keyed by the run that observed it
    catalogues: dict[str, dict] = {}
    product_urls: dict[int, tuple[str, str]] = {}
    for row in db.execute("SELECT * FROM products"):
        domain = row["domain"]
        catalogues.setdefault(domain, {"products": {}})["products"][row["itemurl"]] = {
            "record": json.loads(row["current_json"]),
            "product_code": row["product_code"],
            "change_hint": row["change_hint"],
            "first_seen_run": run_keys[row["first_seen_run"]],
            "last_seen_run": run_keys[row["last_seen_run"]],
        }
        product_urls[row["id"]] = (domain, row["itemurl"])
    counts["products"] = len(product_urls)

    history: dict[tuple[str, str], list[dict]] = {}
    observations = 0
    for row in db.execute("SELECT * FROM observations ORDER BY id"):
        found = product_urls.get(row["product_id"])
        if not found:
            continue
        domain, itemurl = found
        history.setdefault((domain, run_keys.get(row["run_id"], "")), []).append(
            {
                "itemurl": itemurl,
                "price": row["price"],
                "full_price": row["full_price"],
                "in_stock": row["in_stock"],
                "size_availability": row["size_availability"],
            }
        )
        observations += 1
    for (domain, run_key), rows in history.items():
        put(f"history/{domain}/{run_key}.json", {"observations": rows})
    counts["observations"] = observations

    # --- images, keyed by itemurl now that product ids are gone
    images: dict[str, dict[str, list[dict]]] = {}
    image_rows = 0
    for row in db.execute("SELECT * FROM images"):
        found = product_urls.get(row["product_id"])
        if not found:
            continue
        domain, itemurl = found
        images.setdefault(domain, {}).setdefault(itemurl, []).append(
            {
                "url": row["url"],
                "content_hash": row["content_hash"],
                "stored_url": row["stored_url"],
            }
        )
        image_rows += 1
    for domain, held in images.items():
        put(f"images/{domain}.json", held)
    counts["images"] = image_rows

    # --- rules, evidence, scorecards, versions
    books = db.execute("SELECT * FROM recipe_books").fetchall()
    for row in books:
        put(
            f"rules/{row['domain']}.json",
            {"book": json.loads(row["book_json"]), "learned_at": row["learned_at"]},
        )
    counts["rules"] = len(books)

    evidence: dict[str, dict] = {}
    evidence_rows = 0
    for row in db.execute("SELECT * FROM field_evidence"):
        evidence.setdefault(row["domain"], {})[f"{row['field']}|{row['source']}"] = {
            "examined": row["examined"],
            "found": row["found"],
            "run_id": run_keys.get(row["run_id"], ""),
            "searched_at": row["searched_at"],
        }
        evidence_rows += 1
    for domain, held in evidence.items():
        put(f"evidence/{domain}.json", held)
    counts["evidence"] = evidence_rows

    cards = db.execute("SELECT * FROM scorecards").fetchall()
    for row in cards:
        key = run_keys.get(row["run_id"], str(row["run_id"]))
        put(
            f"scores/{row['domain']}/{key}.json",
            {"card": json.loads(row["card_json"]), "run_id": key, "scored_at": row["scored_at"]},
        )
    counts["scorecards"] = len(cards)

    versions = db.execute("SELECT * FROM extraction_versions").fetchall()
    for row in versions:
        put(
            f"versions/{row['domain']}.json",
            {"version": row["version"], "seen_at": row["seen_at"]},
        )
    counts["versions"] = len(versions)

    schedule = db.execute("SELECT * FROM schedule").fetchall()
    for row in schedule:
        put(
            f"control/schedule/{row['domain']}.json",
            {
                "domain": row["domain"],
                "enabled": row["enabled"],
                "cadence_seconds": row["cadence_seconds"],
                "next_due": row["next_due"],
                "claimed_by": None,
                "claimed_at": None,
            },
        )
    counts["schedule"] = len(schedule)

    # The catalogue objects last, and their derived views with them, so a migration
    # interrupted halfway leaves no brand claiming products whose history is missing.
    from backend.archive.store.catalog import Catalog

    for domain, catalogue in catalogues.items():
        put(f"catalogue/{domain}.json", catalogue)
    catalog = Catalog(store)
    for domain in catalogues:
        catalog._write_search_index(domain)
        catalog._refresh_meta(domain)

    db.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="migrate_sqlite")
    ap.add_argument("db", type=Path)
    ap.add_argument(
        "--objects",
        type=Path,
        default=None,
        help="write into this directory instead of R2",
    )
    args = ap.parse_args(argv)

    if not args.db.exists():
        print(f"no such catalogue: {args.db}")
        return 1

    from backend.archive.store.objects import object_store

    store: ObjectStore = DirectoryObjectStore(args.objects) if args.objects else object_store()
    print(f"migrating {args.db} into {type(store).__name__}")
    counts = migrate(args.db, store)
    for kind, n in counts.items():
        print(f"  {kind:<14}{n:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
