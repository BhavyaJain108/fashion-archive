"""What the scraping costs and what the sites make of it.

Two ledgers a long-running scrape needs and did not have:

  RequestLog   every response, kept. A daemon that runs constantly is only worth
               running if it tells us something, and what it can tell us is in the
               responses — which hosts slow down as our rate rises, which start
               answering 403 instead of 429, how long they ask us to wait. Buffered,
               because a fleet pass makes thousands of requests and each one must not
               cost a database commit.

  Spend        tokens as the API itself reports them, not an estimate. Rates are
               settable, because a published price is a fact about today.
"""

import os
import threading
from datetime import datetime, timezone

# $ per million tokens. Override with FINDER_INPUT_RATE / FINDER_OUTPUT_RATE when the
# published prices move, or when a different model is in use.
INPUT_RATE = float(os.getenv("FINDER_INPUT_RATE", "3.0"))
OUTPUT_RATE = float(os.getenv("FINDER_OUTPUT_RATE", "15.0"))


class RequestLog:
    """Collects response observations and writes them in batches."""

    def __init__(self, catalog, batch: int = 200):
        self._catalog = catalog
        self._batch = batch
        self._rows: list[tuple] = []
        self._lock = threading.Lock()

    def __call__(self, host: str, status, latency_ms: int, retry_after) -> None:
        with self._lock:
            self._rows.append(
                (host, status, latency_ms, retry_after, datetime.now(timezone.utc).isoformat())
            )
            full = len(self._rows) >= self._batch
        if full:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            rows, self._rows = self._rows, []
        self._catalog.record_requests(rows)


class Spend:
    """Tokens and their cost, accumulated across the calls one run makes."""

    def __init__(self, input_rate: float = INPUT_RATE, output_rate: float = OUTPUT_RATE):
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0
        self._rates = (input_rate, output_rate)
        self._lock = threading.Lock()

    def add(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.calls += 1

    @property
    def usd(self) -> float:
        rate_in, rate_out = self._rates
        return round(self.input_tokens / 1e6 * rate_in + self.output_tokens / 1e6 * rate_out, 6)

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": self.usd,
        }
