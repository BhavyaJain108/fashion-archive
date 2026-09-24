"""Which catalogue: the object store, or Postgres.

`CATALOG_BACKEND=r2` (the default) is the catalogue as one JSON object per
brand. `CATALOG_BACKEND=pg` keeps runs and plans in the object store and puts
products, photographs and observations in Postgres — see
docs/superpowers/specs/2026-09-24-catalogue-to-postgres-design.md. Every place
that used to build a `Catalog(store)` builds one here instead, so the switch is
one environment variable and a rollback is flipping it back.
"""

from __future__ import annotations

import os

from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import ObjectStore


def backend_name() -> str:
    return os.environ.get("CATALOG_BACKEND", "r2").strip().lower() or "r2"


def open_catalog(store: ObjectStore, **kwargs) -> Catalog:
    if backend_name() == "pg":
        from backend.archive.store.pg_catalog import PgCatalog

        return PgCatalog(store, **kwargs)
    return Catalog(store)
