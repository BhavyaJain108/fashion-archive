"""A fixed-window rate limiter held in Postgres.

Keyed on the client IP for public endpoints and on the user id for
authenticated ones. The window is coarse on purpose: this exists to stop a
script walking the archive, not to shape traffic finely.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import jsonify, request

from backend.auth import db
from backend.auth.middleware import current_user


def _window_start(seconds: int) -> datetime:
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp()) // seconds * seconds
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def hit(conn, *, key: str, limit: int, window_seconds: int) -> bool:
    """Record one request against `key`. True if still within the limit."""
    start = _window_start(window_seconds)
    count = conn.execute(
        """
        INSERT INTO rate_limits (key, window_start, count)
        VALUES (%s, %s, 1)
        ON CONFLICT (key, window_start)
        DO UPDATE SET count = rate_limits.count + 1
        RETURNING count
        """,
        (key, start),
    ).fetchone()[0]
    # Opportunistic sweep of windows nobody will read again.
    conn.execute(
        "DELETE FROM rate_limits WHERE window_start < %s",
        (start - timedelta(seconds=window_seconds * 2),),
    )
    return count <= limit


def client_key() -> str:
    user = current_user()
    if user is not None:
        return f"user:{user.id}"
    fwd = request.headers.get("X-Forwarded-For", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")
    return f"ip:{ip}"


def limited(*, limit: int, window_seconds: int = 60):
    """Decorator: 429 once `limit` requests land in one window for this client."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{fn.__name__}|{client_key()}"
            with db.transaction() as conn:
                ok = hit(conn, key=key, limit=limit, window_seconds=window_seconds)
            if not ok:
                resp = jsonify({"success": False, "error": "rate limited", "code": "RATE_LIMITED"})
                resp.status_code = 429
                resp.headers["Retry-After"] = str(window_seconds)
                return resp
            return fn(*args, **kwargs)

        return wrapper

    return deco
