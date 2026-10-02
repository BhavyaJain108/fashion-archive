"""What the archive holds in photographs: per product, per brand, overall, and in bytes.

Three questions the deck could not answer before 2026-10-02, when 12,998 live products
named photographs of which none had been kept, and the overview said every brand held
zero photographs because it read a counter nothing updated after the image pass:

    which products have no photograph we hold      — the ones to flag and fix
    how complete each brand's archive is           — named, kept, given up, waiting
    what it all weighs in the bucket               — bytes and objects, by brand

A product is counted by what its record *names* (`all_images`, else `main_image_url`)
against the rows `product_images` holds for it. "Given up" is a photograph asked for
`Catalog.GIVE_UP_AFTER` times without an image coming back; "waiting" is the rest of
what is named and not yet kept, which the next image pass fetches.

The bytes come from one listing of `archive/` (the listing carries each object's size,
so nothing is downloaded) and are kept in `control/image_storage.json`, refreshed by the
nightly backup and by `cli images --stats --bytes`. Listing 340,000 objects is a few
hundred requests: right for a night, wrong for every load of a page.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from backend.archive.store.objects import ObjectStore, dumps, loads

STORAGE_KEY = "control/image_storage.json"
PREFIX = "archive/"
# Photographs per brand, as the counters name them, in the order the deck shows them.
FIELDS = (
    "products",
    "complete",
    "partial",
    "none_kept",
    "none_named",
    "named",
    "kept",
    "given_up",
    "waiting",
)


def named_urls(record: dict) -> list[str]:
    """The photographs a record names: its gallery, else its main image."""
    raw = record.get("all_images")
    try:
        urls = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except json.JSONDecodeError:
        urls = []
    urls = [u for u in urls if isinstance(u, str) and u] if isinstance(urls, list) else []
    if not urls and record.get("main_image_url") not in (None, "", "None"):
        urls = [record["main_image_url"]]
    return urls


def product_line(record: dict, rows: list[dict], give_up_after: int) -> dict:
    """One product: what it names, what we keep, what we gave up on, what waits."""
    named = named_urls(record)
    kept = {r["url"] for r in rows if r.get("stored_url")}
    given_up = {
        r["url"]
        for r in rows
        if not r.get("stored_url") and (r.get("misses") or 0) >= give_up_after
    }
    return {
        "itemurl": record.get("itemurl", ""),
        "title": record.get("product_title") or record.get("title"),
        "named": len(named),
        "kept": len(kept),
        "given_up": len(given_up & set(named)),
        "waiting": len([u for u in named if u not in kept and u not in given_up]),
    }


def brand_totals(domain: str, lines: list[dict]) -> dict:
    out: dict[str, Any] = {"domain": domain, **dict.fromkeys(FIELDS, 0)}
    for line in lines:
        out["products"] += 1
        out["named"] += line["named"]
        out["kept"] += line["kept"]
        out["given_up"] += line["given_up"]
        out["waiting"] += line["waiting"]
        if not line["named"]:
            out["none_named"] += 1
        elif not line["kept"]:
            out["none_kept"] += 1
        elif line["kept"] < line["named"]:
            out["partial"] += 1
        else:
            out["complete"] += 1
    return out


def fleet_totals(brands: list[dict]) -> dict:
    out: dict[str, Any] = dict.fromkeys(FIELDS, 0)
    for b in brands:
        for f in FIELDS:
            out[f] += int(b.get(f) or 0)
    out["brands"] = len(brands)
    return out


def flagged(lines: list[dict]) -> list[dict]:
    """The products with no photograph we hold, with why: none named, or none kept."""
    out = []
    for line in lines:
        if line["kept"]:
            continue
        if not line["named"]:
            why = "the shop names no photograph"
        elif line["given_up"] >= line["named"]:
            why = "every photograph it names failed to download"
        else:
            why = "photographs named, not yet downloaded"
        out.append({**line, "why": why})
    return out


# --- bytes ---------------------------------------------------------------------------


def _photograph_root(store: ObjectStore) -> ObjectStore:
    """The store the photographs live in. On R2 they sit at the bucket's root
    (`archive/<brand>/…`, `storage/images.py`) while the control plane lives under its
    own `archive-store/` prefix, so the same bucket is listed without that prefix."""
    from backend.archive.store.objects import R2ObjectStore

    if isinstance(store, R2ObjectStore):
        return R2ObjectStore(store._bucket, client=store._client, prefix="")
    return store


def measure_storage(store: ObjectStore, clock=None) -> dict:
    """List the archive once, total it by brand, and keep the result."""
    sizes = _photograph_root(store).sizes(PREFIX)
    by_brand: dict[str, dict[str, int]] = defaultdict(lambda: {"objects": 0, "bytes": 0})
    for key, size in sizes.items():
        parts = key.split("/")
        domain = parts[1] if len(parts) > 2 else "(loose)"
        by_brand[domain]["objects"] += 1
        by_brand[domain]["bytes"] += size
    row = {
        "at": (clock or (lambda: datetime.now(timezone.utc)))().isoformat(timespec="seconds"),
        "objects": len(sizes),
        "bytes": sum(sizes.values()),
        "by_brand": dict(sorted(by_brand.items())),
    }
    store.put(STORAGE_KEY, dumps(row))
    return row


def load_storage(store: ObjectStore) -> dict | None:
    found = store.get(STORAGE_KEY)
    return loads(found[0]) if found else None
