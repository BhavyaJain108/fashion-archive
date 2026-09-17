"""Probing climbs transports until the brand is readable."""

import httpx
import pytest

from backend.archive.domain.brand import Capability, TransportLevel
from backend.archive.escalate import escalating_prober, readable


def cap(level=TransportLevel.T0, **kw):
    base = dict(domain="x.com", transport=level, bulk_json=False, ldjson_product=False)
    base.update(kw)
    return Capability(**base)


def scripted(by_level: dict, seen: list):
    """A probe that answers by the level of the transport it was handed."""

    def base(domain, transport):
        level = getattr(transport, "level", TransportLevel.T0)
        seen.append(level)
        answer = by_level.get(level)
        if isinstance(answer, Exception):
            raise answer
        return answer if answer is not None else cap()

    return base


@pytest.mark.unit
def test_a_brand_that_answers_plain_http_is_never_escalated():
    seen = []
    base = scripted({TransportLevel.T0: cap(bulk_json=True)}, seen)
    got = escalating_prober(base=base)("x.com", HttpxStub())
    assert got.bulk_json and seen == [TransportLevel.T0]


@pytest.mark.unit
def test_a_brand_that_refuses_plain_http_is_asked_again_in_another_voice():
    """Vivienne Westwood: 403 to Python's handshake, readable to a browser's."""
    seen = []
    base = scripted(
        {TransportLevel.T0: cap(challenged=True), TransportLevel.T1: cap(ldjson_product=True)}, seen
    )
    got = escalating_prober(base=base)("x.com", HttpxStub())
    assert seen == [TransportLevel.T0, TransportLevel.T1]
    assert got.transport is TransportLevel.T1 and got.ldjson_product


@pytest.mark.unit
def test_a_timeout_is_a_refusal_and_still_climbs():
    """Van Cleef answered plain HTTP with fifteen seconds of silence."""
    seen = []
    base = scripted(
        {
            TransportLevel.T0: httpx.ReadTimeout("timed out"),
            TransportLevel.T1: cap(ldjson_product=True),
        },
        seen,
    )
    got = escalating_prober(base=base)("x.com", HttpxStub())
    assert got.transport is TransportLevel.T1 and got.ldjson_product


@pytest.mark.unit
def test_a_password_stops_the_climb_because_no_transport_opens_one():
    seen = []
    base = scripted({TransportLevel.T0: cap(password_gated=True)}, seen)
    escalating_prober(base=base)("x.com", HttpxStub())
    assert seen == [TransportLevel.T0]


@pytest.mark.unit
def test_the_browser_is_only_reached_when_one_was_supplied():
    seen = []
    base = scripted({}, seen)
    escalating_prober(base=base)("x.com", HttpxStub())
    assert TransportLevel.T2 not in seen


@pytest.mark.unit
def test_a_brand_only_a_browser_can_read_is_marked_as_needing_one():
    seen = []
    base = scripted({TransportLevel.T2: cap(ldjson_product=True)}, seen)
    got = escalating_prober(base=base, browser_factory=BrowserStub)("x.com", HttpxStub())
    assert seen[-1] is TransportLevel.T2
    assert got.transport is TransportLevel.T2


@pytest.mark.unit
def test_a_brand_nothing_can_read_still_returns_what_the_first_probe_saw():
    """The plan must record needs_attention, not crash the run."""
    seen = []
    base = scripted({TransportLevel.T0: cap(challenged=True)}, seen)
    got = escalating_prober(base=base)("x.com", HttpxStub())
    assert got.challenged and not readable(got)


@pytest.mark.unit
def test_a_brand_that_answers_nothing_at_any_level_is_still_a_capability():
    seen = []
    base = scripted(
        {
            TransportLevel.T0: httpx.ConnectError("no route"),
            TransportLevel.T1: httpx.ConnectError("no route"),
        },
        seen,
    )
    got = escalating_prober(base=base)("x.com", HttpxStub())
    assert got.domain == "x.com" and not readable(got)


class HttpxStub:
    level = TransportLevel.T0


class BrowserStub:
    level = TransportLevel.T2

    def close(self):
        pass
