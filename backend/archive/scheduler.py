"""The control plane: which brands are scraped, how often, and whether to keep going.

Everything here is rows, not code. A brand is added, dropped, paused or re-timed by
writing to the database while the daemon is running, and a code deploy does not touch
any of it. That separation is the point: the scraping keeps running so we can watch how
sites react to it, and the code underneath is replaced whenever we like.

Claiming is atomic, so several workers can share one schedule without coordinating.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEFAULT_CADENCE = 86_400  # a day


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

    def __init__(self, catalog, worker_id: str = "worker-1", stale_claim_seconds: int = 3600):
        self._db = catalog._db
        self.worker_id = worker_id
        # A worker that dies mid-brand leaves its claim behind. Nothing resumes the run
        # itself, but the brand must not be locked out of the schedule for ever.
        self.stale_claim_seconds = stale_claim_seconds
        self._db.execute("INSERT OR IGNORE INTO daemon_control (id, stop) VALUES (1, 0)")
        self._db.commit()

    # --- the brand list -------------------------------------------------------------

    def add(
        self,
        domain: str,
        cadence_seconds: int = DEFAULT_CADENCE,
        now: datetime | None = None,
    ) -> None:
        """A newly added brand is due immediately."""
        self._db.execute(
            "INSERT INTO schedule (domain, enabled, cadence_seconds, next_due) "
            "VALUES (?, 1, ?, ?) ON CONFLICT(domain) DO UPDATE SET "
            "enabled=1, cadence_seconds=excluded.cadence_seconds",
            (domain, cadence_seconds, _iso(now or _now())),
        )
        self._db.commit()

    def set_enabled(self, domain: str, enabled: bool) -> None:
        self._db.execute(
            "UPDATE schedule SET enabled=? WHERE domain=?", (1 if enabled else 0, domain)
        )
        self._db.commit()

    def set_cadence(self, domain: str, cadence_seconds: int) -> None:
        self._db.execute(
            "UPDATE schedule SET cadence_seconds=? WHERE domain=?", (cadence_seconds, domain)
        )
        self._db.commit()

    def rows(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM schedule ORDER BY domain")]

    # --- stopping -------------------------------------------------------------------

    def request_stop(self, stop: bool = True) -> None:
        """Stopping is a flag, not a kill: the worker finishes its brand and exits."""
        self._db.execute("UPDATE daemon_control SET stop=? WHERE id=1", (1 if stop else 0,))
        self._db.commit()

    def should_stop(self) -> bool:
        row = self._db.execute("SELECT stop FROM daemon_control WHERE id=1").fetchone()
        return bool(row["stop"]) if row else False

    def set_code_version(self, version: str) -> None:
        self._db.execute("UPDATE daemon_control SET code_version=? WHERE id=1", (version,))
        self._db.commit()

    def code_version(self) -> str | None:
        row = self._db.execute("SELECT code_version FROM daemon_control WHERE id=1").fetchone()
        return row["code_version"] if row else None

    # --- claiming -------------------------------------------------------------------

    def claim_next(self, now: datetime | None = None) -> Due | None:
        """Take the next due brand, atomically, or return None if nothing is ready."""
        now = now or _now()
        stale = _iso(now - timedelta(seconds=self.stale_claim_seconds))
        cur = self._db.execute(
            "UPDATE schedule SET claimed_by=?, claimed_at=? "
            "WHERE domain = (SELECT domain FROM schedule "
            "                WHERE enabled=1 AND next_due<=? "
            "                  AND (claimed_by IS NULL OR claimed_at < ?) "
            "                ORDER BY next_due LIMIT 1) "
            "RETURNING domain, cadence_seconds",
            (self.worker_id, _iso(now), _iso(now), stale),
        )
        row = cur.fetchone()
        self._db.commit()
        return Due(row["domain"], row["cadence_seconds"]) if row else None

    def release(self, domain: str, cadence_seconds: int, now: datetime | None = None) -> None:
        """Hand the brand back and set when it is next wanted."""
        now = now or _now()
        self._db.execute(
            "UPDATE schedule SET claimed_by=NULL, claimed_at=NULL, next_due=? WHERE domain=?",
            (_iso(now + timedelta(seconds=cadence_seconds)), domain),
        )
        self._db.commit()

    def defer(self, domain: str, seconds: int, now: datetime | None = None) -> None:
        """Push a brand out without counting it as done — a host asking us to wait."""
        now = now or _now()
        self._db.execute(
            "UPDATE schedule SET claimed_by=NULL, claimed_at=NULL, next_due=? WHERE domain=?",
            (_iso(now + timedelta(seconds=seconds)), domain),
        )
        self._db.commit()
