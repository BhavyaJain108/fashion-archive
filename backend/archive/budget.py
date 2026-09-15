"""How fast we are allowed to talk to one host.

The request ledger records that a shop asked us to slow down. This is the part that
listens. Nothing consulted it before, so the daemon would go on making the same requests
that provoked the 429 it had just written down.

The policy is deliberately dull, because the failure mode of a clever one is a brand
that stops answering:

  a minimum gap between requests to a host, so we never burst;
  a stand-down until the moment a host's Retry-After names, when it sends one;
  a doubling stand-down when it refuses without saying for how long;
  a longer one for 401/403, which is not a rate limit but a decision that we are a bot —
  arguing with that by retrying is how a temporary block becomes a permanent one;
  and a single success clears the penalty, since the host has plainly forgiven us.

State is per process and shared by every worker in it. It is seeded from the ledger on
start, so a restart does not walk straight back into a block we already knew about.
"""

import threading
import time as _time
from datetime import datetime, timedelta, timezone

DEFAULT_GAP = 0.5  # seconds between requests to one host: 2/second, sustained

# How fast we are willing to go once a host has shown it does not mind. Nobody
# publishes these numbers, so we find them: speed up while answers stay clean, halve
# on the first refusal, then creep back up. The floor is the fastest we will ever go,
# and it differs by what is on the other end.
#
#   an image CDN serves static bytes for millions of shops and is built for volume;
#   a shop's own storefront is a real application doing real work for real customers.
#
# 97% of what this archive fetches is images from one CDN, so that floor is where the
# hours are won, and the storefront floor costs us almost nothing to keep polite.
CDN_FLOOR = 1 / 30  # 30 a second
SHOP_FLOOR = 1 / 5  # 5 a second
CEILING = 8.0  # never crawl slower than this, refusals aside
EASE = 0.97  # multiplicative speed-up per clean answer
_CDN_MARKERS = ("cdn.", "cdn-", "images.", "img.", ".cdn", "cloudfront.net", "akamaized.net")


def floor_for(host: str) -> float:
    """The fastest we will ask this host, by what it appears to be."""
    h = host.lower()
    return CDN_FLOOR if any(m in h for m in _CDN_MARKERS) else SHOP_FLOOR


BUSY_BACKOFF = 60.0  # first stand-down when a host says 429/503 without a Retry-After
MAX_BACKOFF = 1800.0
REFUSED_BACKOFF = 900.0  # 401/403: a bot decision, not a rate limit
BUSY = (429, 503)
REFUSED = (401, 403)


class HostBudget:
    """Paces requests per host. Thread-safe; shared by the workers in one process."""

    def __init__(
        self,
        gap: float = DEFAULT_GAP,
        sleep=_time.sleep,
        clock=_time.monotonic,
    ):
        self.gap = gap
        self._sleep = sleep
        self._clock = clock
        self._next_allowed: dict[str, float] = {}
        self._penalty: dict[str, float] = {}
        # The gap we are currently using for each host, which moves with what it says.
        self._gap_for: dict[str, float] = {}
        self._lock = threading.Lock()

    def gap_for(self, host: str) -> float:
        return self._gap_for.get(host, self.gap)

    def acquire(self, host: str) -> float:
        """Block until this host may be asked again. Returns how long that took."""
        with self._lock:
            ready = self._next_allowed.get(host, 0.0)
            now = self._clock()
            wait = max(0.0, ready - now)
            # Reserve this slot before releasing the lock, so two workers sharing a host
            # queue behind each other instead of both deciding they may go now.
            self._next_allowed[host] = max(ready, now) + self._gap_for.get(host, self.gap)
        if wait > 0:
            self._sleep(wait)
        return wait

    def observe(self, host: str, status: int | None, retry_after: int | None = None) -> None:
        """Learn from what the host just answered."""
        with self._lock:
            if status in BUSY or status in REFUSED:
                # Back off hard: we were going too fast, so halve the rate as well as
                # standing down. Approaching a limit is cheap; being blocked is not.
                current = self._gap_for.get(host, self.gap)
                self._gap_for[host] = min(CEILING, max(current, floor_for(host)) * 2)
                self._next_allowed[host] = self._clock() + self._stand_down(
                    host, status, retry_after
                )
            elif status is not None and status < 400:
                self._penalty.pop(host, None)  # forgiven
                # A clean answer earns a little more speed, never past this host's floor.
                current = self._gap_for.get(host, self.gap)
                self._gap_for[host] = max(floor_for(host), current * EASE)

    def _stand_down(self, host: str, status: int, retry_after: int | None) -> float:
        if retry_after:
            return float(retry_after)
        if status in REFUSED:
            return REFUSED_BACKOFF
        previous = self._penalty.get(host, 0.0)
        penalty = min(previous * 2 if previous else BUSY_BACKOFF, MAX_BACKOFF)
        self._penalty[host] = penalty
        return penalty

    def blocked_for(self, host: str) -> float:
        """Seconds until this host may be asked again — 0 when it is free."""
        with self._lock:
            return max(0.0, self._next_allowed.get(host, 0.0) - self._clock())

    def seed_from(self, catalog, minutes: int = 30) -> int:
        """Carry recent refusals across a restart, so we do not walk back into them."""
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        seeded = 0
        for row in catalog.host_stats(since=since):
            if (row["busy"] or 0) or (row["refused"] or 0):
                wait = float(row["max_retry_after"] or BUSY_BACKOFF)
                with self._lock:
                    self._next_allowed[row["host"]] = self._clock() + wait
                seeded += 1
        return seeded
