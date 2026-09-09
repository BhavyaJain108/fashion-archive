"""Transports: how requests are made. Injected into connectors, never owned by them (spec §4.0)."""

import time
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from backend.archive.domain.brand import TransportLevel

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class Response(Protocol):
    """The slice of a response the connectors use.

    Named as a shape rather than a class because two things answer to it:
    httpx.Response, and the browser transport's own object, which cannot be an
    httpx.Response because Playwright never produced one. The protocol said
    httpx.Response for months and was simply wrong; nothing noticed because every
    call site duck-types.
    """

    # Read-only members throughout: a plain attribute satisfies a property, but not
    # the other way round, and httpx exposes several of these as properties while the
    # browser response sets them in __init__.
    @property
    def url(self) -> Any: ...

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    @property
    def headers(self) -> Any: ...

    @property
    def content(self) -> bytes: ...

    def json(self) -> Any: ...


class Transport(Protocol):
    level: TransportLevel

    def get(self, url: str) -> Response: ...


class HttpxTransport:
    """T0/T1 plain-HTTP transport with a browser-grade header profile."""

    def __init__(
        self,
        level: TransportLevel = TransportLevel.T0,
        client: httpx.Client | None = None,
        sink=None,
        budget=None,
    ):
        self.level = level
        self._client = client or httpx.Client(
            headers=BROWSER_HEADERS, follow_redirects=True, timeout=15.0
        )
        # Request ledger: every request this transport ever made, for auditability.
        self.ledger: list[dict] = []
        # Where the ledger goes to be kept. Scraping constantly is only worth doing if
        # it tells us how sites react to it, and that lives in the responses: which
        # hosts degrade as our rate rises, which answer 403 rather than 429 (a WAF
        # calling us a bot, a different thing from a rate limit), how long they ask us
        # to wait. In memory it is thrown away when the run ends.
        self._sink = sink
        # How fast this host may be asked. Without it the ledger records a 429 and we
        # go straight back to making the request that caused it.
        self._budget = budget

    def get(self, url: str) -> httpx.Response:
        host = urlparse(url).netloc
        if self._budget is not None:
            self._budget.acquire(host)
        started = time.monotonic()
        try:
            resp = self._client.get(url)
        except Exception:
            self._record(url, None, started, None)
            raise
        retry_after = _retry_after(resp)
        if self._budget is not None:
            self._budget.observe(host, resp.status_code, retry_after)
        self._record(url, resp.status_code, started, retry_after)
        self.ledger.append({"url": url, "status": resp.status_code, "bytes": len(resp.content)})
        return resp

    def _record(self, url: str, status: int | None, started: float, retry_after: int | None):
        if self._sink is None:
            return
        host = urlparse(url).netloc
        self._sink(host, status, int((time.monotonic() - started) * 1000), retry_after)


def _retry_after(resp) -> int | None:
    """How long the host asked us to wait, when it says so."""
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None  # an HTTP-date form; the number is the useful case
