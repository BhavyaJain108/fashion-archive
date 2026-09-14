"""Plain HTTP, in a real browser's accent.

HttpxTransport sends Chrome's headers over Python's TLS stack. A WAF hashes the
ClientHello (JA3/JA4) and the HTTP/2 SETTINGS frame before it reads a single header, so
what it sees is a Chrome claim delivered with a Python fingerprint on HTTP/1.1 — a
contradiction no honest client produces, and a stronger bot signal than an unmodified
`python-httpx` User-Agent would have been.

curl_cffi is libcurl built against BoringSSL with real browsers' cipher lists, extension
ordering and h2 settings. Same one request, same ~200 ms, no browser process.

Deliberately no header profile of our own: `impersonate` already supplies a complete,
self-consistent set in the right order, and layering BROWSER_HEADERS on top would
reintroduce exactly the mismatch this module exists to remove.
"""

from backend.archive.domain.brand import TransportLevel
from backend.archive.transport import LedgeredTransport

DEFAULT_IMPERSONATE = "chrome142"
TIMEOUT = 15.0


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
        return self._ensure_session().get(url, allow_redirects=True)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
