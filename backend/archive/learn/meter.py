"""What a brand costs, in the units the walls are priced in.

Requests and bytes by rung, requests through the proxy, seconds in a browser, model
calls and their tokens, wall-clock. Dollars are a view over those — each unit times
its price — so a price change never re-costs history, and the deck can say *which*
resource a brand is heavy on rather than only that it is.

The transports already keep a ledger of every request they made. A Meter is handed
each transport a run builds and reads the ledgers when the run is over; nothing in the
request path changes.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.archive.domain.brand import DiscoveryChannel, FetchChannel, TransportLevel

# --- unit prices ---------------------------------------------------------------------
# Set the ones the owner pays; the defaults are what a request costs when nobody is
# charging for it: the bytes and the seconds, priced at what a small worker costs.


@dataclass(frozen=True)
class Prices:
    proxy_usd_per_1k: float = 0.0  # what the egress proxy charges per thousand requests
    browser_usd_per_second: float = 0.0  # a worker-second with Chromium open
    usd_per_gb: float = 0.0  # egress, when the host charges for it
    worker_usd_per_second: float = 0.0  # the worker's own time, whatever it does

    @classmethod
    def from_env(cls) -> Prices:
        def f(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, "") or default)
            except ValueError:
                return default

        return cls(
            proxy_usd_per_1k=f("ARCHIVE_PRICE_PROXY_USD_PER_1K", 0.0),
            browser_usd_per_second=f("ARCHIVE_PRICE_BROWSER_USD_PER_SECOND", 0.0),
            usd_per_gb=f("ARCHIVE_PRICE_USD_PER_GB", 0.0),
            worker_usd_per_second=f("ARCHIVE_PRICE_WORKER_USD_PER_SECOND", 0.0),
        )


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --- one run's resources ---------------------------------------------------------------


@dataclass
class Meter:
    """Counts what a piece of work used. Hand it every transport the work builds."""

    prices: Prices = field(default_factory=Prices.from_env)
    _transports: list = field(default_factory=list)
    llm_calls: int = 0
    llm_tokens: int = 0
    llm_usd: float = 0.0
    wall_seconds: float = 0.0
    runs: int = 0
    probes: int = 0

    def track(self, transport):
        if transport is not None and transport not in self._transports:
            self._transports.append(transport)
        return transport

    def note_llm(self, usd: float, calls: int = 1, tokens: int = 0) -> None:
        self.llm_usd += float(usd)
        self.llm_calls += int(calls)
        self.llm_tokens += int(tokens)

    def snapshot(self) -> dict:
        requests: dict[str, int] = {}
        nbytes: dict[str, int] = {}
        proxy = 0
        browser_seconds = 0.0
        for t in self._transports:
            level = getattr(t, "level", TransportLevel.T0)
            level = level.value if hasattr(level, "value") else str(level)
            rows = getattr(t, "ledger", None) or []
            requests[level] = requests.get(level, 0) + len(rows)
            nbytes[level] = nbytes.get(level, 0) + sum(int(r.get("bytes") or 0) for r in rows)
            if level == TransportLevel.T1P.value:
                proxy += len(rows)
            if level == TransportLevel.T2.value:
                browser_seconds += sum(float(r.get("seconds") or 0.0) for r in rows)
        out = {
            "requests": requests,
            "bytes": nbytes,
            "proxy_requests": proxy,
            "browser_seconds": round(browser_seconds, 3),
            "llm_calls": self.llm_calls,
            "llm_tokens": self.llm_tokens,
            "llm_usd": round(self.llm_usd, 6),
            "wall_seconds": round(self.wall_seconds, 3),
            "runs": self.runs,
            "probes": self.probes,
        }
        out["usd"] = cost_usd(out, self.prices)
        return out


def cost_usd(snapshot: dict, prices: Prices) -> float:
    """Price a snapshot. LLM spend is already dollars; the rest is units × price."""
    usd = float(snapshot.get("llm_usd") or 0.0)
    usd += int(snapshot.get("proxy_requests") or 0) * prices.proxy_usd_per_1k / 1000.0
    usd += float(snapshot.get("browser_seconds") or 0.0) * prices.browser_usd_per_second
    total_bytes = sum(int(v) for v in (snapshot.get("bytes") or {}).values())
    usd += total_bytes / 1e9 * prices.usd_per_gb
    usd += float(snapshot.get("wall_seconds") or 0.0) * prices.worker_usd_per_second
    return round(usd, 6)


# --- what a brand should cost -----------------------------------------------------------

# Seconds a browser spends on one page, measured on Gentle Monster (learning 14).
BROWSER_SECONDS_PER_PAGE = 3.0
# Bytes a request costs, by what it fetches: a feed page of 250 products, a product
# page, a sitemap file. Rough, and honest about being rough — the measured meter
# replaces the estimate after two cycles.
_FEED_PAGE_BYTES = 400_000
_PRODUCT_PAGE_BYTES = 300_000
_JSON_BYTES = 20_000
_SITEMAP_BYTES = 200_000


def requests_per_check(discovery: str, fetch: str, products: int, full: bool) -> tuple[int, int]:
    """(requests, bytes) one check of the brand costs on this lane. A check that is not
    full reads only what changed, which the change signal decides; the estimate takes
    a tenth of the catalogue as the moving part."""
    products = max(int(products or 0), 1)
    read = products if full else max(1, math.ceil(products / 10))
    if discovery == DiscoveryChannel.BULK_JSON.value:
        pages = math.ceil(products / 250) + 1
        return pages, pages * _FEED_PAGE_BYTES
    if discovery == DiscoveryChannel.WOO_API.value:
        pages = math.ceil(products / 100) + 1
        return pages, pages * _JSON_BYTES * 5
    if discovery == DiscoveryChannel.PAGE_DATA.value:
        return 1 + read, _JSON_BYTES * (1 + read)
    # sitemap-based: the sitemap files, then one request per product read
    sitemap_files = 1 + math.ceil(products / 5000)
    if fetch == FetchChannel.PLATFORM_JSON.value:
        return sitemap_files + read, sitemap_files * _SITEMAP_BYTES + read * _JSON_BYTES
    return sitemap_files + read, sitemap_files * _SITEMAP_BYTES + read * _PRODUCT_PAGE_BYTES


def predict(
    products: int,
    composition: str | None,
    cadence_seconds: int | None,
    sweep_seconds: int | None,
    prices: Prices,
    measured_per_check_usd: float | None = None,
) -> dict:
    """What this brand should cost per check and per day on its lane and cadences.

    A measured figure, when the meter has one, replaces the estimate for the per-check
    cost; the per-day figure still comes from the cadences, which are ours to set.
    """
    transport, discovery, fetch = (
        "t0",
        DiscoveryChannel.SITEMAP.value,
        FetchChannel.STRUCTURED_DATA.value,
    )
    if composition:
        parts = composition.split("×")
        if len(parts) >= 3:
            transport, discovery, fetch = parts[0], parts[1], parts[2]
    reqs, nbytes = requests_per_check(discovery, fetch, products, full=False)
    full_reqs, full_bytes = requests_per_check(discovery, fetch, products, full=True)
    snapshot = {
        "requests": {transport: reqs},
        "bytes": {transport: nbytes},
        "proxy_requests": reqs if transport == TransportLevel.T1P.value else 0,
        "browser_seconds": reqs * BROWSER_SECONDS_PER_PAGE
        if transport == TransportLevel.T2.value
        else 0.0,
        "llm_usd": 0.0,
        "wall_seconds": reqs
        * (BROWSER_SECONDS_PER_PAGE if transport == TransportLevel.T2.value else 0.5),
    }
    per_check = cost_usd(snapshot, prices)
    if measured_per_check_usd is not None:
        per_check = float(measured_per_check_usd)
    checks_per_day = 86_400 / cadence_seconds if cadence_seconds else 1.0
    sweeps_per_day = 86_400 / sweep_seconds if sweep_seconds else 0.0
    # A sweep re-reads the cheapest stock source; on a feed it is the feed, on a
    # page lane it is the sitemap and only what changed. Priced as a delta check.
    per_day = per_check * checks_per_day + per_check * 0.5 * sweeps_per_day
    return {
        "composition": composition,
        "products": int(products or 0),
        "per_check_requests": reqs,
        "per_check_bytes": nbytes,
        "per_full_requests": full_reqs,
        "per_full_bytes": full_bytes,
        "per_check_usd": round(per_check, 6),
        "per_product_usd": round(per_check / max(int(products or 0), 1), 8),
        "checks_per_day": round(checks_per_day + sweeps_per_day, 3),
        "per_day_usd": round(per_day, 6),
        "measured": measured_per_check_usd is not None,
    }
