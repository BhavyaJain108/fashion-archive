"""The indexed text behind free-text search over shows.

firstVIEW can search designer names and nothing else, so "chanel fw25" had
no query to be — it would have had to be guessed apart into a designer, a
year and a season, which is guesswork about word order that fails quietly.

Holding the archive locally removes the need: each show is indexed with
everything someone might type for it, including the shorthand nobody spells
out. That expansion is what these tests pin. Get it wrong and search does
not break, it just stops finding things — the worst kind of wrong.

Pure string work, no database.
"""

from __future__ import annotations

import pytest
from high_fashion.show_index import SEASON_RANK, normalise, search_text, sort_rank

pytestmark = pytest.mark.unit


def show(**over):
    base = {
        "c": "57696",
        "d": "Yohji Yamamoto",
        "s": "Fall / Winter",
        "y": 2025,
        "g": "Women",
        "n": "Ready-to-Wear",
        "t": "Runway Collection",
        "p": "Paris",
    }
    base.update(over)
    return base


class TestNormalise:
    def test_strips_accents(self):
        assert normalise("Comme des Garçons") == "comme des garcons"

    def test_flattens_punctuation_to_spaces(self):
        assert normalise("Ready-to-Wear") == "ready to wear"
        assert normalise("Fall / Winter") == "fall winter"

    def test_collapses_runs_of_space(self):
        assert normalise("  A   B  ") == "a b"

    def test_survives_nothing(self):
        assert normalise("") == ""
        assert normalise(None) == ""


class TestSearchText:
    @pytest.mark.parametrize(
        "term",
        [
            "yohji",
            "yamamoto",  # the designer
            "paris",
            "women",  # where and who for
            "2025",  # the year in full
            "fall winter",
            "fw",
            "aw",
            "fw2025",
            "fw25",  # the two ways a season-year is ever written
            "aw2025",
            "aw25",
            "ready to wear",
            "rtw",
        ],
    )
    def test_finds_what_people_type(self, term):
        assert term in search_text(show())

    def test_spring_summer_shorthand(self):
        text = search_text(show(s="Spring / Summer", y=2019))
        assert "ss2019" in text
        assert "ss19" in text
        assert "spring summer" in text

    def test_couture_without_haute(self):
        assert "couture" in search_text(show(n="Haute Couture"))

    def test_cruise_answers_to_resort(self):
        assert "resort" in search_text(show(s="Cruise"))

    def test_single_digit_years_keep_two_places(self):
        """2005 is 'ss05', never 'ss5'."""
        assert "ss05" in search_text(show(s="Spring / Summer", y=2005))
        assert "ss5" not in search_text(show(s="Spring / Summer", y=2005))

    def test_every_term_of_a_query_is_present(self):
        """What "chanel fw25" actually relies on: both terms in one row."""
        text = search_text(show(d="Chanel", s="Fall / Winter", y=2025))
        assert all(term in text for term in ("chanel", "fw25"))

    def test_a_missing_season_is_not_an_error(self):
        text = search_text(show(s=None))
        assert "yohji" in text
        assert "2025" in text

    def test_accented_designers_are_searchable_unaccented(self):
        assert "comme des garcons" in search_text(show(d="Comme des Garçons"))


class TestSortRank:
    def test_later_years_first(self):
        assert sort_rank(show(y=2026)) > sort_rank(show(y=2019))

    def test_later_season_first_within_a_year(self):
        """F/W 2026 is listed above S/S 2026, the way the site does."""
        assert sort_rank(show(y=2026, s="Fall / Winter")) > sort_rank(
            show(y=2026, s="Spring / Summer")
        )

    def test_year_outranks_season(self):
        """S/S 2027 still comes before F/W 2026."""
        assert sort_rank(show(y=2027, s="Spring / Summer")) > sort_rank(
            show(y=2026, s="Fall / Winter")
        )

    def test_every_season_is_ranked(self):
        """An unranked season would sort below everything in its own year."""
        from high_fashion.firstview import SEASONS

        assert set(SEASONS) == set(SEASON_RANK)

    def test_a_missing_year_sorts_last(self):
        assert sort_rank(show(y=None)) < sort_rank(show(y=1989))
