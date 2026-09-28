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
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

from backend.archive.connectors.base import ChannelBusy
from backend.archive.recommend import recommend
from backend.archive.scheduler import Scheduler
from backend.archive.score import score
from backend.archive.store.catalog import Catalog
from backend.archive.store.factory import open_catalog
from backend.archive.store.objects import ObjectStore

POLL_SECONDS = 10
# A run that has written no position for this long is reported with its stack.
STUCK_AFTER_SECONDS = 600
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
# The container's memory, in MB, above which the daemon finishes the brands it is on
# and exits so Render starts a fresh one. The instance has 2 GiB; on 2026-09-28 the
# worker climbed from 0.9 to 2.0 GB over eight hours and was killed by the host, which
# takes whatever run is in flight with it. Leaving on our own terms loses nothing.
MEMORY_RESTART_MB = int(os.environ.get("ARCHIVE_MEMORY_RESTART_MB", "1600"))


def _iso_ago(seconds: int) -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


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


def memory_mb(root: str = "/sys/fs/cgroup") -> float | None:
    """What the container holds, as the host counts it before killing: all memory
    charged to the cgroup less the file cache it can drop. Chromium's processes are
    in the same cgroup, which is why this is read here and not from our own RSS.
    None outside a container."""
    for current, stat, cache_key in (
        ("memory.current", "memory.stat", "inactive_file"),  # cgroup v2
        ("memory/memory.usage_in_bytes", "memory/memory.stat", "total_inactive_file"),
    ):
        try:
            with open(f"{root}/{current}") as f:
                used = int(f.read().strip())
            cache = 0
            with open(f"{root}/{stat}") as f:
                for line in f:
                    key, _, value = line.partition(" ")
                    if key == cache_key:
                        cache = int(value)
            return (used - cache) / 2**20
        except (OSError, ValueError):
            continue
    return None


def give_back() -> None:
    """Hand freed heap back to the host. glibc keeps what a large brand's run freed
    for reuse, so a finished run still counted against the 2 GiB until this."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # not glibc (a Mac checkout): nothing to hand back this way


def _held() -> str:
    """The container's memory as a log suffix, so a climb can be pinned on the brand
    run or the learning tick that made it (the 2026-09-28 leak)."""
    held = memory_mb()
    return "" if held is None else f", holding {held:.0f} MB"


def superseded(mine: str, stored: str | None) -> bool:
    """Whether a newer daemon has announced itself. Only two real versions count."""
    return bool(mine and stored) and mine != "unknown" and stored != "unknown" and mine != stored


def run_once(catalog: Catalog, scheduler: Scheduler, do_brand, log=print, before=None) -> bool:
    """Claim one due brand and scrape it. False when nothing was due.

    `before(domain)` runs once the brand is claimed and before it is scraped: the
    learning loop uses it to onboard a brand that has no dossier yet, so the deck
    watches the probe, the signature and the wall before the first run's progress."""
    due = scheduler.claim_next()
    if due is None:
        return False
    started = time.monotonic()
    brand = catalog.get_brand(due.domain)
    beat_off = threading.Event()
    if before is not None:
        try:
            before(due.domain)
        except Exception as e:  # noqa: BLE001 — onboarding must never cost the run
            log(f"{due.domain}: before-run hook: {type(e).__name__}: {e}")

    run_thread = threading.current_thread()

    def beat() -> None:
        while not beat_off.wait(HEARTBEAT_SECONDS):
            try:
                scheduler.touch(due.domain)
                # The worker's own liveness too: it is written per poll, and a run
                # is longer than the window between polls.
                scheduler.beat_worker(scheduler.worker_id)
            except Exception:  # a missed beat is survivable; a dead worker is not
                pass
            # A beat proves this thread breathes, not that the run moves. When the
            # brand has written no position for a while, say where the run's thread
            # is standing, so a hang names its own cause in the log.
            try:
                p = catalog.load_progress(due.domain) or {}
                stale = (p.get("updated_at") or "") < _iso_ago(STUCK_AFTER_SECONDS)
                if stale:
                    frames = sys._current_frames().get(run_thread.ident or -1)
                    where = "".join(traceback.format_stack(frames)[-6:]) if frames else "?"
                    log(
                        f"{due.domain}: no progress for {STUCK_AFTER_SECONDS // 60}m; run thread at:\n{where}"
                    )
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=beat, daemon=True).start()
    learning = due.mode == "learn"
    sweeping = due.mode == "sweep"
    try:
        if learning:
            records, cost = do_brand(brand, mode="learn", retry_searched=due.retry_searched)
        elif sweeping:
            records, cost = do_brand(brand, mode="sweep")
        else:
            # "full" when the row asked for one (run now with the full option, or the
            # CLI); every other turn is a delta. Dropping the mode here is why a
            # queued full run for Entire Studios came out as a delta (2026-09-25).
            records, cost = do_brand(brand, mode="full") if due.mode == "full" else do_brand(brand)
    except ChannelBusy as e:
        # Not a failure of the brand or of our code: the host wants us to wait, and it
        # must not consume the brand's turn in the rotation.
        log(f"{due.domain} busy: {e}")
        beat_off.set()
        if learning:
            scheduler.release_after_learn(due.domain, not_before=BUSY_BACKOFF)
        elif sweeping:
            scheduler.release_after_sweep(due.domain, not_before=BUSY_BACKOFF)
        else:
            scheduler.defer(due.domain, BUSY_BACKOFF)
        return True
    except Exception as e:  # one hostile site must never stop the loop
        log(f"{due.domain} crashed: {type(e).__name__}: {e}")
        beat_off.set()
        if learning:
            scheduler.release_after_learn(due.domain)
        elif sweeping:
            scheduler.release_after_sweep(due.domain)
        else:
            scheduler.release(due.domain, due.cadence_seconds)
        return True

    beat_off.set()
    if sweeping:
        # No scorecard and no photographs: only stock moved, and the brand's real
        # turn is where it was. The run row says what was checked and what changed.
        run = catalog.latest_run(due.domain) or {}
        log(
            f"{due.domain} sweep done: {run.get('checked', 0)} checked, "
            f"{run.get('changed', 0)} changed, {run.get('seconds', 0)} s"
        )
        scheduler.release_after_sweep(due.domain)
        catalog.release_products(due.domain)
        return True
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
        f"${card.cost_usd}, {card.seconds_per_product}s/product{_held()}"
    )
    streak, reason = catalog.attention(due.domain)
    wait = backoff(due.cadence_seconds, streak)
    if wait != due.cadence_seconds:
        log(f"{due.domain} needs a human ({streak} runs: {reason}); next look in {wait // 3600}h")
    scheduler.release(due.domain, wait)


def learner(store_factory, loop_factory, version: str, every: int, log=print, drain=None) -> None:
    """The learning loop's own thread: one tick every `every` seconds, until the daemon
    stops or a newer one is up. A tick that fails is logged and the next one runs;
    the loop is bookkeeping and probing, never the scrape itself."""
    store: ObjectStore = store_factory()
    catalog = open_catalog(store)
    scheduler = Scheduler(store)
    loop = loop_factory(store, catalog)
    try:
        while True:
            if scheduler.should_stop() or superseded(version, scheduler.code_version()):
                return
            if drain is not None and drain.is_set():
                return
            try:
                summary = loop.tick()
                log(
                    f"learn: {len(summary.get('onboarded', []))} onboarded, "
                    f"{len(summary.get('actions', []))} actions, "
                    f"{len(summary.get('analyses', []))} analyses, "
                    f"{len(summary.get('landed', []))} landed, {summary.get('seconds')}s"
                    f"{_held()}"
                )
            except Exception as e:  # noqa: BLE001
                log(f"learn: tick failed: {type(e).__name__}: {e}")
            # Sleep in short steps so a stop flag is seen within a poll.
            for _ in range(max(1, every // POLL_SECONDS)):
                if scheduler.should_stop() or (drain is not None and drain.is_set()):
                    return
                time.sleep(POLL_SECONDS)
    finally:
        catalog.close()


def worker(
    store_factory,
    worker_id: str,
    do_brand_factory,
    version: str,
    log=print,
    before_factory=None,
    drain=None,
    memory=memory_mb,
) -> None:
    """One worker: claim, scrape, release, until told to stop or the code changes.

    Each worker builds its own store, because a store holds a network client and the
    workers are threads."""
    from backend.archive.backup import daily_backup

    store: ObjectStore = store_factory()
    catalog = open_catalog(store)
    scheduler = Scheduler(store, worker_id=worker_id)
    do_brand = do_brand_factory(catalog)
    before = before_factory(store, catalog) if before_factory is not None else None
    # The date this worker last looked at the backup claim. It looks once per day,
    # not once per poll: the claim is one object in the bucket and every worker
    # reading it every ten seconds would be most of the daemon's requests.
    backup_day: str | None = None
    try:
        while True:
            try:
                if scheduler.should_stop():
                    return
                if superseded(version, scheduler.code_version()):
                    log(f"{worker_id}: a newer daemon is up; standing down")
                    return
                if drain is not None:
                    held = memory()
                    if held is not None and held > MEMORY_RESTART_MB and not drain.is_set():
                        log(
                            f"{worker_id}: container holds {held:.0f} MB "
                            f"(limit {MEMORY_RESTART_MB}); restarting between brands"
                        )
                        drain.set()
                    if drain.is_set():
                        return
                # Seen recently, by the deck: a thread that died used to be invisible.
                scheduler.beat_worker(worker_id)
                today = datetime.now(timezone.utc).date().isoformat()
                if today != backup_day:
                    backup_day = today
                    # The first worker to see the date change takes the day's backup;
                    # the claim on control/backup.json is what stops a second one.
                    daily_backup(store, catalog, worker_id, log=log)
                if run_once(catalog, scheduler, do_brand, log=log, before=before):
                    give_back()
                else:
                    time.sleep(POLL_SECONDS)
            except Exception as e:  # noqa: BLE001 — a transient must not end the worker
                # Before this, any store error outside do_brand (a 503 from the
                # bucket, a timeout) ended the thread for good, and one dead worker
                # halved the fleet with nothing on the deck to say so.
                log(f"{worker_id}: {type(e).__name__}: {e}; carrying on in 30s")
                time.sleep(30)
    finally:
        catalog.close()


def serve(
    store_factory,
    do_brand_factory,
    workers: int = 1,
    log=print,
    loop_factory=None,
    before_factory=None,
    learn_every: int = 900,
) -> None:
    """Run N workers over one schedule until the stop flag is set.

    Takes a callable that makes a store rather than a directory, because in production
    the store is a bucket and a bucket has no path on disk. With a `loop_factory` the
    learning loop ticks in a thread of its own beside the workers."""
    version = code_version()
    Scheduler(store_factory()).set_code_version(version)
    # Set by the first worker to see memory over the limit: each thread stops at its
    # next gap between brands, serve returns, the process exits and Render restarts it.
    drain = threading.Event()
    held = memory_mb()
    log(
        f"memory: {'unreadable, no restart guard' if held is None else f'{held:.0f} MB'}"
        f" (restart above {MEMORY_RESTART_MB} MB)"
    )
    log(
        f"daemon up: {workers} worker(s){' + learning loop' if loop_factory else ''} "
        f"on {version[:8]} at {datetime.now(timezone.utc):%H:%M}"
    )

    threads = [
        threading.Thread(
            target=worker,
            args=(store_factory, f"worker-{i + 1}", do_brand_factory, version),
            kwargs={"log": log, "before_factory": before_factory, "drain": drain},
            daemon=True,
        )
        for i in range(workers)
    ]
    if loop_factory is not None:
        threads.append(
            threading.Thread(
                target=learner,
                args=(store_factory, loop_factory, version, learn_every),
                kwargs={"log": log, "drain": drain},
                daemon=True,
            )
        )
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log("daemon down" + (" to shed memory" if drain.is_set() else ""))
