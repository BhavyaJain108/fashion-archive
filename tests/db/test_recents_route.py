"""The recents endpoint, over a real Postgres.

`recent_collections` does not store season_url. It stores gender, year and
season, and season_url is a pure function of those three — so the endpoint has
to derive it.

That matters because a favourite's identity is
(user_id, season_url, collection_url, look_number). A look kept from the
recents drawer and the same look kept from the show list must produce the same
key. Without the derivation the drawer sends '' and the list sends a URL, the
two land as separate rows, and removing one leaves the other behind — silently,
with both paths reporting success.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("flask", reason="flask not installed")

from auth import repository as repo  # noqa: E402
from flask import Flask  # noqa: E402

from backend.api import high_fashion_routes as routes  # noqa: E402
from backend.userdata import recents  # noqa: E402

pytestmark = pytest.mark.db


@pytest.fixture
def user(conn):
    return repo.create_user(conn, email="rec@example.com", password_hash="h", display_name="Rec")


@pytest.fixture
def client(conn, user, monkeypatch):
    """The real handler on the test's own transaction."""

    @contextmanager
    def transaction():
        yield conn

    monkeypatch.setattr(routes.db, "transaction", transaction)
    monkeypatch.setattr(routes, "current_user", lambda: user)

    app = Flask(__name__)
    routes.register_high_fashion_routes(app)
    app.config["TESTING"] = True
    return app.test_client()


def _record(conn, user, **kw):
    recents.record(
        conn,
        user_id=user.id,
        collection_id=kw.get("collection_id", "1234"),
        designer=kw.get("designer", "Gucci"),
        season=kw.get("season", "Fall / Winter"),
        year=kw.get("year", 2024),
        gender=kw.get("gender", "Women"),
        collection_url=kw.get("collection_url", "https://example.com/gucci-fw24"),
    )


def test_a_recent_carries_a_season_url(client, conn, user):
    _record(conn, user)

    body = client.get("/api/recents").get_json()
    row = body["recents"][0]

    assert row["season_url"], "a recent with gender, year and season must carry a season_url"


def test_the_drawer_and_the_list_key_a_look_identically(client, conn, user):
    """The invariant the derivation exists for."""
    _record(conn, user)

    from_drawer = client.get("/api/recents").get_json()["recents"][0]

    # What the show list sends for the same show.
    from_list = routes._index_row_to_dict(
        {
            "collection_id": "1234",
            "designer": "Gucci",
            "gender": "Women",
            "year": 2024,
            "season": "Fall / Winter",
        }
    )

    assert from_drawer["season_url"] == from_list["season_url"]


def test_a_sparse_recent_does_not_crash_the_endpoint(client, conn, user):
    """A show recorded before its metadata arrived has nulls in all three."""
    _record(conn, user, gender=None, year=None, season=None)

    response = client.get("/api/recents")

    assert response.status_code == 200
    assert "season_url" in response.get_json()["recents"][0]


# ---------------------------------------------------------------------------
# Through `_record_recent`, not around it.
#
# The tests above seed `recents.record` directly with a year and a gender. That
# is not how a row gets written in production: `_record_recent` is the only
# writer, and what it passes is what the drawer later hands back. Seeding the
# table by hand tests the derivation and nothing about whether the values it
# derives from are ever there.
#
# So these open a show the way the app does — POST /api/download-images/stream,
# which is the one path that records a visit — and then read /api/recents and
# build a favourite's key out of the row, exactly as the client does. The
# assertion is the invariant itself: the same show, reached the two ways, is
# one key.
# ---------------------------------------------------------------------------

from backend.high_fashion import collection_cache, show_index  # noqa: E402
from backend.high_fashion import firstview as fv  # noqa: E402

# One show, in the shape the index holds and the shape the list renders.
SHOW = {
    "c": "5678",
    "d": "Balenciaga",
    "s": "Spring / Summer",
    "y": 2019,
    "g": "Women",
    "n": "Ready-to-Wear",
    "t": "Runway Collection",
    "p": "Paris",
}
INDEX_ROW = {
    "collection_id": SHOW["c"],
    "designer": SHOW["d"],
    "season": SHOW["s"],
    "year": SHOW["y"],
    "gender": SHOW["g"],
    "category": SHOW["n"],
    "shoot_type": SHOW["t"],
    "city": SHOW["p"],
}


def _seed_show(conn):
    show_index.upsert(conn, [SHOW])


def _seed_cached_images(conn):
    """The show already in the shared cache, so opening it is pure database.

    A cache hit replays the same meta/image/done events as a live fetch and
    records the visit through the same `_record_recent` call, so it exercises
    the writer without touching firstVIEW.
    """
    collection_cache.put(
        conn,
        collection_id=SHOW["c"],
        quality=fv.QUALITY_FULL,
        images=[
            {
                "index": 1,
                "filename": "001.jpg",
                "key": "runway/001.jpg",
                "path": "https://images.example.com/runway/001.jpg",
            }
        ],
        designer=SHOW["d"],
        season=SHOW["s"],
        gender=SHOW["g"],
        category=SHOW["n"],
    )


def _open_the_show(client):
    """What the app does when a reader clicks a row: open it."""
    response = client.post(
        "/api/download-images/stream",
        json={"collectionUrl": fv.collection_url(SHOW["c"]), "designerName": SHOW["d"]},
    )
    response.get_data()  # drain the stream so the generator finishes
    return response


def _look_key(row, look_number):
    """A favourite's identity, built off one row exactly as the client does.

    `lookTarget` in useFavourites.js reads `season_url` and `url` off whichever
    row the reader was looking at, and `lookKey` in useSaves.js turns those two
    plus the number into the key. Both the recents drawer and the show list
    hand their rows to the same `handleCollectionSelect`, so the field names
    below are the same field names either way.
    """
    return (row.get("season_url") or "", row.get("url") or "", str(look_number))


@pytest.fixture
def opened(client, conn):
    _seed_show(conn)
    _seed_cached_images(conn)
    _open_the_show(client)
    return client.get("/api/recents").get_json()["recents"][0]


def test_opening_a_show_records_the_season_it_is_in(opened):
    """The drawer row has to name a season, or its favourites key on ''."""
    assert opened["year"] == SHOW["y"]
    assert opened["gender"] == SHOW["g"]
    assert opened["season_url"], "a show opened from the app must record a season_url"


def test_opening_a_show_records_the_one_url_the_show_has(opened):
    """`?id=NNN` and `?id=NNN&list=all` are two keys for one show."""
    assert opened["url"] == fv.collection_url(SHOW["c"])


def test_the_url_is_normalised_where_it_is_written(client, conn, user):
    """The stored value, not the served one.

    `get_recents` normalises on the way out as well, so the endpoint would
    still be right with a bad row underneath it. That second layer is there for
    rows an older deploy wrote; it is not a reason for the writer to go on
    writing a url the rest of the app does not use.
    """
    _seed_show(conn)
    _seed_cached_images(conn)
    _open_the_show(client)

    stored = conn.execute(
        "SELECT collection_url FROM recent_collections WHERE collection_id = %s",
        (SHOW["c"],),
    ).fetchone()[0]

    assert stored == fv.collection_url(SHOW["c"])


def test_a_row_stored_the_old_way_is_still_served_normalised(client, conn, user):
    """The other layer: a row written before the fix, read back today.

    The backfill in schema.sql repairs these on boot, but the endpoint must not
    depend on it having run against this particular database yet.
    """
    conn.execute(
        """
        INSERT INTO recent_collections
            (user_id, collection_id, designer, collection_url)
        VALUES (%s, %s, %s, %s)
        """,
        (
            user.id,
            SHOW["c"],
            SHOW["d"],
            "https://www.firstview.com/collection_images.php?id=" + SHOW["c"],
        ),
    )

    row = client.get("/api/recents").get_json()["recents"][0]

    assert row["url"] == fv.collection_url(SHOW["c"])


def test_the_drawer_and_the_list_build_the_same_favourite(opened):
    """The invariant, end to end.

    A look starred from the recents drawer and the same look starred from the
    show list must be one row in `favourites`. That is
    (season_url, collection_url, look_number), and the first two come off
    whichever row the reader was looking at.
    """
    from_list = routes._index_row_to_dict(INDEX_ROW)

    assert _look_key(opened, 7) == _look_key(from_list, 7)


# ---------------------------------------------------------------------------
# The rows that are already stored.
#
# Fixing the writer fixes nothing that is already in the table, and a row is
# only rewritten when its show is opened again — so a favourite kept from the
# drawer would go on splitting for every show the reader has seen but not
# revisited. schema.sql repairs them on boot, and has to stay a no-op on every
# boot after the first.
# ---------------------------------------------------------------------------

from auth.migrate import apply_schema  # noqa: E402

BAD_URL = "https://www.firstview.com/collection_images.php?id=5678"


def _a_row_written_the_old_way(conn, user):
    """What `_record_recent` used to store: bare url, no year, no gender."""
    conn.execute(
        """
        INSERT INTO recent_collections
            (user_id, collection_id, designer, season, year, gender,
             collection_url)
        VALUES (%s, %s, %s, NULL, NULL, NULL, %s)
        """,
        (user.id, SHOW["c"], SHOW["d"], BAD_URL),
    )


def _stored(conn, user):
    return conn.execute(
        """
        SELECT collection_url, season, year, gender
          FROM recent_collections
         WHERE user_id = %s AND collection_id = %s
        """,
        (user.id, SHOW["c"]),
    ).fetchone()


def test_the_backfill_repairs_a_row_written_the_old_way(conn, user):
    _seed_show(conn)
    _a_row_written_the_old_way(conn, user)

    apply_schema(conn)

    url, season, year, gender = _stored(conn, user)
    assert url == fv.collection_url(SHOW["c"])
    assert (season, year, gender) == (SHOW["s"], SHOW["y"], SHOW["g"])


def test_the_backfill_changes_nothing_on_the_second_boot(conn, user):
    """It runs on every boot forever, so a second run must be a no-op."""
    _seed_show(conn)
    _a_row_written_the_old_way(conn, user)

    apply_schema(conn)
    after_first = _stored(conn, user)
    apply_schema(conn)
    after_second = _stored(conn, user)

    assert after_first == after_second


def test_the_backfill_leaves_a_row_it_cannot_name_alone(conn, user):
    """An id that is not one of firstVIEW's numeric ones is not a URL we can
    build, and a guessed one would be worse than the one already there."""
    conn.execute(
        """
        INSERT INTO recent_collections
            (user_id, collection_id, designer, collection_url)
        VALUES (%s, %s, %s, %s)
        """,
        (user.id, "https://elsewhere.example/show", "Someone", "https://elsewhere.example/show"),
    )

    apply_schema(conn)

    kept = conn.execute(
        "SELECT collection_url FROM recent_collections WHERE collection_id = %s",
        ("https://elsewhere.example/show",),
    ).fetchone()[0]
    assert kept == "https://elsewhere.example/show"
