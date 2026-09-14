"""Albums: named groups of things a user has already saved.

An album holds favourites, not looks. A membership row names a favourite by
its id, so an album can only ever show things the user still has saved, and
there is no second copy of a look's identity to drift from the first — which
is the bug phase 3 found twice.

Three decisions are worth stating here because the tables alone do not say
them:

**One album name per user, case-insensitively.** `albums_user_name_key` in
`schema.sql`. The name is the only handle the user has on an album, so two
albums called "Resort" are two identical rows in a picker and a coin flip
about which one a thing landed in. Scoped to the user, so two people can both
have a "Resort".

**`sort_index` is sparse, not dense.** Items are appended at `max + SORT_GAP`
and `move` writes the midpoint of the item's two new neighbours, so a drag is
one UPDATE of one row whatever N is. Only when a gap finally closes — about
ten midpoint drops into the same slot — does `renumber` respace the album, and
that is one statement. The alternative, rewriting 0..N-1 on every drag, is N
writes per drag forever; fractional indices are the same idea with a float's
precision loss and no honest point at which to repair it.

**Deleting an album does not delete the favourites in it.** `album_items` is
what cascades, and nothing else. An album is an arrangement of things the user
kept, not the keeping of them. `remove_item` is not `favourites.remove`, and
the opposite mistake loses saved work with no way back.

Like the rest of this layer these functions take a connection and never commit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from . import favourites

# The space left between two neighbours. Ten successive midpoint insertions
# into one gap exhaust 1024, and each one that does costs nothing extra until
# the last, which renumbers the album. Larger would buy more depth and is not
# free: an album is capped by the integer column, and 1024 leaves room for two
# million items before that is anywhere in sight.
SORT_GAP = 1024

# How far a repeated "drag to the front" may walk before the album is respaced
# instead. Each such move subtracts SORT_GAP with nothing below it to bisect,
# so without a floor it would eventually run off the bottom of an integer.
SORT_FLOOR = -(2**30)

LAYOUT_MODES = ("grid", "canvas")

# What each sort mode orders by, as the ORDER BY it becomes. Interpolated into
# SQL, which is why the value is looked up in this dict and never taken from a
# caller's string.
#
# 'added' is `sort_index`, which is insertion order until somebody drags
# something — appends land above the current maximum — and the user's own order
# after that. It is deliberately not `favourites.created_at`: when a thing was
# saved and when it was put in this album are different facts, and it is the
# second one an album is ordering by.
#
# 'season' is alphabetical by season name, not chronological. `favourites` has
# no year or season column to order by — only the display string — so "Fall
# 2024" sorts before "Spring 2024". A chronological season order needs columns
# that do not exist yet; naming the limitation here beats a regex over a
# display string that would be right for firstVIEW's spellings and wrong for
# the next source's.
SORT_ORDERS = {
    "added": "i.sort_index, i.favourite_id",
    "designer": "lower(f.collection_designer), i.sort_index, i.favourite_id",
    "season": "f.season_name, i.sort_index, i.favourite_id",
}

# Every favourites column `favourites.shape` reads, so an album item is the
# same JSON the library already renders plus its place in the album.
_FAVOURITE_COLUMNS = """
    f.id, f.kind, f.season_name, f.season_url, f.season_link_text,
    f.collection_designer, f.collection_url, f.collection_id,
    f.look_number, f.look_total, f.image_path,
    f.view_filters, f.view_name, f.notes, f.created_at
"""


class BlankName(ValueError):
    """An album with no name. There is nothing to click on in a picker."""


class DuplicateName(ValueError):
    """This user already has an album by this name."""


class UnknownOption(ValueError):
    """A layout_mode or sort_by neither the table nor the client knows."""


def _dict_cursor(conn):
    """A cursor yielding dicts, imported lazily the way favourites.py does."""
    from psycopg.rows import dict_row

    return conn.cursor(row_factory=dict_row)


def clean_name(name: Any) -> str:
    """The name as it is stored: no leading or trailing space, not empty.

    Trimmed rather than rejected for the space, because " Resort" is a typo and
    not a different album — and because the uniqueness index would otherwise
    let it be one.
    """
    name = (name or "").strip() if isinstance(name, str) else ""
    if not name:
        raise BlankName("an album needs a name")
    return name


def check_layout_mode(mode: str) -> str:
    if mode not in LAYOUT_MODES:
        raise UnknownOption(
            f"unknown layout_mode {mode!r}; expected one of {', '.join(LAYOUT_MODES)}"
        )
    return mode


def check_sort_by(sort_by: str) -> str:
    if sort_by not in SORT_ORDERS:
        raise UnknownOption(
            f"unknown sort_by {sort_by!r}; expected one of {', '.join(SORT_ORDERS)}"
        )
    return sort_by


def shape(row: dict[str, Any]) -> dict[str, Any]:
    """One album row as the JSON the frontend consumes."""
    album = {
        "id": row["id"],
        "name": row["name"],
        "layout_mode": row["layout_mode"],
        "sort_by": row["sort_by"],
        "created_at": row["created_at"].isoformat(),
    }
    # Only the listing computes these; a single album carries its items instead.
    if "item_count" in row:
        album["item_count"] = row["item_count"]
        album["cover_image_path"] = row["cover_image_path"]
    return album


def shape_item(row: dict[str, Any]) -> dict[str, Any]:
    """One member of an album: the favourite, plus where it sits.

    The favourite half is `favourites.shape` exactly, so a tile in an album and
    a tile in the library are the same object to the client.

    `placement` is null in every field until phase 6 writes a canvas layout. It
    is present anyway so the client reads one shape in both layout modes.
    """
    item = favourites.shape(row)
    item["sort_index"] = row["sort_index"]
    item["placement"] = {"x": row["x"], "y": row["y"], "w": row["w"], "z": row["z"]}
    return item


def create(
    conn,
    *,
    user_id: UUID,
    name: str,
    layout_mode: str = "grid",
    sort_by: str = "added",
) -> dict[str, Any]:
    """Make an album. Raises DuplicateName if the user already has one.

    ON CONFLICT DO NOTHING rather than letting the unique index raise: these
    functions never commit, so a constraint violation would abort the caller's
    whole transaction on the way to being turned into a 409. A no-op insert
    that returns no row says the same thing and leaves the transaction usable.
    """
    name = clean_name(name)
    check_layout_mode(layout_mode)
    check_sort_by(sort_by)

    with _dict_cursor(conn) as cur:
        cur.execute(
            """
            INSERT INTO albums (user_id, name, layout_mode, sort_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, lower(name)) DO NOTHING
            RETURNING id, name, layout_mode, sort_by, created_at
            """,
            (user_id, name, layout_mode, sort_by),
        )
        row = cur.fetchone()

    if row is None:
        raise DuplicateName(f"an album called {name!r} already exists")
    return shape(row)


def rename(conn, *, user_id: UUID, album_id: int, name: str) -> bool:
    """Rename an album. False if the user has no such album.

    The clash is looked up before the UPDATE rather than caught after it, for
    the reason `create` uses ON CONFLICT: a raised unique violation would poison
    a transaction this layer does not own. The index is still the last word — a
    concurrent insert of the same name between these two statements raises, and
    should.
    """
    name = clean_name(name)
    taken = conn.execute(
        "SELECT 1 FROM albums WHERE user_id = %s AND lower(name) = lower(%s) AND id <> %s",
        (user_id, name, album_id),
    ).fetchone()
    if taken is not None:
        raise DuplicateName(f"an album called {name!r} already exists")

    cur = conn.execute(
        "UPDATE albums SET name = %s WHERE id = %s AND user_id = %s",
        (name, album_id, user_id),
    )
    return cur.rowcount > 0


def set_options(
    conn,
    *,
    user_id: UUID,
    album_id: int,
    layout_mode: str | None = None,
    sort_by: str | None = None,
) -> bool:
    """Change how an album is laid out or sorted. False if there is no such
    album.

    Only what is passed is written, the way `following.set_notification_
    preferences` does it: a client sending one of the two must not reset the
    other to its default.
    """
    if layout_mode is not None:
        check_layout_mode(layout_mode)
    if sort_by is not None:
        check_sort_by(sort_by)
    if layout_mode is None and sort_by is None:
        return get(conn, user_id=user_id, album_id=album_id) is not None

    cur = conn.execute(
        """
        UPDATE albums
           SET layout_mode = coalesce(%s, layout_mode),
               sort_by     = coalesce(%s, sort_by)
         WHERE id = %s AND user_id = %s
        """,
        (layout_mode, sort_by, album_id, user_id),
    )
    return cur.rowcount > 0


def delete(conn, *, user_id: UUID, album_id: int) -> bool:
    """Delete an album. False if the user has no such album.

    The favourites that were in it stay saved. Only the membership rows go,
    which is `album_items.album_id ON DELETE CASCADE` and nothing else.
    """
    cur = conn.execute("DELETE FROM albums WHERE id = %s AND user_id = %s", (album_id, user_id))
    return cur.rowcount > 0


def get(conn, *, user_id: UUID, album_id: int) -> dict[str, Any] | None:
    """One album, or None — including when it belongs to somebody else.

    None rather than a raise, so a route can answer 404 for both cases without
    telling the caller which one it was.
    """
    with _dict_cursor(conn) as cur:
        cur.execute(
            """
            SELECT id, name, layout_mode, sort_by, created_at
            FROM albums WHERE id = %s AND user_id = %s
            """,
            (album_id, user_id),
        )
        row = cur.fetchone()
    return shape(row) if row else None


def list_albums(conn, *, user_id: UUID) -> list[dict[str, Any]]:
    """A user's albums, newest first, each with a count and a cover.

    The cover is the first item in the album's own order that has an image.
    Saved views have none — a view is a set of filters, so `image_path` is the
    empty string — and an album of nothing but views gets a null cover rather
    than a broken one.
    """
    with _dict_cursor(conn) as cur:
        cur.execute(
            """
            SELECT a.id, a.name, a.layout_mode, a.sort_by, a.created_at,
                   (SELECT count(*) FROM album_items i WHERE i.album_id = a.id)
                       AS item_count,
                   cover.image_path AS cover_image_path
              FROM albums a
              LEFT JOIN LATERAL (
                   SELECT f.image_path
                     FROM album_items i
                     JOIN favourites f ON f.id = i.favourite_id
                    WHERE i.album_id = a.id AND f.image_path <> ''
                    ORDER BY i.sort_index, i.favourite_id
                    LIMIT 1
              ) cover ON true
             WHERE a.user_id = %s
             ORDER BY a.created_at DESC, a.id DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return [shape(row) for row in rows]


def add_item(conn, *, user_id: UUID, album_id: int, favourite_id: int) -> bool:
    """Put a favourite in an album. False if it was already in it.

    False also when the album or the favourite is not this user's: the JOIN
    below only matches a favourite whose owner is the album's owner, so an id
    guessed from someone else's collection inserts nothing. A caller that needs
    to tell "already there" from "not yours" asks `get` first — which a route
    does anyway, to answer 404.

    The new item goes above every existing one, which is what appending means
    for a list the user has been arranging by hand.
    """
    cur = conn.execute(
        """
        INSERT INTO album_items (album_id, favourite_id, sort_index)
        SELECT a.id, f.id,
               coalesce((SELECT max(i.sort_index) FROM album_items i
                          WHERE i.album_id = a.id), 0) + %s
          FROM albums a
          JOIN favourites f ON f.user_id = a.user_id
         WHERE a.id = %s AND a.user_id = %s AND f.id = %s
        ON CONFLICT (album_id, favourite_id) DO NOTHING
        RETURNING favourite_id
        """,
        (SORT_GAP, album_id, user_id, favourite_id),
    )
    return cur.fetchone() is not None


def remove_item(conn, *, user_id: UUID, album_id: int, favourite_id: int) -> bool:
    """Take a favourite out of an album. False if it was not in it.

    It stays saved. This is the other of the two destructive acts the UI has to
    keep apart; `favourites.remove` is the one that un-saves.
    """
    cur = conn.execute(
        """
        DELETE FROM album_items i
         USING albums a
         WHERE i.album_id = a.id
           AND a.id = %s AND a.user_id = %s
           AND i.favourite_id = %s
        """,
        (album_id, user_id, favourite_id),
    )
    return cur.rowcount > 0


def list_items(
    conn, *, user_id: UUID, album_id: int, sort_by: str | None = None
) -> list[dict[str, Any]]:
    """What is in an album, in the album's stored order unless overridden.

    Returns [] for an album that is empty and for one that is not this user's.
    A caller distinguishing the two asks `get`.
    """
    if sort_by is None:
        album = get(conn, user_id=user_id, album_id=album_id)
        if album is None:
            return []
        sort_by = album["sort_by"]
    order = SORT_ORDERS[check_sort_by(sort_by)]

    with _dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT {_FAVOURITE_COLUMNS},
                   i.sort_index, i.x, i.y, i.w, i.z
              FROM album_items i
              JOIN albums a     ON a.id = i.album_id
              JOIN favourites f ON f.id = i.favourite_id
             WHERE a.id = %s AND a.user_id = %s
             ORDER BY {order}
            """,
            (album_id, user_id),
        )
        rows = cur.fetchall()
    return [shape_item(row) for row in rows]


def _order(conn, album_id: int) -> list[tuple[int, int]]:
    """(favourite_id, sort_index) for one album, in order."""
    return conn.execute(
        """
        SELECT favourite_id, sort_index FROM album_items
         WHERE album_id = %s ORDER BY sort_index, favourite_id
        """,
        (album_id,),
    ).fetchall()


def renumber(conn, *, album_id: int) -> int:
    """Respace an album at SORT_GAP, keeping the order it is already in.

    One statement, N rows. Called when a gap has closed and there is no integer
    left between two neighbours — roughly every tenth drag into the same slot,
    not every drag — and available to a caller that wants to tidy up.
    """
    cur = conn.execute(
        """
        UPDATE album_items i
           SET sort_index = o.position * %s
          FROM (SELECT favourite_id,
                       row_number() OVER (ORDER BY sort_index, favourite_id) AS position
                  FROM album_items WHERE album_id = %s) o
         WHERE i.album_id = %s AND i.favourite_id = o.favourite_id
        """,
        (SORT_GAP, album_id, album_id),
    )
    return cur.rowcount


def move(
    conn, *, user_id: UUID, album_id: int, favourite_id: int, after: int | None = None
) -> bool:
    """Move one item to sit directly after another. False if it is not there.

    `after=None` moves it to the front. This is the drag primitive, and it
    writes exactly one row: the item's new index is the midpoint of its two new
    neighbours. Only when those neighbours are adjacent integers does it cost
    more, and then it is one renumber of one album followed by the same single
    write.

    The album's current order is read first. That is a read of N rows, not N
    writes — the thing sparse indices exist to avoid.
    """
    if (
        conn.execute(
            "SELECT 1 FROM albums WHERE id = %s AND user_id = %s", (album_id, user_id)
        ).fetchone()
        is None
    ):
        return False

    rows = _order(conn, album_id)
    present = {fav for fav, _ in rows}
    if favourite_id not in present:
        return False
    if after is not None and after not in present:
        return False
    if after == favourite_id:
        return True

    def bounds(rows: list[tuple[int, int]]) -> tuple[int | None, int | None]:
        """The indices this item would land between, with itself taken out."""
        index_of = dict(rows)
        rest = [fav for fav, _ in rows if fav != favourite_id]
        here = 0 if after is None else rest.index(after) + 1
        low = index_of[rest[here - 1]] if here > 0 else None
        high = index_of[rest[here]] if here < len(rest) else None
        return low, high

    low, high = bounds(rows)
    if low is None and high is None:
        new_index = SORT_GAP
    elif low is None:
        new_index = high - SORT_GAP
        if new_index < SORT_FLOOR:
            renumber(conn, album_id=album_id)
            low, high = bounds(_order(conn, album_id))
            new_index = high - SORT_GAP
    elif high is None:
        new_index = low + SORT_GAP
    else:
        if high - low < 2:
            renumber(conn, album_id=album_id)
            low, high = bounds(_order(conn, album_id))
        new_index = low + (high - low) // 2

    cur = conn.execute(
        "UPDATE album_items SET sort_index = %s WHERE album_id = %s AND favourite_id = %s",
        (new_index, album_id, favourite_id),
    )
    return cur.rowcount > 0


def set_order(conn, *, user_id: UUID, album_id: int, favourite_ids: list[int]) -> int:
    """Write a whole order at once. Returns how many rows moved.

    One statement for any N, for the caller that has the full arrangement in
    hand — a reorder endpoint taking a list, rather than one request per item.
    Anything in the album but absent from the list keeps the index it had, so
    the list should be the whole album.
    """
    cur = conn.execute(
        """
        UPDATE album_items i
           SET sort_index = o.position * %s
          FROM unnest(%s::bigint[]) WITH ORDINALITY AS o(favourite_id, position)
         WHERE i.album_id = %s
           AND i.favourite_id = o.favourite_id
           AND EXISTS (SELECT 1 FROM albums a
                        WHERE a.id = i.album_id AND a.user_id = %s)
        """,
        (SORT_GAP, list(favourite_ids), album_id, user_id),
    )
    return cur.rowcount


def set_layout(conn, *, user_id: UUID, album_id: int, placements: list[dict[str, Any]]) -> int:
    """Write the canvas placement of many items at once. Returns rows moved.

    Placement lives on the membership row because a layout is per album — the
    same favourite can sit in two albums at two positions. Absent items keep
    what they had; the client sends the whole arrangement after a debounce.
    """
    ids = [int(p["favourite_id"]) for p in placements]
    xs = [int(p["x"]) for p in placements]
    ys = [int(p["y"]) for p in placements]
    ws = [int(p["w"]) for p in placements]
    zs = [int(p["z"]) for p in placements]
    cur = conn.execute(
        """
        UPDATE album_items i
           SET x = o.x, y = o.y, w = o.w, z = o.z
          FROM unnest(%s::bigint[], %s::int[], %s::int[], %s::int[], %s::int[])
               AS o(favourite_id, x, y, w, z)
         WHERE i.album_id = %s
           AND i.favourite_id = o.favourite_id
           AND EXISTS (SELECT 1 FROM albums a
                        WHERE a.id = i.album_id AND a.user_id = %s)
        """,
        (ids, xs, ys, ws, zs, album_id, user_id),
    )
    return cur.rowcount
