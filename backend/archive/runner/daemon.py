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

import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.archive.connectors.base import ChannelBusy
from backend.archive.scheduler import Scheduler
from backend.archive.score import score
from backend.archive.store.catalog import Catalog

POLL_SECONDS = 10
# How long to stand a brand down when its host asks us to slow down. Long enough that
# the window a shop counts requests over has moved on.
BUSY_BACKOFF = 1800


def code_version() -> str:
    """The commit the worker is running, so a deploy is visible to it."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return "unknown"


def run_once(catalog: Catalog, scheduler: Scheduler, do_brand, log=print) -> bool:
    """Claim one due brand and scrape it. False when nothing was due."""
    due = scheduler.claim_next()
    if due is None:
        return False
    started = time.monotonic()
    brand = catalog.get_brand(due.domain)
    try:
        records, cost = do_brand(brand)
    except ChannelBusy as e:
        # Not a failure of the brand or of our code: the host wants us to wait, and it
        # must not consume the brand's turn in the rotation.
        log(f"{due.domain} busy: {e}")
        scheduler.defer(due.domain, BUSY_BACKOFF)
        return True
    except Exception as e:  # one hostile site must never stop the loop
        log(f"{due.domain} crashed: {type(e).__name__}: {e}")
        scheduler.release(due.domain, due.cadence_seconds)
        return True

    card = score(records, seconds=time.monotonic() - started, cost_usd=cost)
    run = catalog.latest_run(due.domain)
    if run:
        catalog.save_scorecard(run["id"], due.domain, card)
    log(
        f"{due.domain} {card.products} products, "
        f"{'PASS' if card.required_ok else 'FAIL ' + ','.join(card.required_gaps)}, "
        f"{card.fields_filled:.0%} fields, {card.images_per_product} img/product, "
        f"${card.cost_usd}, {card.seconds_per_product}s/product"
    )
    scheduler.release(due.domain, due.cadence_seconds)
    return True


def worker(db_path: Path, worker_id: str, do_brand_factory, version: str, log=print) -> None:
    """One worker: claim, scrape, release, until told to stop or the code changes."""
    catalog = Catalog(db_path)
    scheduler = Scheduler(catalog, worker_id=worker_id)
    do_brand = do_brand_factory(catalog)
    try:
        while not scheduler.should_stop():
            if code_version() != version:
                log(f"{worker_id}: code changed, standing down for the new version")
                return
            if not run_once(catalog, scheduler, do_brand, log=log):
                time.sleep(POLL_SECONDS)
    finally:
        catalog.close()


def serve(db_path: Path, do_brand_factory, workers: int = 1, log=print) -> None:
    """Run N workers over one schedule until the stop flag is set."""
    version = code_version()
    catalog = Catalog(db_path)
    Scheduler(catalog).set_code_version(version)
    catalog.close()
    log(f"daemon up: {workers} worker(s) on {version[:8]} at {datetime.now(timezone.utc):%H:%M}")

    threads = [
        threading.Thread(
            target=worker,
            args=(db_path, f"worker-{i + 1}", do_brand_factory, version),
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
