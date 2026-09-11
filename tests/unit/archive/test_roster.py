import pytest

from backend.archive.roster import BRANDS_YML, RosterEntry, app_roster, load_roster

YML = """
brands:
  - {domain: small.com, homepage_url: "https://small.com", display_name: "Small", size: small}
  - {domain: www.mid.com, homepage_url: "https://www.mid.com", size: mid}
  - {domain: big.com, homepage_url: "https://big.com", display_name: "Big", size: large}
  - {domain: outlet.com, homepage_url: "https://outlet.com", size: multi_brand}
"""


@pytest.fixture()
def roster_file(tmp_path):
    path = tmp_path / "brands.yml"
    path.write_text(YML)
    return path


@pytest.mark.unit
def test_every_brand_stays_in_the_file(roster_file):
    # The scraper can still be pointed at a house or an outlet; only the app withholds
    # them. Dropping them from the roster entirely would be a different decision.
    assert {e.domain for e in load_roster(roster_file)} == {
        "small.com",
        "www.mid.com",
        "big.com",
        "outlet.com",
    }


@pytest.mark.unit
def test_app_shows_small_and_mid_only_in_name_order(roster_file):
    # "mid" before "Small": the sidebar reads by name, so the sort is by name.
    assert [e.domain for e in app_roster(roster_file)] == ["www.mid.com", "small.com"]


@pytest.mark.unit
def test_name_falls_back_to_the_domain_stem():
    assert RosterEntry("www.mid.com", "https://www.mid.com").name == "mid"
    assert RosterEntry("x.com", "https://x.com", display_name="Ecks").name == "Ecks"


@pytest.mark.unit
def test_shipped_roster_parses_and_is_all_classified():
    entries = load_roster(BRANDS_YML)
    assert entries, "brands.yml is the roster; an empty one is a bug"
    assert all(e.size in ("small", "mid", "large", "multi_brand") for e in entries)
    assert all(e.homepage_url.startswith("https://") for e in entries)
    assert len({e.domain for e in entries}) == len(entries)
    assert app_roster(BRANDS_YML), "the page would have nothing to show"
