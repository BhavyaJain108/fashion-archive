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
from backend.archive import facets, roster, taxonomy
from backend.archive.audit import CLASSES
from backend.archive.domain.product import E0005_FIELDS
from backend.archive.evidence import describe
from backend.archive.roster import load_roster
from backend.archive.scheduler import Scheduler
from backend.archive.spend_cap import DailyCap
from backend.archive.store.catalog import Catalog
from backend.archive.store.factory import open_catalog
from backend.archive.store.objects import ObjectStore, loads, object_store

# A worker says it is alive every five minutes. Twice that and something is wrong: a
# claim nobody is working is the shape every dead worker has left behind.
HEARTBEAT_GRACE_MINUTES = 12
# After this the schedule itself lets another worker take the brand.
STALE_CLAIM_MINUTES = 15

# What Scheduler.run_now can answer, in the deck's words. The refusals carry a code
# the page can act on; a paused brand is not refused — it runs once and stays paused.
RUN_REFUSALS = {
    "held": ("already being scraped", "HELD"),
    "dead": ("its worker has stopped — release it first", "DEAD"),
}
RUN_WORDS = {
    "queued": "queued",
    "queued_once": "queued once (stays paused)",
    "held": "already being scraped",
    "dead": "worker dead — release first",
    "unknown": "not on the schedule",
}

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


# --- last actions --------------------------------------------------------------------
# A run's event log, told as sentences. The log is exact and terse; this is the same
# facts in the order they happened, in words, so the top of a brand page reads as
# "what happened last time" rather than a list of event names.

_TRANSPORT_WORDS = {
    "t0": "plain HTTP",
    "t1": "a browser's handshake, no browser",
    "t2": "a real browser",
    "t4": "nothing — the shop is password-gated",
}


def _narrate(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    fetch_errors = 0
    imaged = 0
    skipped = 0
    started = None
    for e in events:
        kind = e.get("event")
        at = e.get("t")
        if started is None and at:
            started = at

        def say(text: str, when: str | None = at) -> None:
            out.append({"at": when, "text": text})

        if kind == "planned":
            comp = e.get("composition") or ""
            t = comp.split("×")[0] if comp else ""
            way = _TRANSPORT_WORDS.get(t, t)
            if e.get("status") == "ready":
                say(f"Decided how to get in: {comp} — reading over {way}")
            elif e.get("status") == "skip_gated":
                say("Probed the shop: it is behind a password, so nothing was read")
            else:
                say("Probed the shop and found no way to read it at any transport")
        elif kind == "transport":
            say(f"Connecting over {_TRANSPORT_WORDS.get(e.get('level'), e.get('level'))}")
        elif kind == "relearned-through-browser":
            say(f"The browser found where products live: {e.get('prefix')}")
        elif kind == "discovered":
            say(f"Found {e.get('refs', 0):,} product links")
        elif kind == "capped":
            say(
                f"Kept the first {e.get('kept', 0):,} of {e.get('found', 0):,} (a cap for this run)"
            )
        elif kind == "selected":
            total, to_fetch = e.get("total", 0), e.get("to_fetch", 0)
            if e.get("mode") == "full" or to_fetch == total:
                say(f"Reading all {total:,} products")
            else:
                say(f"{to_fetch:,} of {total:,} products looked new or changed; reading those")
        elif kind == "calibrated":
            say(f"Checked a first sample of {e.get('sample')} products — every one had a title")
        elif kind == "extraction-changed":
            say("Our own extractor changed since the last run, so everything is read again")
        elif kind == "already-searched":
            skipped = len(e.get("fields") or [])
        elif kind == "recipes-need-rendering":
            say("The learned rules need a browser and none was available; skipped them")
        elif kind == "escalated-to-rendered":
            say("Switched to a browser because the learned rules need a rendered page")
        elif kind == "finder-added":
            fields = ", ".join(e.get("fields") or [])
            say(f"Learned a rule for {fields} from one product page")
        elif kind == "finder-retry-rendered":
            say("A page yielded nothing static; trying it rendered in a browser")
        elif kind == "finder-failed":
            say(f"A finder call failed: {str(e.get('error', ''))[:120]}")
        elif kind == "finder-unauthorised":
            say("The Anthropic key was refused — the finder stopped for this run")
        elif kind == "finder-budget-spent":
            say(f"The finder's daily allowance was spent ({e.get('detail', '')}); stopped asking")
        elif kind == "learn-budget-spent":
            say(f"Asked the model about {e.get('budget')} pages, this run's limit")
        elif kind == "finder-unavailable":
            say(f"The finder could not run at all this time ({e.get('attempts')} attempts)")
        elif kind == "fetch-error":
            fetch_errors += 1
        elif kind == "skip-product":
            pass
        elif kind == "images-archived":
            imaged += 1
        elif kind == "brand-field-repaired":
            say(
                f"Repaired the brand field on {e.get('applied_to', 0):,} products ({e.get('reason')})"
            )
        elif kind == "time-budget-spent":
            say(f"Ran out of time with {e.get('unreached', 0):,} products unread")
        elif kind == "channel-busy":
            say("The shop asked us to slow down; standing down for half an hour")
        elif kind == "plan-failed":
            say(f"The plan {e.get('composition')} failed: {e.get('reason')}")
        elif kind == "needs-attention":
            say("No plan works for this shop right now — a person needs to look")
        elif kind == "skipped-gated":
            say("The shop is password-gated; nothing to read until it opens")
        elif kind == "evidence-recorded":
            pass
        elif kind == "finalized":
            v = e.get("verdict")
            word = {
                "ok": "went well",
                "degraded": "went well enough, with reservations",
                "failed": "failed",
            }.get(v, v)
            say(
                f"Finished — the run {word}: {e.get('extracted', 0):,} products stored, {e.get('errors', 0)} errors"
            )
        elif kind == "run-crashed":
            say(f"The run crashed: {str(e.get('error', ''))[:120]}")
    if skipped:
        out.insert(
            min(2, len(out)),
            {
                "at": started,
                "text": f"Skipped {skipped} fields asked about within the last 14 days",
            },
        )
    if fetch_errors:
        out.append({"at": None, "text": f"{fetch_errors:,} product pages failed to load"})
    if imaged:
        out.append({"at": None, "text": f"Archived photographs for {imaged:,} products"})
    return out


def _names() -> dict[str, str]:
    # Every brand the archive follows, not only the ones the app shows: the deck
    # lists large houses too, and they have names.
    return {e.domain: e.name for e in load_roster(store=_store())}


# --- notes ------------------------------------------------------------------------
# What the owner wants changed, written where it was noticed. One object, a list of
# short notes with a done flag; the CLI's `notes` prints the open ones so whoever
# works on the deck next — a person or an agent — starts from the same list.
NOTES_KEY = "control/notes.json"
NOTE_MAX = 2000


def _notes(store):
    found = store.get(NOTES_KEY)
    held = loads(found[0]) if found else {"notes": []}
    return held, (found[1] if found else None)


def _save_notes(store, held, etag):
    from backend.archive.store.objects import dumps

    store.put(NOTES_KEY, dumps(held), if_match=etag)


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
        # Paused, but the owner asked for one run: it goes on the next poll.
        "run_once": bool(row.get("run_once")),
        # "learn" when the next claim is a finder-only run.
        "next_mode": row.get("next_mode") or None,
        "cadence_seconds": row.get("cadence_seconds"),
        "claimed_by": claimed,
        "claimed_at": row.get("claimed_at"),
        # When the run began; claimed_at moves with every heartbeat.
        "claimed_since": row.get("claimed_since") or row.get("claimed_at"),
        "heartbeat_minutes": None if age is None else round(age, 1),
        "worker_alive": alive,
        "empty_because": _why_empty(domain, catalog) if not live else None,
        # Runs in a row that ended needing a person, and the last reason.
        "attention_streak": meta.get("attention_streak") or 0,
        "attention_reason": meta.get("attention_reason"),
        # The top line of what recommend() ranked after the last run.
        "next_action": meta.get("next_action"),
        "next_priority": meta.get("next_priority"),
        "next_at": meta.get("next_at"),
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
        catalog = open_catalog(store)
        finder_cap = float(os.environ.get("FINDER_DAILY_USD", "0") or 0)
        # The three reads that do not depend on each other, together.
        with ThreadPoolExecutor(max_workers=3) as pool:
            fleet_f = pool.submit(store.get, "fleet.json")
            rows_f = pool.submit(Scheduler(store).rows)
            workers_f = pool.submit(Scheduler(store).workers_seen)
            finder_f = pool.submit(DailyCap(store, finder_cap).summary)
            found = fleet_f.result()
            rows = {r["domain"]: r for r in rows_f.result()}
            finder = finder_f.result()
            try:
                workers_seen = workers_f.result()
            except Exception:  # noqa: BLE001 — liveness is a bonus, never a blocker
                workers_seen = {}
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

        # Where each running scrape is. Only the held brands, read together — a
        # small object each, rewritten by the worker every twenty seconds.
        held = [b for b in brands if b["claimed_by"]]
        if held:
            with ThreadPoolExecutor(max_workers=min(8, len(held))) as pool:
                found_progress = list(pool.map(lambda b: catalog.load_progress(b["domain"]), held))
            for b, p in zip(held, found_progress, strict=True):
                # A progress object older than the claim belongs to an earlier run.
                if p and (p.get("updated_at") or "") >= (b.get("claimed_since") or ""):
                    b["progress"] = {
                        "phase": p.get("phase"),
                        "done": p.get("done"),
                        "total": p.get("total"),
                        "updated_at": p.get("updated_at"),
                    }

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
            "workers": {"running": running, "stalled": stalled, "seen": workers_seen},
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
        catalog = open_catalog(store)
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
        if summary["claimed_by"]:
            p = catalog.load_progress(brand_id)
            if p and (p.get("updated_at") or "") >= (summary.get("claimed_since") or ""):
                summary["progress"] = {
                    "phase": p.get("phase"),
                    "done": p.get("done"),
                    "total": p.get("total"),
                    "updated_at": p.get("updated_at"),
                }

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
        # A run row still open from before the current claim (or with no claim at all)
        # belongs to a worker that is gone; the row itself is closed by the next run.
        since = summary.get("claimed_since") or ""
        for r in runs:
            if r.get("exit_status") is None and (
                not summary["claimed_by"] or r["started_at"] < since
            ):
                r["abandoned"] = (
                    r.get("abandoned") or "the worker was replaced before this run finished"
                )
        latest_fill = (cards[0].get("field_fill") if cards else None) or {}

        # What happened last time, in words: the newest run that left a log.
        last_actions = None
        for r in runs[:3]:
            text = catalog.load_run_log(brand_id, r["id"])
            if not text:
                continue
            events = []
            for line in text.splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
            last_actions = {
                "run_id": r["id"],
                "started_at": r.get("started_at"),
                "finished_at": r.get("finished_at"),
                "mode": r.get("mode"),
                "lines": _narrate(events),
            }
            break
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
                "last_actions": last_actions,
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
        text = open_catalog(_store()).load_run_log(brand_id, run_id)
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
            for h in open_catalog(_store()).host_stats(days=7)
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
        # live: on the site now. gone: was on the site and is not any more. all: both.
        # With `run`, the same three as of that run, plus added: first seen in it.
        status = request.args.get("status", "live")
        # A run id carries "+00:00"; a client that did not encode the plus sends a space.
        run = (request.args.get("run") or "").strip().replace(" ", "+") or None
        if status not in ("live", "gone", "all", "added") or (status == "added" and not run):
            return jsonify({"success": False, "error": "status is live, gone, all or added"}), 400
        if run and not _RUN_ID.match(run):
            return jsonify({"success": False, "error": "not a run id", "code": "BAD_RUN"}), 400
        catalog = open_catalog(_store())
        history = catalog.product_history(brand_id)
        if run:
            rows = catalog.products_at_run(brand_id, run, status)
        else:
            rows = catalog.current_products(brand_id, live_only=(status == "live"))
            if status == "gone":
                rows = [r for r in rows if not history.get(r.get("itemurl"), {}).get("live")]
        catalog.release_products(brand_id)
        # The runs a reader may pick from, newest first: id, when, mode.
        runs = [
            {"id": r["id"], "at": r["id"].rsplit("-", 1)[0], "mode": r.get("mode")}
            for r in catalog.recent_runs(brand_id, 40)
            if r.get("exit_status") in (0, 1) and r.get("coverage") is not None
        ]
        if q:
            rows = [r for r in rows if q in str(r.get("product_title") or "").lower()]
        # What each product answers to in the archive's shared vocabulary, so the `type`
        # chip filters by the one facet that means the same on every brand. Applied on
        # the way out, never stored: the book is the source, and editing it re-answers
        # every brand at once.
        rows = taxonomy.typed(rows, taxonomy.load(_store()))
        # The brand's own facets — colours, sizes, materials, categories, tags, stock,
        # sale, price — read off the products and applied the way a shop's page does:
        # any of a facet's chosen values, all of the chosen facets. ?colour=Black&size=M
        selected = {
            f: {v.strip() for v in request.args.getlist(f) if v.strip()}
            for f in facets.FACETS
            if request.args.getlist(f)
        }
        sized_in_stock = request.args.get("sized_in_stock") in ("1", "true")
        try:
            price_min = float(request.args["price_min"]) if request.args.get("price_min") else None
            price_max = float(request.args["price_max"]) if request.args.get("price_max") else None
        except ValueError:
            return jsonify({"success": False, "error": "price bounds are numbers"}), 400
        # Counts before the price cut, so the chips still say what each would leave.
        facet_counts = facets.counts(rows, selected, sized_in_stock)
        prices = facets.price_range(rows)
        rows = facets.apply(rows, selected, sized_in_stock)
        rows = facets.within_price(rows, price_min, price_max)
        # Most recently scraped first, so a fresh run's products lead.
        rows.sort(
            key=lambda r: history.get(r.get("itemurl"), {}).get("last_seen") or "", reverse=True
        )
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
            "material_info",
            "category1",
            "category2",
            taxonomy.TYPE_FIELD,
            "additional_tags",
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
            row.update(history.get(r.get("itemurl"), {}))
            page.append(row)
        return jsonify(
            {
                "success": True,
                "domain": brand_id,
                "total": len(rows),
                "offset": offset,
                "run": run,
                "status": status,
                "runs": runs,
                "facets": facet_counts,
                # How much of this brand the shared vocabulary can place. The gap is
                # the work left: words nobody has taught it, or products whose title
                # never says what they are.
                "typed": sum(1 for r in rows if r.get(taxonomy.TYPE_FIELD)),
                "selected": {f: sorted(v) for f, v in selected.items()},
                "sized_in_stock": sized_in_stock,
                "price_range": prices,
                "price_min": price_min,
                "price_max": price_max,
                "products": page,
            }
        )

    @app.route("/api/dev/brands/<brand_id>/changes", methods=["GET"])
    def dev_brand_changes(brand_id):
        """What each run added and removed, newest first. Reads the catalogue, so it
        is its own request and lets the catalogue go as soon as it has counted."""
        if not _is_owner():
            return _forbidden()
        if bad := _bad_domain(brand_id):
            return bad
        catalog = open_catalog(_store())
        changes = catalog.catalogue_changes(brand_id)
        catalog.release_products(brand_id)
        return jsonify({"success": True, "domain": brand_id, "changes": changes})

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
        catalog = open_catalog(_store())
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
        # The deck's idea of a dead worker (no beat for twelve minutes) is the one
        # the answer must agree with, so the schedule is asked with that limit.
        sched = Scheduler(_store(), stale_claim_seconds=HEARTBEAT_GRACE_MINUTES * 60)
        outcome = sched.run_now(brand_id)
        if outcome == "unknown":
            return jsonify(
                {"success": False, "error": "not on the schedule", "code": "NOT_FOUND"}
            ), 404
        if outcome in RUN_REFUSALS:
            error, code = RUN_REFUSALS[outcome]
            return jsonify({"success": False, "error": error, "code": code}), 409
        _forget_overview()
        return jsonify({"success": True, "domain": brand_id, "outcome": outcome})

    @app.route("/api/dev/brands/<brand_id>/learn", methods=["POST"])
    def dev_brand_learn(brand_id):
        """Queue a learn run: the finder reads a spread of product pages and writes
        rules; nothing goes to the catalogue and the brand's scheduled turn is kept.
        Body: {"retry_searched": bool} to ask again about fields already searched."""
        if not _is_owner():
            return _forbidden()
        if not _from_our_site():
            return _cross_site()
        if bad := _bad_domain(brand_id):
            return bad
        body = request.get_json(silent=True) or {}
        sched = Scheduler(_store(), stale_claim_seconds=HEARTBEAT_GRACE_MINUTES * 60)
        outcome = sched.learn_now(brand_id, retry_searched=bool(body.get("retry_searched")))
        if outcome == "unknown":
            return jsonify(
                {"success": False, "error": "not on the schedule", "code": "NOT_FOUND"}
            ), 404
        if outcome in RUN_REFUSALS:
            error, code = RUN_REFUSALS[outcome]
            return jsonify({"success": False, "error": error, "code": code}), 409
        _forget_overview()
        return jsonify({"success": True, "domain": brand_id, "outcome": outcome, "mode": "learn"})

    @app.route("/api/dev/brands/<brand_id>/release", methods=["POST"])
    def dev_brand_release(brand_id):
        """Take a dead worker's claim off the brand now rather than in fifteen
        minutes. Refused while the claim's heartbeat is still fresh — that worker is
        alive, and two hands on one catalogue is the thing the claim exists to
        prevent."""
        if not _is_owner():
            return _forbidden()
        if not _from_our_site():
            return _cross_site()
        if bad := _bad_domain(brand_id):
            return bad
        sched = Scheduler(_store())
        row = sched.row(brand_id)
        if row is None:
            return jsonify(
                {"success": False, "error": "not on the schedule", "code": "NOT_FOUND"}
            ), 404
        if row.get("claimed_by") is None:
            return jsonify({"success": True, "domain": brand_id, "released": False})
        age = _minutes_since(row.get("claimed_at"))
        if age is not None and age <= HEARTBEAT_GRACE_MINUTES:
            return jsonify(
                {"success": False, "error": "that worker is still alive", "code": "ALIVE"}
            ), 409
        sched.force_release(brand_id)
        _forget_overview()
        return jsonify({"success": True, "domain": brand_id, "released": True})

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
        row = sched.row(brand_id)
        if row is None:
            return jsonify(
                {"success": False, "error": "not on the schedule", "code": "NOT_FOUND"}
            ), 404
        enabled = request.path.endswith("/resume")
        sched.set_enabled(brand_id, enabled)
        _forget_overview()
        # A worker holding the brand finishes its run; the pause holds after that.
        return jsonify(
            {
                "success": True,
                "domain": brand_id,
                "enabled": enabled,
                "after_run": row.get("claimed_by") is not None,
            }
        )

    @app.route("/api/dev/brands", methods=["POST"])
    def dev_brand_add():
        """Add a brand from the deck: {"domain", "display_name"?, "show": bool}.

        Three writes, the same three the CLI's `brands add` makes plus the roster:
        the roster addition (so the app knows its name and whether to show it), the
        brand row, and the schedule row — due at once, so a worker picks it up
        within its next poll.
        """
        if not _is_owner():
            return _forbidden()
        if not _from_our_site():
            return _cross_site()
        body = request.get_json(silent=True) or {}
        domain = str(body.get("domain") or "").strip().lower()
        domain = re.sub(r"^https?://", "", domain).split("/")[0]
        if not _DOMAIN.match(domain):
            return jsonify({"success": False, "error": "not a domain", "code": "BAD_DOMAIN"}), 400
        display_name = str(body.get("display_name") or "").strip()[:80] or None
        size = "small" if body.get("show", True) else "large"
        store = _store()
        try:
            entry = roster.add_entry(store, domain, display_name=display_name, size=size)
        except Exception as e:  # noqa: BLE001 — a conflict on the roster object, retry once
            entry = roster.add_entry(store, domain, display_name=display_name, size=size)
            current_app.logger.warning("roster add retried: %s", e)
        from backend.archive.domain.brand import Brand

        catalog = open_catalog(store)
        catalog.upsert_brand(
            catalog.get_brand(domain)
            or Brand(domain=domain, homepage_url=entry.homepage_url, display_name=display_name)
        )
        sched = Scheduler(store)
        already = any(r["domain"] == domain for r in sched.rows())
        sched.add(domain)
        _forget_overview()
        return jsonify(
            {
                "success": True,
                "domain": domain,
                "name": entry.name,
                "shown": size == "small",
                "already_scheduled": already,
            }
        )

    @app.route("/api/dev/notes", methods=["GET"])
    def dev_notes():
        if not _is_owner():
            return _forbidden()
        held, _ = _notes(_store())
        return jsonify({"success": True, "notes": held.get("notes", [])})

    @app.route("/api/dev/notes", methods=["POST"])
    def dev_note_add():
        if not _is_owner():
            return _forbidden()
        if not _from_our_site():
            return _cross_site()
        text = str((request.get_json(silent=True) or {}).get("text") or "").strip()
        if not text:
            return jsonify({"success": False, "error": "an empty note", "code": "EMPTY"}), 400
        store = _store()
        held, etag = _notes(store)
        note = {
            "id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"),
            "text": text[:NOTE_MAX],
            "at": datetime.now(timezone.utc).isoformat(),
            "done": False,
        }
        held.setdefault("notes", []).append(note)
        _save_notes(store, held, etag)
        return jsonify({"success": True, "note": note})

    @app.route("/api/dev/notes/<note_id>", methods=["POST"])
    def dev_note_edit(note_id):
        """{"done": bool} to tick or untick; {"delete": true} to remove."""
        if not _is_owner():
            return _forbidden()
        if not _from_our_site():
            return _cross_site()
        if not re.fullmatch(r"[0-9T]{1,32}", note_id):
            return jsonify({"success": False, "error": "not a note id", "code": "BAD_ID"}), 400
        body = request.get_json(silent=True) or {}
        store = _store()
        held, etag = _notes(store)
        notes = held.get("notes", [])
        note = next((x for x in notes if x.get("id") == note_id), None)
        if note is None:
            return jsonify({"success": False, "error": "no such note", "code": "NOT_FOUND"}), 404
        if body.get("delete"):
            held["notes"] = [x for x in notes if x.get("id") != note_id]
        else:
            note["done"] = bool(body.get("done"))
            if note["done"]:
                note["done_at"] = datetime.now(timezone.utc).isoformat()
            else:
                note.pop("done_at", None)
        _save_notes(store, held, etag)
        return jsonify({"success": True, "notes": held["notes"]})

    @app.route("/api/dev/batch", methods=["POST"])
    def dev_batch():
        """One command over several brands: {"action": "run"|"pause"|"resume",
        "domains": [...]}. Each brand is answered on its own — a held brand does
        not stop the others — and the reply says what happened to every one."""
        if not _is_owner():
            return _forbidden()
        if not _from_our_site():
            return _cross_site()
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        domains = body.get("domains")
        if action not in ("run", "pause", "resume") or not isinstance(domains, list):
            return jsonify(
                {"success": False, "error": "action and domains required", "code": "BAD_REQUEST"}
            ), 400
        if len(domains) > 200:
            return jsonify({"success": False, "error": "too many brands", "code": "TOO_MANY"}), 400
        sched = Scheduler(_store(), stale_claim_seconds=HEARTBEAT_GRACE_MINUTES * 60)
        known = {r["domain"] for r in sched.rows()}
        results = {}
        for domain in domains:
            if not isinstance(domain, str) or not _DOMAIN.match(domain):
                results[str(domain)] = "not a domain"
            elif domain not in known:
                results[domain] = "not on the schedule"
            elif action == "run":
                results[domain] = RUN_WORDS[sched.run_now(domain)]
            else:
                sched.set_enabled(domain, action == "resume")
                results[domain] = "paused" if action == "pause" else "resumed"
        _forget_overview()
        return jsonify({"success": True, "action": action, "results": results})

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
        catalog = open_catalog(store)
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
