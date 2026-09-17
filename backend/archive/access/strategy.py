"""The shelf: every named way of getting in, ordered by what it costs.

Transports were constructed at eight hardcoded call sites, which meant there was no way
to say "try this brand that way" — and nothing is measurable until it has a name. These
are the names.

Tier is not price. At the free tiers the cost is seconds and fragility: a browser lane
is $0 and still unusable for a brand re-scraped hourly, because three seconds a page
does not fit inside a day at our volume. `usd_per_1k` exists so a paid adapter slots in
later without changing the shape of a result.

Nothing here imports an optional library at module load. A missing curl_cffi makes one
strategy unavailable; it must never stop the CLI from listing the shelf.
"""

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from backend.archive.domain.brand import TransportLevel


class StrategyUnavailable(RuntimeError):
    """Asked to build a strategy whose library is not installed."""


@dataclass(frozen=True)
class Strategy:
    name: str
    tier: int  # sort key: cheapest first
    kind: Literal["http", "browser"]
    level: TransportLevel  # what fingerprint.probe gates its deep probes on
    usd_per_1k: float
    requires: str | None  # the import that must exist, if any
    factory: Callable[[], object] = field(repr=False)
    seq: int = 0  # position on the shelf, set at registration

    @property
    def rank(self) -> tuple[int, int]:
        """Sort key. Tier first, then the order the shelf was written in — within a tier
        that order is a judgement (the likeliest profile first), and sorting by name
        would quietly replace it with the alphabet."""
        return (self.tier, self.seq)

    @property
    def available(self) -> bool:
        return self.requires is None or _installed(self.requires)

    def build(self):
        if not self.available:
            raise StrategyUnavailable(
                f"{self.name} needs {self.requires!r}, which is not installed"
            )
        return self.factory()


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _httpx():
    from backend.archive.transport import HttpxTransport

    return HttpxTransport()


def _cffi(profile: str):
    def make():
        from backend.archive.access.cffi import CurlCffiTransport

        return CurlCffiTransport(impersonate=profile)

    return make


def _browser(driver: str):
    def make():
        # The challenge-aware subclass rather than the bare transport: a browser that
        # retries before a JS challenge has finished sees the challenge every time
        # (Gentle Monster, 2026-09-17 — see LEARNINGS.md).
        from backend.archive.browser.challenge import ChallengeAwareBrowser

        return ChallengeAwareBrowser(driver=driver)

    return make


_SHELF = (
    # The control. Kept in the ladder so every sweep records what today's transport
    # does, which is the only way we see a brand's defences change under us.
    Strategy("httpx", 0, "http", TransportLevel.T0, 0.0, None, _httpx),
    # Brands fingerprint specific browser versions, so the profiles are separate
    # cells rather than one "curl_cffi" row. A current build first: a handshake from
    # a browser two years out of date is its own signal, whatever else it gets right.
    Strategy("cffi:chrome142", 1, "http", TransportLevel.T1, 0.0, "curl_cffi", _cffi("chrome142")),
    Strategy("cffi:chrome131", 1, "http", TransportLevel.T1, 0.0, "curl_cffi", _cffi("chrome131")),
    Strategy("cffi:safari184", 1, "http", TransportLevel.T1, 0.0, "curl_cffi", _cffi("safari184")),
    # T2 so fingerprint.probe pays for its deep probes: once a browser has loaded the
    # page anyway, that is the only way a challenged brand's URL shape is ever learned.
    Strategy(
        "playwright", 3, "browser", TransportLevel.T2, 0.0, "playwright", _browser("playwright")
    ),
    Strategy(
        "patchright", 4, "browser", TransportLevel.T2, 0.0, "patchright", _browser("patchright")
    ),
)

# Position on the shelf is part of the ordering, so it is stamped on here rather than
# repeated in six constructor calls.
_REGISTRY: dict[str, Strategy] = {s.name: replace(s, seq=i) for i, s in enumerate(_SHELF)}


def all_strategies() -> list[Strategy]:
    """The whole shelf, cheapest first."""
    return sorted(_REGISTRY.values(), key=lambda s: s.rank)


def get(name: str) -> Strategy:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(s.name for s in all_strategies())
        raise KeyError(f"no strategy {name!r}; the shelf holds: {known}") from None


def select(spec: str) -> list[Strategy]:
    """Parse a comma-separated list of names, returned cheapest first whatever the order
    they were asked for in — the ladder is only meaningful climbed from the bottom."""
    picked = [get(n.strip()) for n in spec.split(",") if n.strip()]
    return sorted(picked, key=lambda s: s.rank)
