"""The shelf of named ways to get in.

Nothing about a transport is testable until it has a name; these are the names.
"""

import pytest

from backend.archive.access import strategy as S
from backend.archive.domain.brand import TransportLevel


@pytest.mark.unit
def test_the_ladder_is_ordered_cheapest_first():
    tiers = [s.tier for s in S.all_strategies()]
    assert tiers == sorted(tiers)
    assert S.all_strategies()[0].name == "httpx"


@pytest.mark.unit
def test_every_registered_name_resolves():
    for s in S.all_strategies():
        assert S.get(s.name) is s


@pytest.mark.unit
def test_an_unknown_name_says_so_and_lists_the_real_ones():
    with pytest.raises(KeyError) as e:
        S.get("cffi:netscape")
    assert "cffi:netscape" in str(e.value) and "httpx" in str(e.value)


@pytest.mark.unit
def test_listing_the_shelf_imports_nothing():
    """A missing optional dependency must not break the CLI, so nothing is imported
    until a strategy is actually built."""
    import sys

    for mod in ("curl_cffi", "playwright", "patchright"):
        sys.modules.pop(mod, None)
    S.all_strategies()
    assert not {"curl_cffi", "playwright", "patchright"} & set(sys.modules)


@pytest.mark.unit
def test_httpx_is_always_available_and_builds_a_working_transport():
    s = S.get("httpx")
    assert s.available
    t = s.build()
    assert hasattr(t, "get") and t.level is TransportLevel.T0


@pytest.mark.unit
def test_a_strategy_whose_library_is_missing_reports_unavailable(monkeypatch):
    monkeypatch.setattr(S, "_installed", lambda name: False)
    assert S.get("cffi:chrome142").available is False


@pytest.mark.unit
def test_building_an_unavailable_strategy_names_the_missing_library(monkeypatch):
    monkeypatch.setattr(S, "_installed", lambda name: False)
    with pytest.raises(S.StrategyUnavailable) as e:
        S.get("cffi:chrome142").build()
    assert "curl_cffi" in str(e.value)


@pytest.mark.unit
def test_browser_strategies_are_marked_as_such():
    """The escalation policy sends an empty room to a renderer, so it has to be able
    to tell which strategies render."""
    kinds = {s.name: s.kind for s in S.all_strategies()}
    assert kinds["httpx"] == "http"
    assert kinds["cffi:chrome142"] == "http"
    assert kinds["playwright"] == "browser"
    assert kinds["patchright"] == "browser"


@pytest.mark.unit
def test_browser_strategies_report_t2_so_deep_probes_run():
    """fingerprint.probe only pays for the deep probes on a challenged site when the
    transport says T2; a browser lane that reported T0 would learn nothing extra."""
    for name in ("playwright", "patchright"):
        assert S.get(name).level is TransportLevel.T2


@pytest.mark.unit
def test_free_tiers_cost_nothing_and_say_so():
    assert all(s.usd_per_1k == 0.0 for s in S.all_strategies())


@pytest.mark.unit
def test_names_can_be_parsed_from_a_comma_list():
    picked = S.select("httpx,patchright")
    assert [s.name for s in picked] == ["httpx", "patchright"]


@pytest.mark.unit
def test_selecting_keeps_the_cheapest_first_order_whatever_order_was_asked_for():
    assert [s.name for s in S.select("patchright,httpx")] == ["httpx", "patchright"]
