"""The only module that touches the DB (spec §4.4). Append-only runs/observations."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.archive.domain.brand import Brand, ScrapePlan
from backend.archive.domain.run import Coverage

_SCHEMA = Path(__file__).parent / "schema.sql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Catalog:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA.read_text())

    def close(self) -> None:
        self._db.close()

    # --- brands ---
    def upsert_brand(self, brand: Brand) -> None:
        self._db.execute(
            "INSERT INTO brands (domain, homepage_url, display_name, notes) VALUES (?,?,?,?) "
            "ON CONFLICT(domain) DO UPDATE SET homepage_url=excluded.homepage_url, "
            "display_name=excluded.display_name, notes=excluded.notes",
            (brand.domain, brand.homepage_url, brand.display_name, brand.notes),
        )
        self._db.commit()

    def get_brand(self, domain: str) -> Brand | None:
        row = self._db.execute("SELECT * FROM brands WHERE domain=?", (domain,)).fetchone()
        if not row:
            return None
        return Brand(
            domain=row["domain"],
            homepage_url=row["homepage_url"],
            display_name=row["display_name"],
            notes=row["notes"],
        )

    def list_brands(self) -> list[Brand]:
        rows = self._db.execute("SELECT * FROM brands ORDER BY domain").fetchall()
        return [
            Brand(
                domain=r["domain"],
                homepage_url=r["homepage_url"],
                display_name=r["display_name"],
                notes=r["notes"],
            )
            for r in rows
        ]

    def set_brand_state(self, domain: str, state: str) -> None:
        self._db.execute("UPDATE brands SET state=? WHERE domain=?", (state, domain))
        self._db.commit()

    def get_brand_state(self, domain: str) -> str:
        row = self._db.execute("SELECT state FROM brands WHERE domain=?", (domain,)).fetchone()
        return row["state"] if row else "new"

    # --- plans ---
    def save_plan(self, plan: ScrapePlan) -> None:
        self._db.execute(
            "INSERT INTO scrape_plans (domain, plan_json, fingerprinted_at) VALUES (?,?,?) "
            "ON CONFLICT(domain) DO UPDATE SET plan_json=excluded.plan_json, "
            "fingerprinted_at=excluded.fingerprinted_at",
            (plan.domain, plan.model_dump_json(), plan.fingerprinted_at),
        )
        self._db.commit()

    def load_plan(self, domain: str) -> ScrapePlan | None:
        row = self._db.execute(
            "SELECT plan_json FROM scrape_plans WHERE domain=?", (domain,)
        ).fetchone()
        return ScrapePlan.model_validate_json(row["plan_json"]) if row else None

    # --- runs ---
    def open_run(self, domain: str, mode: str) -> int:
        cur = self._db.execute(
            "INSERT INTO runs (domain, mode, started_at) VALUES (?,?,?)", (domain, mode, _now())
        )
        self._db.commit()
        assert cur.lastrowid is not None  # an INSERT always yields one
        return cur.lastrowid

    def finalize_run(self, run_id: int, exit_status: int, coverage: Coverage | None) -> None:
        self._db.execute(
            "UPDATE runs SET finished_at=?, exit_status=?, coverage_json=? WHERE id=?",
            (_now(), exit_status, coverage.model_dump_json() if coverage else None, run_id),
        )
        self._db.commit()

    def latest_run(self, domain: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM runs WHERE domain=? ORDER BY id DESC LIMIT 1", (domain,)
        ).fetchone()
        return dict(row) if row else None

    # --- products & observations ---
    def record_product(self, domain: str, run_id: int, record, change_hint: str | None) -> bool:
        from backend.archive.domain.product import WATCHED_FIELDS

        row = self._db.execute(
            "SELECT id, current_json FROM products WHERE domain=? AND itemurl=?",
            (domain, record.itemurl),
        ).fetchone()
        record_json = record.model_dump_json()
        changed = True
        if row:
            prev = json.loads(row["current_json"])
            cur = record.model_dump()
            changed = any(prev.get(f) != cur.get(f) for f in WATCHED_FIELDS)
            self._db.execute(
                "UPDATE products SET last_seen_run=?, change_hint=?, current_json=? WHERE id=?",
                (run_id, change_hint, record_json, row["id"]),
            )
            product_id = row["id"]
        else:
            cur_ = self._db.execute(
                "INSERT INTO products (domain, itemurl, product_code, change_hint, "
                "first_seen_run, last_seen_run, current_json) VALUES (?,?,?,?,?,?,?)",
                (
                    domain,
                    record.itemurl,
                    record.product_code,
                    change_hint,
                    run_id,
                    run_id,
                    record_json,
                ),
            )
            product_id = cur_.lastrowid
        if changed:
            self._db.execute(
                "INSERT INTO observations (product_id, run_id, price, full_price, in_stock, size_availability) "
                "VALUES (?,?,?,?,?,?)",
                (
                    product_id,
                    run_id,
                    record.price,
                    record.full_price,
                    None if record.in_stock is None else int(record.in_stock),
                    record.size_availability,
                ),
            )
        self._db.commit()
        return changed

    def mark_seen(self, domain: str, run_id: int, urls: list[str]) -> None:
        self._db.executemany(
            "UPDATE products SET last_seen_run=? WHERE domain=? AND itemurl=?",
            [(run_id, domain, u) for u in urls],
        )
        self._db.commit()

    def get_change_hints(self, domain: str) -> dict[str, str]:
        rows = self._db.execute(
            "SELECT itemurl, change_hint FROM products WHERE domain=? AND change_hint IS NOT NULL",
            (domain,),
        ).fetchall()
        return {r["itemurl"]: r["change_hint"] for r in rows}

    def observation_count(self, domain: str) -> int:
        return self._db.execute(
            "SELECT COUNT(*) c FROM observations o JOIN products p ON p.id=o.product_id WHERE p.domain=?",
            (domain,),
        ).fetchone()["c"]

    def current_products(self, domain: str, live_only: bool = True) -> list[dict]:
        if live_only:
            # The most recent run that got as far as measuring its own coverage. A run
            # that never reached the catalogue — rate limited, or its plan failed —
            # finalises without coverage, and treating it as the reference made 500
            # stored products stop being "current": the rows were still here, they had
            # just stopped being visible. A run that did read the catalogue and did not
            # see a product still delists it, which is the point of this view.
            latest = self._db.execute(
                "SELECT id FROM runs WHERE domain=? AND exit_status IN (0,1) "
                "AND coverage_json IS NOT NULL ORDER BY id DESC LIMIT 1",
                (domain,),
            ).fetchone()
            if not latest:
                return []
            rows = self._db.execute(
                "SELECT current_json FROM products WHERE domain=? AND last_seen_run=?",
                (domain, latest["id"]),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT current_json FROM products WHERE domain=?", (domain,)
            ).fetchall()
        return [json.loads(r["current_json"]) for r in rows]

    # --- learned field rules ---
    def rewrite_field(self, domain: str, field: str, value) -> int:
        """Set one field to one value across a brand's current products.

        Used when a check over the whole catalogue shows a field was mapped from the
        wrong place — that verdict can only be reached once every product is in, so the
        repair happens after the run rather than per product.
        """
        rows = self._db.execute(
            "SELECT id, current_json FROM products WHERE domain=?", (domain,)
        ).fetchall()
        for row in rows:
            record = json.loads(row["current_json"])
            record[field] = value
            self._db.execute(
                "UPDATE products SET current_json=? WHERE id=?",
                (json.dumps(record), row["id"]),
            )
        self._db.commit()
        return len(rows)

    def record_requests(self, rows: list[tuple]) -> None:
        """Store a batch of (host, status, latency_ms, retry_after, at) observations."""
        if not rows:
            return
        self._db.executemany(
            "INSERT INTO requests (host, status, latency_ms, retry_after, at) VALUES (?,?,?,?,?)",
            rows,
        )
        self._db.commit()

    def host_stats(self, since: str | None = None) -> list[dict]:
        """How each host has been answering us."""
        where = "WHERE at >= ?" if since else ""
        args = (since,) if since else ()
        return [
            dict(r)
            for r in self._db.execute(
                f"SELECT host, COUNT(*) AS requests, "
                f"  SUM(status = 200) AS ok, "
                f"  SUM(status IN (429, 503)) AS busy, "
                f"  SUM(status IN (401, 403)) AS refused, "
                f"  SUM(status IS NULL) AS errored, "
                f"  CAST(AVG(latency_ms) AS INTEGER) AS avg_ms, "
                f"  MAX(retry_after) AS max_retry_after "
                f"FROM requests {where} GROUP BY host ORDER BY requests DESC",
                args,
            )
        ]

    def extraction_version_for(self, domain: str) -> str | None:
        row = self._db.execute(
            "SELECT version FROM extraction_versions WHERE domain=?", (domain,)
        ).fetchone()
        return row["version"] if row else None

    def set_extraction_version(self, domain: str, version: str) -> None:
        self._db.execute(
            "INSERT INTO extraction_versions (domain, version, seen_at) VALUES (?,?,?) "
            "ON CONFLICT(domain) DO UPDATE SET version=excluded.version, "
            "seen_at=excluded.seen_at",
            (domain, version, datetime.now(timezone.utc).isoformat()),
        )
        self._db.commit()

    def save_scorecard(self, run_id: int, domain: str, card) -> None:
        self._db.execute(
            "INSERT INTO scorecards (run_id, domain, card_json, scored_at) VALUES (?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET card_json=excluded.card_json, "
            "scored_at=excluded.scored_at",
            (run_id, domain, json.dumps(card.as_dict()), datetime.now(timezone.utc).isoformat()),
        )
        self._db.commit()

    def scorecards(self, domain: str, limit: int = 20) -> list[dict]:
        return [
            {**json.loads(r["card_json"]), "run_id": r["run_id"], "scored_at": r["scored_at"]}
            for r in self._db.execute(
                "SELECT run_id, card_json, scored_at FROM scorecards WHERE domain=? "
                "ORDER BY run_id DESC LIMIT ?",
                (domain, limit),
            )
        ]

    def record_evidence(self, domain: str, run_id: int, rows: list[tuple]) -> None:
        """Store what this run searched, per field and source. The latest run wins."""
        now = datetime.now(timezone.utc).isoformat()
        self._db.executemany(
            "INSERT INTO field_evidence (domain, field, source, examined, found, run_id, "
            "searched_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(domain, field, source) DO UPDATE SET "
            "examined=excluded.examined, found=excluded.found, run_id=excluded.run_id, "
            "searched_at=excluded.searched_at",
            [(domain, f, src, n, hits, run_id, now) for f, src, n, hits in rows],
        )
        self._db.commit()

    def load_evidence(self, domain: str) -> dict[tuple[str, str], tuple[int, int]]:
        return {
            (r["field"], r["source"]): (r["examined"], r["found"])
            for r in self._db.execute(
                "SELECT field, source, examined, found FROM field_evidence WHERE domain=?",
                (domain,),
            )
        }

    def save_recipe_book(self, book) -> None:
        self._db.execute(
            "INSERT INTO recipe_books (domain, book_json, learned_at) VALUES (?,?,?) "
            "ON CONFLICT(domain) DO UPDATE SET book_json=excluded.book_json, "
            "learned_at=excluded.learned_at",
            (book.domain, book.model_dump_json(), book.learned_at),
        )
        self._db.commit()

    def load_recipe_book(self, domain: str):
        from backend.archive.domain.recipe import RecipeBook

        row = self._db.execute(
            "SELECT book_json FROM recipe_books WHERE domain=?", (domain,)
        ).fetchone()
        return RecipeBook.model_validate_json(row["book_json"]) if row else None

    # --- images ---
    def product_id_for(self, domain: str, itemurl: str) -> int | None:
        row = self._db.execute(
            "SELECT id FROM products WHERE domain=? AND itemurl=?", (domain, itemurl)
        ).fetchone()
        return row["id"] if row else None

    def known_image_urls(self, product_id: int) -> set[str]:
        rows = self._db.execute(
            "SELECT url FROM images WHERE product_id=?", (product_id,)
        ).fetchall()
        return {r["url"] for r in rows}

    def record_image(self, product_id: int, url: str, local_path: str, content_hash: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO images (product_id, url, local_path, content_hash) VALUES (?,?,?,?)",
            (product_id, url, local_path, content_hash),
        )
        self._db.commit()

    def image_count(self, domain: str) -> int:
        return self._db.execute(
            "SELECT COUNT(*) c FROM images i JOIN products p ON p.id=i.product_id WHERE p.domain=?",
            (domain,),
        ).fetchone()["c"]

    def status_rows(self) -> list[dict]:
        rows = self._db.execute(
            """SELECT b.domain, b.state,
                      (SELECT COUNT(*) FROM products p WHERE p.domain=b.domain) AS products,
                      r.coverage_json, r.finished_at, r.mode
               FROM brands b
               LEFT JOIN runs r ON r.id = (SELECT id FROM runs WHERE domain=b.domain
                                           AND exit_status IS NOT NULL ORDER BY id DESC LIMIT 1)
               ORDER BY b.domain"""
        ).fetchall()
        out = []
        for r in rows:
            cov = json.loads(r["coverage_json"]) if r["coverage_json"] else None
            out.append(
                {
                    "domain": r["domain"],
                    "state": r["state"],
                    "products": r["products"],
                    "coverage_pct": cov["coverage_pct"] if cov else None,
                    "verdict": cov["verdict"] if cov else None,
                    "freshness": r["finished_at"],
                    "mode": r["mode"],
                }
            )
        return out
