"""Share tokens: mint, resolve, revoke.

A token is the whole secret. It is generated from a CSPRNG and stored as-is;
nothing about the target is recoverable from it and nothing about the token is
recoverable from the target. `resolve` is the only read path and it answers for
one token at a time.
"""

from __future__ import annotations

import json
import secrets
from typing import Any
from uuid import UUID

KINDS = ("look", "show", "album")


def mint(conn, *, user_id: UUID, kind: str, target: dict[str, Any]) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown share kind: {kind!r}")
    # 16 random bytes -> 22 url-safe characters. Never derived from the target.
    token = secrets.token_urlsafe(16)
    conn.execute(
        """
        INSERT INTO share_tokens (token, user_id, kind, target)
        VALUES (%s, %s, %s, %s::jsonb)
        """,
        (token, user_id, kind, json.dumps(target)),
    )
    return token


def resolve(conn, *, token: str) -> dict[str, Any] | None:
    """The live target behind a token, or None for unknown AND revoked alike."""
    row = conn.execute(
        """
        SELECT user_id, kind, target
          FROM share_tokens
         WHERE token = %s AND revoked_at IS NULL
        """,
        (token,),
    ).fetchone()
    if row is None:
        return None
    user_id, kind, target = row
    if not isinstance(target, dict):
        target = json.loads(target)
    return {"user_id": user_id, "kind": kind, "target": target}


def revoke(conn, *, user_id: UUID, token: str) -> bool:
    """Revoke one of the user's own tokens. Someone else's token is not found."""
    cur = conn.execute(
        """
        UPDATE share_tokens
           SET revoked_at = now()
         WHERE token = %s AND user_id = %s AND revoked_at IS NULL
        """,
        (token, user_id),
    )
    return cur.rowcount == 1


def list_mine(conn, *, user_id: UUID) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT token, kind, target, created_at
          FROM share_tokens
         WHERE user_id = %s AND revoked_at IS NULL
         ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()
    out = []
    for token, kind, target, created_at in rows:
        if not isinstance(target, dict):
            target = json.loads(target)
        out.append(
            {
                "token": token,
                "kind": kind,
                "target": target,
                "created_at": created_at.isoformat() if created_at else None,
            }
        )
    return out
