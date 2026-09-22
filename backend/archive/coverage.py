"""S7 — LEARN: which of the 42 E0005 fields a brand actually gives up.

This is where the improvement loop starts, and it is deliberately a command rather than
something someone has to write for themselves. S6 (`capability`) reports five columns and
they all read 100% long before the record is any good; the first time the whole field set
was measured at once, most of them were empty and nobody knew. A number that only covers what
already works cannot tell you what to do next.

    python -m backend.archive.runner.cli coverage --shown

Read a column downwards to see what one brand withholds, and a row across to see what no
brand gives us — a row of zeros is either a field nothing publishes, or a rule waiting to
be written. `access/LEARNINGS.md` says how to tell the difference and how to add one.
"""

from backend.archive.connectors import get_connector
from backend.archive.connectors.base import ChannelBlocked, SkipProduct
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import E0005_FIELDS
from backend.archive.escalate import escalating_prober
from backend.archive.planner import compose_plan
from backend.archive.transport import for_level

EMPTY: tuple[object, ...] = (None, "", [], {})


def field_coverage(
    brand: Brand,
    transport,
    sample: int = 5,
    prober=None,
    composer=compose_plan,
    connector_factory=get_connector,
    transport_factory=for_level,
) -> tuple[dict[str, float], int, str]:
    """Fill rate per E0005 field over a sample of products. Writes nothing.

    Returns (fill, catalogue size, note). A brand we cannot read returns an empty dict
    and says why, rather than a row of zeros that reads like a brand publishing nothing.
    """
    prober = prober or escalating_prober()
    try:
        cap = prober(brand.domain, transport)
        plan = composer(cap)
        if plan.status != "ready":
            return {}, 0, plan.status
        work = transport
        if plan.transport != getattr(transport, "level", plan.transport):
            work = transport_factory(plan.transport)
        try:
            connector = connector_factory(plan)
            refs = connector.discover(brand, work)
            records = []
            for ref in refs[:sample]:
                try:
                    records.append(connector.fetch(ref, work))
                except (SkipProduct, ChannelBlocked):
                    continue
                except Exception:  # noqa: BLE001 — one bad product is not a verdict
                    continue
            if not records:
                return {}, len(refs), "no products read"
            fill = {
                f: sum(1 for r in records if getattr(r, f, None) not in EMPTY) / len(records)
                for f in E0005_FIELDS
            }
            return fill, len(refs), ""
        finally:
            if work is not transport and hasattr(work, "close"):
                work.close()
    except Exception as e:  # noqa: BLE001 — a report never raises
        return {}, 0, f"{type(e).__name__}: {e}"[:60]


def format_coverage(rows: dict[str, tuple[dict[str, float], int, str]]) -> str:
    """One column per brand, one row per field, and the rows nobody fills marked."""
    if not rows:
        return "nothing measured"
    names = list(rows)
    width = max(12, min(16, max(len(n) for n in names) + 1))
    head = "FIELD".ljust(26) + "".join(_short(n).rjust(width) for n in names)
    out = [head, "-" * len(head)]

    for field in E0005_FIELDS:
        cells = []
        for n in names:
            fill = rows[n][0]
            cells.append(("-" if not fill else f"{fill.get(field, 0.0):.0%}").rjust(width))
        line = field.ljust(26) + "".join(cells)
        measured = [n for n in names if rows[n][0]]
        if measured and all(rows[n][0].get(field, 0.0) == 0.0 for n in measured):
            line += "   empty" if len(measured) == 1 else "   no brand fills this"
        out.append(line)

    out.append("")
    out.append("catalogue".ljust(26) + "".join(str(rows[n][1]).rjust(width) for n in names))
    filled = {n: sum(1 for v in rows[n][0].values() if v > 0) for n in names if rows[n][0]}
    if filled:
        out.append(
            "fields filled".ljust(26)
            + "".join((f"{filled.get(n, 0)}/{len(E0005_FIELDS)}").rjust(width) for n in names)
        )
    for n in names:
        if rows[n][2]:
            out.append(f"{n}: {rows[n][2]}")
    return "\n".join(out)


def _short(domain: str) -> str:
    return domain.removeprefix("www.").split(".")[0][:15]
