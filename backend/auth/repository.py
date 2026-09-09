"""Data access for accounts, sessions and email tokens.

Every SQL statement in the auth system lives here. Routes and services call
these functions; nothing above this layer builds a query. That boundary is what
lets the storage engine change without touching request handling, and it keeps
parameterisation in one auditable place.

Functions take an open connection rather than opening their own, so a caller can
run several operations in one transaction — issuing a password reset and
revoking every existing session, for instance, must be all-or-nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from psycopg.rows import dict_row

from .tokens import hash_token

Purpose = Literal["verify", "reset"]


class EmailAlreadyExists(Exception):
    """Raised when an email is already registered.

    Callers must not leak this to an unauthenticated response — doing so tells
    an attacker which addresses have accounts.
    """

    def __init__(self, email: str):
        super().__init__(f"email already registered: {email}")
        self.email = email


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    password_hash: str
    display_name: str
    email_verified_at: datetime | None
    created_at: datetime
    last_login_at: datetime | None
    is_active: bool

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


_USER_COLUMNS = (
    "id, email, password_hash, display_name, "
    "email_verified_at, created_at, last_login_at, is_active"
)


def _to_user(row: dict | None) -> User | None:
    return User(**row) if row else None


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


def create_user(conn, *, email: str, password_hash: str, display_name: str) -> User:
    """Insert a new, unverified account.

    ON CONFLICT rather than catching UniqueViolation: a raised constraint error
    would abort the caller's transaction, forcing every caller to wrap this in a
    savepoint. Returning no row instead keeps the transaction usable, and the
    conflict check stays atomic — a read-then-insert would race.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO users (email, password_hash, display_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO NOTHING
            RETURNING {_USER_COLUMNS}
            """,
            (email, password_hash, display_name),
        )
        row = cur.fetchone()
    if row is None:
        raise EmailAlreadyExists(email)
    return _to_user(row)


def get_user_by_email(conn, email: str) -> User | None:
    """Look up an active account. Case-insensitive via the citext column."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_USER_COLUMNS} FROM users WHERE email = %s AND is_active",
            (email,),
        )
        return _to_user(cur.fetchone())


def get_user_by_id(conn, user_id: UUID) -> User | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s AND is_active",
            (user_id,),
        )
        return _to_user(cur.fetchone())


def mark_email_verified(conn, user_id: UUID) -> None:
    conn.execute("UPDATE users SET email_verified_at = now() WHERE id = %s", (user_id,))


def update_last_login(conn, user_id: UUID) -> None:
    conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))


def set_password_hash(conn, user_id: UUID, password_hash: str) -> None:
    """Replace a password hash. Callers should also revoke sessions — see
    `delete_all_sessions` — so a reset locks out anyone already signed in."""
    conn.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id)
    )


def deactivate_user(conn, user_id: UUID) -> None:
    """Soft delete: the row and its data stay, but the account stops resolving."""
    conn.execute("UPDATE users SET is_active = false WHERE id = %s", (user_id,))
    delete_all_sessions(conn, user_id)


def delete_user(conn, user_id: UUID) -> None:
    """Hard delete. Sessions, email tokens and user data cascade."""
    conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------


def create_session(conn, *, user_id: UUID, token: str, ttl: timedelta) -> None:
    """Store a session by hash. The plaintext token goes to the browser only."""
    conn.execute(
        """
        INSERT INTO sessions (token_hash, user_id, expires_at)
        VALUES (%s, %s, now() + %s)
        """,
        (hash_token(token), user_id, ttl),
    )


def get_session_user(conn, token: str) -> User | None:
    """The active user behind a session token, or None.

    Expiry is evaluated by Postgres against `now()`, so it never depends on the
    application server's clock or timezone.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT {", ".join("u." + c.strip() for c in _USER_COLUMNS.split(","))}
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > now() AND u.is_active
            """,
            (hash_token(token),),
        )
        return _to_user(cur.fetchone())


def touch_session(conn, token: str, *, ttl: timedelta) -> None:
    """Record use and roll the expiry forward, keeping active users signed in."""
    conn.execute(
        """
        UPDATE sessions
        SET last_used_at = now(), expires_at = now() + %s
        WHERE token_hash = %s
        """,
        (ttl, hash_token(token)),
    )


def refresh_session_if_stale(
    conn, token: str, *, ttl: timedelta, refresh_after: timedelta
) -> None:
    """Roll a session's expiry forward, but only once it has gone stale.

    Rolling expiry is what keeps an active user signed in indefinitely while
    still expiring an abandoned session. The staleness guard exists so that an
    authenticated request does not write to the database every single time — a
    page that fires ten API calls would otherwise cause ten UPDATEs.

    now() is the transaction start time, not the wall clock. That is correct
    here because one request is one transaction, but it means several calls
    within a single transaction all compute the same expiry.
    """
    conn.execute(
        """
        UPDATE sessions
        SET last_used_at = now(), expires_at = now() + %s
        WHERE token_hash = %s AND last_used_at < now() - %s
        """,
        (ttl, hash_token(token), refresh_after),
    )


def delete_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = %s", (hash_token(token),))


def delete_all_sessions(conn, user_id: UUID) -> None:
    """Sign out every device. Used on password reset and deactivation."""
    conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


def delete_expired_sessions(conn) -> int:
    """Housekeeping. Expired rows are already rejected by `get_session_user`;
    this only stops the table growing without bound."""
    cur = conn.execute("DELETE FROM sessions WHERE expires_at <= now()")
    return cur.rowcount


# --------------------------------------------------------------------------
# Email tokens
# --------------------------------------------------------------------------


def create_email_token(
    conn, *, user_id: UUID, token: str, purpose: Purpose, ttl: timedelta
) -> None:
    """Store a verification or reset token by hash."""
    conn.execute(
        """
        INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at)
        VALUES (%s, %s, %s, now() + %s)
        """,
        (hash_token(token), user_id, purpose, ttl),
    )


def consume_email_token(conn, token: str, *, purpose: Purpose) -> UUID | None:
    """Redeem a token exactly once, returning its user id or None.

    The check and the consume are a single UPDATE, so two simultaneous requests
    with the same token cannot both succeed — a read-then-write would let them.
    """
    cur = conn.execute(
        """
        UPDATE email_tokens
        SET consumed_at = now()
        WHERE token_hash = %s
          AND purpose = %s
          AND consumed_at IS NULL
          AND expires_at > now()
        RETURNING user_id
        """,
        (hash_token(token), purpose),
    )
    row = cur.fetchone()
    return row[0] if row else None


def delete_expired_email_tokens(conn) -> int:
    cur = conn.execute("DELETE FROM email_tokens WHERE expires_at <= now()")
    return cur.rowcount
