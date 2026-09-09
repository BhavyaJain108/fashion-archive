"""Postgres connection management.

A pool rather than a connection per request: opening a Postgres connection costs
a TCP round trip plus authentication, which is significant next to the queries
auth actually runs. The pool is sized for the deployment shape described in the
spec — one gunicorn worker with 8 threads — so a handful of connections covers
every thread with headroom.

`transaction()` is the only place auth code commits. The repository deliberately
never commits, so the unit of work is decided by the caller, and one request that
touches several tables either lands completely or not at all.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

from .migrate import apply_schema

DEFAULT_MIN_SIZE = 1
DEFAULT_MAX_SIZE = 10

_pool: ConnectionPool | None = None


class DatabaseNotConfigured(RuntimeError):
    """Raised when DATABASE_URL is absent. Fail loudly at boot rather than on
    the first login attempt in production."""


def init_pool(
    database_url: str | None = None,
    *,
    min_size: int = DEFAULT_MIN_SIZE,
    max_size: int = DEFAULT_MAX_SIZE,
    apply_migrations: bool = True,
) -> ConnectionPool:
    """Open the pool and bring the schema up to date. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool

    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set. On Render it is supplied by the database "
            "service; locally, put it in config/.env."
        )

    _pool = ConnectionPool(url, min_size=min_size, max_size=max_size, open=True)
    _pool.wait(timeout=10)

    if apply_migrations:
        with transaction() as conn:
            apply_schema(conn)

    return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise DatabaseNotConfigured("init_pool() has not been called")
    return _pool


def close_pool() -> None:
    """Release every connection. Used at shutdown and between tests."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction():
    """A connection in a transaction: commits on success, rolls back on error.

    Rolling back on *any* exception is deliberate. A half-applied registration —
    user row written, verification token not — would leave an account that can
    never be verified and whose email address is permanently taken.
    """
    with get_pool().connection() as conn:
        conn.autocommit = False
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
