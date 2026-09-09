"""Capability probing: how well does the scraper work on a brand, measured on a small sample.

The unit of success here is a brand type conquered, not products banked. This never writes
to the catalog — it fetches a handful of products, measures field quality, and returns a
verdict. Cheap enough to run across the whole fleet in minutes.
"""

from dataclasses import dataclass, field

from backend.archive.connectors import get_connector
from backend.archive.connectors.base import ChannelBlocked, SkipProduct
from backend.archive.domain.brand import Brand, Capability, ScrapePlan
from backend.archive.fingerprint import probe
from backend.archive.planner import compose_plan
from backend.archive.verify import field_fill_rates

CORE_FIELDS = ("product_title", "price", "in_stock", "all_images")


@dataclass
class CapabilityReport:
    domain: str
    lane: str = "-"
    verdict: str = "untested"  # full | partial | poor | blocked | gated | unreachable
    catalog_size: int | None = None
    sampled: int = 0
    fill: dict[str, float] = field(default_factory=dict)
    note: str = ""
    requests: int = 0
    seconds: float = 0.0

    def core_fill(self) -> float:
        if not self.fill:
            return 0.0
        return min(self.fill.get(f, 0.0) for f in CORE_FIELDS)


def classify(fill: dict[str, float]) -> str:
    """full = core fields AND sizes; partial = core only; poor = core incomplete."""
    if not fill:
        return "poor"
    core = min(fill.get(f, 0.0) for f in CORE_FIELDS)
    if core < 0.9:
        return "poor"
    return "full" if fill.get("size_info", 0.0) >= 0.9 else "partial"


def probe_brand(
    brand: Brand,
    transport,
    sample: int = 5,
    browser: bool = False,
    prober=probe,
    composer=compose_plan,
    connector_factory=get_connector,
) -> CapabilityReport:
    """Fingerprint → plan → fetch `sample` products → measure. Writes nothing."""
    rep = CapabilityReport(domain=brand.domain)
    try:
        cap: Capability = prober(brand.domain, transport)
        plan: ScrapePlan = composer(cap, browser=browser)
        rep.lane = plan.composition
        if plan.status == "skip_gated":
            rep.verdict, rep.note = "gated", "store is password-gated"
            return rep
        if plan.status != "ready":
            rep.verdict = "blocked"
            rep.note = "no lane: " + ", ".join(f"{k}={v}" for k, v in cap.evidence.items())
            return rep

        connector = connector_factory(plan)
        try:
            refs = connector.discover(brand, transport)
        except ChannelBlocked as e:
            rep.verdict, rep.note = "blocked", f"discover: {e}"
            return rep
        rep.catalog_size = len(refs)

        records, errs = [], []
        for r in refs[:sample]:
            try:
                records.append(connector.fetch(r, transport))
            except SkipProduct as e:
                errs.append(str(e))
            except Exception as e:  # noqa: BLE001 — a probe reports failures, never raises
                errs.append(f"{type(e).__name__}: {e}")
        rep.sampled = len(records)
        rep.fill = {k: round(v, 2) for k, v in field_fill_rates(records).items()}
        rep.verdict = classify(rep.fill) if records else "blocked"
        if errs and not records:
            rep.note = f"fetch: {errs[0][:80]}"
        elif errs:
            rep.note = f"{len(errs)} of {len(errs) + len(records)} samples failed"
    except Exception as e:  # noqa: BLE001
        rep.verdict, rep.note = "unreachable", f"{type(e).__name__}: {e}"[:100]
    finally:
        rep.requests = len(getattr(transport, "ledger", []))
    return rep


def format_matrix(reports: list[CapabilityReport], show_gated: bool = False) -> str:
    """The capability matrix: one row per brand, worst verdicts last.

    Password-gated stores are collapsed to a footnote by default — there is nothing to
    measure until they open, and five identical rows every run is noise.
    """
    order = {"full": 0, "partial": 1, "poor": 2, "blocked": 3, "gated": 4, "unreachable": 5}
    shown = reports if show_gated else [r for r in reports if r.verdict != "gated"]
    rows = sorted(shown, key=lambda r: (order.get(r.verdict, 9), r.domain))
    cols = ("product_title", "price", "in_stock", "size_info", "all_images")
    head = (
        f"{'BRAND':<26}{'LANE':<34}{'CAT':>7}  "
        + "".join(f"{c.split('_')[-1][:5].upper():>6}" for c in cols)
        + "  VERDICT   NOTE"
    )
    out = [head, "-" * len(head)]
    for r in rows:
        cells = "".join(f"{(f'{r.fill[c]:.0%}' if c in r.fill else '-'):>6}" for c in cols)
        cat = str(r.catalog_size) if r.catalog_size is not None else "-"
        out.append(
            f"{r.domain:<26}{r.lane[:33]:<34}{cat:>7}  {cells}  {r.verdict:<9} {r.note[:44]}"
        )
    tally: dict[str, int] = {}
    for r in reports:
        tally[r.verdict] = tally.get(r.verdict, 0) + 1
    out.append("")
    out.append(
        "  ".join(f"{k}={v}" for k, v in sorted(tally.items(), key=lambda kv: order.get(kv[0], 9)))
    )
    gated = [r.domain for r in reports if r.verdict == "gated"]
    if gated and not show_gated:
        out.append(f"gated (watched, nothing to measure yet): {', '.join(sorted(gated))}")
    return "\n".join(out)
