"""Favourite looks, stored per user in Postgres.

Replaces `high_fashion/favourites_db.py`, which kept one SQLite file per user
and copied every favourited image into that user's own directory. Two problems
made that untenable for hosting: the paths were relative to the working
directory, so running the server from elsewhere silently produced an empty
database, and duplicating images per user multiplied storage for files the
archive already holds centrally.

Favourites now reference the central image rather than copying it. That is why
there is no `cleanup_orphaned_images` equivalent — there are no per-user copies
to orphan.

Like the auth repository, these functions take a connection and never commit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row


def add(
    conn,
    *,
    user_id: UUID,
    season: dict,
    collection: dict,
    look: dict,
    image_path: str,
    notes: str = "",
) -> bool:
    """Favourite a look. Returns False if it was already favourited.

    ON CONFLICT rather than a raised constraint error, so favouriting something
    twice is a no-op instead of aborting the caller's transaction.
    """
    cur = conn.execute(
        """
        INSERT INTO favourites (
            user_id, season_name, season_url, season_link_text,
            collection_designer, collection_url,
            look_number, look_total, image_path, notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, season_url, collection_url, look_number) DO NOTHING
        RETURNING id
        """,
        (
            user_id,
            season.get("name", ""),
            season.get("url", ""),
            season.get("link_text"),
            collection.get("designer", ""),
            collection.get("url", ""),
            look.get("number", look.get("lookNumber", 0)),
            look.get("total", look.get("lookTotal")),
            image_path,
            notes or None,
        ),
    )
    return cur.fetchone() is not None


def remove(
    conn, *, user_id: UUID, season_url: str, collection_url: str, look_number: int
) -> bool:
    """Unfavourite a look. Returns False if it was not favourited."""
    cur = conn.execute(
        """
        DELETE FROM favourites
        WHERE user_id = %s AND season_url = %s
          AND collection_url = %s AND look_number = %s
        """,
        (user_id, season_url, collection_url, look_number),
    )
    return cur.rowcount > 0


def exists(
    conn, *, user_id: UUID, season_url: str, collection_url: str, look_number: int
) -> bool:
    cur = conn.execute(
        """
        SELECT 1 FROM favourites
        WHERE user_id = %s AND season_url = %s
          AND collection_url = %s AND look_number = %s
        """,
        (user_id, season_url, collection_url, look_number),
    )
    return cur.fetchone() is not None


def list_all(conn, *, user_id: UUID) -> list[dict[str, Any]]:
    """Every favourite for a user, newest first.

    The nested shape is the one the frontend already consumes; keeping it means
    the storage swap is invisible above this layer.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, season_name, season_url, season_link_text,
                   collection_designer, collection_url,
                   look_number, look_total, image_path, notes, created_at
            FROM favourites
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row["id"],
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
            "image_path": row["image_path"],
            "date_added": row["created_at"].isoformat(),
            "notes": row["notes"],
        }
        for row in rows
    ]


def stats(conn, *, user_id: UUID) -> dict[str, int]:
    """Counts for one user's collection."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT count(*)                             AS total_favourites,
                   count(DISTINCT season_url)           AS unique_seasons,
                   count(DISTINCT collection_url)       AS unique_collections,
                   count(DISTINCT collection_designer)  AS unique_designers
            FROM favourites
            WHERE user_id = %s
            """,
            (user_id,),
        )
        return dict(cur.fetchone())
