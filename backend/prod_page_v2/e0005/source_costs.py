"""
Global source-cost table.

Cost is a property of the **method kind** (where the data comes from), not the
field. Two fields fetched from the same source share the same cost. The
orchestrator uses these numbers to pick the cheapest verified method when a
field has multiple catalog rows.

Two sources of cost data, in this order of preference:

1. `measured_costs_ms` on the SiteCatalog — empirical timings recorded during
   discovery or first production run. Per-website, since e.g. one site's
   Shopify endpoint might be on a CDN edge (50ms) and another's might hit
   origin (400ms).

2. `STATIC_SOURCE_COST_MS` — sensible defaults applied when no measurement
   exists yet.
"""

from __future__ import annotations

import time
from typing import Dict, Optional


# Approximate per-call latency in milliseconds for each method kind, when no
# per-website measurement is available. These reflect amortized cost — i.e.
# `shopify_product_json` is 200ms even though its HTTP cost is shared across
# every field that uses it; we attribute the full cost to the method kind so
# ranking treats every Shopify-served field consistently.
STATIC_SOURCE_COST_MS: Dict[str, float] = {
    # Pure parse over cached raw HTML — bounded by string length.
    "ld_json_path":           2.0,
    "ld_json_images":         2.0,
    "ld_json_offers_availability": 2.0,
    "og_meta":                2.0,
    "url_pattern":            1.0,  # regex over memo.url; allowed only for product_code

    # Local file or in-memory lookup.
    "nav_tree":               5.0,

    # One HTTP call amortized across all fields it serves.
    "shopify_product_json":   200.0,

    # One HTTP call to a brand's product API (availability / variants /
    # pricing endpoints discovered from the network log). Amortized across
    # every field served from the same endpoint.
    "network_api":            150.0,

    # Playwright queries after the page is already rendered.
    "dom_selector":           50.0,
    "dom_attr":               50.0,

    # In-memory scan of captured network log.
    "network_images":         5.0,

    # Click + wait + read.
    "accordion_read":         600.0,

    # Combine multiple inner methods with a template. Cost is the SUM of
    # the inner methods' costs in practice; the orchestrator can't see that
    # so we use a representative-bucket cost here.
    "compose":                60.0,

    # Per-product LLM call (batched across all fallback fields). Paid once
    # per product; high relative cost so it sorts to the bottom.
    "llm_batch_extraction":   1500.0,
}


# Cost class label — coarse buckets used for human-readable reports.
def cost_class(method_kind: str, measured: Optional[Dict[str, float]] = None) -> str:
    """Return a short label for the cost bucket of `method_kind`."""
    ms = source_cost_ms(method_kind, measured)
    if ms <= 5:
        return "instant"
    if ms <= 100:
        return "fast"
    if ms <= 400:
        return "medium"
    return "slow"


def source_cost_ms(method_kind: str, measured: Optional[Dict[str, float]] = None) -> float:
    """Return the latency cost in ms for `method_kind`, preferring a per-site
    measurement when available, falling back to the static default. Unknown
    methods get a high default so they sort last."""
    if measured and method_kind in measured:
        return float(measured[method_kind])
    return STATIC_SOURCE_COST_MS.get(method_kind, 1000.0)


# ---------------------------------------------------------------------------
# Lightweight timer for capturing per-site measurements during discovery
# ---------------------------------------------------------------------------

class CostMeter:
    """Accumulates timings per method kind for one discovery run.

    Wrap each method invocation with `with meter.time(kind):` to record. At
    the end of discovery, call `meter.average()` and stash the result on the
    SiteCatalog's site_meta["measured_costs_ms"].
    """

    def __init__(self):
        self._samples: Dict[str, list[float]] = {}

    class _Span:
        def __init__(self, meter: "CostMeter", kind: str):
            self.meter = meter
            self.kind = kind
            self.t0 = 0.0

        def __enter__(self):
            self.t0 = time.perf_counter()
            return self

        def __exit__(self, *_):
            elapsed_ms = (time.perf_counter() - self.t0) * 1000.0
            self.meter._samples.setdefault(self.kind, []).append(elapsed_ms)

    def time(self, kind: str) -> "_Span":
        return CostMeter._Span(self, kind)

    def average(self) -> Dict[str, float]:
        return {k: round(sum(v) / len(v), 2) for k, v in self._samples.items() if v}
