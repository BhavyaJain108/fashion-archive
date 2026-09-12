"""Which shows are already in R2, so they are not fetched twice.

Opening a show used to mean downloading every look from firstVIEW again —
250 requests to someone else's site and most of a minute before the first
picture appeared, even for a show opened moments earlier. The images were
already in R2; nothing remembered that.

A hit here returns the stored URLs with no request to firstVIEW at all.

The cache is shared rather than per-user: the pixels are the same whoever
asks, so a show one person opens is instant for everyone after. What is
per-user is which shows you have looked at, which lives in
`backend/userdata/recents.py`.

Bounded to CACHE_LIMIT shows, evicted least-recently-opened first, with
their R2 objects. This is a personal archive for a few people, so the limit
is small on purpose.
"""

from __future__ import annotations

import json
from typing import Any, Optional

# Roughly a season's browsing for a handful of users. Raise it if shows start
# falling out of cache faster than they are revisited.
CACHE_LIMIT = 100


def get(conn, *, collection_id: str, quality: str) -> Optional[dict[str, Any]]:
    """The stored images for a show, or None.

    A different `quality` is a miss rather than a match, so asking for full
    size never silently returns thumbnails.
    """
    row = conn.execute(
        """
        SELECT designer, season, gender, category, shoot_type,
               images, look_count
          FROM cached_collections
         WHERE collection_id = %s AND quality = %s
        """,
        (collection_id, quality),
    ).fetchone()
    if row is None:
        return None

    designer, season, gender, category, shoot_type, images, look_count = row
    return {
        "designer": designer,
        "season": season,
        "gender": gender,
        "category": category,
        "shoot_type": shoot_type,
        "images": images if isinstance(images, list) else json.loads(images),
        "look_count": look_count,
    }


def touch(conn, *, collection_id: str) -> None:
    """Mark a show as just opened, so eviction sees it as recent."""
    conn.execute(
        "UPDATE cached_collections SET last_accessed_at = now() WHERE collection_id = %s",
        (collection_id,),
    )


def forget(conn, *, collection_id: str) -> None:
    """Drop one entry without touching R2.

    For entries that should never have been written — an empty one, say.
    There are no objects to delete, because nothing was ever stored.
    """
    conn.execute("DELETE FROM cached_collections WHERE collection_id = %s", (collection_id,))


def put(
    conn,
    *,
    collection_id: str,
    quality: str,
    images: list[dict[str, Any]],
    designer: str | None = None,
    season: str | None = None,
    gender: str | None = None,
    category: str | None = None,
    shoot_type: str | None = None,
) -> None:
    """Record a show's stored images, replacing any previous entry."""
    conn.execute(
        """
        INSERT INTO cached_collections (
            collection_id, designer, season, gender, category, shoot_type,
            images, look_count, quality, cached_at, last_accessed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (collection_id) DO UPDATE SET
            designer         = EXCLUDED.designer,
            season           = EXCLUDED.season,
            gender           = EXCLUDED.gender,
            category         = EXCLUDED.category,
            shoot_type       = EXCLUDED.shoot_type,
            images           = EXCLUDED.images,
            look_count       = EXCLUDED.look_count,
            quality          = EXCLUDED.quality,
            cached_at        = now(),
            last_accessed_at = now()
        """,
        (
            collection_id, designer, season, gender, category, shoot_type,
            json.dumps(images), len(images), quality,
        ),
    )


def evict(conn, store=None, *, limit: int = CACHE_LIMIT) -> int:
    """Drop the least recently opened shows beyond `limit`.

    Returns how many shows were evicted. R2 objects are deleted where the
    store supports it; a store that cannot delete simply leaves the bytes,
    which costs storage but never correctness — the row is gone either way,
    so the next request re-fetches and overwrites.
    """
    rows = conn.execute(
        """
        SELECT collection_id, images
          FROM cached_collections
         ORDER BY last_accessed_at DESC
        OFFSET %s
        """,
        (limit,),
    ).fetchall()
    if not rows:
        return 0

    delete = getattr(store, "delete", None) if store is not None else None
    for collection_id, images in rows:
        if delete is not None:
            entries = images if isinstance(images, list) else json.loads(images)
            for entry in entries:
                key = entry.get("key")
                if not key:
                    continue
                try:
                    delete(key)
                except Exception as exc:  # noqa: BLE001 — a stuck object must
                    # not block eviction; the row still goes.
                    print(f"cache evict: could not delete {key}: {exc}")

        conn.execute(
            "DELETE FROM cached_collections WHERE collection_id = %s",
            (collection_id,),
        )

    return len(rows)


def stats(conn) -> dict[str, int]:
    """How full the cache is — for /api/cache/stats and for knowing whether
    CACHE_LIMIT is set sensibly."""
    row = conn.execute(
        "SELECT count(*), coalesce(sum(look_count), 0) FROM cached_collections"
    ).fetchone()
    return {"collections": row[0], "images": row[1], "limit": CACHE_LIMIT}
