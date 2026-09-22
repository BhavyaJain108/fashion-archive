"""What a probe's raw wreckage means.

The classifier is the piece the whole harness turns on: a locked door and an empty
room both fail to yield products, and they need opposite fixes.
"""

import socket
import ssl
from typing import Any

import httpx
import pytest

from backend.archive.access.outcome import Outcome, classify
from backend.archive.domain.brand import Capability, TransportLevel


def cap(**kw) -> Capability:
    """A Capability that reached the site and found a readable Shopify feed."""
    base: dict[str, Any] = dict(
        domain="example.com",
        transport=TransportLevel.T0,
        bulk_json=True,
        woo_api=False,
        ldjson_product=False,
        sitemap_url="https://example.com/sitemap.xml",
        password_gated=False,
        challenged=False,
    )
    base.update(kw)
    return Capability(**base)


@pytest.mark.unit
def test_ssl_error_is_a_tls_block():
    exc = httpx.ConnectError("handshake failed")
    exc.__cause__ = ssl.SSLError("TLSV1_ALERT_INTERNAL_ERROR")
    assert classify(None, exc, []) is Outcome.TLS_BLOCKED


@pytest.mark.unit
def test_ssl_named_only_in_the_message_is_still_a_tls_block():
    """curl_cffi reports handshake failures as its own error type, text only."""
    assert classify(None, RuntimeError("OpenSSL/3.2: SSL routines::sslv3 alert"), []) is (
        Outcome.TLS_BLOCKED
    )


@pytest.mark.unit
def test_dns_failure_is_unreachable():
    exc = httpx.ConnectError("nodename nor servname provided")
    exc.__cause__ = socket.gaierror(8, "nodename nor servname provided")
    assert classify(None, exc, []) is Outcome.UNREACHABLE


@pytest.mark.unit
def test_timeout_is_unreachable():
    assert classify(None, httpx.ConnectTimeout("timed out"), []) is Outcome.UNREACHABLE


@pytest.mark.unit
def test_password_gate_beats_everything_else():
    """No transport opens a password, so it must not be reported as a block to climb."""
    assert classify(cap(password_gated=True, challenged=True), None, [200, 401]) is Outcome.GATED


@pytest.mark.unit
def test_429_is_reported_as_a_rate_refusal_not_a_generic_challenge():
    """probe() sets challenged for any of 401/403/429; the raw status is the sharper fact."""
    assert classify(cap(challenged=True), None, [200, 429]) is Outcome.RATE_429


@pytest.mark.unit
def test_403_is_a_waf_refusal():
    assert classify(cap(challenged=True), None, [403, 403]) is Outcome.WAF_403


@pytest.mark.unit
def test_401_is_also_a_waf_refusal():
    assert classify(cap(challenged=True), None, [401]) is Outcome.WAF_403


@pytest.mark.unit
def test_429_wins_over_403_when_both_appear():
    """A rate refusal is the cheaper diagnosis; report it and let the ladder disprove it."""
    assert classify(cap(challenged=True), None, [403, 429]) is Outcome.RATE_429


@pytest.mark.unit
def test_interstitial_with_clean_statuses_is_a_challenge():
    """'Just a moment' served under HTTP 200 — nothing in the statuses gives it away."""
    assert classify(cap(challenged=True), None, [200, 200]) is Outcome.CHALLENGE


@pytest.mark.unit
def test_reachable_with_a_readable_feed_is_ok():
    assert classify(cap(), None, [200, 200]) is Outcome.OK


@pytest.mark.unit
def test_reachable_with_nothing_to_read_is_an_empty_room():
    """Psylos1 and XSAI: 200 everywhere, products rendered in the browser."""
    thin = cap(bulk_json=False, woo_api=False, ldjson_product=False)
    assert classify(thin, None, [200, 200]) is Outcome.OK_THIN


@pytest.mark.unit
def test_a_sitemap_alone_does_not_count_as_something_to_read():
    """A sitemap lists URLs. It does not make those pages parseable, and every
    client-rendered site has one — counting it would classify the empty room as OK."""
    thin = cap(bulk_json=False, woo_api=False, ldjson_product=False)
    assert thin.sitemap_url is not None
    assert classify(thin, None, [200]) is Outcome.OK_THIN


@pytest.mark.unit
@pytest.mark.parametrize("field", ["bulk_json", "woo_api", "ldjson_product"])
def test_any_one_readable_channel_is_enough_for_ok(field):
    kw = {"bulk_json": False, "woo_api": False, "ldjson_product": False, field: True}
    assert classify(cap(**kw), None, [200]) is Outcome.OK
