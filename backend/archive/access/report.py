"""Reading the matrix.

One row per brand, one column per strategy, and the winner named at the end. A cell says
what that lane answered; a dash means it was never tried, which is a different fact and
must not read as a failure — most brands stop after the first rung because it worked.

A refusal measured while our own scraper held the same host is marked. Our Render worker
hits these sites continuously, and a 429 or a 403 is the one answer our own traffic can
manufacture; a reading we cannot trust must not look like one we can.
"""

from backend.archive.access.outcome import Outcome
from backend.archive.access.probe import AccessResult
from backend.archive.access.strategy import Strategy

# Roughly what fingerprint.probe spends per brand: robots, products.json, homepage, and
# one of meta.json or a sitemap look.
GETS_PER_PROBE = 4

# The two outcomes our own concurrent scraping can produce.
_OURS_TO_BLAME = (Outcome.RATE_429, Outcome.WAF_403)


def format_matrix(results: list[AccessResult]) -> str:
    if not results:
        return "nothing swept"

    order = _column_order(results)
    cells = {(r.domain, r.strategy): r for r in results}
    domains = list(dict.fromkeys(r.domain for r in results))

    name_w = max(len("brand"), *(len(d) for d in domains))
    widths = [max(len(c), 10) for c in order]

    head = "  ".join(
        ["brand".ljust(name_w), *(c.ljust(w) for c, w in zip(order, widths, strict=True))]
    )
    lines = [f"{head}  winner", "-" * len(head)]

    suspect = False
    for domain in domains:
        row = [domain.ljust(name_w)]
        for col, w in zip(order, widths, strict=True):
            hit = cells.get((domain, col))
            if hit is None:
                row.append("-".ljust(w))
                continue
            mark = "!" if hit.daemon_active and hit.outcome in _OURS_TO_BLAME else ""
            suspect = suspect or bool(mark)
            row.append((hit.outcome.value + mark).ljust(w))
        row.append(_winner_cell(domain, results))
        lines.append("  ".join(row))

    lines.append("")
    lines.append(_tally(results))
    if suspect:
        lines.append(
            "! measured while our own daemon held that brand — a 429/403 here may be us, "
            "not the site. Re-run against a paused daemon before trusting it."
        )
    return "\n".join(lines)


def _winner_cell(domain: str, results: list[AccessResult]) -> str:
    won = next((r for r in results if r.domain == domain and r.usable), None)
    if won is not None:
        return f"{won.strategy}  {won.seconds:.2f}s"
    last = [r for r in results if r.domain == domain][-1]
    if last.outcome is Outcome.OK_THIN:
        return "— empty room: needs rendering, not a better key"
    if last.outcome is Outcome.GATED:
        return "— password"
    return "— still shut"


def _column_order(results: list[AccessResult]) -> list[str]:
    from backend.archive.access.strategy import get

    seen = list(dict.fromkeys(r.strategy for r in results))

    def rank(name: str) -> tuple[int, int]:
        try:
            return get(name).rank
        except KeyError:
            # A name the shelf no longer holds — a sweep read back from an older run.
            # Park it after everything current rather than dropping the column.
            return (99, seen.index(name))

    return sorted(seen, key=rank)


def _tally(results: list[AccessResult]) -> str:
    domains = {r.domain for r in results}
    opened = {r.domain for r in results if r.usable}
    requests = sum(r.requests for r in results)
    spend = sum(r.usd for r in results)
    seconds = sum(r.seconds for r in results)
    line = (
        f"{len(opened)}/{len(domains)} brands open  ·  "
        f"{len(results)} probes  ·  {requests} requests  ·  {seconds:.1f}s"
    )
    return line + (f"  ·  ${spend:.2f}" if spend else "  ·  $0")


def format_plan(domains: list[str], strategies: list[Strategy]) -> str:
    """What a sweep would do, without doing any of it."""
    first = min((s.tier for s in strategies), default=0)
    floor = len(domains) * GETS_PER_PROBE
    ceiling = len(domains) * len(strategies) * GETS_PER_PROBE
    lines = [
        f"would sweep {len(domains)} brand(s) against "
        f"{len(strategies)} strateg{'y' if len(strategies) == 1 else 'ies'}:",
        "  " + ", ".join(s.name for s in strategies),
        "",
        f"at least {floor} requests (every brand on tier {first}), "
        f"at most {ceiling} if every brand refuses every rung.",
        "",
        "hosts:",
        *(f"  https://{d}" for d in domains),
    ]
    return "\n".join(lines)
