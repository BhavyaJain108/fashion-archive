"""The only module that touches storage, now over objects instead of a table.

Every method the SQLite version had, with the same name and the same meaning, so
nothing above this file knows the difference. Underneath, the layout is one object
per brand per kind, because two workers never scrape the same brand — the claim
prevents it — so nothing but the control plane is ever contended.

Three things are worth knowing before reading further.

`catalogue/<domain>.json` holds every product with its untouched connector payload.
The largest is 9.8 MB. It is read once at the start of a run, mutated in memory, and
flushed — writing it per product would be 9.8 MB per product. So `close()` is
load-bearing here in a way it was not before.

`catalogue/<domain>.meta.json` holds only counts, state and freshness. The sidebar
draws 32 brands, and reading 32 catalogues to do it would pull 55 MB over the wire
for a column of numbers.

`search/<domain>.json` holds the fields a tile and a search need and nothing else.
A stored record averages 7.8 KB because of that payload; the slim form of a
500-product brand is 275 KB. Search reads these.
"""

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from backend.archive.domain.brand import Brand, ScrapePlan
from backend.archive.domain.run import Coverage
from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads

FLUSH_EVERY = 200

# What a tile and the search box need. The rest of a record is the connector's own
# payload, kept so a mapping can be re-derived, and meaningless to a browser.
SEARCH_FIELDS = (
    "itemurl",
    "product_title",
    "product_code",
    "brand",
    "price",
    "full_price",
    "currency",
    "in_stock",
    "main_image_url",
    "all_images",
    "size_info",
    "size_availability",
    "size_stock_counts",
    "color_info",
    "material_info",
    "description",
    "additional_tags",
    *(f"category{i}" for i in range(1, 11)),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    """Sortable by time, unique without a counter to hand out.

    The SQLite version used an autoincrementing integer, which an object store has no
    way to produce. A timestamp plus six hex characters sorts the same way and needs
    no coordination between workers.
    """
    return f"{_now()}-{secrets.token_hex(3)}"


class Catalog:
    def __init__(self, store: ObjectStore):
        self._store = store
        # A brand's catalogue, held while a run writes to it. domain -> (products, dirty)
        self._open: dict[str, dict[str, Any]] = {}
        self._dirty: set[str] = set()
        self._pending_observations: dict[tuple[str, str], list[dict]] = {}
        self._since_flush = 0

    # --- object helpers ---
    def _read(self, key: str, default: Any = None) -> Any:
        found = self._store.get(key)
        return loads(found[0]) if found else default

    def _write(self, key: str, value: Any) -> None:
        self._store.put(key, dumps(value))

    def close(self) -> None:
        self.flush()

    # --- brands ---
    def upsert_brand(self, brand: Brand) -> None:
        key = f"brands/{brand.domain}.json"
        existing = self._read(key, {})
        self._write(
            key,
            {
                "domain": brand.domain,
                "homepage_url": brand.homepage_url,
                "display_name": brand.display_name,
                "notes": brand.notes,
                "state": existing.get("state", "new"),
            },
        )

    def get_brand(self, domain: str) -> Brand | None:
        row = self._read(f"brands/{domain}.json")
        if not row:
            return None
        return Brand(
            domain=row["domain"],
            homepage_url=row["homepage_url"],
            display_name=row.get("display_name"),
            notes=row.get("notes"),
        )

    def list_brands(self) -> list[Brand]:
        return [
            b
            for b in (self.get_brand(self._domain_of(k)) for k in self._store.list("brands/"))
            if b is not None
        ]

    @staticmethod
    def _domain_of(key: str) -> str:
        return key.split("/", 1)[1].removesuffix(".json")

    def set_brand_state(self, domain: str, state: str) -> None:
        key = f"brands/{domain}.json"
        row = self._read(key, {"domain": domain, "homepage_url": f"https://{domain}"})
        row["state"] = state
        self._write(key, row)

    def get_brand_state(self, domain: str) -> str:
        return self._read(f"brands/{domain}.json", {}).get("state", "new")

    # --- plans ---
    def save_plan(self, plan: ScrapePlan) -> None:
        self._write(
            f"plans/{plan.domain}.json",
            {"plan": json.loads(plan.model_dump_json()), "fingerprinted_at": _now()},
        )

    def load_plan(self, domain: str) -> ScrapePlan | None:
        row = self._read(f"plans/{domain}.json")
        return ScrapePlan(**row["plan"]) if row else None

    # --- runs ---
    def open_run(self, domain: str, mode: str) -> str:
        run_id = new_run_id()
        self._write(
            f"runs/{domain}/{run_id}.json",
            {
                "id": run_id,
                "domain": domain,
                "mode": mode,
                "started_at": _now(),
                "finished_at": None,
                "exit_status": None,
                "coverage": None,
            },
        )
        index = self._read(f"runs/{domain}/index.json", {"runs": []})
        index["runs"].append(run_id)
        self._write(f"runs/{domain}/index.json", index)
        return run_id

    def run_ids(self, domain: str) -> list[str]:
        return sorted(self._read(f"runs/{domain}/index.json", {"runs": []})["runs"])

    def _run(self, domain: str, run_id: str) -> dict | None:
        return self._read(f"runs/{domain}/{run_id}.json")

    def _domain_of_run(self, run_id: str) -> str | None:
        for key in self._store.list("runs/"):
            if key.endswith(f"/{run_id}.json"):
                return key.split("/")[1]
        return None

    def finalize_run(self, run_id: str, exit_status: int, coverage: Coverage | None) -> None:
        domain = self._domain_of_run(run_id)
        if domain is None:
            return
        self.flush()
        row = self._run(domain, run_id) or {}
        row["finished_at"] = _now()
        row["exit_status"] = exit_status
        row["coverage"] = json.loads(coverage.model_dump_json()) if coverage else None
        self._write(f"runs/{domain}/{run_id}.json", row)
        # After the run row, not before. Both of these filter on the latest covered
        # run, and during the flush above this run had no coverage yet — so they would
        # have matched the previous run and left the index describing products that
        # were no longer the current ones. On a brand's second run that emptied it.
        self._write_search_index(domain)
        self._refresh_meta(domain)

    def latest_run(self, domain: str) -> dict | None:
        for run_id in reversed(self.run_ids(domain)):
            row = self._run(domain, run_id)
            if row and row.get("exit_status") is not None:
                return row
        return None

    def _latest_covered_run(self, domain: str) -> str | None:
        """The run a product must have been seen in to count as still listed.

        The most recent one that got as far as measuring its own coverage. A run that
        never reached the catalogue — rate limited, or its plan failed — finalises
        without coverage, and treating it as the reference made 500 stored products
        stop being current: the records were still there, they had just stopped being
        visible. A run that did read the catalogue and did not see a product still
        delists it, which is the point of this view.
        """
        for run_id in reversed(self.run_ids(domain)):
            row = self._run(domain, run_id)
            if row and row.get("exit_status") in (0, 1) and row.get("coverage") is not None:
                return run_id
        return None

    # --- the catalogue ---
    def _catalogue(self, domain: str) -> dict[str, Any]:
        if domain not in self._open:
            self._open[domain] = self._read(f"catalogue/{domain}.json", {"products": {}})
        return self._open[domain]

    def record_product(self, domain: str, run_id: str, record, change_hint: str | None) -> bool:
        from backend.archive.domain.product import WATCHED_FIELDS

        products = self._catalogue(domain)["products"]
        current = json.loads(record.model_dump_json())
        previous = products.get(record.itemurl)
        changed = True
        if previous:
            changed = any(previous["record"].get(f) != current.get(f) for f in WATCHED_FIELDS)
            previous.update(
                {"record": current, "change_hint": change_hint, "last_seen_run": run_id}
            )
        else:
            products[record.itemurl] = {
                "record": current,
                "product_code": record.product_code,
                "change_hint": change_hint,
                "first_seen_run": run_id,
                "last_seen_run": run_id,
            }
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
        if self._since_flush >= FLUSH_EVERY:
            self.flush()
        return changed

    def flush(self) -> None:
        """Write what is held in memory.

        Called every FLUSH_EVERY products and on close. A run killed between flushes
        loses at most that many products, where the SQLite version lost none — which
        is the cost of not writing a 9.8 MB object per product, and acceptable because
        a killed run is re-run from the start rather than resumed.
        """
        for domain in sorted(self._dirty):
            self._write(f"catalogue/{domain}.json", self._open[domain])
            self._write_search_index(domain)
            self._refresh_meta(domain)
        self._dirty.clear()
        for (domain, run_id), rows in sorted(self._pending_observations.items()):
            key = f"history/{domain}/{run_id}.json"
            held = self._read(key, {"observations": []})
            held["observations"].extend(rows)
            self._write(key, held)
        self._pending_observations.clear()
        self._since_flush = 0

    def _write_search_index(self, domain: str) -> None:
        products = self._catalogue(domain)["products"]
        live = self._latest_covered_run(domain)
        slim = [
            {k: row["record"].get(k) for k in SEARCH_FIELDS}
            for row in products.values()
            if live is None or row["last_seen_run"] == live
        ]
        self._write(f"search/{domain}.json", {"products": slim})

    def _refresh_meta(self, domain: str) -> None:
        products = self._catalogue(domain)["products"]
        live = self._latest_covered_run(domain)
        latest = self.latest_run(domain)
        coverage = (latest or {}).get("coverage") or {}
        self._write(
            f"catalogue/{domain}.meta.json",
            {
                "domain": domain,
                "products": len(products),
                "live_products": sum(
                    1 for r in products.values() if live and r["last_seen_run"] == live
                ),
                "state": self.get_brand_state(domain),
                "freshness": (latest or {}).get("finished_at"),
                "mode": (latest or {}).get("mode"),
                "coverage_pct": coverage.get("coverage_pct"),
                "verdict": coverage.get("verdict"),
            },
        )

    def mark_seen(self, domain: str, run_id: str, urls: list[str]) -> None:
        products = self._catalogue(domain)["products"]
        for url in urls:
            if url in products:
                products[url]["last_seen_run"] = run_id
        self._dirty.add(domain)

    def get_change_hints(self, domain: str) -> dict[str, str]:
        return {
            url: row["change_hint"]
            for url, row in self._catalogue(domain)["products"].items()
            if row.get("change_hint") is not None
        }

    def observation_count(self, domain: str) -> int:
        self.flush()
        total = 0
        for key in self._store.list(f"history/{domain}/"):
            total += len(self._read(key, {"observations": []})["observations"])
        return total

    def current_products(self, domain: str, live_only: bool = True) -> list[dict]:
        products = self._catalogue(domain)["products"]
        if not live_only:
            return [row["record"] for row in products.values()]
        live = self._latest_covered_run(domain)
        if live is None:
            return []
        return [row["record"] for row in products.values() if row["last_seen_run"] == live]

    def rewrite_field(self, domain: str, field: str, value) -> int:
        """Set one field to one value across a brand's products.

        Used when a check over the whole catalogue shows a field was mapped from the
        wrong place — a verdict only reachable once every product is in, so the repair
        happens after the run rather than per product.
        """
        products = self._catalogue(domain)["products"]
        for row in products.values():
            row["record"][field] = value
        self._dirty.add(domain)
        self.flush()
        return len(products)

    def search_products(
        self, domains: list[str], needle: str, limit: int = 200
    ) -> list[tuple[str, dict]]:
        """Products of these brands whose slim record mentions `needle`.

        Over search/<domain>.json rather than the catalogues: the question is asked
        about titles, materials, colours and categories interchangeably, all of which
        are in the slim form, and the full records are 200 times the bytes.
        """
        if not domains or not needle:
            return []
        self.flush()
        wanted = needle.lower()
        hits: list[tuple[str, dict]] = []
        for domain in domains:
            for record in self._read(f"search/{domain}.json", {"products": []})["products"]:
                if wanted in dumps(record).decode().lower():
                    hits.append((domain, record))
                    if len(hits) >= limit:
                        return hits
        return hits

    # --- learned field rules ---
    def save_recipe_book(self, book) -> None:
        self._write(
            f"rules/{book.domain}.json",
            {"book": json.loads(book.model_dump_json()), "learned_at": _now()},
        )

    def load_recipe_book(self, domain: str):
        from backend.archive.domain.recipe import RecipeBook

        row = self._read(f"rules/{domain}.json")
        return RecipeBook(**row["book"]) if row else None

    # --- evidence ---
    def record_evidence(self, domain: str, run_id: str, rows: list[tuple]) -> None:
        key = f"evidence/{domain}.json"
        held = self._read(key, {})
        for field, source, examined, found in rows:
            held[f"{field}|{source}"] = {
                "examined": examined,
                "found": found,
                "run_id": run_id,
                "searched_at": _now(),
            }
        self._write(key, held)

    def load_evidence(self, domain: str) -> dict[tuple[str, str], tuple[int, int]]:
        held = self._read(f"evidence/{domain}.json", {})
        out = {}
        for pair, row in held.items():
            field, source = pair.split("|", 1)
            out[(field, source)] = (row["examined"], row["found"])
        return out

    # --- images ---
    def _images(self, domain: str) -> dict[str, list[dict]]:
        return self._read(f"images/{domain}.json", {})

    def record_image(
        self,
        domain: str,
        itemurl: str,
        url: str,
        content_hash: str,
        stored_url: str | None = None,
    ) -> None:
        key = f"images/{domain}.json"
        held = self._read(key, {})
        rows = held.setdefault(itemurl, [])
        for row in rows:
            if row["url"] == url:
                row["content_hash"] = content_hash
                row["stored_url"] = stored_url or row.get("stored_url")
                break
        else:
            rows.append({"url": url, "content_hash": content_hash, "stored_url": stored_url})
        self._write(key, held)

    def known_image_urls(self, domain: str, itemurl: str) -> set[str]:
        return {row["url"] for row in self._images(domain).get(itemurl, [])}

    def stored_image_urls(self, domain: str, itemurl: str) -> set[str]:
        return {
            row["url"] for row in self._images(domain).get(itemurl, []) if row.get("stored_url")
        }

    def archived_images(self, domain: str) -> dict[str, list[str]]:
        """Where we serve each product's photographs from, keyed by itemurl.

        The URL in a record is the shop's copy and can stop resolving; these are the
        bytes we kept, which is the whole reason the files are archived rather than
        only their addresses.
        """
        out = {}
        for itemurl, rows in self._images(domain).items():
            urls = [r["stored_url"] for r in rows if r.get("stored_url")]
            if urls:
                out[itemurl] = urls
        return out

    def images_awaiting_archive(self, domain: str) -> list[tuple[str, list[str]]]:
        """(itemurl, image urls not yet stored) for this brand's live products.

        Driven off what the records say rather than off the run that wrote them, so the
        image pass can be re-run at any time and picks up exactly what is missing.
        """
        held = self._images(domain)
        work = []
        for record in self.current_products(domain):
            itemurl = record.get("itemurl", "")
            done = {r["url"] for r in held.get(itemurl, []) if r.get("stored_url")}
            raw = record.get("all_images")
            try:
                urls = json.loads(raw) if isinstance(raw, str) else (raw or [])
            except json.JSONDecodeError:
                urls = []
            if not isinstance(urls, list):
                urls = []
            missing = [u for u in urls if isinstance(u, str) and u not in done]
            if missing:
                work.append((itemurl, missing))
        return work

    def stored_image_count(self, domain: str) -> int:
        return sum(1 for rows in self._images(domain).values() for r in rows if r.get("stored_url"))

    # --- scorecards, request ledger, extraction versions ---
    def save_scorecard(self, run_id: str, domain: str, card) -> None:
        self._write(
            f"scores/{domain}/{run_id}.json",
            {"card": card.as_dict(), "run_id": run_id, "scored_at": _now()},
        )

    def scorecards(self, domain: str, limit: int = 20) -> list[dict]:
        keys = sorted(self._store.list(f"scores/{domain}/"), reverse=True)[:limit]
        out = []
        for key in keys:
            row = self._read(key)
            if row:
                out.append({**row["card"], "run_id": row["run_id"], "scored_at": row["scored_at"]})
        return out

    def record_requests(self, rows: list[tuple]) -> None:
        """Store a batch of (host, status, latency_ms, retry_after, at) observations."""
        if not rows:
            return
        self._write(
            f"requests/{_now()}-{secrets.token_hex(3)}.json",
            {"rows": [list(r) for r in rows]},
        )

    def host_stats(self, since: str | None = None) -> list[dict]:
        """How each host has been answering us."""
        tallies: dict[str, dict[str, Any]] = {}
        for key in self._store.list("requests/"):
            for host, status, latency, retry_after, at in self._read(key, {"rows": []})["rows"]:
                if since and at < since:
                    continue
                t = tallies.setdefault(
                    host,
                    {
                        "host": host,
                        "requests": 0,
                        "ok": 0,
                        "busy": 0,
                        "refused": 0,
                        "errored": 0,
                        "_latency": [],
                        "max_retry_after": None,
                    },
                )
                t["requests"] += 1
                if status == 200:
                    t["ok"] += 1
                elif status in (429, 503):
                    t["busy"] += 1
                elif status in (401, 403):
                    t["refused"] += 1
                elif status is None:
                    t["errored"] += 1
                if latency is not None:
                    t["_latency"].append(latency)
                if retry_after is not None:
                    t["max_retry_after"] = max(t["max_retry_after"] or 0, retry_after)
        out = []
        for t in tallies.values():
            latency = t.pop("_latency")
            t["avg_ms"] = int(sum(latency) / len(latency)) if latency else None
            out.append(t)
        return sorted(out, key=lambda t: -t["requests"])

    def extraction_version_for(self, domain: str) -> str | None:
        return self._read(f"versions/{domain}.json", {}).get("version")

    def set_extraction_version(self, domain: str, version: str) -> None:
        self._write(f"versions/{domain}.json", {"version": version, "seen_at": _now()})

    # --- the fleet view ---
    def _meta(self, domain: str) -> dict:
        return self._read(f"catalogue/{domain}.meta.json", {})

    def live_product_counts(self) -> dict[str, int]:
        """Products per brand that are still listed — the number the app can show.

        From the meta objects, never the catalogues. Reading 32 catalogues to draw a
        column of numbers would pull 55 MB for something a few hundred bytes can say.
        """
        counts = {}
        for key in self._store.list("catalogue/"):
            if not key.endswith(".meta.json"):
                continue
            row = self._read(key, {})
            if row.get("live_products"):
                counts[row["domain"]] = row["live_products"]
        return counts

    def status_rows(self) -> list[dict]:
        out = []
        for key in self._store.list("brands/"):
            domain = self._domain_of(key)
            meta = self._meta(domain)
            out.append(
                {
                    "domain": domain,
                    "state": self.get_brand_state(domain),
                    "products": meta.get("products", 0),
                    "coverage_pct": meta.get("coverage_pct"),
                    "verdict": meta.get("verdict"),
                    "freshness": meta.get("freshness"),
                    "mode": meta.get("mode"),
                }
            )
        return sorted(out, key=lambda r: r["domain"])


__all__ = ["Catalog", "Conflict", "FLUSH_EVERY", "new_run_id"]
