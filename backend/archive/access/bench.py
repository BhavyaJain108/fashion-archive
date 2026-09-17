"""The sweep: every brand up the ladder, stopping as soon as something works.

Early exit is what makes this affordable. The full cross product of 37 brands against
six strategies is 888 probes; climbing only where a brand actually refuses is about 75,
because most of the roster answers on the first rung and never leaves it.

Every attempt is kept, not just the winning one. The failures are the record — which
lane a brand refused, on which date, is the only way we see its defences change under
us later.
"""

from collections.abc import Callable, Iterable

from backend.archive.access.policy import next_strategies
from backend.archive.access.probe import AccessResult, try_access
from backend.archive.access.strategy import Strategy


def sweep(
    domains: Iterable[str],
    strategies: list[Strategy],
    probe_fn: Callable[..., AccessResult] = try_access,
    on_result: Callable[[AccessResult], None] | None = None,
    **probe_kw,
) -> list[AccessResult]:
    """Climb the ladder for each brand in turn. Returns every attempt, in order."""
    usable = [s for s in strategies if s.available]
    results: list[AccessResult] = []

    for domain in domains:
        for result in _climb(domain, usable, probe_fn, probe_kw):
            results.append(result)
            if on_result is not None:
                on_result(result)
    return results


def _climb(domain, strategies, probe_fn, probe_kw):
    remaining = sorted(strategies, key=lambda s: s.rank)
    while remaining:
        current, remaining = remaining[0], remaining[1:]
        result = probe_fn(domain, current, **probe_kw)
        yield result
        remaining = next_strategies(result.outcome, remaining)


def winners(results: list[AccessResult]) -> dict[str, AccessResult]:
    """The cheapest strategy that actually worked, per brand.

    Only OK counts. OK_THIN answered 200 and gave us nothing to read, and recording that
    as access would quietly mark the brand solved so nobody looked at it again.
    """
    out: dict[str, AccessResult] = {}
    for r in results:
        if r.usable and r.domain not in out:
            out[r.domain] = r
    return out
