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

# One real collection page URL, in the spelling the archive list uses.
SHOW_URL = "https://www.firstview.com/collection_images.php?id=12345&list=all"


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


class TestNormaliseFilters:
    """What the server stores when a client saves a view.

    This is the whole identity of a saved view: `md5(view_filters::text)` is the
    unique index, so anything that reaches the stored document changes what the
    view IS. A stray key means the same view saved twice is two rows, and the
    second one can never be found by the first one's filters again.
    """

    def test_the_keys_are_the_query_string_ones(self):
        """web_ui/src/app/routes.js decides which filters exist. If this list
        and that one drift, a filter the UI sends is silently dropped."""
        assert set(favourites.FILTER_KEYS) == {
            "gender",
            "year",
            "season",
            "category",
            "shootType",
            "city",
            "letter",
        }

    def test_a_known_filter_survives(self):
        assert favourites.normalise_filters({"city": "Paris"}) == {"city": "Paris"}

    def test_an_unknown_key_is_dropped(self):
        """A page number or an auth token arriving beside the filters would
        otherwise be part of the view's identity."""
        assert favourites.normalise_filters(
            {"city": "Paris", "page": 3, "token": "abc"}
        ) == {"city": "Paris"}

    def test_an_empty_value_is_dropped(self):
        """The client's own rule is `value !== ''` — an unset filter is not a
        filter, and storing it would make "Paris" and "Paris with the year box
        empty" two different saved views."""
        assert favourites.normalise_filters({"city": "Paris", "year": ""}) == {"city": "Paris"}

    def test_whitespace_is_not_a_value(self):
        assert favourites.normalise_filters({"city": "  ", "year": " 1997 "}) == {"year": "1997"}

    def test_a_number_becomes_its_text(self):
        """A filter comes off a URL as text. `1997` and `"1997"` are the same
        view and must not hash differently."""
        assert favourites.normalise_filters({"year": 1997}) == {"year": "1997"}
        assert favourites.normalise_filters({"year": 1997}) == favourites.normalise_filters(
            {"year": "1997"}
        )

    @pytest.mark.parametrize("value", [None, True, False, [], {}, ["Paris"], {"a": 1}])
    def test_a_value_that_is_not_a_filter_is_dropped(self, value):
        assert favourites.normalise_filters({"city": value}) == {}

    @pytest.mark.parametrize("raw", [None, "Paris", 7, [], ["city"]])
    def test_a_body_that_is_not_an_object_is_no_filters(self, raw):
        assert favourites.normalise_filters(raw) == {}

    def test_nothing_filtered_is_an_empty_object(self):
        assert favourites.normalise_filters({}) == {}

    def test_key_order_is_gone_by_the_time_it_is_stored(self):
        """Built by walking FILTER_KEYS, so the client's ordering is gone before
        canonical_filters even sees it."""
        one = favourites.canonical_filters(
            favourites.normalise_filters({"year": "1997", "city": "Paris"})
        )
        other = favourites.canonical_filters(
            favourites.normalise_filters({"city": "Paris", "year": "1997"})
        )
        assert one == other

    def test_junk_cannot_buy_a_second_row(self):
        """The property the unique index needs: two requests meaning the same
        view produce the same text however sloppily they were written."""
        clean = favourites.normalise_filters({"city": "Paris", "year": "1997"})
        noisy = favourites.normalise_filters(
            {"year": 1997, "city": " Paris ", "page": 2, "season": "", "junk": None}
        )
        assert favourites.canonical_filters(clean) == favourites.canonical_filters(noisy)


class TestDeriveViewName:
    """A display string for the library to list. Not an identity."""

    def test_the_values_read_in_filter_order(self):
        assert (
            favourites.derive_view_name({"city": "Paris", "gender": "Womens", "year": "1997"})
            == "Womens · 1997 · Paris"
        )

    def test_one_filter_is_just_its_value(self):
        assert favourites.derive_view_name({"city": "Paris"}) == "Paris"

    def test_nothing_filtered_has_a_name_anyway(self):
        """A view with no filters is the whole archive, which is a thing a
        person may well save."""
        assert favourites.derive_view_name({}) == favourites.WHOLE_ARCHIVE

    def test_junk_does_not_reach_the_name(self):
        assert favourites.derive_view_name({"city": "Paris", "token": "secret"}) == "Paris"

    def test_a_name_is_not_an_identity(self):
        """Same name, different filters — two views, and the index says so."""
        one = favourites.canonical_filters(favourites.normalise_filters({"city": "Paris"}))
        other = favourites.canonical_filters(favourites.normalise_filters({"city": "Milan"}))
        assert one != other


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
        assert conn.params[8] == 12
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
        assert conn.params[8] == 7
        assert conn.params[9] == 30

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
        assert conn.params[8] is None
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
        assert conn.params[12] == '{"city":"Paris","year":1997}'
        assert conn.params[13] == "Paris 1997"
        assert "%s::jsonb" in conn.sql

    def test_the_other_kinds_store_no_filters(self):
        conn = FakeConn(row=(1,))
        favourites.add(conn, user_id=USER, look={"number": 1})
        assert conn.params[12] is None

    def test_a_missing_image_is_the_empty_string_not_null(self):
        """image_path is NOT NULL, and a saved view has no image."""
        conn = FakeConn(row=(1,))
        favourites.add(conn, user_id=USER, kind="view", view_filters={"city": "Paris"})
        assert conn.params[10] == ""

    def test_the_collection_url_is_sent_twice_once_to_derive_the_id(self):
        """collection_id is not a parameter — it is the collection_url put
        through the database's own derivation, in the same statement that
        stores the url. That is what makes the pair impossible to write
        inconsistently, and it is why the url appears twice in the params."""
        conn = FakeConn(row=(1,))
        favourites.add(
            conn,
            user_id=USER,
            collection={"designer": "Balenciaga", "url": SHOW_URL},
            look={"number": 12},
        )
        assert conn.params[6] == SHOW_URL
        assert conn.params[7] == SHOW_URL
        assert "collection_url, collection_id" in conn.sql
        assert "favourites_collection_id(%s)" in conn.sql

    def test_a_caller_cannot_supply_a_collection_id(self):
        """A collection dict carrying an id is not asked for it. A caller that
        could supply one could supply one the url disagrees with, which is two
        identities for one show — the thing the column exists to prevent."""
        conn = FakeConn(row=(1,))
        favourites.add(
            conn,
            user_id=USER,
            collection={"designer": "Balenciaga", "url": SHOW_URL, "id": "999999"},
            look={"number": 12},
        )
        assert "999999" not in conn.params

    def test_a_view_derives_its_id_from_the_nothing_it_has(self):
        """A saved view has no show at all. Its collection_url is the empty
        string the NOT NULL column needs, and the empty string derives no id —
        so a view stores null, which is the honest answer."""
        conn = FakeConn(row=(1,))
        favourites.add(conn, user_id=USER, kind="view", view_filters={"city": "Paris"})
        assert conn.params[6] == ""
        assert conn.params[7] == ""

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
        assert saved.params[12] == removing.params[1]

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
            "collection_url": SHOW_URL,
            "collection_id": "12345",
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
        assert set(item["collection"]) == {"designer", "url", "id"}
        assert set(item["look"]) == {"number", "total"}

    def test_the_collection_carries_the_id_the_database_derived(self):
        """The better identity reaches the client. Nothing keys on it there
        yet — useSaves still restates the url indexes — but a client that
        cannot see it can never start."""
        item = favourites.shape(self.row())
        assert item["collection"]["id"] == "12345"
        assert item["collection"]["url"] == SHOW_URL

    def test_a_row_with_no_derivable_id_reads_as_none(self):
        """A saved view, or a look whose url is not a collection page. Null
        rather than an empty string: there is no show here, and '' would read
        as a show whose id happens to be blank."""
        item = favourites.shape(self.row(collection_url="", collection_id=None))
        assert item["collection"]["id"] is None

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
        # From the DO block the drop lives in, not from the first DO block in
        # the file — the collection_id constraint added one above it.
        drop = SCHEMA.index("DROP CONSTRAINT")
        block = SCHEMA[SCHEMA.rindex("DO $$", 0, drop) : drop]
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

    def test_the_unique_indexes_are_untouched_by_collection_id(self):
        """The scope line of this change, pinned.

        collection_id is made available, not made the key. Re-keying the table
        is not reversible and needs a merge strategy for the duplicate rows
        already in production, so the three identities stay exactly as they
        were until that is a deliberate change of its own.
        """
        assert "(user_id, season_url, collection_url, look_number) WHERE kind = 'look'" in SCHEMA
        assert "(user_id, season_url, collection_url) WHERE kind = 'show'" in SCHEMA
        assert "(user_id, md5(view_filters::text)) WHERE kind = 'view'" in SCHEMA
        for line in SCHEMA.splitlines():
            if "UNIQUE INDEX" in line or "favourites_look_key" in line:
                assert "collection_id" not in line, line

    def test_the_derivation_is_one_expression_not_two(self):
        """The backfill, the INSERT and the CHECK all call the same function.

        A second spelling of "which show is this url" is exactly the bug
        collection_id was added to end, so there is only ever one.
        """
        insert = (
            Path(__file__).resolve().parents[2] / "backend" / "userdata" / "favourites.py"
        ).read_text()
        assert "CREATE OR REPLACE FUNCTION favourites_collection_id" in SCHEMA
        assert "SET collection_id = favourites_collection_id(collection_url)" in SCHEMA
        assert "favourites_collection_id(collection_url)" in SCHEMA.split("CHECK", 1)[1]
        assert "favourites_collection_id(%s)" in insert

    def test_the_derivation_function_is_immutable(self):
        """A CHECK constraint may only call an immutable function, and a rule
        that could return two answers for one url is not a rule."""
        body = SCHEMA[SCHEMA.index("CREATE OR REPLACE FUNCTION favourites_collection_id") :]
        assert "IMMUTABLE" in body.split("$$", 1)[0]

    def test_the_backfill_stops_matching_once_it_has_run(self):
        """Re-run on every boot. Its WHERE clause is what makes the second run
        and every run after it update nothing — and what repairs a row if the
        rule above it ever changes."""
        assert (
            "WHERE collection_id IS DISTINCT FROM favourites_collection_id(collection_url)"
            in SCHEMA
        )

    def test_the_backfill_writes_nothing_but_the_id(self):
        """A row whose url this rule does not recognise keeps its url exactly
        as it was and gets a null id. The backfill must never repair a URL."""
        update = SCHEMA[SCHEMA.index("UPDATE favourites") :]
        update = update[: update.index(";")]
        assert update.count("SET") == 1
        assert "collection_url =" not in update

    def test_the_check_constraint_is_added_only_once(self):
        """Postgres has no ADD CONSTRAINT IF NOT EXISTS for a CHECK, so the
        guard is a pg_constraint lookup by the name we chose."""
        add = SCHEMA.index("ADD CONSTRAINT favourites_collection_id_matches_url")
        block = SCHEMA[SCHEMA.rindex("DO $$", 0, add) : add]
        assert "IF NOT EXISTS (" in block
        assert "pg_constraint" in block
        assert "conname = 'favourites_collection_id_matches_url'" in block

    def test_the_backfill_runs_before_the_constraint_is_added(self):
        """Otherwise the validating scan meets rows with a null id and a real
        url, and the whole boot fails on a table it was about to repair."""
        assert SCHEMA.index("UPDATE favourites\n   SET collection_id") < SCHEMA.index(
            "ADD CONSTRAINT favourites_collection_id_matches_url"
        )

    def test_the_file_holds_no_percent_sign(self):
        """It is handed to psycopg as one string; a percent sign is the one
        character it could read as a placeholder."""
        assert "%" not in SCHEMA
