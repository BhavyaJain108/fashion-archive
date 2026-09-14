"""The dated notebook: what worked, for which brand, on which day.

Two objects, and the split between them is the point.

`access/sweeps/<when>.json` is append-only, one object per sweep, holding every attempt
including the failures. This is the history. Whatever opens a brand today stops opening
it eventually — sites update their defences — and the only way to see that coming is to
be able to look back at when a lane started refusing.

`access/current.json` is the rolled-up answer: the cheapest strategy that worked per
brand, when it first did, and when it was last confirmed. One read, and the file a
planner would consult if we later let it pick a transport on its own.

A brand that stops working is marked lost rather than dropped. Deleting the row would
erase precisely the event worth noticing.
"""

from backend.archive.access.outcome import Outcome
from backend.archive.access.probe import AccessResult
from backend.archive.store.objects import dumps, loads

SWEEPS = "access/sweeps/"
CURRENT = "access/current.json"


def save_sweep(objects, results: list[AccessResult], at: str) -> None:
    """Write one sweep, then fold it into the current answer."""
    objects.put(f"{SWEEPS}{at}.json", dumps([r.to_row() for r in results]))
    _roll_up(objects, results, at)


def load_sweep(objects, at: str) -> list[AccessResult]:
    got = objects.get(f"{SWEEPS}{at}.json")
    if got is None:
        return []
    return [AccessResult.from_row(row) for row in loads(got[0])]


def sweep_dates(objects) -> list[str]:
    """Every sweep taken, oldest first. Keys sort as ISO timestamps do."""
    return [key[len(SWEEPS) : -len(".json")] for key in sorted(objects.list(SWEEPS))]


def load_current(objects) -> dict:
    got = objects.get(CURRENT)
    return loads(got[0]) if got else {}


def history(objects, domain: str) -> list[tuple[str, AccessResult]]:
    """Every recorded outcome for one brand, oldest first.

    The winning attempt where there was one, otherwise the last thing tried — which is
    what a reader wants when asking "when did this brand start refusing us".
    """
    out: list[tuple[str, AccessResult]] = []
    for at in sweep_dates(objects):
        attempts = [r for r in load_sweep(objects, at) if r.domain == domain]
        if not attempts:
            continue
        out.append((at, next((r for r in attempts if r.usable), attempts[-1])))
    return out


def _roll_up(objects, results: list[AccessResult], at: str) -> None:
    """Fold a sweep into current.json, leaving brands it did not touch alone."""
    current = load_current(objects)

    for domain, attempts in _by_domain(results).items():
        won = next((r for r in attempts if r.usable), None)
        was = current.get(domain, {})

        if won is None:
            # Reached but unreadable, or refused outright. Either way there is no lane
            # to record; keep the row so the loss is visible rather than silent.
            last = attempts[-1]
            current[domain] = {
                "strategy": None,
                "outcome": last.outcome.value,
                "seconds": round(last.seconds, 3),
                "usd": round(last.usd, 6),
                "first_seen": None,
                "last_verified": at,
                "lost_at": at if was.get("strategy") else was.get("lost_at"),
            }
            continue

        # A brand that moved to a different lane starts its clock again: how long *this*
        # lane has held is the number worth keeping.
        held = was.get("strategy") == won.strategy
        current[domain] = {
            "strategy": won.strategy,
            "outcome": won.outcome.value,
            "seconds": round(won.seconds, 3),
            "usd": round(won.usd, 6),
            "first_seen": was.get("first_seen") if held else at,
            "last_verified": at,
            "lost_at": None,
        }

    objects.put(CURRENT, dumps(current))


def _by_domain(results: list[AccessResult]) -> dict[str, list[AccessResult]]:
    out: dict[str, list[AccessResult]] = {}
    for r in results:
        out.setdefault(r.domain, []).append(r)
    return out


def summarise(current: dict) -> dict[str, int]:
    """How the roster stands: how many brands on each outcome."""
    counts: dict[str, int] = {}
    for entry in current.values():
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


__all__ = [
    "Outcome",
    "history",
    "load_current",
    "load_sweep",
    "save_sweep",
    "summarise",
    "sweep_dates",
]
