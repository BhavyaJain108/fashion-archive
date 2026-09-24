"""A sweep: what is in stock, and at what price, from the cheapest source there is.

Sizes in stock are the one thing about a product that changes hourly, and a delta
run answers that question by re-reading product pages and photographs. A sweep reads
only the bulk feed the brand's plan already uses — Shopify's `/products.json`
(with the same `country=` market the connector always sends) or WooCommerce's Store
API — and writes the stock fields of products the catalogue already holds. No
product pages, no images, no finder, no probing, and it never adds or removes a
product: a product the feed has and the catalogue does not is the next delta run's.

A brand on the structured-data lane has no such feed. It is skipped with the reason
written on the run row, and nothing is fetched.

A sweep is not a covered run. The run row carries no coverage, so the reference run
stays where it was and `last_covered_run` is untouched; the row says only what was
checked, what changed, and how long it took.
"""

import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from backend.archive.connectors import get_connector
from backend.archive.connectors.base import ChannelBlocked, ChannelBusy, SkipProduct
from backend.archive.domain.brand import Brand, DiscoveryChannel, TransportLevel, shop_target
from backend.archive.runner.run import _take_lock
from backend.archive.store.catalog import STOCK_FIELDS, Catalog
from backend.archive.transport import for_level

# The lanes whose discovery response already states stock: one feed page carries
# every variant's `available` and price. Anything else would need product pages.
CHEAP_STOCK_LANES = (DiscoveryChannel.BULK_JSON, DiscoveryChannel.WOO_API)
NO_CHEAP_SOURCE = "no cheap stock source"


def stock_update(record) -> dict:
    """The stock fields of one fresh record, in the shape update_stock takes.
    `size_info` rides along so the catalogue can tell whether the sizes moved."""
    out = {"itemurl": record.itemurl, "size_info": record.size_info}
    for field in STOCK_FIELDS:
        out[field] = getattr(record, field, None)
    out["offers"] = record.offers
    return out


def sweep_brand(
    brand: Brand,
    catalog: Catalog,
    transport,
    locks_dir: Path = Path("locks"),
    log_dir: Path = Path("logs/runs"),
    connector_factory=get_connector,
    transport_factory=for_level,
    browser_transport_factory=None,
    clock=time.monotonic,
) -> int:
    """One sweep of one brand. 0 when the stock was read (or the brand has no cheap
    source and was skipped), 1 when the feed could not be read, 2 on a crash."""
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock = locks_dir / f"{brand.domain}.lock"
    if not _take_lock(lock):
        return 0  # a live run holds the brand; overlap is a skip, not an alarm

    work_transport = transport
    started = clock()
    run_id = catalog.open_run(brand.domain, "sweep")
    log_path = log_dir / brand.domain / f"{run_id}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(event: str, **kw) -> None:
        with log_path.open("a") as f:
            f.write(
                json.dumps({"t": datetime.now(timezone.utc).isoformat(), "event": event, **kw})
                + "\n"
            )

    def skip(reason: str, status: int = 0) -> int:
        catalog.finalize_run(run_id, status, None, domain=brand.domain)
        catalog.annotate_run(brand.domain, run_id, reason=reason, checked=0, changed=0)
        log("sweep-skipped", reason=reason)
        return status

    try:
        # The plan is read, never made: a sweep is not a diagnosis, and a brand with
        # no plan yet has no catalogue to update either.
        plan = catalog.load_plan(brand.domain)
        if plan is None or plan.status != "ready":
            return skip("no working plan yet — run a delta first")
        if plan.discovery not in CHEAP_STOCK_LANES:
            return skip(NO_CHEAP_SOURCE)
        if plan.transport == TransportLevel.T1:
            work_transport = transport_factory(TransportLevel.T1)
        elif plan.transport == TransportLevel.T2:
            if browser_transport_factory is None:
                return skip("the feed needs a browser and none is available")
            work_transport = browser_transport_factory()

        connector = connector_factory(plan)
        try:
            refs = connector.discover(shop_target(brand, plan), work_transport)
        except ChannelBusy as e:
            # The host wants us to wait. The daemon hears this and holds the next
            # sweep back; the brand's real turn is not touched.
            catalog.finalize_run(run_id, 1, None, domain=brand.domain)
            catalog.annotate_run(brand.domain, run_id, reason=f"host asked us to wait: {e}")
            log("channel-busy", reason=str(e))
            raise
        except ChannelBlocked as e:
            # Not a verdict on the plan: a feed refused once is the delta run's to
            # diagnose, with the ladder and the probe. Say so and stop.
            return skip(f"feed blocked: {e}", status=1)
        log("discovered", refs=len(refs))

        updates = []
        for ref in refs:
            try:
                rec = connector.fetch(ref, work_transport)  # the feed payload, no request
            except SkipProduct:
                continue
            updates.append(stock_update(rec))
        changed = catalog.update_stock(brand.domain, run_id, updates)
        seconds = round(clock() - started, 1)
        catalog.annotate_run(
            brand.domain, run_id, checked=len(updates), changed=changed, seconds=seconds
        )
        catalog.finalize_run(run_id, 0, None, domain=brand.domain)
        log("swept", checked=len(updates), changed=changed, seconds=seconds)
        return 0
    except ChannelBusy:
        raise
    except Exception as e:  # noqa: BLE001 — one hostile site must never kill the fleet
        catalog.finalize_run(run_id, 2, None, domain=brand.domain)
        catalog.annotate_run(brand.domain, run_id, reason=f"crashed: {type(e).__name__}: {e}"[:200])
        log(
            "run-crashed",
            error=f"{type(e).__name__}: {e}",
            where=traceback.format_exc().strip().splitlines()[-12:],
        )
        return 2
    finally:
        if work_transport is not transport and hasattr(work_transport, "close"):
            work_transport.close()
        try:
            if log_path.exists():
                catalog.save_run_log(brand.domain, run_id, log_path.read_text())
        except Exception:  # noqa: BLE001
            pass
        lock.unlink(missing_ok=True)
