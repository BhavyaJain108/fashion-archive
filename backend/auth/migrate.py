"""Schema application.

`schema.sql` is written to be idempotent, so this runs on every boot and is a
no-op once the tables exist. That keeps a fresh Render deploy and a developer's
scratch database on identical paths — there is no separate "set up the database"
step to forget.
"""

from __future__ import annotations

from pathlib import Path

# Order matters: user data tables reference users(id), so auth goes first.
SCHEMA_PATHS = (
    Path(__file__).with_name("schema.sql"),
    Path(__file__).parent.parent / "userdata" / "schema.sql",
)


def apply_schema(conn) -> None:
    """Create any missing tables, extensions and indexes."""
    for path in SCHEMA_PATHS:
        conn.execute(path.read_text())
