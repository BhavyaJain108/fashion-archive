"""Reading the matrix, and choosing what to sweep."""

import pytest

from backend.archive.access.outcome import Outcome
from backend.archive.access.probe import AccessResult
from backend.archive.access.report import format_matrix, format_plan
from backend.archive.access.strategy import get
from backend.archive.access.targets import failing_domains
from backend.archive.roster import RosterEntry


def r(domain, strategy, outcome, **kw):
    return AccessResult(domain, strategy, outcome, requests=4, **kw)


@pytest.mark.unit
def test_the_columns_are_the_strategies_tried_cheapest_first():
    out = format_matrix(
        [r("a.com", "cffi:chrome142", Outcome.OK), r("a.com", "httpx", Outcome.WAF_403)]
    )
    header = out.splitlines()[0]
    assert header.index("httpx") < header.index("cffi:chrome142")


@pytest.mark.unit
def test_a_strategy_never_tried_on_a_brand_shows_as_untried_not_as_a_failure():
    out = format_matrix(
        [
            r("a.com", "httpx", Outcome.OK),
            r("b.com", "httpx", Outcome.WAF_403),
            r("b.com", "patchright", Outcome.OK),
        ]
    )
    row = next(line for line in out.splitlines() if line.startswith("a.com"))
    assert "ok" in row and "-" in row


@pytest.mark.unit
def test_the_winning_strategy_is_named():
    out = format_matrix(
        [r("a.com", "httpx", Outcome.RATE_429), r("a.com", "patchright", Outcome.OK)]
    )
    assert "patchright" in out.splitlines()[-1] or "patchright" in out


@pytest.mark.unit
def test_a_brand_nothing_opened_is_shown_as_still_shut():
    out = format_matrix([r("gentlemonster.com", "httpx", Outcome.WAF_403)])
    row = next(line for line in out.splitlines() if line.startswith("gentlemonster.com"))
    assert "waf_403" in row


@pytest.mark.unit
def test_a_rate_refusal_measured_during_our_own_scrape_is_flagged_as_unreliable():
    """Our Render worker hits the same hosts. A 429 taken while it held the brand may
    be us, and a reading we cannot trust must not look like one we can."""
    out = format_matrix([r("staud.clothing", "httpx", Outcome.RATE_429, daemon_active=True)])
    assert "!" in out
    assert "daemon" in out.lower()


@pytest.mark.unit
def test_a_clean_rate_refusal_is_not_flagged():
    out = format_matrix([r("staud.clothing", "httpx", Outcome.RATE_429, daemon_active=False)])
    assert "daemon" not in out.lower()


@pytest.mark.unit
def test_an_empty_matrix_says_so_rather_than_printing_a_bare_header():
    assert "nothing" in format_matrix([]).lower()


@pytest.mark.unit
def test_the_dry_run_plan_counts_the_requests_it_would_make():
    plan = format_plan(["a.com", "b.com"], [get("httpx"), get("cffi:chrome142")])
    assert "a.com" in plan and "b.com" in plan
    assert "8" in plan  # 2 brands x 4 GETs on the first rung


@pytest.mark.unit
def test_the_dry_run_plan_names_the_hosts_it_would_touch():
    assert "staud.clothing" in format_plan(["staud.clothing"], [get("httpx")])


ROSTER = [
    RosterEntry("staud.clothing", "https://staud.clothing", "STAUD", "429 to plain http", "mid"),
    RosterEntry("kuurth.com", "https://kuurth.com", "KUURTH", None, "small"),
    RosterEntry(
        "coltmcr.com", "https://coltmcr.com", "COLTMCR", "password-gated 2026-08-26", "small"
    ),
    RosterEntry("psylos1.com", "https://psylos1.com", "Psylos1", "custom nextjs", "mid"),
    RosterEntry(
        "www.vancleefarpels.com",
        "https://www.vancleefarpels.com",
        "VCA",
        "TLS-level block",
        "large",
    ),
    RosterEntry(
        "laluneofficial.com", "https://laluneofficial.com", "La Lune", "wordpress", "small"
    ),
]


@pytest.mark.unit
def test_the_failing_set_picks_the_brands_whose_notes_record_a_refusal():
    assert "staud.clothing" in failing_domains(ROSTER)
    assert "www.vancleefarpels.com" in failing_domains(ROSTER)


@pytest.mark.unit
def test_a_brand_with_no_notes_is_not_in_the_failing_set():
    assert "kuurth.com" not in failing_domains(ROSTER)


@pytest.mark.unit
def test_a_note_that_only_names_the_platform_is_not_a_failure():
    assert "laluneofficial.com" not in failing_domains(ROSTER)


@pytest.mark.unit
def test_password_gated_brands_are_left_out_because_no_transport_opens_a_password():
    assert "coltmcr.com" not in failing_domains(ROSTER)


@pytest.mark.unit
def test_a_client_rendered_brand_is_in_the_failing_set():
    """It produces nothing today, and the sweep's job is to say why — that it is an
    empty room and not a locked door."""
    assert "psylos1.com" in failing_domains(ROSTER)
