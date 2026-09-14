"""What a probe's wreckage actually means.

Everything the harness decides rests on this one distinction: a site that refused us
and a site that let us in but had nothing readable both produce no products, and the
fixes are opposite. Climbing the transport ladder opens the first and is pure waste on
the second — a better TLS fingerprint cannot render JavaScript.

So the classifier is deliberately blunt and ordered. It reads the Capability that
fingerprint.probe already returns, whatever exception the transport raised, and the
statuses in the transport's ledger, and it commits to one word.
"""

import socket
import ssl
from collections.abc import Iterator
from enum import Enum

from backend.archive.domain.brand import Capability

# A handshake we were not allowed to finish. The type is the reliable signal, but only
# httpx raises a real ssl.SSLError — curl_cffi reports the same event as its own error
# class carrying OpenSSL's text, so the words are worth reading too.
_TLS_MARKERS = ("ssl", "tls", "handshake", "sslv3", "wrong_version_number")

# We never reached the host at all. Distinct from a refusal, because there is nothing
# here to escalate against: a dearer transport does not fix DNS.
_UNREACHABLE_TYPES = (socket.gaierror, ConnectionError, TimeoutError)


class Outcome(str, Enum):
    OK = "ok"  # reached, and something on it can be read
    OK_THIN = "ok_thin"  # reached, nothing readable — the empty room
    TLS_BLOCKED = "tls_blocked"  # hung up during the handshake
    WAF_403 = "waf_403"  # heard us out, then refused
    RATE_429 = "rate_429"  # "slow down" — often a fingerprint verdict in disguise
    CHALLENGE = "challenge"  # an interstitial, served with a clean status
    GATED = "gated"  # a password. No transport opens one.
    UNREACHABLE = "unreachable"  # never got there

    @property
    def reached(self) -> bool:
        return self in (Outcome.OK, Outcome.OK_THIN)


def classify(
    cap: Capability | None,
    exc: BaseException | None,
    statuses: list[int],
) -> Outcome:
    """One word for how this attempt went. Ordered: the sharpest fact wins."""
    if exc is not None:
        return Outcome.TLS_BLOCKED if _is_tls(exc) else Outcome.UNREACHABLE
    if cap is None:
        return Outcome.UNREACHABLE

    # A password is not a door to pick. Checked before the refusals because a gated
    # store commonly answers 401 as well, and reporting that as a WAF block would send
    # the ladder climbing after something no transport can reach.
    if cap.password_gated:
        return Outcome.GATED

    # probe() sets `challenged` for any of 401/403/429, which collapses three different
    # problems into one flag. The raw status is the sharper fact and the one that says
    # which fix to reach for, so read it first and keep CHALLENGE for the case it is the
    # only evidence there is — an interstitial served under HTTP 200.
    if 429 in statuses:
        return Outcome.RATE_429
    if 403 in statuses or 401 in statuses:
        return Outcome.WAF_403
    if cap.challenged:
        return Outcome.CHALLENGE

    # Reached it. Is there anything on it we can actually read? A sitemap does not count:
    # it lists URLs without making any of them parseable, and every client-rendered site
    # publishes one — counting it would file the empty room under OK, which is the single
    # mistake this whole module exists to prevent.
    if cap.bulk_json or cap.woo_api or cap.ldjson_product:
        return Outcome.OK
    return Outcome.OK_THIN


def _is_tls(exc: BaseException) -> bool:
    chain = list(_causes(exc))
    if any(isinstance(e, ssl.SSLError) for e in chain):
        return True
    if any(isinstance(e, _UNREACHABLE_TYPES) for e in chain):
        return False
    text = " ".join(str(e) for e in chain).lower()
    return any(marker in text for marker in _TLS_MARKERS)


def _causes(exc: BaseException) -> Iterator[BaseException]:
    """The exception and everything it was raised from, without looping on a cycle."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__
