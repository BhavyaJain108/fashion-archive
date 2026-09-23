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


class LedgeredTransport:
    """The bookkeeping every HTTP transport owes, with the fetching left abstract.

    Pacing a host, noticing what it answered and writing that down are the same job
    whichever library carries the request, so a second transport should inherit them
    rather than copy them — a copy is how one lane quietly stops honouring Retry-After.
    Subclasses implement `_fetch`; everything around it is here.
    """

    def __init__(self, level: TransportLevel = TransportLevel.T0, sink=None, budget=None):
        self.level = level
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

    def _fetch(self, url: str):
        raise NotImplementedError

    def get(self, url: str):
        host = urlparse(url).netloc
        if self._budget is not None:
            self._budget.acquire(host)
        started = time.monotonic()
        try:
            resp = self._fetch(url)
        except Exception:
            self._record(url, None, started, None)
            raise
        retry_after = _retry_after(resp)
        if self._budget is not None:
            self._budget.observe(host, resp.status_code, retry_after)
        self._record(url, resp.status_code, started, retry_after)
        self.ledger.append({"url": url, "status": resp.status_code, "bytes": len(resp.content)})
        return resp

    def statuses(self) -> list[int]:
        """Every status this transport saw, in order. What the classifier reads."""
        return [row["status"] for row in self.ledger]

    def _record(self, url: str, status: int | None, started: float, retry_after: int | None):
        if self._sink is None:
            return
        host = urlparse(url).netloc
        self._sink(host, status, int((time.monotonic() - started) * 1000), retry_after)


class HttpxTransport(LedgeredTransport):
    """T0/T1 plain-HTTP transport with a browser-grade header profile.

    The headers say Chrome; Python's TLS stack says otherwise, and a WAF hashes the
    handshake before it reads a header. That mismatch is why several brands refuse this
    lane — CurlCffiTransport below is the one that does not have it.
    """

    def __init__(
        self,
        level: TransportLevel = TransportLevel.T0,
        client: httpx.Client | None = None,
        sink=None,
        budget=None,
    ):
        super().__init__(level=level, sink=sink, budget=budget)
        self._client = client or httpx.Client(
            headers=BROWSER_HEADERS, follow_redirects=True, timeout=15.0
        )

    def _fetch(self, url: str) -> httpx.Response:
        # Streamed, so a body larger than any page or photograph we want is dropped
        # before it is in memory; a whole read of a hostile or broken response could
        # take the worker with it.
        resp = self._client.send(self._client.build_request("GET", url), stream=True)
        try:
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                raise ResponseTooLarge(f"{url}: {declared} bytes declared")
            body = bytearray()
            for chunk in resp.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BODY_BYTES:
                    raise ResponseTooLarge(f"{url}: over {MAX_BODY_BYTES} bytes")
        finally:
            resp.close()
        # iter_bytes() already decoded the transfer encoding. The headers still name
        # it, and a Response built with them decodes the body a second time: every
        # gzip page on the fleet raised DecodingError on 2026-09-23 for exactly that.
        headers = httpx.Headers(
            [(k, v) for k, v in resp.headers.multi_items() if k.lower() not in _CODING_HEADERS]
        )
        return httpx.Response(
            resp.status_code, headers=headers, content=bytes(body), request=resp.request
        )


def _retry_after(resp) -> int | None:
    """How long the host asked us to wait, when it says so."""
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None  # an HTTP-date form; the number is the useful case


# --- T1: plain HTTP in a real browser's accent -------------------------------------

DEFAULT_IMPERSONATE = "chrome142"
TIMEOUT = 15.0

# The largest response worth reading: a product page is under a megabyte, a
# photograph under a few. Anything past this is not ours to keep.
MAX_BODY_BYTES = 20 * 1024 * 1024


# Headers that describe the wire form of a body we have already decoded.
_CODING_HEADERS = ("content-encoding", "content-length", "transfer-encoding")


class ResponseTooLarge(Exception):
    """A response bigger than any page or photograph we want."""


class _Body:
    """A curl_cffi response read to a cap: the same attributes the rest reads."""

    def __init__(self, resp, content: bytes):
        self.status_code = resp.status_code
        self.headers = resp.headers
        self.url = getattr(resp, "url", None)
        self.content = content
        encoding = getattr(resp, "encoding", None) or "utf-8"
        try:
            self.text = content.decode(encoding, errors="replace")
        except LookupError:
            self.text = content.decode("utf-8", errors="replace")


class CurlCffiTransport(LedgeredTransport):
    """T1 transport whose TLS handshake is indistinguishable from the named browser."""

    def __init__(
        self,
        impersonate: str = DEFAULT_IMPERSONATE,
        level: TransportLevel = TransportLevel.T1,
        sink=None,
        budget=None,
        session=None,
    ):
        super().__init__(level=level, sink=sink, budget=budget)
        self.impersonate = impersonate
        # Injected in tests; built lazily otherwise so importing this module never
        # requires curl_cffi to be installed.
        self._session = session

    def _ensure_session(self):
        if self._session is None:
            from curl_cffi import requests as cffi_requests

            self._session = cffi_requests.Session(impersonate=self.impersonate, timeout=TIMEOUT)
        return self._session

    def _fetch(self, url: str):
        resp = self._ensure_session().get(url, allow_redirects=True, stream=True)
        try:
            declared = resp.headers.get("content-length")
            if declared and str(declared).isdigit() and int(declared) > MAX_BODY_BYTES:
                raise ResponseTooLarge(f"{url}: {declared} bytes declared")
            body = bytearray()
            for chunk in resp.iter_content():
                body.extend(chunk)
                if len(body) > MAX_BODY_BYTES:
                    raise ResponseTooLarge(f"{url}: over {MAX_BODY_BYTES} bytes")
        finally:
            resp.close()
        return _Body(resp, bytes(body))

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None


def for_level(level: TransportLevel, sink=None, budget=None):
    """The transport a plan's level asks for.

    T0 is Python's own HTTP. T1 is the same single request with a real browser's TLS
    handshake, which is what several brands were refusing us over. T2 is a real browser,
    which costs seconds a page and is the last resort rather than the default.
    """
    if level == TransportLevel.T2:
        from backend.archive.browser.challenge import ChallengeAwareBrowser

        return ChallengeAwareBrowser()
    if level == TransportLevel.T1:
        return CurlCffiTransport(sink=sink, budget=budget)
    return HttpxTransport(sink=sink, budget=budget)
