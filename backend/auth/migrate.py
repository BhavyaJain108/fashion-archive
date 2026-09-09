"""Schema application.

`schema.sql` is written to be idempotent, so this runs on every boot and is a
no-op once the tables exist. That keeps a fresh Render deploy and a developer's
scratch database on identical paths — there is no separate "set up the database"
step to forget.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def apply_schema(conn) -> None:
    """Create any missing auth tables, extensions and indexes."""
    conn.execute(SCHEMA_PATH.read_text())
