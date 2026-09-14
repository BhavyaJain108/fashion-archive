"""Saved things, stored per user in Postgres.

Replaces `high_fashion/favourites_db.py`, which kept one SQLite file per user
and copied every favourited image into that user's own directory. Two problems
made that untenable for hosting: the paths were relative to the working
directory, so running the server from elsewhere silently produced an empty
database, and duplicating images per user multiplied storage for files the
archive already holds centrally.

Favourites now reference the central image rather than copying it. That is why
there is no `cleanup_orphaned_images` equivalent — there are no per-user copies
to orphan.

A favourite is one of three kinds:

    look    one photograph — season + collection + number
    show    a whole run — season + collection, no number
    view    a filtered slice of the archive — the filters themselves

They differ only in what identifies them, so `kind` picks the key and the rest
is shared. Each kind's identity is a partial unique index in `schema.sql`; the
fragments below restate those indexes' columns exactly, because ON CONFLICT on
a partial index has to repeat the index predicate before Postgres will infer
it.

Like the auth repository, these functions take a connection and never commit.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any
from uuid import UUID

KINDS = ("look", "show", "view")


class UnknownKind(ValueError):
    """A kind no index covers. Rejected here rather than stored as junk."""


def _dict_cursor(conn):
    """A cursor yielding dicts.

    psycopg is imported here rather than at module scope so the pure
    query-building above can be imported and tested without the driver.
    """
    from psycopg.rows import dict_row

    return conn.cursor(row_factory=dict_row)


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise UnknownKind(f"unknown kind {kind!r}; expected one of {', '.join(KINDS)}")
    return kind


def canonical_filters(filters: Any) -> str:
    """A saved view's filters as the one text that stands for them.

    Sorted keys and no incidental whitespace, so `{year, city}` and
    `{city, year}` are one saved view rather than two. Postgres normalises
    jsonb the same way, which is what makes `md5(view_filters::text)` a usable
    key; this only means the stored document reads the way we matched it.
    """
    return json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))


# The filters a saved view may carry, in the order a derived name reads them.
#
# This is `FILTER_KEYS` in web_ui/src/app/routes.js, which is what the archive's
# query string is parsed against. It is restated here because the server cannot
# take the client's word for it: `md5(view_filters::text)` is the identity of a
# saved view, so one stray key — a timestamp, a page number, a typo — makes the
# same view a second row that the first save will never match again.
FILTER_KEYS = ("gender", "year", "season", "city", "category", "shootType", "letter")

# What a view with nothing filtered is called. A name is a display string, so
# this one is allowed to collide; the filters are what make two rows two rows.
WHOLE_ARCHIVE = "All of the archive"


def normalise_filters(raw: Any) -> dict[str, str]:
    """The filters as they identify a view: known keys, non-empty values.

    The same rule the client applies on the way out of the query string
    (`FILTER_KEYS.has(key) && value !== ''`), applied again here because the
    client is not the only thing that can POST. Unknown keys are dropped rather
    than refused: a newer frontend sending a filter this server has not heard of
    should save the view it does understand, not fail.

    Numbers become their text, because a filter arrives from a URL as text and
    `{"year": 1997}` and `{"year": "1997"}` must not be two saved views.
    Anything that is not a string or a number is not a filter value and is
    dropped — a list or an object here would be somebody else's payload.
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, str] = {}
    for key in FILTER_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            continue  # bool is an int; a filter is never true.
        if isinstance(value, (int, float)):
            value = str(value)
        elif isinstance(value, str):
            value = value.strip()
        else:
            continue
        if value:
            out[key] = value
    return out


def derive_view_name(filters: Any) -> str:
    """A name for a view the client did not name.

    The filter values, read in the order FILTER_KEYS lists them, which is the
    order they read as English: "Womens · 1997 · Paris". Not an identity — two
    views can share a name — so it is built from the values alone and leaves the
    keys out, because "Womens · 1997 · Paris" is what the filter bar shows and
    "gender=Womens, year=1997" is not.
    """
    filters = normalise_filters(filters)
    values = [filters[key] for key in FILTER_KEYS if key in filters]
    return " · ".join(values) if values else WHOLE_ARCHIVE


def conflict_target(kind: str) -> str:
    """The ON CONFLICT clause naming this kind's partial index.

    The WHERE is not decoration: without the index predicate Postgres cannot
    infer a partial index and raises instead of doing nothing.
    """
    check_kind(kind)
    return {
        "look": "(user_id, season_url, collection_url, look_number) WHERE kind = 'look'",
        "show": "(user_id, season_url, collection_url) WHERE kind = 'show'",
        "view": "(user_id, md5(view_filters::text)) WHERE kind = 'view'",
    }[kind]


def key_clause(kind: str) -> tuple[str, tuple[str, ...]]:
    """The WHERE fragment identifying one saved thing, and the names of the
    arguments it consumes, in placeholder order.

    Returning the names rather than the values keeps this pure, and keeps
    `remove` and `exists` from drifting apart — they ask the same question, and
    a `remove` that matched on a different key than `exists` would delete a row
    the star said was not there.
    """
    check_kind(kind)
    return {
        "look": (
            "kind = 'look' AND user_id = %s AND season_url = %s "
            "AND collection_url = %s AND look_number = %s",
            ("user_id", "season_url", "collection_url", "look_number"),
        ),
        "show": (
            "kind = 'show' AND user_id = %s AND season_url = %s AND collection_url = %s",
            ("user_id", "season_url", "collection_url"),
        ),
        # Through jsonb on both sides, so the client's key order cannot make a
        # saved view unfindable.
        "view": (
            "kind = 'view' AND user_id = %s AND md5(view_filters::text) = md5(%s::jsonb::text)",
            ("user_id", "view_filters"),
        ),
    }[kind]


def _key_params(kind: str, values: dict[str, Any]) -> tuple:
    _, names = key_clause(kind)
    return tuple(values[name] for name in names)


def _look_number(kind: str, look: dict | None) -> int | None:
    """The number that identifies a look, and None for the kinds that have no
    position.

    A function rather than an expression inside `add`, because `add_returning_id`
    has to key its lookup on exactly the number `add` stored. Two spellings of
    "which look is this" is the same class of bug as two spellings of a key.
    """
    if kind != "look":
        return None
    look = look or {}
    return look.get("number", look.get("lookNumber", 0))


def add(
    conn,
    *,
    user_id: UUID,
    kind: str = "look",
    season: dict | None = None,
    collection: dict | None = None,
    look: dict | None = None,
    image_path: str = "",
    notes: str = "",
    view_filters: Any = None,
    view_name: str | None = None,
) -> bool:
    """Save something. Returns False if it was already saved.

    `kind` defaults to 'look' and the look arguments keep the shape they had,
    so every existing caller reads unchanged.

    ON CONFLICT rather than a raised constraint error, so saving something
    twice is a no-op instead of aborting the caller's transaction.
    """
    check_kind(kind)
    season = season or {}
    collection = collection or {}
    look = look or {}

    # A show is the whole run, so it has no number; a view has no show at all.
    # The text columns are NOT NULL from when every row was a look, so what a
    # kind does not have is the empty string rather than a null.
    look_number = _look_number(kind, look)

    # Read once and sent twice: once as the column, once to the function that
    # derives collection_id from it. The caller never supplies the id — a
    # caller that could would be a caller that could disagree with the URL, and
    # a CHECK constraint in schema.sql would reject the row anyway. A saved view
    # has no show, so its empty collection_url derives a null id, which is what
    # a view should carry.
    collection_url = collection.get("url", "")

    cur = conn.execute(
        f"""
        INSERT INTO favourites (
            user_id, kind, season_name, season_url, season_link_text,
            collection_designer, collection_url, collection_id,
            look_number, look_total, image_path, notes,
            view_filters, view_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, favourites_collection_id(%s),
                %s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT {conflict_target(kind)} DO NOTHING
        RETURNING id
        """,
        (
            user_id,
            kind,
            season.get("name", ""),
            season.get("url", ""),
            season.get("link_text"),
            collection.get("designer", ""),
            collection_url,
            collection_url,
            look_number,
            look.get("total", look.get("lookTotal")),
            image_path or "",
            notes or None,
            canonical_filters(view_filters) if kind == "view" else None,
            view_name,
        ),
    )
    return cur.fetchone() is not None


def add_returning_id(
    conn,
    *,
    user_id: UUID,
    kind: str = "look",
    season: dict | None = None,
    collection: dict | None = None,
    look: dict | None = None,
    image_path: str = "",
    notes: str = "",
    view_filters: Any = None,
    view_name: str | None = None,
) -> tuple[int | None, bool]:
    """Save something and return (id, created).

    `add` answers whether a row was written, which is all the favourites
    endpoints ever needed. A caller that must then reference the row — the
    album add endpoint, which saves a look and puts it in an album — needs the
    id whether this request created it or a previous one did, and `add`'s
    RETURNING gives nothing back for the second case.

    The lookup is keyed here rather than by the caller, on the arguments that
    were just stored, so the id an album is handed is by construction the row
    `remove` and `exists` would find for the same target.
    """
    created = add(
        conn,
        user_id=user_id,
        kind=kind,
        season=season,
        collection=collection,
        look=look,
        image_path=image_path,
        notes=notes,
        view_filters=view_filters,
        view_name=view_name,
    )
    favourite_id = find_id(
        conn,
        user_id=user_id,
        kind=kind,
        season_url=(season or {}).get("url", ""),
        collection_url=(collection or {}).get("url", ""),
        look_number=_look_number(kind, look),
        view_filters=view_filters,
    )
    return favourite_id, created


def remove(
    conn,
    *,
    user_id: UUID,
    kind: str = "look",
    season_url: str = "",
    collection_url: str = "",
    look_number: int | None = None,
    view_filters: Any = None,
) -> bool:
    """Unsave something. Returns False if it was not saved."""
    where, _ = key_clause(kind)
    params = _key_params(
        kind,
        {
            "user_id": user_id,
            "season_url": season_url,
            "collection_url": collection_url,
            "look_number": look_number,
            "view_filters": canonical_filters(view_filters),
        },
    )
    cur = conn.execute(f"DELETE FROM favourites WHERE {where}", params)
    return cur.rowcount > 0


def exists(
    conn,
    *,
    user_id: UUID,
    kind: str = "look",
    season_url: str = "",
    collection_url: str = "",
    look_number: int | None = None,
    view_filters: Any = None,
) -> bool:
    where, _ = key_clause(kind)
    params = _key_params(
        kind,
        {
            "user_id": user_id,
            "season_url": season_url,
            "collection_url": collection_url,
            "look_number": look_number,
            "view_filters": canonical_filters(view_filters),
        },
    )
    cur = conn.execute(f"SELECT 1 FROM favourites WHERE {where}", params)
    return cur.fetchone() is not None


def find_id(
    conn,
    *,
    user_id: UUID,
    kind: str = "look",
    season_url: str = "",
    collection_url: str = "",
    look_number: int | None = None,
    view_filters: Any = None,
) -> int | None:
    """The id of one saved thing, or None if it is not saved.

    `add` answers whether a row was written; this answers which row is there,
    which is what a caller that has to reference the favourite afterwards needs
    — the album add endpoint saves a look and then puts it in an album, and
    the id is the only handle between the two halves.

    It goes through `key_clause` like `remove` and `exists` do, for the reason
    stated at the top of this module: a lookup keyed on different columns than
    the delete would hand an album the wrong row, and the two would disagree
    only for the kinds nobody tested.
    """
    where, _ = key_clause(kind)
    params = _key_params(
        kind,
        {
            "user_id": user_id,
            "season_url": season_url,
            "collection_url": collection_url,
            "look_number": look_number,
            "view_filters": canonical_filters(view_filters),
        },
    )
    row = conn.execute(f"SELECT id FROM favourites WHERE {where}", params).fetchone()
    return row[0] if row else None


def owns(conn, *, user_id: UUID, favourite_id: int) -> bool:
    """Is this favourite id this user's?

    The user id is in the WHERE rather than compared afterwards, so an id
    belonging to somebody else is indistinguishable from one that never
    existed. A caller answering an HTTP request needs exactly that: both are a
    404, and telling them apart would confirm a stranger's row exists.
    """
    row = conn.execute(
        "SELECT 1 FROM favourites WHERE id = %s AND user_id = %s", (favourite_id, user_id)
    ).fetchone()
    return row is not None


def shape(row: dict[str, Any]) -> dict[str, Any]:
    """One database row as the JSON the frontend consumes.

    Every kind carries every key, so a caller reads `kind` and then the part it
    cares about, rather than guessing from which keys happen to be present. The
    seven look keys are exactly the ones that were here before the other kinds
    existed; `kind` and `view` are the additions.
    """
    return {
        "id": row["id"],
        "kind": row["kind"],
        "season": {
            "name": row["season_name"],
            "url": row["season_url"],
            "link_text": row["season_link_text"],
        },
        # `id` is firstVIEW's own id for the show, derived from the url by the
        # database. It rides along so the client has the better identity to
        # hand; nothing keys on it yet, here or there.
        "collection": {
            "designer": row["collection_designer"],
            "url": row["collection_url"],
            "id": row["collection_id"],
        },
        "look": {"number": row["look_number"], "total": row["look_total"]},
        "view": {"name": row["view_name"], "filters": row["view_filters"]},
        "image_path": row["image_path"],
        "date_added": row["created_at"].isoformat(),
        "notes": row["notes"],
    }


# The most rows one request will ever return, however many are asked for.
# `limit` reaches here off a query string, so it is somebody's input and a
# request for a billion rows must cost what a request for this many costs.
MAX_LIST_LIMIT = 1000

# What one page holds when the caller does not say. Deliberately generous: the
# library draws a Finder grid and a page that does not fill the window is a
# scroll that loads twice before the reader has seen anything.
DEFAULT_PAGE_LIMIT = 200

# The order every listing here reads in, stated once. `list_all`, `list_page`
# and the cursor comparison must agree about it or a cursor names a place in
# one order and is applied in another.
_PAGE_ORDER = "ORDER BY created_at DESC, id DESC"


def list_all(
    conn, *, user_id: UUID, kind: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Everything a user has saved, newest first.

    All three kinds interleaved, because the library lists them that way. Pass
    `kind` for one of them, and `limit` for the newest N.

    `limit` is still not defaulted to a number, and still should not be. A cap
    is not a page: a reader over it loses the tail with no way to ask for the
    rest, silently. `list_page` below is the paged reading, and it is what the
    library and the archive page now use; this stays for the caller that
    genuinely wants the lot, and the ceiling bounds the worst case.

    What made a cap actively dangerous here was that the client keyed its stars
    off exactly these rows, so a row that did not arrive was a dark star over a
    look the reader had saved — and pressing it wrote a second copy. That is no
    longer true: `list_keys` answers the star, in full, and the rows are the
    display half only. See `list_keys`.
    """
    where = "user_id = %s"
    params: tuple = (user_id,)
    if kind is not None:
        where += " AND kind = %s"
        params += (check_kind(kind),)

    bound = ""
    if limit is not None:
        bound = "LIMIT %s"
        params += (max(0, min(int(limit), MAX_LIST_LIMIT)),)

    with _dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT id, kind, season_name, season_url, season_link_text,
                   collection_designer, collection_url, collection_id,
                   look_number, look_total, image_path,
                   view_filters, view_name, notes, created_at
            FROM favourites
            WHERE {where}
            {_PAGE_ORDER}
            {bound}
            """,
            params,
        )
        rows = cur.fetchall()

    return [shape(row) for row in rows]


# ---------------------------------------------------------------- paging ---
#
# A page is taken by CURSOR, not by OFFSET, and the reason is this page's own
# behaviour rather than a general preference.
#
# `browse_catalog` pages the show index with LIMIT/OFFSET, and that is right
# there: the catalogue is 55,700 read-only rows nobody deletes while they are
# reading them. The library is the opposite. It is the list of the reader's own
# saves, it is the page that unsaves things, and it is the page that pages. Take
# a row out above the cursor and every later OFFSET slides by one: the next page
# starts one row late, and the row that fell through the gap is never drawn
# again until a reload. Unsave three things while scrolling and three saves
# silently vanish from a list whose entire job is to hold them.
#
# A key cursor cannot slide. It names the last row actually delivered — its
# (created_at, id) — and the next page is everything strictly after it in the
# same order. Rows removed above it were already drawn; rows added above it
# belong to the top of the list, where a reload puts them, and not to the
# middle of a scroll.
#
# The pair, not created_at alone: `created_at` is a timestamp and two saves in
# the same millisecond are one value. `id` breaks the tie, and it is in the
# ORDER BY for exactly that reason, so the row comparison below is total.

class BadCursor(ValueError):
    """A cursor this server did not mint. A 400, not a silent first page.

    Silently restarting on a cursor we cannot read is the worse failure: a
    load-more control would hand back the page it already has, forever, and
    look like a list that will not end.
    """


def encode_cursor(row: dict[str, Any]) -> str:
    """The place a page stopped, as one opaque string.

    base64url over `<timestamp>|<uuid>` rather than the pair in the clear: this
    travels in a query string, `created_at.isoformat()` ends in `+00:00`, and a
    `+` in a query string is a space by the time Flask has parsed it. Encoding
    it removes the question rather than relying on every caller to escape.
    """
    raw = f"{row['created_at'].isoformat()}|{row['id']}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[str, int] | None:
    """A cursor as the (created_at, id) pair it names, or None for the first page.

    The timestamp goes back to Postgres as text and is cast in the statement, so
    nothing here has to know how psycopg would adapt a datetime. The id is
    `favourites.id`, a bigserial, and is parsed to an int here — a cursor whose
    second half is not a number names no row, and is refused rather than left to
    a cast to refuse with a database error.
    """
    if cursor is None or cursor == "":
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        at, sep, ident = raw.partition("|")
        if not at or not sep or not ident:
            raise ValueError("cursor is not a pair")
        # Both halves are checked here rather than left to the casts in the
        # statement. A cast that refuses raises a database error mid-transaction
        # — a 500 over somebody's query string — where this is a 400 that says
        # which parameter was wrong.
        datetime.fromisoformat(at)
        return at, int(ident)
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise BadCursor(f"unreadable cursor {cursor!r}") from exc


def list_page(
    conn,
    *,
    user_id: UUID,
    kind: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """One page of a user's saves, newest first, plus what is left.

        {"rows": [...], "total": int, "hasMore": bool, "nextCursor": str|None}

    `total` is the count of the WHOLE list under the same `kind`, not of the
    page — it is what the sidebar counts with, and a count of the page would
    make the library claim the reader has as many saves as happen to be drawn.

    `hasMore` is measured rather than inferred: the query asks for one row more
    than the caller wanted and reports whether it arrived. `len(rows) == limit`
    would claim another page exists every time the list divides evenly by the
    page size, and the reader would meet an empty "load more" at the end of
    every exact multiple.
    """
    # At least one row. `limit` comes off a query string, and zero used to make
    # this answer `hasMore: True` with `nextCursor: None`: the query asks for
    # one row more than it wants, that one arrived, and `rows` was then sliced
    # to nothing — so there was another page and no bookmark to reach it with.
    # A load-more control reading that has a button it can press for ever over
    # a list that never grows. A page of nothing is not a page.
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    after = decode_cursor(cursor)

    where = "user_id = %s"
    params: tuple = (user_id,)
    if kind is not None:
        where += " AND kind = %s"
        params += (check_kind(kind),)

    with _dict_cursor(conn) as cur:
        cur.execute(f"SELECT count(*) AS n FROM favourites WHERE {where}", params)
        total = cur.fetchone()["n"]

        page_where = where
        page_params = params
        if after is not None:
            # A row comparison, which is the whole of the cursor: it is the
            # exact inverse of `ORDER BY created_at DESC, id DESC`, so "after
            # the last row of the previous page" is one expression rather than
            # the three-way OR that spelling it per column would need.
            page_where += " AND (created_at, id) < (%s::timestamptz, %s::bigint)"
            page_params = page_params + after

        cur.execute(
            f"""
            SELECT id, kind, season_name, season_url, season_link_text,
                   collection_designer, collection_url, collection_id,
                   look_number, look_total, image_path,
                   view_filters, view_name, notes, created_at
            FROM favourites
            WHERE {page_where}
            {_PAGE_ORDER}
            LIMIT %s
            """,
            page_params + (limit + 1,),
        )
        fetched = cur.fetchall()

    has_more = len(fetched) > limit
    rows = fetched[:limit]
    return {
        "rows": [shape(row) for row in rows],
        "total": total,
        "hasMore": has_more,
        # Only when there is a next page to ask for. A cursor handed out at the
        # end of the list is an invitation to fetch nothing.
        "nextCursor": encode_cursor(rows[-1]) if has_more and rows else None,
    }


def list_keys(conn, *, user_id: UUID) -> list[dict[str, Any]]:
    """Every save this user has, as its identity and nothing else.

    This is what makes paging the rows safe. The client lights a star by asking
    whether the thing on screen is in the set of saved things, and that question
    is asked of every thumbnail in a strip — so the answer has to be local and
    it has to be COMPLETE. Page the list the star reads and a look saved on page
    two reads as unsaved on the archive page, and pressing the star then writes
    a second save of a row the server already holds.

    So the rows are paged and the keys are not. A key is the five columns the
    three unique indexes are built from and nothing else: no designer, no season
    name, no image path, no notes, no timestamp. That is what makes "all of
    them" affordable where "all of the rows" was not — the heavy half of a
    favourite is the display half, and the star never looks at it.

    The shape is `shape`'s nesting minus the display fields, deliberately, so
    the client's one key function reads a key row and a full row identically.
    """
    with _dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT kind, season_url, collection_url, look_number, view_filters
            FROM favourites
            WHERE user_id = %s
            {_PAGE_ORDER}
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "kind": row["kind"],
            "season": {"url": row["season_url"]},
            "collection": {"url": row["collection_url"]},
            "look": {"number": row["look_number"]},
            "view": {"filters": row["view_filters"]},
        }
        for row in rows
    ]


def stats(conn, *, user_id: UUID) -> dict[str, int]:
    """Counts for one user's collection.

    The distinct counts cover looks and shows only: a view's season and
    collection columns are empty strings standing in for NOT NULL, and counting
    those would report a season nobody saved.
    """
    with _dict_cursor(conn) as cur:
        cur.execute(
            """
            SELECT count(*)                                   AS total_favourites,
                   count(*) FILTER (WHERE kind = 'look')       AS looks,
                   count(*) FILTER (WHERE kind = 'show')       AS shows,
                   count(*) FILTER (WHERE kind = 'view')       AS views,
                   count(DISTINCT season_url)
                       FILTER (WHERE kind IN ('look', 'show'))  AS unique_seasons,
                   count(DISTINCT collection_url)
                       FILTER (WHERE kind IN ('look', 'show'))  AS unique_collections,
                   count(DISTINCT collection_designer)
                       FILTER (WHERE kind IN ('look', 'show'))  AS unique_designers
            FROM favourites
            WHERE user_id = %s
            """,
            (user_id,),
        )
        return dict(cur.fetchone())
