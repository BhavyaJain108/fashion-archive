"""The owner's view of the machinery: what is scraped, what it costs, what is broken.

Not part of the app people visit. It answers questions the public pages never ask —
which worker is on which brand, whose heartbeat stopped, and which brands the archive
cannot reach and why.

Two rules shape what this reads:

  the schedule and fleet objects are small and answer most questions, so the overview
  is a handful of reads no matter how many brands there are;

  a brand's catalogue is not. psylos1's is 35 MB, and parsing it to count photographs
  is what killed the worker. Anything needing it is a separate request for one brand,
  never part of the overview.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify

from backend.archive.roster import app_roster
from backend.archive.scheduler import Scheduler
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import ObjectStore, loads, object_store

# A worker says it is alive every five minutes. Twice that and something is wrong: a
# claim nobody is working is the shape every dead worker has left behind.
HEARTBEAT_GRACE_MINUTES = 12


def _store() -> ObjectStore:
    root = os.environ.get("ARCHIVE_OBJECTS")
    return object_store(Path(root) if root else None)


def _owner_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def _forbidden():
    return jsonify(
        {"success": False, "error": "not an owner of this archive", "code": "NOT_OWNER"}
    ), 403


def _is_owner() -> bool:
    """Whether this request's user may see the machinery.

    An empty allowlist denies everyone rather than allowing everyone. The opposite
    default turns a forgotten environment variable into an open door.
    """
    from backend.auth.middleware import current_user

    allowed = _owner_emails()
    if not allowed:
        return False
    user = current_user()
    return user is not None and (getattr(user, "email", "") or "").lower() in allowed


def _minutes_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 60


def _why_empty(domain: str, catalog: Catalog) -> str | None:
    """Why a brand shows nothing, from what the archive recorded rather than a guess."""
    state = catalog.get_brand_state(domain)
    if state == "gated":
        return "the shop is behind a password"
    plan = catalog.load_plan(domain)
    if plan is not None and "t2" in (plan.composition or ""):
        return "needs a browser, which the scraper image does not carry"
    if state == "needs_attention":
        return "the last run could not reach it"
    return None


def register_dev_routes(app: Flask) -> None:
    @app.route("/api/dev/overview", methods=["GET"])
    def dev_overview():
        if not _is_owner():
            return _forbidden()

        store = _store()
        catalog = Catalog(store)
        found = store.get("fleet.json")
        fleet = loads(found[0]) if found else {}
        rows = {r["domain"]: r for r in Scheduler(store).rows()}
        names = {e.domain: e.name for e in app_roster()}

        brands: list[dict] = []
        running: list[str] = []
        stalled: list[str] = []
        for domain in sorted(rows):
            row = rows[domain]
            meta = fleet.get(domain) or {}
            live = meta.get("live_products") or 0
            claimed = row.get("claimed_by")
            age = _minutes_since(row.get("claimed_at"))
            alive = (
                None if claimed is None else (age is not None and age <= HEARTBEAT_GRACE_MINUTES)
            )
            brands.append(
                {
                    "domain": domain,
                    "name": names.get(domain, domain),
                    "live_products": live,
                    "photographs": meta.get("images") or 0,
                    "state": meta.get("state"),
                    "verdict": meta.get("verdict"),
                    "coverage_pct": meta.get("coverage_pct"),
                    "last_run": meta.get("freshness"),
                    "last_mode": meta.get("mode"),
                    "next_due": row.get("next_due"),
                    "enabled": bool(row.get("enabled")),
                    "cadence_seconds": row.get("cadence_seconds"),
                    "claimed_by": claimed,
                    "heartbeat_minutes": None if age is None else round(age, 1),
                    "worker_alive": alive,
                    "empty_because": _why_empty(domain, catalog) if not live else None,
                }
            )
            if claimed:
                (running if alive else stalled).append(domain)

        return jsonify(
            {
                "success": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "totals": {
                    "brands": len(brands),
                    "showing": sum(1 for b in brands if b["live_products"]),
                    "live_products": sum(b["live_products"] for b in brands),
                    "photographs": sum(b["photographs"] for b in brands),
                },
                "workers": {"running": running, "stalled": stalled},
                "brands": brands,
            }
        )

    @app.route("/api/dev/brands/<brand_id>/photographs", methods=["GET"])
    def dev_brand_photographs(brand_id):
        """Photographs stored and still wanted, for one brand.

        Its own request because answering it parses that brand's catalogue — 35 MB for
        the largest. Asking it for every brand at once is what the overview avoids.
        """
        if not _is_owner():
            return _forbidden()
        catalog = Catalog(_store())
        stored = catalog.stored_image_count(brand_id)
        waiting = sum(len(urls) for _, urls in catalog.images_awaiting_archive(brand_id))
        catalog.release_products(brand_id)
        return jsonify({"success": True, "domain": brand_id, "stored": stored, "waiting": waiting})
