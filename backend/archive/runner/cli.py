"""archive CLI: plan | scrape | status (spec §4.6). Run as python -m backend.archive.runner.cli."""

import argparse
import json
import time
from pathlib import Path
from typing import Any, cast

import yaml

from backend.archive.budget import HostBudget
from backend.archive.capability import format_matrix, probe_brand
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import E0005_FIELDS, ProductRecord
from backend.archive.fingerprint import probe
from backend.archive.images import ImageStore
from backend.archive.observe import RequestLog, Spend
from backend.archive.planner import compose_plan
from backend.archive.runner.run import run_brand
from backend.archive.score import score
from backend.archive.store.catalog import Catalog
from backend.archive.transport import HttpxTransport, Transport

_DEFAULT_BRANDS = Path(__file__).parent.parent / "brands.yml"
_DEFAULT_DB = Path("backend/archive/data/catalog.db")


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


def _seed(catalog: Catalog, brands_path: Path) -> list[Brand]:
    brands = load_brands(brands_path)
    for b in brands:
        catalog.upsert_brand(b)
    return brands


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
    ):
        sp = sub.add_parser(name)
        sp.add_argument("--db", type=Path, default=_DEFAULT_DB)
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
            sp.add_argument("--gap", type=float, default=0.5, help="seconds between hits on a host")
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
            sp.add_argument(
                "--adopt-only",
                action="store_true",
                help="upload what is already on disk and ask no shop for anything",
            )
        if name == "show":
            sp.add_argument("domain")
            sp.add_argument("--limit", type=int, default=3)
            sp.add_argument("--field", help="show only products where this field is filled")
        if name == "daemon":
            sp.add_argument("action", choices=["start", "stop", "status"])
            sp.add_argument("--workers", type=int, default=1)
        if name == "brands":
            sp.add_argument("action", choices=["add", "drop", "pause", "resume", "cadence"])
            sp.add_argument("domain", nargs="?")
            sp.add_argument("--every", type=int, default=86400, help="cadence in seconds")
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
        if name == "scrape":
            sp.add_argument("domain", nargs="?")
            sp.add_argument("--all", action="store_true")
            group = sp.add_mutually_exclusive_group()
            group.add_argument("--delta", action="store_true")
            group.add_argument("--full", action="store_true")
            sp.add_argument("--locks", type=Path, default=Path("backend/archive/data/locks"))
            sp.add_argument("--logs", type=Path, default=Path("backend/archive/data/logs"))
            sp.add_argument(
                "--archive-images",
                action="store_true",
                help="fetch image bytes during the scrape (normally left to `images`)",
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
                default=0.5,
                help="seconds between requests to one host (0 = no pacing)",
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

    catalog = Catalog(args.db)
    try:
        brands = _seed(catalog, args.brands) if args.brands.exists() else []

        if args.cmd == "plan":
            cap = probe(args.domain, HttpxTransport())
            plan = compose_plan(cap)
            catalog.upsert_brand(Brand(domain=args.domain, homepage_url=f"https://{args.domain}"))
            catalog.save_plan(plan)
            print(f"{plan.domain}  {plan.composition}  {plan.status}")
            return 0

        if args.cmd == "scrape":
            targets = brands if args.all else [b for b in brands if b.domain == args.domain]
            if not targets and args.domain:
                targets = [Brand(domain=args.domain, homepage_url=f"https://{args.domain}")]
                catalog.upsert_brand(targets[0])
            mode = "full" if args.full else "delta"
            # Both ledgers a long run needs: what the sites answered, and what we spent.
            requests_log = RequestLog(catalog)
            spend = Spend()
            host_budget = HostBudget(gap=args.gap)
            carried = host_budget.seed_from(catalog)
            if carried:
                print(f"  standing down on {carried} host(s) refused recently")
            transport = HttpxTransport(sink=requests_log, budget=host_budget)
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
                from backend.archive.browser.transport import PlaywrightTransport

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
                    field_finder=_field_finder if args.find_fields else None,
                    max_products=args.max_products or None,
                    learn_budget=args.learn_budget,
                    time_budget=args.time_budget or None,
                )
                # The daemon scores every run; a hand-run scrape is the same work and
                # is worth the same record, or the two loops disagree about a brand.
                run = catalog.latest_run(b.domain)
                stored = [ProductRecord(**cast(Any, r)) for r in catalog.current_products(b.domain)]
                if run and stored:
                    card = score(stored, cost_usd=spend.usd - spent_before)
                    catalog.save_scorecard(run["id"], b.domain, card)
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
            return worst

        if args.cmd == "images":
            from backend.archive.runner.archive_images import archive_all, outstanding

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
                    f"{outcome.domain:<32}{outcome.stored:>7} stored "
                    f"({outcome.adopted} off disk, {outcome.fetched} fetched)  "
                    f"{outcome.failed} failed  {outcome.outstanding} left"
                )

            results = archive_all(
                domains,
                args.db,
                sink,
                workers=args.workers,
                gap=args.gap,
                limit=args.limit,
                width=args.width or None,
                adopt_only=args.adopt_only,
                on_done=_report,
            )
            kept = sum(r.stored for r in results)
            left = sum(r.outstanding for r in results)
            print(f"\n{kept} image(s) stored, {left} still outstanding")
            return 0

        if args.cmd == "capability":
            targets = brands if args.all else [b for b in brands if b.domain == args.domain]
            if not targets and args.domain:
                targets = [Brand(domain=args.domain, homepage_url=f"https://{args.domain}")]
            reports = []
            for b in targets:
                t: Transport
                if args.browser:
                    from backend.archive.browser.transport import PlaywrightTransport

                    t = PlaywrightTransport(headless=not args.headful)
                else:
                    t = HttpxTransport()
                try:
                    rep = probe_brand(b, t, sample=args.sample, browser=args.browser)
                finally:
                    if hasattr(t, "close"):
                        t.close()
                reports.append(rep)
                print(f"  probed {b.domain:<26} {rep.verdict}", flush=True)
            print()
            print(format_matrix(reports, show_gated=args.show_gated))
            return 0

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

            sched = Scheduler(catalog)
            if args.action == "add":
                catalog.upsert_brand(
                    catalog.get_brand(args.domain)
                    or Brand(domain=args.domain, homepage_url=f"https://{args.domain}")
                )
                sched.add(args.domain, args.every)
            elif args.action == "cadence":
                sched.set_cadence(args.domain, args.every)
            elif args.action in ("drop", "pause"):
                sched.set_enabled(args.domain, False)
            else:
                sched.set_enabled(args.domain, True)
            print(f"{'DOMAIN':<28}{'ON':<4}{'EVERY':>8}  NEXT DUE")
            for r in sched.rows():
                print(
                    f"{r['domain']:<28}{'y' if r['enabled'] else 'n':<4}"
                    f"{r['cadence_seconds']:>8}  {r['next_due'][:19]}"
                    f"{'  (running)' if r['claimed_by'] else ''}"
                )
            return 0

        if args.cmd == "daemon":
            from backend.archive.runner.daemon import serve
            from backend.archive.scheduler import Scheduler

            sched = Scheduler(catalog)
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
            sched.request_stop(False)  # a fresh start clears a previous stop
            catalog.close()

            def factory(cat):
                def do_brand(brand):
                    run_brand(
                        brand,
                        cat,
                        HttpxTransport(),
                        mode="delta",
                        locks_dir=args.locks if hasattr(args, "locks") else Path("locks"),
                        log_dir=Path("backend/archive/data/logs"),
                    )
                    rows = cat.current_products(brand.domain)
                    return [ProductRecord(**cast(Any, r)) for r in rows], 0.0

                return do_brand

            serve(args.db, factory, workers=args.workers)
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
