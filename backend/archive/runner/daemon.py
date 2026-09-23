"""The loop that keeps scraping while the code underneath is replaced.

The worker holds no state. It wakes, asks the schedule what is due, does one brand,
writes a scorecard, and repeats. Every scheduling decision is a row that can be edited
while it runs, so adding a brand, pausing one, or stopping the whole thing needs no
deploy and interrupts nothing mid-brand.

Two properties come from doing exactly one brand per iteration:

  a deploy is picked up between brands, never during one, so no catalogue is ever
  written by two versions of the code;

  stopping is a flag — the worker finishes the brand it is on and exits with that run
  finalised, rather than being killed with a run half-written.

Workers are threads over one schedule. Claiming is atomic, so they need no coordination
beyond the database.
"""

import os
import subprocess
import threading
import time
from datetime import datetime, timezone

from backend.archive.connectors.base import ChannelBusy
from backend.archive.recommend import recommend
from backend.archive.scheduler import Scheduler
from backend.archive.score import score
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import ObjectStore

POLL_SECONDS = 10
# How often a worker says it is still alive. Well under the hour a claim takes to go
# stale, so a live worker never loses its brand and a dead one still frees it.
HEARTBEAT_SECONDS = 300
# How long to stand a brand down when its host asks us to slow down. Long enough that
# the window a shop counts requests over has moved on.
BUSY_BACKOFF = 1800
# A brand that ends needing a person, run after run, was re-probed every cycle for
# nothing. After this many identical endings its turns come at longer gaps, doubling
# each time up to the factor below — still probed, so a site that opens up is noticed,
# just not every day.
ATTENTION_PATIENCE = 3
ATTENTION_MAX_FACTOR = 16


def backoff(cadence_seconds: int, attention_streak: int) -> int:
    """When a brand is next wanted, given how many runs in a row needed a person."""
    if attention_streak < ATTENTION_PATIENCE:
        return cadence_seconds
    factor = min(ATTENTION_MAX_FACTOR, 2 ** (attention_streak - ATTENTION_PATIENCE + 1))
    return cadence_seconds * factor


def code_version() -> str:
    """The commit the worker is running. Render names it in the environment; a
    checkout answers from git; anything else is "unknown" and never compared.

    It matters at deploy time: Render keeps the previous container alive for a
    minute after the new one is healthy, and on 2026-09-23 the old daemon took
    three queued runs in that minute and crashed them with a bug the new code had
    fixed. A worker that sees a newer version in the store stands down between
    brands instead of claiming another.
    """
    from_host = os.environ.get("RENDER_GIT_COMMIT", "").strip()
    if from_host:
        return from_host
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def superseded(mine: str, stored: str | None) -> bool:
    """Whether a newer daemon has announced itself. Only two real versions count."""
    return bool(mine and stored) and mine != "unknown" and stored != "unknown" and mine != stored


def run_once(catalog: Catalog, scheduler: Scheduler, do_brand, log=print) -> bool:
    """Claim one due brand and scrape it. False when nothing was due."""
    due = scheduler.claim_next()
    if due is None:
        return False
    started = time.monotonic()
    brand = catalog.get_brand(due.domain)
    beat_off = threading.Event()

    def beat() -> None:
        while not beat_off.wait(HEARTBEAT_SECONDS):
            try:
                scheduler.touch(due.domain)
            except Exception:  # a missed beat is survivable; a dead worker is not
                pass

    threading.Thread(target=beat, daemon=True).start()
    learning = due.mode == "learn"
    try:
        if learning:
            records, cost = do_brand(brand, mode="learn", retry_searched=due.retry_searched)
        else:
            records, cost = do_brand(brand)
    except ChannelBusy as e:
        # Not a failure of the brand or of our code: the host wants us to wait, and it
        # must not consume the brand's turn in the rotation.
        log(f"{due.domain} busy: {e}")
        beat_off.set()
        if learning:
            scheduler.release_after_learn(due.domain, not_before=BUSY_BACKOFF)
        else:
            scheduler.defer(due.domain, BUSY_BACKOFF)
        return True
    except Exception as e:  # one hostile site must never stop the loop
        log(f"{due.domain} crashed: {type(e).__name__}: {e}")
        beat_off.set()
        if learning:
            scheduler.release_after_learn(due.domain)
        else:
            scheduler.release(due.domain, due.cadence_seconds)
        return True

    beat_off.set()
    if learning:
        # No scorecard: nothing was stored, so there is nothing to score, and a card
        # of zero products would read as a failed gate on the deck. The run row
        # says what was learned; the brand's turn is restored, not consumed.
        log(f"{due.domain} learn run done, ${cost:.3f}")
        scheduler.release_after_learn(due.domain)
        catalog.release_products(due.domain)
        return True
    try:
        _score_and_release(catalog, scheduler, due, records, cost, started, log)
    finally:
        # The parsed catalogue of a 35 MB brand must not sit in this worker until its
        # next flush, and the brand must never stay claimed because scoring failed.
        catalog.release_products(due.domain)
        row = scheduler.row(due.domain) or {}
        if row.get("claimed_by") == scheduler.worker_id:
            scheduler.release(due.domain, due.cadence_seconds)
    return True


def _score_and_release(catalog, scheduler, due, records, cost, started, log) -> None:
    card = score(records, seconds=time.monotonic() - started, cost_usd=cost)
    run = catalog.latest_run(due.domain)
    if run:
        catalog.save_scorecard(run["id"], due.domain, card)
        # What to fix first, written where the deck can read it. The judgement already
        # existed in recommend.py; it was a command nobody ran.
        try:
            catalog.save_recommendations(due.domain, run["id"], recommend(catalog, due.domain))
        except Exception as e:  # advice must never cost a run
            log(f"{due.domain} recommend failed: {type(e).__name__}: {e}")
    log(
        f"{due.domain} {card.products} products, "
        f"{'PASS' if card.required_ok else 'FAIL ' + ','.join(card.required_gaps)}, "
        f"{card.fields_filled:.0%} fields, {card.images_per_product} img/product, "
        f"${card.cost_usd}, {card.seconds_per_product}s/product"
    )
    streak, reason = catalog.attention(due.domain)
    wait = backoff(due.cadence_seconds, streak)
    if wait != due.cadence_seconds:
        log(f"{due.domain} needs a human ({streak} runs: {reason}); next look in {wait // 3600}h")
    scheduler.release(due.domain, wait)


def worker(store_factory, worker_id: str, do_brand_factory, version: str, log=print) -> None:
    """One worker: claim, scrape, release, until told to stop or the code changes.

    Each worker builds its own store, because a store holds a network client and the
    workers are threads."""
    store: ObjectStore = store_factory()
    catalog = Catalog(store)
    scheduler = Scheduler(store, worker_id=worker_id)
    do_brand = do_brand_factory(catalog)
    try:
        while True:
            try:
                if scheduler.should_stop():
                    return
                if superseded(version, scheduler.code_version()):
                    log(f"{worker_id}: a newer daemon is up; standing down")
                    return
                # Seen recently, by the deck: a thread that died used to be invisible.
                scheduler.beat_worker(worker_id)
                if not run_once(catalog, scheduler, do_brand, log=log):
                    time.sleep(POLL_SECONDS)
            except Exception as e:  # noqa: BLE001 — a transient must not end the worker
                # Before this, any store error outside do_brand (a 503 from the
                # bucket, a timeout) ended the thread for good, and one dead worker
                # halved the fleet with nothing on the deck to say so.
                log(f"{worker_id}: {type(e).__name__}: {e}; carrying on in 30s")
                time.sleep(30)
    finally:
        catalog.close()


def serve(store_factory, do_brand_factory, workers: int = 1, log=print) -> None:
    """Run N workers over one schedule until the stop flag is set.

    Takes a callable that makes a store rather than a directory, because in production
    the store is a bucket and a bucket has no path on disk."""
    version = code_version()
    Scheduler(store_factory()).set_code_version(version)
    log(f"daemon up: {workers} worker(s) on {version[:8]} at {datetime.now(timezone.utc):%H:%M}")

    threads = [
        threading.Thread(
            target=worker,
            args=(store_factory, f"worker-{i + 1}", do_brand_factory, version),
            kwargs={"log": log},
            daemon=True,
        )
        for i in range(workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log("daemon down")
