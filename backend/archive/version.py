"""A fingerprint of the code that decides what a stored record contains.

A delta run only refetches products whose change-hint moved, so it carries old records
forward untouched. That is right when only the shop has changed and wrong when we have:
after the Woo mapper stopped calling an unpurchasable zero a price, the three rows it
was written for kept their 0.00, because nothing about those products had changed on the
shop's side and the run never looked at them again.

So the extraction code carries a version, and a brand whose last run used a different
one is scraped in full whatever mode was asked for. Only the modules that decide the
contents of a record are included — a change to the planner or the reporting has nothing
to re-derive.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).parent

# What a stored record is made of: the mappers, the record itself, the rule engine, and
# the fill logic that combines them.
_EXTRACTION = (
    "connectors",
    "domain/product.py",
    "finder.py",
    "runner/run.py",
)


def _files() -> list[Path]:
    out: list[Path] = []
    for entry in _EXTRACTION:
        path = _ROOT / entry
        out.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return sorted(p for p in out if p.exists())


@lru_cache(maxsize=1)
def extraction_version() -> str:
    """Twelve hex characters over the extraction modules, stable within a process."""
    digest = hashlib.sha256()
    for path in _files():
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
