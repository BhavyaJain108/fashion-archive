"""Which shops the archive follows, and which of those the app shows.

brands.yml is the roster as shipped. The deck can add to it at run time, and those
additions are recorded in the store — control/roster.json — beside the schedule they
join. The roster anyone reads is the file plus the additions, additions winning where
a domain appears in both, so a brand can be re-described from the deck without a
commit. Nothing removes a brand from the file; pausing it is the schedule's job.

Additions are read only when the shipped file is asked for by default. A caller that
names a file (tests, a one-off roster) gets exactly that file.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

BRANDS_YML = Path(__file__).parent / "brands.yml"
ADDED_KEY = "control/roster.json"

# The sizes the app shows. large houses run enterprise bot defences and are not what this
# archive is for; a multi_brand outlet sells other labels, so its `brand` column stops
# naming one brand and every per-brand measurement stops meaning anything.
APP_SIZES = ("small", "mid")
SIZES = ("small", "mid", "large", "multi_brand")

# The additions are one small object; the API asks for the roster several times per
# request, so the read is kept for a minute per process.
_CACHE_SECONDS = 60.0
_added_cache: tuple[float, list] | None = None
_lock = threading.Lock()


@dataclass(frozen=True)
class RosterEntry:
    domain: str
    homepage_url: str
    display_name: str | None = None
    notes: str | None = None
    size: str = "small"
    added_at: str | None = None  # set only on entries added from the deck

    @property
    def name(self) -> str:
        return self.display_name or self.domain.removeprefix("www.").split(".")[0]


def _entry(b: dict) -> RosterEntry:
    return RosterEntry(
        domain=b["domain"],
        homepage_url=b.get("homepage_url") or f"https://{b['domain']}",
        display_name=b.get("display_name"),
        notes=b.get("notes"),
        size=b.get("size", "small"),
        added_at=b.get("added_at"),
    )


def _default_store():
    import os

    from backend.archive.store.objects import object_store

    root = os.environ.get("ARCHIVE_OBJECTS")
    return object_store(Path(root) if root else None)


def added_entries(store=None, fresh: bool = False) -> list[RosterEntry]:
    """The brands added from the deck, from the store."""
    global _added_cache
    if store is None:
        with _lock:
            hit = _added_cache
        if hit and not fresh and time.monotonic() - hit[0] < _CACHE_SECONDS:
            return list(hit[1])
        store = _default_store()
    from backend.archive.store.objects import loads

    found = store.get(ADDED_KEY)
    rows = (loads(found[0]) if found else {}).get("brands", [])
    entries = [_entry(b) for b in rows if b.get("domain")]
    with _lock:
        _added_cache = (time.monotonic(), list(entries))
    return entries


def forget_added() -> None:
    global _added_cache
    with _lock:
        _added_cache = None


def add_entry(
    store,
    domain: str,
    display_name: str | None = None,
    size: str = "small",
    homepage_url: str | None = None,
) -> RosterEntry:
    """Record a brand added from the deck. Re-adding a domain re-describes it."""
    from backend.archive.store.objects import dumps, loads

    if size not in SIZES:
        raise ValueError(f"size must be one of {SIZES}")
    found = store.get(ADDED_KEY)
    held = loads(found[0]) if found else {"brands": []}
    entry = RosterEntry(
        domain=domain,
        homepage_url=homepage_url or f"https://{domain}",
        display_name=(display_name or "").strip() or None,
        size=size,
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    held["brands"] = [b for b in held.get("brands", []) if b.get("domain") != domain]
    held["brands"].append({k: v for k, v in asdict(entry).items() if v is not None})
    store.put(ADDED_KEY, dumps(held), if_match=found[1] if found else None)
    forget_added()
    return entry


def load_roster(path: Path | None = None, store=None) -> list[RosterEntry]:
    """The shipped file, plus the deck's additions when no file is named."""
    data = yaml.safe_load((path or BRANDS_YML).read_text()) or {}
    entries = {b["domain"]: _entry(b) for b in data.get("brands", [])}
    if path is None or store is not None:
        for e in added_entries(store):
            entries[e.domain] = e
    return list(entries.values())


def app_roster(
    path: Path | None = None, sizes: tuple[str, ...] = APP_SIZES, store=None
) -> list[RosterEntry]:
    """The roster the My Brands page shows, in display-name order."""
    return sorted(
        (e for e in load_roster(path, store) if e.size in sizes),
        key=lambda e: e.name.lower(),
    )
