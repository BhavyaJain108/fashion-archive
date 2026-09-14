"""The sweep: every brand up the ladder, stopping as soon as something works."""

import pytest

from backend.archive.access.bench import sweep, winners
from backend.archive.access.outcome import Outcome
from backend.archive.access.probe import AccessResult
from backend.archive.access.strategy import Strategy
from backend.archive.domain.brand import TransportLevel

CHEAP = Strategy("cheap", 0, "http", TransportLevel.T0, 0.0, None, lambda: None)
MID = Strategy("mid", 1, "http", TransportLevel.T1, 0.0, None, lambda: None)
BROWSER = Strategy("browser", 3, "browser", TransportLevel.T2, 0.0, None, lambda: None)
LADDER = [CHEAP, MID, BROWSER]


def scripted(*, default=Outcome.OK, **by_strategy):
    """A probe that answers from a script and records what it was asked."""
    calls: list[tuple[str, str]] = []

    def probe_fn(domain, strategy, **kw):
        calls.append((domain, strategy.name))
        outcome = by_strategy.get(strategy.name, default)
        if callable(outcome):
            outcome = outcome(domain)
        return AccessResult(domain, strategy.name, outcome, requests=4)

    probe_fn.calls = calls
    return probe_fn


@pytest.mark.unit
def test_the_cheapest_key_that_works_ends_the_climb():
    p = scripted(default=Outcome.OK)
    results = sweep(["kuurth.com"], LADDER, probe_fn=p)
    assert [c[1] for c in p.calls] == ["cheap"]
    assert len(results) == 1 and results[0].outcome is Outcome.OK


@pytest.mark.unit
def test_a_refusal_climbs_until_something_works():
    p = scripted(cheap=Outcome.RATE_429, mid=Outcome.OK)
    sweep(["staud.clothing"], LADDER, probe_fn=p)
    assert [c[1] for c in p.calls] == ["cheap", "mid"]


@pytest.mark.unit
def test_a_brand_that_refuses_everything_exhausts_the_ladder():
    p = scripted(default=Outcome.WAF_403)
    results = sweep(["gentlemonster.com"], LADDER, probe_fn=p)
    assert [c[1] for c in p.calls] == ["cheap", "mid", "browser"]
    assert len(results) == 3


@pytest.mark.unit
def test_an_empty_room_skips_the_http_tiers_and_goes_to_the_renderer():
    """The rule the whole design turns on: no TLS fingerprint renders JavaScript."""
    p = scripted(cheap=Outcome.OK_THIN, browser=Outcome.OK)
    sweep(["psylos1.com"], LADDER, probe_fn=p)
    assert [c[1] for c in p.calls] == ["cheap", "browser"]


@pytest.mark.unit
def test_a_password_stops_after_one_look():
    p = scripted(default=Outcome.GATED)
    sweep(["coltmcr.com"], LADDER, probe_fn=p)
    assert [c[1] for c in p.calls] == ["cheap"]


@pytest.mark.unit
def test_an_unreachable_host_is_given_exactly_one_second_chance():
    """Hosts flap. One retry is worth it; a ladder climb against DNS is not."""
    p = scripted(default=Outcome.UNREACHABLE)
    sweep(["gone.example"], LADDER, probe_fn=p)
    assert [c[1] for c in p.calls] == ["cheap", "cheap"]


@pytest.mark.unit
def test_a_host_that_comes_back_on_the_retry_carries_on_normally():
    seen = {"n": 0}

    def flaky(domain):
        seen["n"] += 1
        return Outcome.UNREACHABLE if seen["n"] == 1 else Outcome.OK

    p = scripted(cheap=flaky)
    sweep(["flaky.example"], LADDER, probe_fn=p)
    assert [c[1] for c in p.calls] == ["cheap", "cheap"]


@pytest.mark.unit
def test_strategies_whose_library_is_missing_are_skipped_not_attempted():
    missing = Strategy("absent", 1, "http", TransportLevel.T1, 0.0, "no_such_module", lambda: None)
    p = scripted(default=Outcome.WAF_403)
    sweep(["x.com"], [CHEAP, missing, BROWSER], probe_fn=p)
    assert [c[1] for c in p.calls] == ["cheap", "browser"]


@pytest.mark.unit
def test_every_brand_gets_its_own_ladder():
    p = scripted(cheap=lambda d: Outcome.OK if d == "a.com" else Outcome.WAF_403)
    sweep(["a.com", "b.com"], [CHEAP, MID], probe_fn=p)
    assert p.calls == [("a.com", "cheap"), ("b.com", "cheap"), ("b.com", "mid")]


@pytest.mark.unit
def test_every_attempt_is_kept_not_just_the_one_that_worked():
    """The failures are the record: which lane a brand refused is how we notice its
    defences changing later."""
    p = scripted(cheap=Outcome.RATE_429, mid=Outcome.OK)
    results = sweep(["staud.clothing"], LADDER, probe_fn=p)
    assert [(r.strategy, r.outcome) for r in results] == [
        ("cheap", Outcome.RATE_429),
        ("mid", Outcome.OK),
    ]


@pytest.mark.unit
def test_the_winner_is_the_cheapest_strategy_that_worked():
    p = scripted(cheap=Outcome.RATE_429, mid=Outcome.OK)
    got = winners(sweep(["staud.clothing"], LADDER, probe_fn=p))
    assert got["staud.clothing"].strategy == "mid"


@pytest.mark.unit
def test_a_brand_nothing_opened_has_no_winner():
    p = scripted(default=Outcome.WAF_403)
    assert winners(sweep(["gentlemonster.com"], LADDER, probe_fn=p)) == {}


@pytest.mark.unit
def test_an_empty_room_is_not_a_winner_even_though_it_answered_200():
    """Reaching a site we cannot read is not access. Recording it as one would quietly
    mark the brand solved and it would never be looked at again."""
    p = scripted(default=Outcome.OK_THIN)
    assert winners(sweep(["psylos1.com"], [CHEAP], probe_fn=p)) == {}


@pytest.mark.unit
def test_results_are_reported_as_they_land():
    """A sweep of the full roster takes minutes; it must not go silent until the end."""
    seen = []
    p = scripted(cheap=Outcome.RATE_429, mid=Outcome.OK)
    sweep(["staud.clothing"], LADDER, probe_fn=p, on_result=seen.append)
    assert [r.strategy for r in seen] == ["cheap", "mid"]
