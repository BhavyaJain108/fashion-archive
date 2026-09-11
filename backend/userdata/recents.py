"""Shows a user has opened, most recent first.

Distinct from favourites. A favourite is a deliberate keep; this is just
where you have been, so getting back to a show does not mean walking the
year, season, gender and type filters again.

Opening a show you have already seen moves it up the list rather than
adding a second entry — that is what the (user_id, collection_id) primary
key buys.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

# Enough to cover a browsing session without the list becoming its own
# navigation problem.
DEFAULT_LIMIT = 40


def record(
    conn,
    *,
    user_id: UUID,
    collection_id: str,
    designer: str,
    collection_url: str,
    season: Optional[str] = None,
    year: Optional[int] = None,
    gender: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    look_count: Optional[int] = None,
) -> None:
    """Note that a user opened a show, or move it back to the top.

    `thumbnail_url` and `look_count` are only overwritten when supplied, so
    recording a visit before the images arrive does not wipe a thumbnail
    stored on an earlier one.
    """
    conn.execute(
        """
        INSERT INTO recent_collections (
            user_id, collection_id, designer, season, year, gender,
            collection_url, thumbnail_url, look_count, viewed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (user_id, collection_id) DO UPDATE SET
            designer       = EXCLUDED.designer,
            season         = COALESCE(EXCLUDED.season, recent_collections.season),
            year           = COALESCE(EXCLUDED.year, recent_collections.year),
            gender         = COALESCE(EXCLUDED.gender, recent_collections.gender),
            collection_url = EXCLUDED.collection_url,
            thumbnail_url  = COALESCE(EXCLUDED.thumbnail_url,
                                      recent_collections.thumbnail_url),
            look_count     = COALESCE(EXCLUDED.look_count,
                                      recent_collections.look_count),
            viewed_at      = now()
        """,
        (
            user_id, collection_id, designer, season, year, gender,
            collection_url, thumbnail_url, look_count,
        ),
    )


def list_recent(
    conn, *, user_id: UUID, limit: int = DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    """A user's recently opened shows, newest first."""
    rows = conn.execute(
        """
        SELECT collection_id, designer, season, year, gender,
               collection_url, thumbnail_url, look_count, viewed_at
          FROM recent_collections
         WHERE user_id = %s
         ORDER BY viewed_at DESC
         LIMIT %s
        """,
        (user_id, limit),
    ).fetchall()

    return [
        {
            "collection_id": r[0],
            "designer": r[1],
            "season": r[2],
            "year": r[3],
            "gender": r[4],
            "url": r[5],
            "thumbnail_url": r[6],
            "look_count": r[7],
            "viewed_at": r[8].isoformat() if r[8] else None,
        }
        for r in rows
    ]


def clear(conn, *, user_id: UUID) -> int:
    """Forget a user's history. Returns how many entries went."""
    cur = conn.execute(
        "DELETE FROM recent_collections WHERE user_id = %s", (user_id,)
    )
    return cur.rowcount or 0
