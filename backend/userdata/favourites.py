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

import json
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
    look_number = look.get("number", look.get("lookNumber", 0)) if kind == "look" else None

    cur = conn.execute(
        f"""
        INSERT INTO favourites (
            user_id, kind, season_name, season_url, season_link_text,
            collection_designer, collection_url,
            look_number, look_total, image_path, notes,
            view_filters, view_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
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
            collection.get("url", ""),
            look_number,
            look.get("total", look.get("lookTotal")),
            image_path or "",
            notes or None,
            canonical_filters(view_filters) if kind == "view" else None,
            view_name,
        ),
    )
    return cur.fetchone() is not None


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
        "collection": {
            "designer": row["collection_designer"],
            "url": row["collection_url"],
        },
        "look": {"number": row["look_number"], "total": row["look_total"]},
        "view": {"name": row["view_name"], "filters": row["view_filters"]},
        "image_path": row["image_path"],
        "date_added": row["created_at"].isoformat(),
        "notes": row["notes"],
    }


def list_all(conn, *, user_id: UUID, kind: str | None = None) -> list[dict[str, Any]]:
    """Everything a user has saved, newest first.

    All three kinds interleaved, because the library lists them that way. Pass
    `kind` for one of them.
    """
    where = "user_id = %s"
    params: tuple = (user_id,)
    if kind is not None:
        where += " AND kind = %s"
        params += (check_kind(kind),)

    with _dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT id, kind, season_name, season_url, season_link_text,
                   collection_designer, collection_url,
                   look_number, look_total, image_path,
                   view_filters, view_name, notes, created_at
            FROM favourites
            WHERE {where}
            ORDER BY created_at DESC, id DESC
            """,
            params,
        )
        rows = cur.fetchall()

    return [shape(row) for row in rows]


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
