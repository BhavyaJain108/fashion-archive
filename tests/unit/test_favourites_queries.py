"""The queries favourites.py builds, and the schema they assume.

A favourite is now one of three kinds, and each kind has a different key. The
hazard is not that a query fails — a wrong key succeeds. `remove` matching on
three columns where the row is identified by four deletes somebody else's
saved look and reports success; a show keyed on `look_number` matches nothing
because the number is null. So these tests read the fragments directly rather
than going through a database.

They also read `schema.sql`, because two of its properties are what make the
fragments work: the partial indexes must exist before the old constraint is
dropped, and the whole file has to survive being re-run on every boot.

No database. The SQL these build is exercised against a real Postgres by hand;
what is pinned here is that the strings say what we think they say.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from userdata import favourites

pytestmark = pytest.mark.unit

SCHEMA = (Path(__file__).resolve().parents[2] / "backend" / "userdata" / "schema.sql").read_text()

USER = UUID("11111111-1111-1111-1111-111111111111")


class FakeCursor:
    def __init__(self, row, rowcount):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class FakeConn:
    """Records what it was asked to run instead of running it."""

    def __init__(self, row=None, rowcount=0):
        self.calls: list[tuple[str, tuple]] = []
        self._row = row
        self._rowcount = rowcount

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return FakeCursor(self._row, self._rowcount)

    @property
    def sql(self):
        return self.calls[-1][0]

    @property
    def params(self):
        return self.calls[-1][1]


class TestKinds:
    def test_the_three_kinds(self):
        assert favourites.KINDS == ("look", "show", "view")

    @pytest.mark.parametrize("kind", ["look", "show", "view"])
    def test_a_known_kind_passes_through(self, kind):
        assert favourites.check_kind(kind) == kind

    @pytest.mark.parametrize("kind", ["", "Look", "collection", None, "looks"])
    def test_an_unknown_kind_is_refused(self, kind):
        """No index covers an unrecognised kind, so a row with one would be a
        duplicate nobody catches."""
        with pytest.raises(favourites.UnknownKind):
            favourites.check_kind(kind)

    def test_unknown_kind_is_a_value_error(self):
        """The route layer catches ValueError to answer 400."""
        assert issubclass(favourites.UnknownKind, ValueError)


class TestConflictTarget:
    @pytest.mark.parametrize(
        "kind, predicate",
        [("look", "kind = 'look'"), ("show", "kind = 'show'"), ("view", "kind = 'view'")],
    )
    def test_every_target_restates_its_index_predicate(self, kind, predicate):
        """Inference on a partial index fails without its WHERE. Leaving it off
        raises at insert time instead of doing nothing on a duplicate."""
        target = favourites.conflict_target(kind)
        assert target.endswith(f"WHERE {predicate}")

    def test_a_look_is_keyed_on_its_number(self):
        assert favourites.conflict_target("look").startswith(
            "(user_id, season_url, collection_url, look_number)"
        )

    def test_a_show_is_not_keyed_on_a_number_it_does_not_have(self):
        target = favourites.conflict_target("show")
        assert target.startswith("(user_id, season_url, collection_url)")
        assert "look_number" not in target

    def test_a_view_is_keyed_on_its_filters(self):
        assert favourites.conflict_target("view").startswith("(user_id, md5(view_filters::text))")

    @pytest.mark.parametrize("kind", ["look", "show", "view"])
    def test_every_target_is_scoped_to_the_user(self, kind):
        """Global uniqueness would mean the second person to save a thing is
        told they already have it."""
        assert favourites.conflict_target(kind).startswith("(user_id,")

    @pytest.mark.parametrize("kind", ["look", "show", "view"])
    def test_the_target_matches_the_index_in_schema_sql(self, kind):
        """ON CONFLICT infers an index by repeating its definition. If the two
        drift, every insert of that kind raises."""
        columns, predicate = favourites.conflict_target(kind).split(" WHERE ")
        index = f"CREATE UNIQUE INDEX IF NOT EXISTS favourites_{kind}_key ON favourites"
        assert index in SCHEMA
        body = SCHEMA.split(index, 1)[1].split(";", 1)[0]
        assert " ".join(body.split()) == f"{columns} WHERE {predicate}"


class TestKeyClause:
    @pytest.mark.parametrize("kind", ["look", "show", "view"])
    def test_placeholders_and_names_agree(self, kind):
        """One name per placeholder, or the arguments slide along by one and
        the query matches a different row."""
        where, names = favourites.key_clause(kind)
        assert where.count("%s") == len(names)

    @pytest.mark.parametrize("kind", ["look", "show", "view"])
    def test_every_clause_names_its_kind_and_its_user(self, kind):
        where, names = favourites.key_clause(kind)
        assert f"kind = '{kind}'" in where
        assert names[0] == "user_id"

    def test_a_look_is_four_columns(self):
        where, names = favourites.key_clause("look")
        assert names == ("user_id", "season_url", "collection_url", "look_number")
        assert "look_number = %s" in where

    def test_a_show_is_three_and_never_the_number(self):
        """`look_number` is null on a show row, and null matches nothing."""
        where, names = favourites.key_clause("show")
        assert names == ("user_id", "season_url", "collection_url")
        assert "look_number" not in where

    def test_a_view_is_matched_through_jsonb_on_both_sides(self):
        """Comparing text to text would make key order significant again."""
        where, names = favourites.key_clause("view")
        assert names == ("user_id", "view_filters")
        assert "md5(view_filters::text) = md5(%s::jsonb::text)" in where

    def test_an_unknown_kind_has_no_clause(self):
        with pytest.raises(favourites.UnknownKind):
            favourites.key_clause("folder")


class TestCanonicalFilters:
    def test_key_order_does_not_matter(self):
        assert favourites.canonical_filters(
            {"year": 1997, "city": "Paris"}
        ) == favourites.canonical_filters({"city": "Paris", "year": 1997})

    def test_nothing_is_an_empty_object_not_null(self):
        assert favourites.canonical_filters(None) == "{}"
        assert favourites.canonical_filters({}) == "{}"

    def test_different_filters_stay_different(self):
        assert favourites.canonical_filters({"city": "Paris"}) != favourites.canonical_filters(
            {"city": "Milan"}
        )

    def test_a_value_is_not_confused_with_its_string(self):
        assert favourites.canonical_filters({"year": 1997}) != favourites.canonical_filters(
            {"year": "1997"}
        )

    def test_it_is_json_a_database_will_take(self):
        assert favourites.canonical_filters({"city": "Paris"}) == '{"city":"Paris"}'


class TestAdd:
    def test_a_look_keeps_the_call_it_always_had(self):
        """The frontend still calls this shape; Task 3 is what changes it."""
        conn = FakeConn(row=(1,))
        assert (
            favourites.add(
                conn,
                user_id=USER,
                season={"name": "Fall 2024", "url": "s", "link_text": "F24"},
                collection={"designer": "Balenciaga", "url": "c"},
                look={"number": 12, "total": 48},
                image_path="/img/12.jpg",
                notes="the coat",
            )
            is True
        )
        assert conn.params[:2] == (USER, "look")
        assert conn.params[7] == 12
        assert "WHERE kind = 'look'" in conn.sql

    def test_the_camel_case_look_keys_still_work(self):
        conn = FakeConn(row=(1,))
        favourites.add(
            conn,
            user_id=USER,
            season={},
            collection={},
            look={"lookNumber": 7, "lookTotal": 30},
            image_path="/img/7.jpg",
        )
        assert conn.params[7] == 7
        assert conn.params[8] == 30

    def test_a_conflict_reports_false_rather_than_raising(self):
        conn = FakeConn(row=None)
        assert favourites.add(conn, user_id=USER, look={"number": 1}) is False
        assert "DO NOTHING" in conn.sql

    def test_a_show_stores_no_look_number(self):
        """The whole point of dropping NOT NULL: a show is not at a position."""
        conn = FakeConn(row=(1,))
        favourites.add(
            conn,
            user_id=USER,
            kind="show",
            season={"name": "Fall 2024", "url": "s"},
            collection={"designer": "Balenciaga", "url": "c"},
            image_path="/img/1.jpg",
        )
        assert conn.params[1] == "show"
        assert conn.params[7] is None
        assert "WHERE kind = 'show'" in conn.sql

    def test_a_view_stores_canonical_filters(self):
        conn = FakeConn(row=(1,))
        favourites.add(
            conn,
            user_id=USER,
            kind="view",
            view_filters={"year": 1997, "city": "Paris"},
            view_name="Paris 1997",
        )
        assert conn.params[11] == '{"city":"Paris","year":1997}'
        assert conn.params[12] == "Paris 1997"
        assert "%s::jsonb" in conn.sql

    def test_the_other_kinds_store_no_filters(self):
        conn = FakeConn(row=(1,))
        favourites.add(conn, user_id=USER, look={"number": 1})
        assert conn.params[11] is None

    def test_a_missing_image_is_the_empty_string_not_null(self):
        """image_path is NOT NULL, and a saved view has no image."""
        conn = FakeConn(row=(1,))
        favourites.add(conn, user_id=USER, kind="view", view_filters={"city": "Paris"})
        assert conn.params[9] == ""

    def test_an_unknown_kind_never_reaches_the_database(self):
        conn = FakeConn(row=(1,))
        with pytest.raises(favourites.UnknownKind):
            favourites.add(conn, user_id=USER, kind="folder")
        assert conn.calls == []


class TestRemoveAndExists:
    def test_removing_a_look_passes_all_four(self):
        conn = FakeConn(rowcount=1)
        assert (
            favourites.remove(
                conn,
                user_id=USER,
                season_url="s",
                collection_url="c",
                look_number=12,
            )
            is True
        )
        assert conn.params == (USER, "s", "c", 12)

    def test_removing_nothing_reports_false(self):
        conn = FakeConn(rowcount=0)
        assert favourites.remove(conn, user_id=USER, season_url="s", collection_url="c") is False

    def test_removing_a_show_ignores_a_look_number_it_was_handed(self):
        """The caller may pass the look it was looking at. A show is not it."""
        conn = FakeConn(rowcount=1)
        favourites.remove(
            conn, user_id=USER, kind="show", season_url="s", collection_url="c", look_number=12
        )
        assert conn.params == (USER, "s", "c")
        assert "look_number" not in conn.sql

    def test_removing_a_view_matches_on_its_filters(self):
        conn = FakeConn(rowcount=1)
        favourites.remove(
            conn, user_id=USER, kind="view", view_filters={"year": 1997, "city": "Paris"}
        )
        assert conn.params == (USER, '{"city":"Paris","year":1997}')

    def test_a_view_saved_one_key_order_is_removable_in_the_other(self):
        saved = FakeConn(row=(1,))
        favourites.add(saved, user_id=USER, kind="view", view_filters={"year": 1997, "city": "P"})
        removing = FakeConn(rowcount=1)
        favourites.remove(
            removing, user_id=USER, kind="view", view_filters={"city": "P", "year": 1997}
        )
        assert saved.params[11] == removing.params[1]

    @pytest.mark.parametrize("kind", ["look", "show", "view"])
    def test_exists_asks_exactly_what_remove_deletes(self, kind):
        """A star that says saved and a delete that finds nothing is the same
        bug twice. One clause, both callers."""
        found = FakeConn(row=(1,))
        deleted = FakeConn(rowcount=1)
        args = dict(
            user_id=USER,
            kind=kind,
            season_url="s",
            collection_url="c",
            look_number=12,
            view_filters={"city": "Paris"},
        )
        favourites.exists(found, **args)
        favourites.remove(deleted, **args)
        assert found.params == deleted.params
        assert found.sql.split("WHERE", 1)[1] == deleted.sql.split("WHERE", 1)[1]

    def test_exists_reports_absence(self):
        assert favourites.exists(FakeConn(row=None), user_id=USER, look_number=1) is False


class TestShape:
    def row(self, **over):
        base = {
            "id": 3,
            "kind": "look",
            "season_name": "Fall 2024",
            "season_url": "s",
            "season_link_text": "F24",
            "collection_designer": "Balenciaga",
            "collection_url": "c",
            "look_number": 12,
            "look_total": 48,
            "image_path": "/img/12.jpg",
            "view_filters": None,
            "view_name": None,
            "notes": "the coat",
            "created_at": datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
        }
        base.update(over)
        return base

    def test_the_look_keys_are_the_ones_that_were_always_there(self):
        item = favourites.shape(self.row())
        assert {
            "id",
            "season",
            "collection",
            "look",
            "image_path",
            "date_added",
            "notes",
        } <= set(item)
        assert set(item["season"]) == {"name", "url", "link_text"}
        assert set(item["collection"]) == {"designer", "url"}
        assert set(item["look"]) == {"number", "total"}

    def test_every_kind_carries_every_key(self):
        """The UI reads `kind` and then the part it wants, rather than probing
        for which keys exist."""
        look = set(favourites.shape(self.row()))
        show = set(favourites.shape(self.row(kind="show", look_number=None)))
        view = set(
            favourites.shape(
                self.row(kind="view", view_filters={"city": "Paris"}, view_name="Paris")
            )
        )
        assert look == show == view
        assert "kind" in look and "view" in look

    def test_a_show_reads_as_a_show(self):
        item = favourites.shape(self.row(kind="show", look_number=None))
        assert item["kind"] == "show"
        assert item["look"]["number"] is None

    def test_a_view_carries_its_filters_and_name(self):
        item = favourites.shape(
            self.row(kind="view", view_filters={"city": "Paris"}, view_name="Paris")
        )
        assert item["view"] == {"name": "Paris", "filters": {"city": "Paris"}}

    def test_the_date_is_the_string_the_frontend_parses(self):
        assert favourites.shape(self.row())["date_added"] == "2026-01-01T10:00:00+00:00"


class TestSchemaFile:
    """Properties of schema.sql that migrate.py re-runs on every boot."""

    def test_the_indexes_are_created_before_the_constraint_is_dropped(self):
        """Otherwise there is a window with no uniqueness rule on looks at
        all, and a double-click in it saves twice."""
        drop = SCHEMA.index("DROP CONSTRAINT")
        for kind in ("look", "show", "view"):
            assert SCHEMA.index(f"favourites_{kind}_key") < drop

    def test_the_old_constraint_is_found_rather_than_named(self):
        """Postgres generated the name. Guessing it works until it doesn't."""
        assert "pg_constraint" in SCHEMA
        assert "favourites_user_id_season_url_collection_url_look_number_key" not in SCHEMA

    def test_the_drop_is_guarded_so_a_second_boot_does_nothing(self):
        block = SCHEMA[SCHEMA.index("DO $$") : SCHEMA.index("DROP CONSTRAINT")]
        assert "FOR" in block and "pg_constraint" in block

    def test_every_added_column_tolerates_already_being_there(self):
        for line in SCHEMA.splitlines():
            if "ADD COLUMN" in line:
                assert "IF NOT EXISTS" in line, line

    def test_every_index_tolerates_already_being_there(self):
        for line in SCHEMA.splitlines():
            if line.startswith("CREATE") and "INDEX" in line:
                assert "IF NOT EXISTS" in line, line

    def test_look_number_is_made_nullable(self):
        assert "ALTER COLUMN look_number DROP NOT NULL" in SCHEMA

    def test_the_file_holds_no_percent_sign(self):
        """It is handed to psycopg as one string; a percent sign is the one
        character it could read as a placeholder."""
        assert "%" not in SCHEMA
