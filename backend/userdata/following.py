"""Which brands a user follows.

Replaces `auth/user_system/brand_following.py`, which wrote a SQLite file to
`data/user_data/{user_folder}/brand_collections/following.db` — a path relative
to the working directory, and one that does not survive a container with no
persistent disk.

Brand data itself stays central and shared; only the per-user follow list lives
here. The composite primary key (user_id, brand_id) is what enforces that a user
follows a brand at most once.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row


def follow(
    conn, *, user_id: UUID, brand_id: str, brand_name: str, notes: str = ""
) -> bool:
    """Follow a brand. Returns False if already following."""
    cur = conn.execute(
        """
        INSERT INTO brand_following (user_id, brand_id, brand_name, notes)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, brand_id) DO NOTHING
        RETURNING brand_id
        """,
        (user_id, brand_id, brand_name, notes or None),
    )
    return cur.fetchone() is not None


def unfollow(conn, *, user_id: UUID, brand_id: str) -> bool:
    """Unfollow. Returns False if the user was not following it."""
    cur = conn.execute(
        "DELETE FROM brand_following WHERE user_id = %s AND brand_id = %s",
        (user_id, brand_id),
    )
    return cur.rowcount > 0


def is_following(conn, *, user_id: UUID, brand_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM brand_following WHERE user_id = %s AND brand_id = %s",
        (user_id, brand_id),
    )
    return cur.fetchone() is not None


def list_following(conn, *, user_id: UUID) -> list[dict[str, Any]]:
    """Followed brands, most recently followed first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT brand_id, brand_name, followed_at, notes,
                   notify_new_products, notify_price_changes
            FROM brand_following
            WHERE user_id = %s
            ORDER BY followed_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "brand_id": row["brand_id"],
            "brand_name": row["brand_name"],
            "date_followed": row["followed_at"].isoformat(),
            "notes": row["notes"],
            "notify_new_products": row["notify_new_products"],
            "notify_price_changes": row["notify_price_changes"],
        }
        for row in rows
    ]


def count(conn, *, user_id: UUID) -> int:
    cur = conn.execute(
        "SELECT count(*) FROM brand_following WHERE user_id = %s", (user_id,)
    )
    return cur.fetchone()[0]


def set_notification_preferences(
    conn,
    *,
    user_id: UUID,
    brand_id: str,
    notify_new_products: bool | None = None,
    notify_price_changes: bool | None = None,
) -> bool:
    """Update notification flags. None leaves a flag unchanged.

    COALESCE does the leaving-unchanged, so a caller sending one flag does not
    silently reset the other to its default.
    """
    cur = conn.execute(
        """
        UPDATE brand_following
        SET notify_new_products  = COALESCE(%s, notify_new_products),
            notify_price_changes = COALESCE(%s, notify_price_changes)
        WHERE user_id = %s AND brand_id = %s
        """,
        (notify_new_products, notify_price_changes, user_id, brand_id),
    )
    return cur.rowcount > 0


def set_notes(conn, *, user_id: UUID, brand_id: str, notes: str) -> bool:
    cur = conn.execute(
        "UPDATE brand_following SET notes = %s WHERE user_id = %s AND brand_id = %s",
        (notes or None, user_id, brand_id),
    )
    return cur.rowcount > 0
