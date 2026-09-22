"""The owner's view of the machinery: what is scraped, what it costs, what is broken.

Not part of the app people visit. It answers questions the public pages never ask —
which worker is on which brand, whose heartbeat stopped, which brands the archive
cannot reach and why, what each field is worth on each brand, and what to fix first.

Two rules shape what this reads:

  the schedule and fleet objects are small and answer most questions, so the overview
  is a handful of reads no matter how many brands there are — everything a row shows
  was folded into fleet.json by the daemon as it went;

  a brand's catalogue is not. psylos1's is 35 MB, and parsing it to count photographs
  is what killed the worker. Anything needing it is a separate request for one brand,
  never part of the overview.

The deck reads; the daemon writes. The two controls here — run now, pause — are edits
to the schedule object, which is how the daemon has always been steered.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, current_app, jsonify, request

from backend.api import providers
from backend.archive.audit import CLASSES
from backend.archive.domain.product import E0005_FIELDS
from backend.archive.evidence import describe
from backend.archive.roster import app_roster
from backend.archive.scheduler import Scheduler
from backend.archive.spend_cap import DailyCap
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import ObjectStore, loads, object_store

# A worker says it is alive every five minutes. Twice that and something is wrong: a
# claim nobody is working is the shape every dead worker has left behind.
HEARTBEAT_GRACE_MINUTES = 12

# Which audit class each E0005 field belongs to, by the class's one-letter tag.
FIELD_CLASS = {f: label[0] for label, fields, _ in CLASSES for f in fields}
CLASS_NOTES = {label[0]: (label[3:].strip(), note) for label, _, note in CLASSES}


_bucket_store: ObjectStore | None = None
_store_lock = threading.Lock()


def _store() -> ObjectStore:
    """The bucket, built once per process. A fresh client per request meant a fresh
    connection per request; the reads behind one page are dozens, and every one
    paid the handshake again. A directory store (tests, local runs) is cheap and is
    built each time so a test's temporary directory is always the one it set."""
    global _bucket_store
    root = os.environ.get("ARCHIVE_OBJECTS")
    if root:
        return object_store(Path(root))
    with _store_lock:
        if _bucket_store is None:
            _bucket_store = object_store(None)
        return _bucket_store


# --- answering ------------------------------------------------------------------
# Every read here answers with a version tag over its content, and a request that
# carries the version it already holds gets 304 and no body. The page asks every
# minute; most minutes nothing has changed, and the answer to "anything new?" is
# then a few hundred bytes rather than the whole table again. `generated_at` is
# left out of the tag — it changes every call and says nothing about the content.
OVERVIEW_CACHE_SECONDS = 10
_overview_cache: tuple[float, dict] | None = None
_overview_lock = threading.Lock()


def _reply(payload: dict, status: int = 200):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    tagged = {k: v for k, v in payload.items() if k != "generated_at"}
    etag = (
        '"'
        + hashlib.sha1(
            json.dumps(tagged, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        + '"'
    )
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if status == 200 and request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers=headers)
    return Response(body, status=status, mimetype="application/json", headers=headers)


def _forget_overview() -> None:
    global _overview_cache
    with _overview_lock:
        _overview_cache = None


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


# A brand is addressed by its domain, and the domain becomes part of an object key.
# Anything that is not a domain is refused before it reaches a store — a directory
# store would resolve "..", and a bucket would quietly file the read under nonsense.
_DOMAIN = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)
_RUN_ID = re.compile(r"^[A-Za-z0-9T:.+-]{1,80}$")


def _bad_domain(brand_id: str):
    if _DOMAIN.match(brand_id):
        return None
    return jsonify({"success": False, "error": "not a domain", "code": "BAD_DOMAIN"}), 400


def _from_our_site() -> bool:
    """Whether a state-changing request was made by our own page.

    The session cookie is SameSite=Lax, which already keeps it off a cross-site POST;
    this is the second lock on the same door, the one logout also uses. A browser
    always sends Origin on a cross-origin POST, so its absence is a same-origin
    request or a non-browser client, neither of which is the case defended against.
    """
    origin = request.headers.get("Origin")
    if not origin:
        return True
    allowed = {
        str(current_app.config.get(key) or "").rstrip("/")
        for key in ("APP_BASE_URL", "API_BASE_URL")
    }
    allowed.discard("")
    return origin.rstrip("/") in allowed


def _cross_site():
    return jsonify({"success": False, "error": "cross-site request", "code": "BAD_ORIGIN"}), 403


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
    if state == "needs_attention":
        return "the last run could not reach it"
    plan = catalog.load_plan(domain)
    if plan is not None and "t2" in (plan.composition or ""):
        return "read through a browser; slower, and only one worker at a time"
    return None


def _names() -> dict[str, str]:
    return {e.domain: e.name for e in app_roster()}


def _brand_row(domain: str, row: dict, meta: dict, name: str, catalog: Catalog) -> dict:
    live = meta.get("live_products") or 0
    claimed = row.get("claimed_by")
    age = _minutes_since(row.get("claimed_at"))
    alive = None if claimed is None else (age is not None and age <= HEARTBEAT_GRACE_MINUTES)
    card = meta.get("last_card") or {}
    return {
        "domain": domain,
        "name": name,
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
        "claimed_at": row.get("claimed_at"),
        "heartbeat_minutes": None if age is None else round(age, 1),
        "worker_alive": alive,
        "empty_because": _why_empty(domain, catalog) if not live else None,
        # Runs in a row that ended needing a person, and the last reason.
        "attention_streak": meta.get("attention_streak") or 0,
        "attention_reason": meta.get("attention_reason"),
        # The top line of what recommend() ranked after the last run.
        "next_action": meta.get("next_action"),
        "next_priority": meta.get("next_priority"),
        "open_findings": meta.get("open_findings"),
        # The last scorecard's headline numbers, folded into fleet.json by the daemon.
        "gate": card.get("required_ok"),
        "fields_filled": card.get("fields_filled"),
        "seconds_per_product": card.get("seconds_per_product"),
        "cost_usd": card.get("cost_usd"),
        "scored_at": card.get("scored_at"),
    }


def register_dev_routes(app: Flask) -> None:
    def _build_overview() -> dict:
        store = _store()
        catalog = Catalog(store)
        finder_cap = float(os.environ.get("FINDER_DAILY_USD", "0") or 0)
        # The three reads that do not depend on each other, together.
        with ThreadPoolExecutor(max_workers=3) as pool:
            fleet_f = pool.submit(store.get, "fleet.json")
            rows_f = pool.submit(Scheduler(store).rows)
            finder_f = pool.submit(DailyCap(store, finder_cap).summary)
            found = fleet_f.result()
            rows = {r["domain"]: r for r in rows_f.result()}
            finder = finder_f.result()
        fleet = loads(found[0]) if found else {}
        # _brand_row asks the catalogue for state and plan only when a brand shows
        # nothing; hand it the fleet it already has so those reads are the exception.
        catalog._fleet = fleet
        names = _names()

        brands: list[dict] = []
        running: list[str] = []
        stalled: list[str] = []
        for domain in sorted(rows):
            b = _brand_row(
                domain, rows[domain], fleet.get(domain) or {}, names.get(domain, domain), catalog
            )
            brands.append(b)
            if b["claimed_by"]:
                (running if b["worker_alive"] else stalled).append(domain)

        return {
            "success": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "totals": {
                "brands": len(brands),
                "showing": sum(1 for b in brands if b["live_products"]),
                "live_products": sum(b["live_products"] for b in brands),
                "photographs": sum(b["photographs"] for b in brands),
                "need_a_human": sum(1 for b in brands if b["attention_streak"]),
                "failed_gate": sum(1 for b in brands if b["gate"] is False),
            },
            "workers": {"running": running, "stalled": stalled},
            "finder": finder,
            "brands": brands,
        }

    @app.route("/api/dev/overview", methods=["GET"])
    def dev_overview():
        if not _is_owner():
            return _forbidden()
        global _overview_cache
        with _overview_lock:
            cached = _overview_cache
        if cached and time.monotonic() - cached[0] < OVERVIEW_CACHE_SECONDS:
            return _reply(cached[1])
        payload = _build_overview()
        with _overview_lock:
            _overview_cache = (time.monotonic(), payload)
        return _reply(payload)

    @app.route("/api/dev/brands/<brand_id>", methods=["GET"])
    def dev_brand(brand_id):
        """Everything recorded about one brand, field by field.

        Reads the small objects — plan, schedule, scorecards, evidence, recipes,
        recommendations, the request ledger — and never the catalogue.
        """
        if not _is_owner():
            return _forbidden()
        if bad := _bad_domain(brand_id):
            return bad
        store = _store()
        catalog = Catalog(store)
        # Eight independent reads, together. In turn they were most of the page's
        # three seconds; the schedule row alone used to be read by listing every
        # brand's to find one.
        with ThreadPoolExecutor(max_workers=8) as pool:
            row_f = pool.submit(Scheduler(store).row, brand_id)
            brand_f = pool.submit(catalog.get_brand, brand_id)
            fleet_f = pool.submit(catalog.fleet)
            plan_f = pool.submit(catalog.load_plan, brand_id)
            cards_f = pool.submit(catalog.scorecards, brand_id, 20)
            runs_f = pool.submit(catalog.recent_runs, brand_id, 20)
            evidence_f = pool.submit(catalog.load_evidence, brand_id)
            book_f = pool.submit(catalog.load_recipe_book, brand_id)
            recs_f = pool.submit(catalog.load_recommendations, brand_id)
            row = row_f.result()
            known = brand_f.result()
            fleet = fleet_f.result()
            plan = plan_f.result()
            cards = cards_f.result()
            run_rows = runs_f.result()
            evidence = evidence_f.result()
            book = book_f.result()
            recommendations = recs_f.result()
        if row is None and known is None:
            return jsonify({"success": False, "error": "no such brand", "code": "NOT_FOUND"}), 404
        meta = fleet.get(brand_id) or {}
        summary = _brand_row(brand_id, row or {}, meta, _names().get(brand_id, brand_id), catalog)

        plan_out = None
        if plan is not None:
            plan_out = {
                "composition": plan.composition,
                "transport": plan.transport.value,
                "discovery": plan.discovery.value,
                "fetch": plan.fetch.value,
                "change_signal": plan.change_signal.value,
                "status": plan.status,
                "stale": plan.stale,
                "fingerprinted_at": plan.fingerprinted_at,
                "sitemap_url": plan.sitemap_url,
                "product_url_prefix": plan.product_url_prefix,
                "currency": plan.currency,
                "tried": [
                    {"composition": a.composition, "failed_at": a.failed_at, "reason": a.reason}
                    for a in plan.tried
                ],
            }

        # Every run, scored or not: a run that never reached the catalogue has no
        # scorecard but still says what happened, and that is the one worth reading.
        by_run = {c["run_id"]: c for c in cards}
        runs = [{**r, "card": by_run.get(r["id"])} for r in run_rows]
        latest_fill = (cards[0].get("field_fill") if cards else None) or {}
        rules: dict[str, list[dict]] = {}
        for r in book.recipes if book else []:
            rules.setdefault(r.field, []).append(
                {"kind": r.kind, "expression": r.expression, "hits": r.hits}
            )
        fields = [
            {
                "name": f,
                "class": FIELD_CLASS.get(f, "?"),
                "fill": latest_fill.get(f),
                "evidence": describe(evidence, f),
                "rules": rules.get(f, []),
            }
            for f in E0005_FIELDS
        ]

        return _reply(
            {
                "success": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "brand": summary,
                "plan": plan_out,
                "runs": runs,
                "fields": fields,
                "classes": CLASS_NOTES,
                "recipe_book": {
                    "learned_at": book.learned_at,
                    "learned_from_url": book.learned_from_url,
                    "rendered": book.rendered,
                    "rules": len(book.recipes),
                }
                if book
                else None,
                "recommendations": recommendations,
            }
        )

    @app.route("/api/dev/brands/<brand_id>/runs/<run_id>/log", methods=["GET"])
    def dev_run_log(brand_id, run_id):
        """What one run did, event by event, as it wrote it down at the time."""
        if not _is_owner():
            return _forbidden()
        if bad := _bad_domain(brand_id):
            return bad
        if not _RUN_ID.match(run_id):
            return jsonify({"success": False, "error": "not a run id", "code": "BAD_RUN"}), 400
        text = Catalog(_store()).load_run_log(brand_id, run_id)
        if text is None:
            return jsonify(
                {
                    "success": False,
                    "error": "no log kept for this run — runs before 2026-09-22 wrote "
                    "theirs to the worker's disk",
                    "code": "NOT_FOUND",
                }
            ), 404
        events = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                events.append({"event": "unparseable", "raw": line[:500]})
        return jsonify({"success": True, "domain": brand_id, "run_id": run_id, "events": events})

    @app.route("/api/dev/brands/<brand_id>/hosts", methods=["GET"])
    def dev_brand_hosts(brand_id):
        """How the brand's hosts have answered over the last week.

        Its own request because it reads the request ledger — one small object per
        batch, five hundred a week — and the brand page should not wait on it.
        """
        if not _is_owner():
            return _forbidden()
        if bad := _bad_domain(brand_id):
            return bad
        bare = brand_id.removeprefix("www.")
        hosts = [
            h
            for h in Catalog(_store()).host_stats(days=7)
            if h["host"].endswith(brand_id) or h["host"].endswith(bare)
        ]
        return jsonify({"success": True, "domain": brand_id, "days": 7, "hosts": hosts})

    @app.route("/api/dev/brands/<brand_id>/products", methods=["GET"])
    def dev_brand_products(brand_id):
        """A page of the catalogue. Its own request: this is the one read that is
        large, and it is released as soon as the page is cut."""
        if not _is_owner():
            return _forbidden()
        if bad := _bad_domain(brand_id):
            return bad
        try:
            offset = max(0, int(request.args.get("offset", 0)))
            limit = min(500, max(1, int(request.args.get("limit", 100))))
        except ValueError:
            return jsonify({"success": False, "error": "offset and limit are integers"}), 400
        q = (request.args.get("q") or "").strip().lower()
        catalog = Catalog(_store())
        rows = catalog.current_products(brand_id)
        catalog.release_products(brand_id)
        if q:
            rows = [r for r in rows if q in str(r.get("product_title") or "").lower()]
        keep = (
            "itemurl",
            "product_title",
            "product_code",
            "price",
            "full_price",
            "currency",
            "in_stock",
            "main_image_url",
            "size_info",
            "size_availability",
            "color_info",
            "category1",
            "category2",
            "brand",
        )
        page = []
        for r in rows[offset : offset + limit]:
            row = {k: r.get(k) for k in keep}
            # Every photograph, not the first: the gallery is what the archive is for.
            try:
                images = json.loads(r.get("all_images") or "[]")
            except ValueError:
                images = []
            row["images"] = [u for u in images if isinstance(u, str)][:24]
            page.append(row)
        return jsonify(
            {
                "success": True,
                "domain": brand_id,
                "total": len(rows),
                "offset": offset,
                "products": page,
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
        if bad := _bad_domain(brand_id):
            return bad
        catalog = Catalog(_store())
        stored = catalog.stored_image_count(brand_id)
        waiting = sum(len(urls) for _, urls in catalog.images_awaiting_archive(brand_id))
        catalog.release_products(brand_id)
        return jsonify({"success": True, "domain": brand_id, "stored": stored, "waiting": waiting})

    @app.route("/api/dev/brands/<brand_id>/run", methods=["POST"])
    def dev_brand_run(brand_id):
        """Bring the brand's next turn forward to now. A worker polls every ten
        seconds, so it starts within that. Refused while a worker holds it."""
        if not _is_owner():
            return _forbidden()
        if not _from_our_site():
            return _cross_site()
        if bad := _bad_domain(brand_id):
            return bad
        sched = Scheduler(_store())
        if not any(r["domain"] == brand_id for r in sched.rows()):
            return jsonify(
                {"success": False, "error": "not on the schedule", "code": "NOT_FOUND"}
            ), 404
        if not sched.run_now(brand_id):
            return jsonify(
                {"success": False, "error": "already being scraped", "code": "HELD"}
            ), 409
        _forget_overview()
        return jsonify({"success": True, "domain": brand_id})

    @app.route("/api/dev/brands/<brand_id>/pause", methods=["POST"])
    @app.route("/api/dev/brands/<brand_id>/resume", methods=["POST"])
    def dev_brand_enable(brand_id):
        if not _is_owner():
            return _forbidden()
        if not _from_our_site():
            return _cross_site()
        if bad := _bad_domain(brand_id):
            return bad
        sched = Scheduler(_store())
        if not any(r["domain"] == brand_id for r in sched.rows()):
            return jsonify(
                {"success": False, "error": "not on the schedule", "code": "NOT_FOUND"}
            ), 404
        enabled = request.path.endswith("/resume")
        sched.set_enabled(brand_id, enabled)
        _forget_overview()
        return jsonify({"success": True, "domain": brand_id, "enabled": enabled})

    @app.route("/api/dev/costs", methods=["GET"])
    def dev_costs():
        """What it costs: our own ledger first, the providers' own numbers after.

        The finder ledger and per-brand costs are ours and exact. The provider
        figures are theirs, each read separately and cached ten minutes, and a
        provider that cannot be reached says so in its own slot rather than
        taking the page down.
        """
        if not _is_owner():
            return _forbidden()
        store = _store()
        catalog = Catalog(store)
        names = _names()
        finder_cap = float(os.environ.get("FINDER_DAILY_USD", "0") or 0)
        brands = []
        for domain, meta in sorted(catalog.fleet().items()):
            card = meta.get("last_card") or {}
            if not card:
                continue
            brands.append(
                {
                    "domain": domain,
                    "name": names.get(domain, domain),
                    "products": card.get("products"),
                    "cost_usd": card.get("cost_usd"),
                    "seconds_per_product": card.get("seconds_per_product"),
                    "scored_at": card.get("scored_at"),
                }
            )
        # Three providers, three round trips to three continents: asked together,
        # the page waits for the slowest rather than the sum.
        with ThreadPoolExecutor(max_workers=4) as pool:
            finder_f = pool.submit(DailyCap(store, finder_cap).summary)
            anthropic_f = pool.submit(providers.anthropic_costs)
            cloudflare_f = pool.submit(providers.cloudflare_r2)
            render_f = pool.submit(providers.render_services)
            finder = finder_f.result()
            anthropic = anthropic_f.result()
            cloudflare = cloudflare_f.result()
            render = render_f.result()
        return _reply(
            {
                "success": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "finder": finder,
                "brands": brands,
                "providers": {"anthropic": anthropic, "cloudflare": cloudflare, "render": render},
            }
        )
