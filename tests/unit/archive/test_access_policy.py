"""Which key to try next, given how the last one was refused.

The two rules the harness rests on live here: an empty room is not a locked door, and
you stop the moment something works.
"""

import pytest

from backend.archive.access.outcome import Outcome
from backend.archive.access.policy import next_strategies
from backend.archive.access.strategy import all_strategies, get

HTTP_TIERS = [get("cffi:chrome142"), get("cffi:chrome131")]
BROWSERS = [get("playwright"), get("patchright")]
REST = HTTP_TIERS + BROWSERS


@pytest.mark.unit
def test_success_stops_the_climb():
    """The whole point of ordering by cost: never pay for a dearer tier than works."""
    assert next_strategies(Outcome.OK, REST) == []


@pytest.mark.unit
def test_a_password_stops_the_climb():
    assert next_strategies(Outcome.GATED, REST) == []


@pytest.mark.unit
def test_a_timeout_climbs_because_a_silent_waf_looks_like_a_dead_host():
    """Van Cleef dropped plain HTTP without answering; only a different handshake tells
    a silent refusal from a host that is really down."""
    assert next_strategies(Outcome.UNREACHABLE, REST) == REST


@pytest.mark.unit
@pytest.mark.parametrize(
    "outcome",
    [
        Outcome.RATE_429,
        Outcome.WAF_403,
        Outcome.TLS_BLOCKED,
        Outcome.CHALLENGE,
        Outcome.UNREACHABLE,
    ],
)
def test_every_refusal_climbs_the_whole_remaining_ladder(outcome):
    assert next_strategies(outcome, REST) == REST


@pytest.mark.unit
def test_an_empty_room_skips_straight_to_the_renderers():
    """Psylos1 answers 200 with no product data. Three more TLS fingerprints cannot
    render JavaScript, so trying them is pure spend for a guaranteed repeat answer."""
    assert next_strategies(Outcome.OK_THIN, REST) == BROWSERS


@pytest.mark.unit
def test_an_empty_room_with_no_renderer_left_gives_up():
    assert next_strategies(Outcome.OK_THIN, HTTP_TIERS) == []


@pytest.mark.unit
def test_the_climb_keeps_the_cheapest_first_order_it_was_given():
    shuffled = [get("patchright"), get("cffi:chrome142")]
    assert [s.name for s in next_strategies(Outcome.WAF_403, shuffled)] == [
        "cffi:chrome142",
        "patchright",
    ]


@pytest.mark.unit
def test_nothing_left_to_try_is_not_an_error():
    for outcome in Outcome:
        assert next_strategies(outcome, []) == []


@pytest.mark.unit
def test_the_full_shelf_starts_with_the_control():
    """A sweep always records what today's transport does, so a brand's defences
    changing under us shows up as a change in the httpx row."""
    assert all_strategies()[0].name == "httpx"
