"""Which key to try next.

Two rules, and everything else in the harness follows from them.

A locked door and an empty room are different failures. A refusal climbs the ladder,
because a better fingerprint is exactly what a refusal is asking for. A site that
answered 200 with nothing readable on it skips every remaining HTTP tier and goes
straight to a renderer, because no TLS handshake ever written can execute JavaScript,
and trying three more of them buys a guaranteed repeat of the same answer.

Try the cheapest first and stop when one works. A browser lane costs $0 and is still
unusable for a brand re-scraped hourly; the moment something cheaper succeeds there is
nothing left to learn from paying more.
"""

from backend.archive.access.outcome import Outcome
from backend.archive.access.strategy import Strategy

# A refusal, or something that may be one. UNREACHABLE is here because a WAF that drops
# the connection without answering looks identical to a dead host — Van Cleef timed out
# on plain HTTP and was never offered a different handshake (sweep of 2026-09-14).
_CLIMB = (
    Outcome.RATE_429,
    Outcome.WAF_403,
    Outcome.TLS_BLOCKED,
    Outcome.CHALLENGE,
    Outcome.UNREACHABLE,
)


def next_strategies(outcome: Outcome, remaining: list[Strategy]) -> list[Strategy]:
    """What is still worth trying after this outcome, cheapest first.

    `remaining` is whatever has not been tried yet. An empty list back means stop —
    either we are done, or nothing left can change the answer.
    """
    ordered = sorted(remaining, key=lambda s: s.rank)
    if outcome in _CLIMB:
        return ordered
    if outcome is Outcome.OK_THIN:
        return [s for s in ordered if s.kind == "browser"]
    # OK: done. GATED: no transport opens a password.
    return []
