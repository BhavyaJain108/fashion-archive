"""The shopping bag's rows.

One line per (product, variant) per user. Every query carries the user id, the
same way favourites and following do, so a line id from another account is a
row that does not exist rather than one that can be read.

What is stored is what the person chose (product, variant, size, quantity) and
what it cost when they chose it. What it costs now is not stored — the bag
route asks the catalogue each time, so a line can say "changed" instead of
quietly showing a price that is no longer true.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

MAX_LINES = 50  # per user; a bag is a bag, not a wishlist
MAX_QTY = 20  # per line; more than that is a wholesale order, not a purchase

_COLUMNS = (
    "id, brand, itemurl, handle, title, image, platform, variant_id, size, qty, "
    "price, currency, added_at, updated_at"
)


def _row(r: dict[str, Any]) -> dict[str, Any]:
    price = r["price"]
    return {
        "id": int(r["id"]),
        "brand": r["brand"],
        "itemurl": r["itemurl"],
        "handle": r["handle"],
        "title": r["title"],
        "image": r["image"],
        "platform": r["platform"],
        "variant_id": r["variant_id"],
        "size": r["size"],
        "qty": int(r["qty"]),
        "price": float(price) if isinstance(price, Decimal | int | float) else None,
        "currency": r["currency"],
        "added_at": r["added_at"].isoformat() if r["added_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def list_lines(conn, *, user_id: UUID) -> list[dict[str, Any]]:
    """Every line in this user's bag, oldest first — the order they were added."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM bag_lines WHERE user_id = %s ORDER BY added_at, id",
            (user_id,),
        )
        return [_row(r) for r in cur.fetchall()]


def count(conn, *, user_id: UUID) -> int:
    cur = conn.execute("SELECT count(*) FROM bag_lines WHERE user_id = %s", (user_id,))
    return int(cur.fetchone()[0])


def add_line(
    conn,
    *,
    user_id: UUID,
    brand: str,
    itemurl: str,
    variant_id: str | None,
    size: str | None,
    qty: int,
    title: str,
    image: str | None,
    handle: str | None,
    platform: str | None,
    price: float | None,
    currency: str | None,
) -> dict[str, Any]:
    """Put a variant in the bag, or add to it if it is already there.

    Adding the same variant twice is a quantity, not a second row: that is what
    the unique index says, and ON CONFLICT is how the two writes stay one
    statement. The quantity is capped so a double-click on "add" cannot run
    past MAX_QTY either.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO bag_lines
                (user_id, brand, itemurl, handle, title, image, platform,
                 variant_id, size, qty, price, currency)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, itemurl, COALESCE(variant_id, ''), COALESCE(size, ''))
            DO UPDATE SET
                qty = LEAST(bag_lines.qty + EXCLUDED.qty, {MAX_QTY}),
                updated_at = now()
            RETURNING {_COLUMNS}
            """,
            (
                user_id,
                brand,
                itemurl,
                handle,
                title,
                image,
                platform,
                variant_id,
                size,
                min(qty, MAX_QTY),
                price,
                currency,
            ),
        )
        return _row(cur.fetchone())


def set_qty(conn, *, user_id: UUID, line_id: int, qty: int) -> dict[str, Any] | None:
    """Change one line's quantity. None if the line is not this user's."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE bag_lines SET qty = %s, updated_at = now()
            WHERE id = %s AND user_id = %s
            RETURNING {_COLUMNS}
            """,
            (min(qty, MAX_QTY), line_id, user_id),
        )
        row = cur.fetchone()
        return _row(row) if row else None


def remove_line(conn, *, user_id: UUID, line_id: int) -> bool:
    cur = conn.execute("DELETE FROM bag_lines WHERE id = %s AND user_id = %s", (line_id, user_id))
    return cur.rowcount > 0


def clear(conn, *, user_id: UUID) -> int:
    """Empty the bag. Returns how many lines went."""
    cur = conn.execute("DELETE FROM bag_lines WHERE user_id = %s", (user_id,))
    return int(cur.rowcount)
