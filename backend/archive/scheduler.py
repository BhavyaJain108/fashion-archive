"""The control plane: which brands are scraped, how often, and whether to keep going.

Everything here is objects, not code. A brand is added, dropped, paused or re-timed by
writing to the store while the daemon is running, and a code deploy does not touch any
of it. That separation is the point: the scraping keeps running so we can watch how
sites react to it, and the code underneath is replaced whenever we like.

Claiming is the one place in the archive where two workers reach for the same object,
and the only place a conditional write is needed. A worker reads a brand's schedule
with its etag and writes the claim back with If-Match; a refusal means someone else
got there first, and it moves on to the next brand. The SQL version did this with
UPDATE ... RETURNING. R2 refuses a stale If-Match with PreconditionFailed, which is
the same guarantee by a different name.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads

DEFAULT_CADENCE = 86_400  # a day

_SCHEDULE = "control/schedule/"
_DAEMON = "control/daemon.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass
class Due:
    domain: str
    cadence_seconds: int


class Scheduler:
    """Reads and writes the control plane. Holds no state of its own."""

    def __init__(
        self,
        store: ObjectStore,
        worker_id: str = "worker-1",
        stale_claim_seconds: int = 3600,
    ):
        self._store = store
        self.worker_id = worker_id
        # A worker that dies mid-brand leaves its claim behind. Nothing resumes the run
        # itself, but the brand must not be locked out of the schedule for ever.
        self.stale_claim_seconds = stale_claim_seconds

    # --- object helpers -------------------------------------------------------------

    def _read(self, key: str, default=None) -> tuple[dict, str | None]:
        found = self._store.get(key)
        return (
            (loads(found[0]), found[1]) if found else (default if default is not None else {}, None)
        )

    def _write(self, key: str, value: dict, etag: str | None = None) -> None:
        self._store.put(key, dumps(value), if_match=etag)

    def _key(self, domain: str) -> str:
        return f"{_SCHEDULE}{domain}.json"

    # --- the brand list -------------------------------------------------------------

    def add(
        self,
        domain: str,
        cadence_seconds: int = DEFAULT_CADENCE,
        now: datetime | None = None,
    ) -> None:
        """A newly added brand is due immediately."""
        key = self._key(domain)
        row, etag = self._read(key)
        row.update(
            {
                "domain": domain,
                "enabled": 1,
                "cadence_seconds": cadence_seconds,
                "next_due": row.get("next_due") or _iso(now or _now()),
                "claimed_by": row.get("claimed_by"),
                "claimed_at": row.get("claimed_at"),
            }
        )
        self._write(key, row, etag)

    def _amend(self, domain: str, **fields) -> None:
        key = self._key(domain)
        row, etag = self._read(key)
        if not row:
            return
        row.update(fields)
        self._write(key, row, etag)

    def set_enabled(self, domain: str, enabled: bool) -> None:
        self._amend(domain, enabled=1 if enabled else 0)

    def set_cadence(self, domain: str, cadence_seconds: int) -> None:
        self._amend(domain, cadence_seconds=cadence_seconds)

    def rows(self) -> list[dict]:
        out = [self._read(key)[0] for key in self._store.list(_SCHEDULE)]
        return sorted((r for r in out if r), key=lambda r: r["domain"])

    # --- stopping -------------------------------------------------------------------

    def request_stop(self, stop: bool = True) -> None:
        """Stopping is a flag, not a kill: the worker finishes its brand and exits."""
        row, etag = self._read(_DAEMON)
        row["stop"] = 1 if stop else 0
        self._write(_DAEMON, row, etag)

    def should_stop(self) -> bool:
        return bool(self._read(_DAEMON)[0].get("stop"))

    def set_code_version(self, version: str) -> None:
        row, etag = self._read(_DAEMON)
        row["code_version"] = version
        self._write(_DAEMON, row, etag)

    def code_version(self) -> str | None:
        return self._read(_DAEMON)[0].get("code_version")

    # --- claiming -------------------------------------------------------------------

    def claim_next(self, now: datetime | None = None) -> Due | None:
        """Take the next due brand, or return None if nothing is ready.

        Walks the due brands in order and tries to claim each with a conditional write.
        A refusal is not an error — it means another worker claimed that brand between
        our read and our write — so the loop simply tries the next one.
        """
        now = now or _now()
        stale = _iso(now - timedelta(seconds=self.stale_claim_seconds))
        candidates = []
        for key in self._store.list(_SCHEDULE):
            row, etag = self._read(key)
            if not row or not row.get("enabled"):
                continue
            if row["next_due"] > _iso(now):
                continue
            held = row.get("claimed_by") is not None and (row.get("claimed_at") or "") >= stale
            if held:
                continue
            candidates.append((row["next_due"], key, row, etag))

        for _due, key, row, etag in sorted(candidates):
            row["claimed_by"] = self.worker_id
            row["claimed_at"] = _iso(now)
            try:
                self._write(key, row, etag)
            except Conflict:
                continue  # someone else got this brand; try the next
            return Due(row["domain"], row["cadence_seconds"])
        return None

    def release(self, domain: str, cadence_seconds: int, now: datetime | None = None) -> None:
        """Hand the brand back and set when it is next wanted."""
        now = now or _now()
        self._amend(
            domain,
            claimed_by=None,
            claimed_at=None,
            next_due=_iso(now + timedelta(seconds=cadence_seconds)),
        )

    def defer(self, domain: str, seconds: int, now: datetime | None = None) -> None:
        """Push a brand out without counting it as done — a host asking us to wait."""
        now = now or _now()
        self._amend(
            domain,
            claimed_by=None,
            claimed_at=None,
            next_due=_iso(now + timedelta(seconds=seconds)),
        )
