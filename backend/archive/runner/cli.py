"""archive CLI: plan | scrape | status (spec §4.6). Run as python -m backend.archive.runner.cli."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

import yaml

from backend.archive.budget import HostBudget
from backend.archive.capability import format_matrix, probe_brand
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import E0005_FIELDS, ProductRecord
from backend.archive.escalate import escalating_prober
from backend.archive.fingerprint import probe
from backend.archive.images import ImageStore
from backend.archive.observe import RequestLog, Spend
from backend.archive.planner import compose_plan
from backend.archive.runner.run import run_brand
from backend.archive.score import score
from backend.archive.store.catalog import Catalog
from backend.archive.store.factory import open_catalog
from backend.archive.store.objects import ObjectStore, R2ObjectStore, object_store
from backend.archive.transport import HttpxTransport, Transport, for_level

_DEFAULT_BRANDS = Path(__file__).parent.parent / "brands.yml"
# Where objects go when neither --objects nor R2 says otherwise; object_store() owns
# the choice, so there is nothing to decide here.


def load_brands(path: Path) -> list[Brand]:
    data = yaml.safe_load(path.read_text())
    return [Brand(**b) for b in data.get("brands", [])]


def image_sink(images_dir: Path):
    """Where archived photographs go: the bucket when it is configured, a directory when
    it is not. The same two implementations the rest of the app already chooses between,
    so there is one answer to "where are the images" and not two."""
    from backend.storage.images import LocalImageStore, R2ImageStore
    from config.config import config

    if (
        config.R2_ACCOUNT_ID
        and config.R2_ACCESS_KEY_ID
        and config.R2_SECRET_ACCESS_KEY
        and config.R2_BUCKET
    ):
        return R2ImageStore(
            account_id=config.R2_ACCOUNT_ID,
            access_key_id=config.R2_ACCESS_KEY_ID,
            secret_access_key=config.R2_SECRET_ACCESS_KEY,
            bucket=config.R2_BUCKET,
            public_base=config.R2_PUBLIC_BASE,
        )
    return LocalImageStore(root=images_dir, api_base=config.API_BASE_URL)


def _fleet_check(args, catalog: Catalog, brands: list[Brand]) -> int:
    """Every brand, live and from the record, in one table: can we get in today, what
    the last run scored, how many runs in a row needed a person, and what to fix first.

    The live half is `capability` — probe, plan, fetch a few products, measure — and it
    writes nothing. The recorded half is what the daemon left in the bucket. Reading
    them side by side is the point: a brand can probe green today and have failed its
    gate three runs running.
    """
    if args.shown:
        from backend.archive.roster import app_roster

        wanted = {e.domain for e in app_roster(args.brands)}
        targets = [b for b in brands if b.domain in wanted]
    elif args.all:
        targets = brands
    else:
        targets = [b for b in brands if b.domain == args.domain]
    if not targets:
        print("say which brands: a domain, or --shown, or --all", file=sys.stderr)
        return 2

    def _browser():
        from backend.archive.browser.challenge import ChallengeAwareBrowser

        return ChallengeAwareBrowser()

    rows: list[dict[str, Any]] = []
    for b in targets:
        t: Transport = HttpxTransport()
        try:
            rep = probe_brand(
                b,
                t,
                sample=args.sample,
                browser=args.browser,
                prober=escalating_prober(browser_factory=_browser if args.browser else None),
            )
        finally:
            if hasattr(t, "close"):
                t.close()
        cards = catalog.scorecards(b.domain, limit=1)
        card = cards[0] if cards else None
        streak, reason = catalog.attention(b.domain)
        rec = catalog.load_recommendations(b.domain)
        top = (rec or {}).get("findings") or []
        rows.append(
            {
                "domain": b.domain,
                "live": rep.verdict,
                "lane": rep.lane,
                "cat": rep.catalog_size,
                "core": rep.core_fill(),
                "last": (card or {}).get("required_ok"),
                "fields": (card or {}).get("fields_filled"),
                "spp": (card or {}).get("seconds_per_product"),
                "usd": (card or {}).get("cost_usd"),
                "streak": streak,
                "reason": reason or "",
                "next": top[0]["headline"] if top else "",
                "note": rep.note,
            }
        )
        print(f"  checked {b.domain:<26} {rep.verdict:<9} {rep.note[:50]}", flush=True)

    order = {"full": 0, "partial": 1, "poor": 2, "blocked": 3, "gated": 4, "unreachable": 5}
    rows.sort(key=lambda r: (-(r["streak"] or 0), order.get(r["live"], 9), r["domain"]))
    head = (
        f"{'BRAND':<26}{'LIVE':<9}{'LANE':<30}{'CAT':>6}{'CORE':>6}  "
        f"{'GATE':<5}{'FIELDS':>7}{'S/PROD':>7}{'$RUN':>6}{'HUMAN':>6}  NEXT"
    )
    print()
    print(head)
    print("-" * len(head))
    for r in rows:
        gate = "—" if r["last"] is None else ("pass" if r["last"] else "FAIL")
        fields = "—" if r["fields"] is None else f"{r['fields']:.0%}"
        spp = "—" if r["spp"] is None else f"{r['spp']:.1f}"
        usd = "—" if r["usd"] is None else f"{r['usd']:.2f}"
        cat = "—" if r["cat"] is None else str(r["cat"])
        human = f"{r['streak']}×" if r["streak"] else ""
        nxt = r["next"] or (r["reason"] if r["streak"] else r["note"])
        print(
            f"{r['domain']:<26}{r['live']:<9}{r['lane'][:29]:<30}{cat:>6}{r['core']:>6.0%}  "
            f"{gate:<5}{fields:>7}{spp:>7}{usd:>6}{human:>6}  {nxt[:60]}"
        )
    needing = [r for r in rows if r["streak"]]
    failing = [r for r in rows if r["last"] is False]
    print()
    print(
        f"{len(rows)} brands: {sum(1 for r in rows if r['live'] in ('full', 'partial'))} "
        f"readable now, {len(failing)} failed their last gate, "
        f"{len(needing)} need a human"
    )
    return 0


# What a run's recorded reason looks like when our own code broke, as against the
# site refusing us, a password wall or a host asking us to wait.
_CODE_FAULT = (
    "object has no attribute",
    "Error:",
    "Error ",
    "Exception",
    "KeyError",
    "TypeError",
    "ValueError",
    "IndexError",
    "AttributeError",
    "NoneType",
    "crashed:",
)


def _failures(args, catalog: Catalog, brands: list[Brand]) -> int:
    """Runs from the last N hours that ended on our own code, with the line from the
    log that says so. What a bug-fixer reads first; `--all` shows every failed run."""
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()
    found = 0
    for b in brands:
        for run in catalog.recent_runs(b.domain, limit=10):
            if (run.get("started_at") or "") < since or run.get("exit_status") in (None, 0):
                continue
            reason = str(run.get("reason") or "")
            ours = any(m in reason for m in _CODE_FAULT)
            if not ours and not args.all:
                continue
            found += 1
            print(
                f"{b.domain}  run {run['id']}  exit {run['exit_status']}  {'CODE' if ours else 'site'}"
            )
            print(f"    {reason[:300] or '(no reason recorded)'}")
            text = catalog.load_run_log(b.domain, run["id"]) or ""
            for line in text.splitlines():
                if any(k in line for k in ('"plan-failed"', '"run-crashed"', '"fetch-error"')):
                    print(f"    {line[:300]}")
                    break
    print(
        f"\n{found} failed run(s) in the last {args.hours}h"
        + ("" if args.all else " on our own code")
    )
    return 0


def _periods(args, catalog: Catalog, brands: list[Brand]) -> int:
    """`periods migrate <domain>|--all` replays observations into the per-field
    timeline; `periods show <domain> <itemurl>` prints one product's."""
    if args.action == "migrate":
        domains = [b.domain for b in brands] if args.all else [args.domain] if args.domain else []
        if not domains:
            print("periods migrate: give a domain or --all", file=sys.stderr)
            return 2
        for domain in domains:
            r = catalog.migrate_periods(domain)
            print(f"{domain:32s} observations {r['observations']:>7}  periods {r['periods']:>7}")
        return 0
    if not args.domain or not args.itemurl:
        print("periods show: give a domain and an itemurl", file=sys.stderr)
        return 2
    row = catalog.product_history(args.domain, args.itemurl).get(args.itemurl)
    if row is None:
        print(f"{args.itemurl}: not in {args.domain}", file=sys.stderr)
        return 1
    print(
        f"{args.itemurl}\n  first seen {row['first_seen']}  last seen {row['last_seen']}  "
        f"{'live' if row['live'] else 'gone'}"
    )
    for field, held in row["periods"].items():
        print(f"  {field}")
        for p in held:
            print(f"    {p['from']}  →  {p['to']}   {p['value']}")
    return 0


def _seed(catalog: Catalog, brands_path: Path) -> list[Brand]:
    brands = load_brands(brands_path)
    for b in brands:
        catalog.upsert_brand(b)
    return brands


def _held(store: ObjectStore) -> set[str] | None:
    """Brands our own worker is scraping right now, or None when we cannot tell."""
    from backend.archive.scheduler import Scheduler

    try:
        return Scheduler(store).held_domains()
    except Exception:  # noqa: BLE001 — not knowing is a valid answer, failing here is not
        return None


def _products_over_winners(results) -> None:
    """Getting in is only half of it. Hand each brand's winning transport to the pipeline
    we already have and see whether products come out the other end."""
    from backend.archive.access.bench import winners
    from backend.archive.access.strategy import get as get_strategy

    reports = []
    for domain, won in winners(results).items():
        transport = get_strategy(won.strategy).build()
        try:
            rep = probe_brand(
                Brand(domain=domain, homepage_url=f"https://{domain}"),
                transport,
            )
        finally:
            if hasattr(transport, "close"):
                transport.close()
        rep.note = f"[{won.strategy}] {rep.note}"
        reports.append(rep)
        print(f"  products {domain:<26} {rep.verdict}", flush=True)
    if reports:
        print()
        print(format_matrix(reports, show_gated=True))


def _coverage(args, brands: list[Brand]) -> int:
    """S7 — how much of E0005 each brand actually gives up. The loop starts here."""
    from backend.archive.coverage import field_coverage, format_coverage
    from backend.archive.domain.product import E0005_FIELDS
    from backend.archive.roster import app_roster

    if args.domain:
        targets = [Brand(domain=d, homepage_url=f"https://{d}") for d in args.domain]
    elif args.shown:
        wanted = {e.domain for e in app_roster(args.brands)}
        targets = [b for b in brands if b.domain in wanted]
    elif args.all:
        targets = brands
    else:
        print("say which brands: a domain, or --shown, or --all", file=sys.stderr)
        return 2

    def browser():
        from backend.archive.browser.challenge import ChallengeAwareBrowser

        return ChallengeAwareBrowser()

    prober = escalating_prober(browser_factory=browser if args.browser else None)
    rows = {}
    for b in targets:
        transport = HttpxTransport()
        try:
            rows[b.domain] = field_coverage(b, transport, sample=args.sample, prober=prober)
        finally:
            transport.close() if hasattr(transport, "close") else None
        fill, size, note = rows[b.domain]
        print(
            f"  {b.domain:<28} {sum(1 for v in fill.values() if v > 0):>2}"
            f"/{len(E0005_FIELDS)} fields"
            f"  {size:>6} products  {note}",
            flush=True,
        )
    print()
    print(format_coverage(rows))
    return 0


def _access(args, store: ObjectStore, brands: list[Brand]) -> int:
    """Measure what it costs to get into each brand, and write the answer down."""
    from datetime import datetime, timezone

    from backend.archive.access import store as access_store
    from backend.archive.access.bench import sweep
    from backend.archive.access.report import format_matrix, format_plan
    from backend.archive.access.strategy import all_strategies, select
    from backend.archive.access.targets import failing_domains
    from backend.archive.roster import load_roster

    if args.domain:
        domains = list(args.domain)
    elif args.only_failing:
        domains = failing_domains(load_roster(args.brands))
    elif args.all:
        domains = [b.domain for b in brands]
    else:
        print("say which brands: a domain, or --only-failing, or --all", file=sys.stderr)
        return 2
    if not domains:
        print("no brands matched")
        return 0

    strategies = select(args.strategies) if args.strategies else all_strategies()
    missing = [s.name for s in strategies if not s.available]
    strategies = [s for s in strategies if s.available]
    if missing:
        print(f"skipping (library not installed): {', '.join(missing)}\n")
    if not strategies:
        print("no strategies available to try", file=sys.stderr)
        return 2

    if args.dry_run:
        print(format_plan(domains, strategies))
        return 0

    # Our own worker hits these hosts continuously, and a 429 or 403 is the one answer
    # our traffic can manufacture. Snapshot the claims either side of the sweep: a brand
    # held at either end was plausibly being scraped while we measured it. Two list calls
    # rather than one per cell, which on R2 is the difference that matters.
    held_before = _held(store)

    # Short stand-downs on purpose. The daemon waits 15 minutes after a 403 because
    # sustained retrying turns a temporary block permanent; a sweep asks four questions
    # with a different fingerprint and then leaves, which is the thing we are here to
    # measure. A Retry-After the host actually sends is still obeyed in full.
    budget = HostBudget(gap=args.gap, busy_backoff=args.gap * 4, refused_backoff=args.gap * 4)

    def line(r) -> None:
        print(
            f"  {r.domain:<28} {r.strategy:<16} {r.outcome.value:<12} {r.seconds:5.2f}s",
            flush=True,
        )

    results = sweep(domains, strategies, on_result=line, budget=budget)

    held_after = _held(store)
    if held_before is None or held_after is None:
        contended = None  # could not tell, which is not the same as "no"
    else:
        contended = held_before | held_after
    for r in results:
        r.daemon_active = None if contended is None else r.domain in contended

    print()
    print(format_matrix(results))

    if args.products:
        _products_over_winners(results)

    if not args.no_save:
        at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        access_store.save_sweep(store, results, at=at)
        print(f"\nrecorded as access/sweeps/{at}.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archive")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in (
        "plan",
        "scrape",
        "status",
        "capability",
        "daemon",
        "brands",
        "hosts",
        "show",
        "images",
        "access",
        "coverage",
        "fleet-check",
        "notes",
        "failures",
        "periods",
        "backup",
        "restore",
    ):
        sp = sub.add_parser(name)
        sp.add_argument(
            "--objects",
            type=Path,
            default=None,
            help="keep objects in this directory instead of R2",
        )
        sp.add_argument("--brands", type=Path, default=_DEFAULT_BRANDS)
        if name == "images":
            sp.add_argument("domain", nargs="?")
            sp.add_argument("--all", action="store_true", help="every brand in brands.yml")
            sp.add_argument(
                "--shown",
                action="store_true",
                help="only the brands the app shows (small and mid) — usually what you want",
            )
            sp.add_argument(
                "--limit", type=int, default=0, help="images per brand (0 = all of them)"
            )
            sp.add_argument("--workers", type=int, default=4, help="brands fetched at once")
            sp.add_argument(
                "--gap",
                type=float,
                default=0.0,
                help="minimum seconds between hits on a host (0 = each host's own pace)",
            )
            sp.add_argument(
                "--width",
                type=int,
                default=0,
                help="CDN resize width where the CDN offers one (0 = original resolution)",
            )
            sp.add_argument("--images-dir", type=Path, default=Path("backend/archive/data/images"))
            sp.add_argument(
                "--dry-run", action="store_true", help="say how much is outstanding, fetch nothing"
            )
        if name == "show":
            sp.add_argument("domain")
            sp.add_argument("--limit", type=int, default=3)
            sp.add_argument("--field", help="show only products where this field is filled")
        if name == "daemon":
            sp.add_argument("action", choices=["start", "stop", "status"])
            sp.add_argument("--workers", type=int, default=1)
            sp.add_argument(
                "--no-images",
                action="store_true",
                help="scrape catalogues only, leaving the photographs to `images`",
            )
            sp.add_argument("--gap", type=float, default=0.0)
            sp.add_argument("--images-dir", type=Path, default=Path("backend/archive/data/images"))
        if name == "periods":
            sp.add_argument(
                "action",
                choices=["migrate", "show"],
                help="migrate: replay a brand's observations into the per-field timeline; "
                "show: print one product's timeline",
            )
            sp.add_argument("domain", nargs="?")
            sp.add_argument("itemurl", nargs="?")
            sp.add_argument("--all", action="store_true", help="migrate every brand in brands.yml")
        if name == "backup":
            sp.add_argument(
                "--status", action="store_true", help="say what is held and stop; back up nothing"
            )
        if name == "restore":
            sp.add_argument("date", help="a day with a backup, YYYY-MM-DD")
            sp.add_argument("domain", help="the one brand to put back as it was that day")
        if name == "failures":
            sp.add_argument("--hours", type=int, default=24)
            sp.add_argument("--all", action="store_true", help="every failed run, not only ours")
        if name == "brands":
            sp.add_argument(
                "action",
                choices=["add", "drop", "pause", "resume", "cadence", "sweep", "seed", "list"],
            )
            sp.add_argument("domain", nargs="?")
            sp.add_argument(
                "--every",
                type=int,
                default=86400,
                help="cadence in seconds (with `sweep`: seconds between stock sweeps, 0 = off)",
            )
        if name == "coverage":
            sp.add_argument("domain", nargs="*")
            sp.add_argument("--all", action="store_true", help="every brand in brands.yml")
            sp.add_argument(
                "--shown",
                action="store_true",
                help="only the brands the app shows (small and mid)",
            )
            sp.add_argument("--sample", type=int, default=5, help="products read per brand")
            sp.add_argument(
                "--browser", action="store_true", help="allow escalating to a real browser"
            )
        if name == "access":
            sp.add_argument("domain", nargs="*")
            sp.add_argument("--all", action="store_true", help="every brand in brands.yml")
            sp.add_argument(
                "--only-failing",
                action="store_true",
                help="only the brands whose notes record a refusal — usually what you want",
            )
            sp.add_argument(
                "--strategies",
                default="",
                help="comma-separated names to try (default: the whole shelf, cheapest first)",
            )
            sp.add_argument(
                "--dry-run",
                action="store_true",
                help="say which hosts would be asked and how often, then send nothing",
            )
            sp.add_argument("--gap", type=float, default=1.0, help="seconds between hits on a host")
            sp.add_argument(
                "--no-save", action="store_true", help="print the matrix without recording a sweep"
            )
            sp.add_argument(
                "--products",
                action="store_true",
                help="for each brand we got into, run the existing pipeline on a few products "
                "over the transport that worked (writes nothing)",
            )
        if name == "plan":
            sp.add_argument("domain")
        if name == "capability":
            sp.add_argument("domain", nargs="?")
            sp.add_argument("--all", action="store_true")
            sp.add_argument("--sample", type=int, default=5)
            sp.add_argument("--browser", action="store_true")
            sp.add_argument(
                "--show-gated", action="store_true", help="include password-gated stores as rows"
            )
            sp.add_argument(
                "--headful",
                action="store_true",
                help="run the browser visibly — much harder for sites to detect",
            )
        if name == "fleet-check":
            sp.add_argument("domain", nargs="?")
            sp.add_argument("--all", action="store_true", help="every brand in brands.yml")
            sp.add_argument("--shown", action="store_true", help="only the brands the app shows")
            sp.add_argument("--sample", type=int, default=5, help="products fetched per brand")
            sp.add_argument(
                "--browser", action="store_true", help="allow escalating to a real browser"
            )
        if name == "scrape":
            sp.add_argument("domain", nargs="?")
            sp.add_argument("--all", action="store_true", help="every brand in brands.yml")
            sp.add_argument(
                "--shown",
                action="store_true",
                help="only the brands the app shows (small and mid) — usually what you want",
            )
            group = sp.add_mutually_exclusive_group()
            group.add_argument("--delta", action="store_true")
            group.add_argument("--full", action="store_true")
            group.add_argument(
                "--learn",
                action="store_true",
                help="finder only: read a spread of pages, write rules, store no products",
            )
            group.add_argument(
                "--sweep",
                action="store_true",
                help="stock only: re-read the bulk feed and update what is in stock and "
                "at what price; no product pages, no images, nothing added or removed",
            )
            sp.add_argument(
                "--retry-searched",
                action="store_true",
                help="with --learn: ask again about fields already searched and not found",
            )
            sp.add_argument("--locks", type=Path, default=Path("backend/archive/data/locks"))
            sp.add_argument("--logs", type=Path, default=Path("backend/archive/data/logs"))
            sp.add_argument(
                "--archive-images",
                action="store_true",
                help="fetch image bytes inline, product by product (slow; the pass "
                "that runs afterwards is usually what you want)",
            )
            sp.add_argument(
                "--no-images",
                action="store_true",
                help="skip the image pass that otherwise follows the scrape",
            )
            sp.add_argument("--images-dir", type=Path, default=Path("backend/archive/data/images"))
            sp.add_argument(
                "--image-sample",
                type=int,
                default=5,
                help="products per run to archive images for (0 = unlimited)",
            )
            sp.add_argument(
                "--image-width",
                type=int,
                default=1200,
                help="CDN resize width (0 = original resolution)",
            )
            sp.add_argument(
                "--browser",
                action="store_true",
                help="allow the browser transport (T2) for challenged/enterprise brands",
            )
            sp.add_argument(
                "--max-products",
                type=int,
                default=0,
                help="stop after N products per brand (0 = no cap)",
            )
            sp.add_argument(
                "--gap",
                type=float,
                default=0.0,
                help="minimum seconds between requests to one host (0 = each host's own pace)",
            )
            sp.add_argument(
                "--pause",
                type=float,
                default=5.0,
                help="seconds between brands in a multi-brand run (0 = none)",
            )
            sp.add_argument(
                "--time-budget",
                type=float,
                default=0,
                help="seconds a single brand may take before the run stops early (0 = none)",
            )
            sp.add_argument(
                "--learn-budget",
                type=int,
                default=10,
                help="most LLM calls one run may spend learning new field rules",
            )
            sp.add_argument(
                "--find-fields",
                action="store_true",
                help="one LLM call per brand to locate fields the free channels miss",
            )
    args = ap.parse_args(argv)

    store: ObjectStore = object_store(args.objects)
    catalog = open_catalog(store)
    try:
        brands = _seed(catalog, args.brands) if args.brands.exists() else []

        if args.cmd == "periods":
            return _periods(args, catalog, brands)

        if args.cmd == "plan":
            cap = probe(args.domain, HttpxTransport())
            plan = compose_plan(cap)
            catalog.upsert_brand(Brand(domain=args.domain, homepage_url=f"https://{args.domain}"))
            catalog.save_plan(plan)
            print(f"{plan.domain}  {plan.composition}  {plan.status}")
            return 0

        if args.cmd == "scrape":
            if args.shown:
                from backend.archive.roster import app_roster

                wanted = {e.domain for e in app_roster(args.brands)}
                targets = [b for b in brands if b.domain in wanted]
            elif args.all:
                targets = brands
            else:
                targets = [b for b in brands if b.domain == args.domain]
            if not targets and args.domain:
                targets = [Brand(domain=args.domain, homepage_url=f"https://{args.domain}")]
                catalog.upsert_brand(targets[0])
            mode = "learn" if args.learn else "full" if args.full else "delta"
            if args.learn and not args.find_fields:
                args.find_fields = True  # a learn run is the finder; nothing else happens
            # Both ledgers a long run needs: what the sites answered, and what we spent.
            requests_log = RequestLog(catalog)
            spend = Spend()
            host_budget = HostBudget(gap=args.gap)
            carried = host_budget.seed_from(catalog)
            if carried:
                print(f"  standing down on {carried} host(s) refused recently")
            transport = HttpxTransport(sink=requests_log, budget=host_budget)
            if args.sweep:
                # Stock only, from the feed. No scorecard and no image pass: nothing
                # a card measures moved, and no photograph was read.
                from backend.archive.runner.sweep import sweep_brand

                worst = 0
                for i, b in enumerate(targets):
                    if i and args.pause:
                        time.sleep(args.pause)
                    code = sweep_brand(
                        b,
                        catalog,
                        transport,
                        locks_dir=args.locks,
                        log_dir=args.logs,
                        transport_factory=lambda level: for_level(
                            level, sink=requests_log, budget=host_budget
                        ),
                    )
                    run = catalog.latest_run(b.domain) or {}
                    print(
                        f"{b.domain}  exit={code}  sweep  {run.get('checked', 0)} checked  "
                        f"{run.get('changed', 0)} changed  {run.get('seconds', 0)} s"
                        f"{'  (' + run['reason'] + ')' if run.get('reason') else ''}"
                    )
                    worst = max(worst, code)
                requests_log.flush()
                catalog.close()
                return worst
            # Probing asks a brand that may refuse, on purpose, and a refusal there is the
            # answer rather than a reason to stand the host down for a quarter of an hour.
            probe_transport = HttpxTransport(
                sink=requests_log,
                budget=HostBudget(
                    gap=args.gap, busy_backoff=args.gap * 4, refused_backoff=args.gap * 4
                ),
            )
            # A scrape records image URLs; the bytes are the image pass's job. Fetching
            # them here made every scrape wait on 40,000 photographs, which is why the
            # old default only ever archived five products per brand.
            image_store = (
                ImageStore(image_sink(args.images_dir), width=args.image_width or None)
                if args.archive_images
                else None
            )
            image_budget = None if args.image_sample == 0 else args.image_sample

            def _field_finder(domain, url, missing, page_transport):
                from backend.archive.finder_llm import learn_recipes

                resp = page_transport.get(url)
                if resp.status_code != 200:
                    return None
                return learn_recipes(resp.text, url, domain, missing, spend=spend)

            def _browser_factory():
                # The challenge-aware subclass: a browser that reads a page and closes the
                # tab kills the challenge script mid-calculation, so the token never
                # arrives and every request stays at 202 (Gentle Monster, 2026-09-17).
                from backend.archive.browser.challenge import (
                    ChallengeAwareBrowser as PlaywrightTransport,
                )

                return PlaywrightTransport()

            def _report_spend():
                requests_log.flush()
                if spend.calls:
                    print(
                        f"  spent ${spend.usd} over {spend.calls} call(s): "
                        f"{spend.input_tokens} in, {spend.output_tokens} out"
                    )

            worst = 0
            # 24 Shopify stores scraped back-to-back with no gap drew HTTP 429s from
            # three of them on 2026-09-07. A short pause costs a minute and avoids it.
            for i, b in enumerate(targets):
                if i and args.pause:
                    time.sleep(args.pause)
                # Spend accumulates across the whole invocation, so a brand's own cost
                # is the difference across its run. Charging each brand the running
                # total would make every brand after the first look worse than it was.
                spent_before = spend.usd
                calls_before = spend.calls
                code = run_brand(
                    b,
                    catalog,
                    transport,
                    mode=mode,
                    locks_dir=args.locks,
                    log_dir=args.logs,
                    image_store=image_store,
                    image_product_budget=image_budget,
                    browser=args.browser,
                    # --find-fields needs a browser available even without --browser:
                    # some brands only expose sizes once the page renders.
                    browser_transport_factory=(
                        _browser_factory if (args.browser or args.find_fields) else None
                    ),
                    # Ask a brand that refuses plain HTTP again in a browser's voice
                    # before writing it off as unreadable.
                    prober=escalating_prober(
                        browser_factory=_browser_factory if args.browser else None
                    ),
                    probe_transport=probe_transport,
                    field_finder=_field_finder if args.find_fields else None,
                    max_products=args.max_products or None,
                    learn_budget=args.learn_budget,
                    retry_searched=args.retry_searched,
                    time_budget=args.time_budget or None,
                )
                # The daemon scores every run; a hand-run scrape is the same work and
                # is worth the same record, or the two loops disagree about a brand.
                latest = catalog.latest_run(b.domain)
                stored = [ProductRecord(**cast(Any, r)) for r in catalog.current_products(b.domain)]
                if latest and stored:
                    card = score(stored, cost_usd=spend.usd - spent_before)
                    catalog.save_scorecard(latest["id"], b.domain, card)
                    per_product = card.cost_usd / card.products if card.products else 0
                    print(
                        f"{b.domain}  exit={code}  "
                        f"{'PASS' if card.required_ok else 'FAIL'}  "
                        f"{card.products} products  {card.fields_filled:.0%} of 42  "
                        f"{card.images_per_product} img/product  "
                        f"${card.cost_usd:.3f} ({spend.calls - calls_before} calls, "
                        f"${per_product:.5f}/product)"
                    )
                else:
                    print(f"{b.domain}  exit={code}")
                worst = max(worst, code)
            _report_spend()

            # The photographs, unless told not to. A record naming an image we do not
            # hold is a link to someone else's server, and the two halves drifting
            # apart is what "keep the bytes, not the addresses" was meant to prevent.
            #
            # After the catalogue rather than during it: a scrape reads a brand in
            # about a minute and its photographs take an hour, so fetching inline
            # would make every scrape wait on the slow half. Two phases, one command.
            if not args.no_images:
                from backend.archive.runner.archive_images import (
                    archive_all,
                    outstanding,
                    summarise,
                )

                pending = sum(outstanding(catalog, b.domain) for b in targets)
                if pending:
                    print(f"\nimages: {pending} outstanding across {len(targets)} brand(s)")
                    sink = image_sink(args.images_dir)
                    results = archive_all(
                        [b.domain for b in targets],
                        store,
                        sink,
                        gap=args.gap,
                        width=args.image_width or None,
                        on_done=lambda o: print(
                            f"{o.domain:<32}{o.fetched:>7} fetched  "
                            f"{o.failed} failed  {o.outstanding} left"
                        ),
                    )
                    kept, left, errored = summarise(results)
                    tail = "unknown — some brands could not be reached" if left is None else left
                    print(f"images: {kept} stored, {tail} still outstanding")
                    if errored:
                        print(f"images: {errored} brand(s) errored")
                else:
                    print("\nimages: nothing outstanding")
            return worst

        if args.cmd == "images":
            from backend.archive.runner.archive_images import (
                archive_all,
                outstanding,
                summarise,
            )

            if args.shown:
                from backend.archive.roster import app_roster

                domains = [e.domain for e in app_roster(args.brands)]
            elif args.all:
                domains = [b.domain for b in brands]
            else:
                domains = [b.domain for b in brands if b.domain == args.domain]
            if not domains:
                print("nothing to do: name a brand, or pass --shown or --all")
                return 1

            if args.dry_run:
                total = 0
                for domain in domains:
                    n = outstanding(catalog, domain)
                    total += n
                    if n:
                        print(f"{domain:<32}{n:>7} outstanding")
                print(f"{'':<32}{total:>7} in total")
                return 0

            sink = image_sink(args.images_dir)
            print(f"storing to {type(sink).__name__}, {args.workers} brand(s) at a time")

            def _report(outcome):
                print(
                    f"{outcome.domain:<32}{outcome.fetched:>7} fetched  "
                    f"{outcome.failed} failed  {outcome.outstanding} left"
                )

            results = archive_all(
                domains,
                store,
                sink,
                workers=args.workers,
                gap=args.gap,
                limit=args.limit,
                width=args.width or None,
                on_done=_report,
            )
            kept, left, errored = summarise(results)
            tail = "unknown — some brands could not be reached" if left is None else str(left)
            print(f"\n{kept} image(s) stored, {tail} still outstanding")
            if errored:
                print(f"{errored} brand(s) errored; run it again once they are reachable")
                return 1
            return 0

        if args.cmd == "capability":
            targets = brands if args.all else [b for b in brands if b.domain == args.domain]
            if not targets and args.domain:
                targets = [Brand(domain=args.domain, homepage_url=f"https://{args.domain}")]
            reports = []

            def _capability_browser():
                from backend.archive.browser.challenge import ChallengeAwareBrowser

                return ChallengeAwareBrowser(headless=not args.headful)

            for b in targets:
                t: Transport = _capability_browser() if args.browser else HttpxTransport()
                try:
                    rep = probe_brand(
                        b,
                        t,
                        sample=args.sample,
                        browser=args.browser,
                        prober=escalating_prober(
                            browser_factory=_capability_browser if args.browser else None
                        ),
                    )
                finally:
                    if hasattr(t, "close"):
                        t.close()
                reports.append(rep)
                print(f"  probed {b.domain:<26} {rep.verdict}", flush=True)
            print()
            print(format_matrix(reports, show_gated=args.show_gated))
            return 0

        if args.cmd == "fleet-check":
            return _fleet_check(args, catalog, brands)

        if args.cmd == "notes":
            # What the owner wrote on the deck. Open ones first, then the done ones,
            # so whoever picks the work up — a person or an agent — reads one list.
            from backend.archive.store.objects import loads

            found = store.get("control/notes.json")
            notes = (loads(found[0]) if found else {}).get("notes", [])
            if not notes:
                print("no notes")
                return 0
            for done in (False, True):
                for n in notes:
                    if bool(n.get("done")) != done:
                        continue
                    print(f"[{'x' if done else ' '}] {n['at'][:16]}  {n['id']}\n    {n['text']}")
            return 0

        if args.cmd == "failures":
            return _failures(args, catalog, brands)

        if args.cmd == "coverage":
            return _coverage(args, brands)

        if args.cmd == "access":
            return _access(args, store, brands)

        if args.cmd == "show":
            rows = catalog.current_products(args.domain)
            if args.field:
                rows = [r for r in rows if r.get(args.field) not in (None, "", [])]
            if not rows:
                print("nothing stored")
                return 0
            book = catalog.load_recipe_book(args.domain)
            learned = {r.field for r in book.recipes} if book else set()
            for row in rows[: args.limit]:
                print(f"\n{'=' * 78}\n{row['product_title']}\n{row['itemurl']}")
                for f in E0005_FIELDS:
                    v = row.get(f)
                    if v in (None, "", []) or f in ("itemurl", "product_title"):
                        continue
                    if f == "all_images":
                        urls = json.loads(v)
                        print(f"  {f:<20}{len(urls)} images")
                        for u in urls[:3]:
                            print(f"  {'':<20}  {u[:86]}")
                        continue
                    mark = "  <- learned" if f in learned else ""
                    print(f"  {f:<20}{str(v)[:80]}{mark}")
                blank = [f for f in E0005_FIELDS if row.get(f) in (None, "", [])]
                print(f"  {'(blank)':<20}{len(blank)} fields: {', '.join(blank[:9])}…")
            print(f"\nshowing {min(args.limit, len(rows))} of {len(rows)} products")
            return 0

        if args.cmd == "hosts":
            rows = catalog.host_stats()
            if not rows:
                print("no requests recorded yet")
                return 0
            print(
                f"{'HOST':<30}{'REQS':>7}{'OK':>7}{'BUSY':>6}{'REFUSED':>8}"
                f"{'ERR':>5}{'AVG ms':>8}{'RETRY-AFTER':>12}"
            )
            for r in rows:
                print(
                    f"{r['host']:<30}{r['requests']:>7}{r['ok'] or 0:>7}{r['busy'] or 0:>6}"
                    f"{r['refused'] or 0:>8}{r['errored'] or 0:>5}{r['avg_ms'] or 0:>8}"
                    f"{(str(r['max_retry_after']) if r['max_retry_after'] else '—'):>12}"
                )
            return 0

        if args.cmd == "brands":
            from backend.archive.scheduler import Scheduler

            sched = Scheduler(store)
            if args.action == "seed":
                # Every brand the app shows, onto the schedule. The daemon reads this
                # and nothing else, so a brand missing from here is a brand that never
                # gets scraped however carefully it is listed in brands.yml.
                from backend.archive.roster import app_roster

                added = 0
                for entry in app_roster(args.brands):
                    if not any(r["domain"] == entry.domain for r in sched.rows()):
                        sched.add(entry.domain, args.every)
                        added += 1
                print(f"added {added} brand(s) to the schedule")
            elif args.action == "list":
                pass
            elif args.action == "add":
                catalog.upsert_brand(
                    catalog.get_brand(args.domain)
                    or Brand(domain=args.domain, homepage_url=f"https://{args.domain}")
                )
                sched.add(args.domain, args.every)
            elif args.action == "cadence":
                sched.set_cadence(args.domain, args.every)
            elif args.action == "sweep":
                sched.set_sweep(args.domain, args.every)
            elif args.action in ("drop", "pause"):
                sched.set_enabled(args.domain, False)
            else:
                sched.set_enabled(args.domain, True)
            print(f"{'DOMAIN':<28}{'ON':<4}{'EVERY':>8}{'SWEEP':>7}  NEXT DUE")
            for r in sched.rows():
                sweep = r.get("sweep_seconds") or 0
                print(
                    f"{r['domain']:<28}{'y' if r['enabled'] else 'n':<4}"
                    f"{r['cadence_seconds']:>8}{(str(sweep) if sweep else '—'):>7}  "
                    f"{r['next_due'][:19]}"
                    f"{'  (running)' if r['claimed_by'] else ''}"
                )
            return 0

        if args.cmd in ("backup", "restore"):
            from backend.archive import backup as bk

            if args.cmd == "backup" and args.status:
                s = bk.status(store)
                print(f"last:  {s.get('day')} {s.get('state')} by {s.get('worker')}")
                if s.get("error"):
                    print(f"error: {s['error']}")
                print(f"days:  {', '.join(s['days']) or 'none'}")
                return 0
            if not hasattr(catalog, "_pg"):
                print(
                    "the catalogue is not on Postgres here: set CATALOG_BACKEND=pg and "
                    "DATABASE_URL, then run again",
                    file=sys.stderr,
                )
                return 2
            if args.cmd == "backup":
                m = bk.backup(catalog, store)
                for table, st in m["tables"].items():
                    print(
                        f"{table:<22}{st['rows']:>8} rows {st['bytes'] / 1e6:>8.1f} MB "
                        f"{st['seconds']}s"
                    )
                print(
                    f"{m['r2']['copied']} objects copied, {len(m['pruned'])} old days pruned, "
                    f"{m['seconds']}s → backups/{m['day']}/"
                )
                return 0
            counts = bk.restore(catalog, store, args.date, args.domain)
            for table, n in counts.items():
                print(f"{table:<22}{n:>8} rows")
            print(f"{args.domain} is as it was on {args.date}")
            return 0

        if args.cmd == "daemon":
            from backend.archive.runner.daemon import serve
            from backend.archive.scheduler import Scheduler

            sched = Scheduler(store)
            if args.action == "stop":
                sched.request_stop()
                print("stop requested — workers finish the brand they are on and exit")
                return 0
            if args.action == "status":
                rows = sched.rows()
                running = [r for r in rows if r["claimed_by"]]
                print(f"stop flag: {'set' if sched.should_stop() else 'clear'}")
                print(f"version:   {sched.code_version()}")
                print(
                    f"brands:    {sum(1 for r in rows if r['enabled'])} enabled, "
                    f"{len(running)} running"
                )
                for r in running:
                    print(f"   {r['domain']:<28}{r['claimed_by']}  since {r['claimed_at'][:19]}")
                return 0
            # Without this the worst outcome is silent. When a credential is missing,
            # object_store falls back to a directory inside the container: the daemon
            # boots, logs "daemon up", finds no brands in its empty local store and
            # sleeps for ever, having written nothing anywhere anyone will look.
            if args.objects is None and not isinstance(store, R2ObjectStore):
                print(
                    "refusing to start: R2 is not configured and no --objects was given. "
                    "Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and "
                    "R2_BUCKET, or pass --objects <dir> to run against a directory.",
                    file=sys.stderr,
                )
                return 2
            sched.request_stop(False)  # a fresh start clears a previous stop
            catalog.close()
            budget = HostBudget(gap=args.gap)
            budget.seed_from(catalog)  # hosts that refused us recently stay stood down
            # What the finder may spend across the fleet today. Zero keeps it off, which
            # is what the daemon did unconditionally until 2026-09-22.
            finder_cap_usd = float(os.getenv("FINDER_DAILY_USD", "0") or 0)

            def factory(cat):
                from backend.archive.spend_cap import DailyCap

                spend = Spend()
                cap = DailyCap(cat.store, finder_cap_usd)

                def _browser_factory():
                    # The image carries Chromium now, so a brand behind a challenge
                    # gets a real browser — for the 2.5s it takes to mint the cookie,
                    # after which every page goes over plain HTTP (learning 14).
                    from backend.archive.browser.challenge import ChallengeAwareBrowser

                    return ChallengeAwareBrowser()

                def _field_finder(domain, url, missing, page_transport):
                    from backend.archive.finder_llm import learn_recipes

                    # A trimmed page is up to ~28k tokens, about $0.10 on a heavy page.
                    # It was 0.2 when the finder sent 220k characters; before that, 0.02
                    # was a tenth of a real call and let the day overshoot by a call
                    # per worker.
                    cap.check(estimate_usd=0.1)  # raises FinderBudgetSpent
                    before = spend.usd
                    resp = page_transport.get(url)
                    if resp.status_code != 200:
                        return None
                    try:
                        return learn_recipes(resp.text, url, domain, missing, spend=spend)
                    finally:
                        cap.charge(spend.usd - before)

                def do_brand(brand, mode="delta", retry_searched=False):
                    spent_before = spend.usd
                    # What the sites answered, kept with the catalogue: the deck's
                    # per-host latency and refusal counts come from this ledger, and
                    # until today the daemon's transport had no sink, so those
                    # numbers only ever existed for scrapes run by hand.
                    requests_log = RequestLog(cat)
                    if mode == "sweep":
                        # Stock from the feed and nothing else: no pages, no images,
                        # no finder, no scorecard.
                        from backend.archive.runner.sweep import sweep_brand

                        try:
                            sweep_brand(
                                brand,
                                cat,
                                HttpxTransport(sink=requests_log, budget=budget),
                                locks_dir=args.locks if hasattr(args, "locks") else Path("locks"),
                                log_dir=Path("backend/archive/data/logs"),
                                browser_transport_factory=_browser_factory,
                                transport_factory=lambda level: for_level(
                                    level, sink=requests_log, budget=budget
                                ),
                            )
                        finally:
                            requests_log.flush()
                        return None, 0.0
                    try:
                        run_brand(
                            brand,
                            cat,
                            # Paced and stood down like the hand-run scrape: without
                            # the budget a 429 mid-run was followed by the next
                            # request at once, for every product left.
                            HttpxTransport(sink=requests_log, budget=budget),
                            mode=mode,
                            retry_searched=retry_searched,
                            locks_dir=args.locks if hasattr(args, "locks") else Path("locks"),
                            log_dir=Path("backend/archive/data/logs"),
                            browser=True,
                            browser_transport_factory=_browser_factory,
                            prober=escalating_prober(browser_factory=_browser_factory),
                            # Probing asks a brand that may refuse, on purpose. On the
                            # paced transport a refusal stands the host down for a
                            # quarter of an hour and the probe then sleeps on its own
                            # evidence — both workers sat on gated brands for the
                            # whole afternoon of 2026-09-23. The probe gets a short
                            # fuse, as the hand-run scrape always has.
                            probe_transport=HttpxTransport(
                                sink=requests_log,
                                budget=HostBudget(
                                    gap=args.gap,
                                    busy_backoff=max(args.gap * 4, 2.0),
                                    refused_backoff=max(args.gap * 4, 2.0),
                                ),
                            ),
                            field_finder=_field_finder if finder_cap_usd > 0 else None,
                            # Ask about everything the run can, not ten pages' worth:
                            # the daily ceiling is the throttle, and what a page did
                            # not yield is asked again on a later product or run.
                            # Fifteen pages at ~$0.10 (was ~$0.17 before the trimmer)
                            # is $1.50 — one brand cannot spend the fleet's day; what a
                            # page did not yield is asked again on a later run.
                            learn_budget=15,
                            transport_factory=lambda level: for_level(
                                level, sink=requests_log, budget=budget
                            ),
                            # A brand cannot hold a worker for a day: 20,000 products,
                            # six hours, then the rest is reported as missing coverage.
                            max_products=20_000,
                            time_budget=6 * 3600,
                        )
                    finally:
                        requests_log.flush()
                    if mode == "learn":
                        # Nothing stored, nothing to photograph or score.
                        return None, spend.usd - spent_before
                    # The photographs with the catalogue, the same as a hand-run
                    # scrape. A daemon that kept the records fresh and let the images
                    # fall behind would be filling the archive with links to other
                    # people's servers.
                    if not args.no_images:
                        from backend.archive.runner.archive_images import archive_brand

                        # Its own store: `store` belongs to the main thread and the
                        # workers are threads, so they would share one client.
                        archive_brand(
                            brand.domain,
                            object_store(args.objects),
                            image_sink(args.images_dir),
                            budget,
                            limit=5000,  # products per pass; the rest next time
                        )
                    rows = cat.current_products(brand.domain)
                    return [ProductRecord(**cast(Any, r)) for r in rows], spend.usd - spent_before

                return do_brand

            serve(lambda: object_store(args.objects), factory, workers=args.workers)
            return 0

        # status
        rows = catalog.status_rows()
        print(f"{'BRAND':<28}{'STATE':<16}{'PRODUCTS':>9}{'COVERAGE':>10}{'VERDICT':>10}  FRESH")
        for r in rows:
            cov = f"{r['coverage_pct']:.0%}" if r["coverage_pct"] is not None else "—"
            print(
                f"{r['domain']:<28}{r['state']:<16}{r['products']:>9}{cov:>10}"
                f"{(r['verdict'] or '—'):>10}  {r['freshness'] or '—'}"
            )
        return 0
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main())
