"""One cell of the matrix: this brand, that strategy, what happened and what it cost.

fingerprint.probe already asks a brand the four questions worth asking and takes its
transport by injection, so a cell is that call with a stopwatch around it and a verdict
after it. What is added here is the cost — a strategy that works and cannot be afforded
at our refresh rate has not solved anything — and the classification, which is what
turns "failed" into something a person can act on.
"""

import time
from dataclasses import dataclass, field

from backend.archive.access.outcome import Outcome, classify
from backend.archive.access.strategy import Strategy
from backend.archive.domain.brand import Capability
from backend.archive.fingerprint import probe


@dataclass
class AccessResult:
    domain: str
    strategy: str
    outcome: Outcome
    seconds: float = 0.0
    requests: int = 0
    statuses: list[int] = field(default_factory=list)
    usd: float = 0.0
    # Whether our own scraper held this brand while we measured it. A 429 or a 403 is
    # the one thing our own traffic can manufacture, so a reading taken during a scrape
    # is not clean. None means we could not tell, which is not the same as False.
    daemon_active: bool | None = None
    note: str = ""
    capability: Capability | None = None

    @property
    def usable(self) -> bool:
        return self.outcome is Outcome.OK

    def to_row(self) -> dict:
        """The flat form that goes into the object store."""
        return {
            "domain": self.domain,
            "strategy": self.strategy,
            "outcome": self.outcome.value,
            "seconds": round(self.seconds, 3),
            "requests": self.requests,
            "statuses": self.statuses,
            "usd": round(self.usd, 6),
            "daemon_active": self.daemon_active,
            "note": self.note,
        }

    @classmethod
    def from_row(cls, row: dict) -> "AccessResult":
        return cls(
            domain=row["domain"],
            strategy=row["strategy"],
            outcome=Outcome(row["outcome"]),
            seconds=row.get("seconds", 0.0),
            requests=row.get("requests", 0),
            statuses=row.get("statuses", []),
            usd=row.get("usd", 0.0),
            daemon_active=row.get("daemon_active"),
            note=row.get("note", ""),
        )


def try_access(
    domain: str,
    strategy: Strategy,
    budget=None,
    sink=None,
    retry_pause: float = 1.0,
    daemon_active: bool | None = None,
) -> AccessResult:
    """Ask one brand one way, and say what came back.

    The transport is built here and torn down here. Reusing one across cells would let a
    browser context that already holds a challenge cookie make the next strategy look
    better than it is, and the whole point of the sweep is comparing them honestly.
    """
    transport = strategy.build()
    _wire(transport, budget, sink)

    cap: Capability | None = None
    exc: BaseException | None = None
    started = time.monotonic()
    try:
        cap = probe(domain, transport, retry_pause=retry_pause)
    except Exception as e:  # noqa: BLE001 — the failure is the measurement
        exc = e
    finally:
        seconds = time.monotonic() - started
        _close(transport)

    statuses = [s for s in _statuses(transport) if s is not None]
    return AccessResult(
        domain=domain,
        strategy=strategy.name,
        outcome=classify(cap, exc, statuses),
        seconds=seconds,
        requests=len(transport.ledger),
        statuses=statuses,
        usd=len(transport.ledger) * strategy.usd_per_1k / 1000,
        daemon_active=daemon_active,
        note=f"{type(exc).__name__}: {exc}" if exc is not None else "",
        capability=cap,
    )


def _wire(transport, budget, sink) -> None:
    """Hand the transport the pacing and the ledger sink, when it takes them."""
    if budget is not None and hasattr(transport, "_budget"):
        transport._budget = budget
    if sink is not None and hasattr(transport, "_sink"):
        transport._sink = sink


def _statuses(transport) -> list[int]:
    if hasattr(transport, "statuses"):
        return transport.statuses()
    return [row.get("status") for row in getattr(transport, "ledger", [])]


def _close(transport) -> None:
    closer = getattr(transport, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:  # noqa: BLE001 — a browser that will not shut down is not the finding
            pass
