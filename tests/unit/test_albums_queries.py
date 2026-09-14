"""The album SQL, read as strings.

Two things here do not need a database to go wrong. `schema.sql` re-runs on
every boot with no migration versioning, so a statement that is not written to
be a no-op the second time takes the API down on its next deploy rather than at
the moment it was written. And `sort_by` is interpolated into an ORDER BY,
which is the one place in this module where a caller's string could reach the
query text.

The behaviour these support is exercised against a real Postgres in
tests/db/test_albums.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from userdata import albums

pytestmark = pytest.mark.unit

SCHEMA = (Path(__file__).resolve().parents[2] / "backend" / "userdata" / "schema.sql").read_text()


class TestTheSchemaSurvivesBeingReRun:
    def test_every_create_in_the_file_is_guarded(self):
        """No migration versioning: the whole file is applied on every boot."""
        unguarded = [
            statement
            for statement in re.findall(r"CREATE (?:UNIQUE )?(?:TABLE|INDEX)[^;]*", SCHEMA)
            if "IF NOT EXISTS" not in statement
        ]
        assert unguarded == []

    def test_the_album_tables_are_there(self):
        assert "CREATE TABLE IF NOT EXISTS albums" in SCHEMA
        assert "CREATE TABLE IF NOT EXISTS album_items" in SCHEMA

    def test_removing_a_favourite_cascades_out_of_every_album(self):
        assert "favourite_id bigint NOT NULL REFERENCES favourites(id) ON DELETE CASCADE" in SCHEMA

    def test_deleting_an_album_cascades_its_memberships_and_nothing_else(self):
        assert "album_id     bigint NOT NULL REFERENCES albums(id) ON DELETE CASCADE" in SCHEMA
        # The favourites table has no reference to albums at all, so there is
        # nothing for an album's deletion to reach.
        favourites_ddl = SCHEMA[
            SCHEMA.index("CREATE TABLE IF NOT EXISTS favourites") : SCHEMA.index(
                "CREATE INDEX IF NOT EXISTS idx_favourites_user"
            )
        ]
        assert "album" not in favourites_ddl

    def test_an_album_holds_a_favourite_once(self):
        assert "PRIMARY KEY (album_id, favourite_id)" in SCHEMA

    def test_the_name_is_unique_per_user_case_insensitively(self):
        assert (
            "CREATE UNIQUE INDEX IF NOT EXISTS albums_user_name_key ON albums (user_id, lower(name))"
            in SCHEMA
        )

    def test_the_referencing_side_of_the_cascade_is_indexed(self):
        """Postgres indexes the referenced side of a foreign key and not the
        referencing one, so un-saving would seq-scan album_items without this."""
        assert "ON album_items (favourite_id)" in SCHEMA

    def test_the_canvas_columns_are_there_and_nullable(self):
        assert "x integer, y integer, w integer, z integer" in SCHEMA


class TestTheSortIsAClosedSet:
    def test_only_known_sorts_reach_an_order_by(self):
        for sort_by in albums.SORT_ORDERS:
            assert albums.check_sort_by(sort_by) == sort_by

    def test_anything_else_raises(self):
        for bad in ("id", "", "sort_index; DROP TABLE albums", "added "):
            with pytest.raises(albums.UnknownOption):
                albums.check_sort_by(bad)

    def test_the_stored_sorts_are_the_ones_the_table_allows(self):
        """The CHECK constraint and this dict have to name the same three, or a
        stored value has no ORDER BY and the album will not render."""
        assert "sort_by IN ('added', 'designer', 'season')" in SCHEMA
        assert set(albums.SORT_ORDERS) == {"added", "designer", "season"}

    def test_the_layout_modes_match_the_table_too(self):
        assert "layout_mode IN ('grid', 'canvas')" in SCHEMA
        assert set(albums.LAYOUT_MODES) == {"grid", "canvas"}


class TestTheName:
    def test_it_is_trimmed(self):
        assert albums.clean_name("  Resort ") == "Resort"

    def test_inner_space_is_left_alone(self):
        assert albums.clean_name("Resort 2001") == "Resort 2001"

    @pytest.mark.parametrize("name", ["", "   ", "\t\n", None, 7, []])
    def test_nothing_to_click_on_is_refused(self, name):
        with pytest.raises(albums.BlankName):
            albums.clean_name(name)
