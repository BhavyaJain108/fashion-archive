"""A daily ceiling on what the field finder may spend, shared by every worker.

Learning a field rule is one model call over one product page, and it is the only
thing in the daemon that costs money per run. It used to be switched off there for
exactly that reason — "deliberate, not a background activity" — which meant the one
component that learns never ran on the machine that scrapes.

This is the other answer: let it run, under a number. The number lives in one object
in the bucket, so two worker threads on two brands draw from the same day's allowance,
and a restart does not forget what the morning cost. When the day's allowance is gone
the finder stops for the day and says so; it does not fail, and the fields it did not
get to are not recorded as searched — a budget stop is not evidence of absence.

The day boundary is UTC midnight, the same clock everything else here is stamped in.
"""

from datetime import datetime, timezone

from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads

KEY = "control/finder_spend.json"
# Days of per-day totals kept, so the deck can show what the finder has been costing.
HISTORY_DAYS = 90
# Conditional-write attempts before giving up on recording a charge. Two threads
# charging at once is the realistic worst case; five is generous.
_ATTEMPTS = 5


class FinderBudgetSpent(RuntimeError):
    """Today's allowance is gone. Raised before a call, never after one."""


class DailyCap:
    def __init__(self, store: ObjectStore, usd_per_day: float, clock=None):
        self._store = store
        self.usd_per_day = float(usd_per_day)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _today(self) -> str:
        return self._clock().date().isoformat()

    def _read(self) -> tuple[dict, str | None]:
        found = self._store.get(KEY)
        return (loads(found[0]), found[1]) if found else ({}, None)

    def spent_today(self) -> float:
        row, _ = self._read()
        return float(row.get("usd", 0.0)) if row.get("day") == self._today() else 0.0

    def allow(self, estimate_usd: float = 0.0) -> bool:
        """Whether one more call, costing about `estimate_usd`, fits in today."""
        if self.usd_per_day <= 0:
            return False
        return self.spent_today() + estimate_usd <= self.usd_per_day

    def check(self, estimate_usd: float = 0.0) -> None:
        if not self.allow(estimate_usd):
            raise FinderBudgetSpent(
                f"${self.spent_today():.2f} of ${self.usd_per_day:.2f} spent today"
            )

    def charge(self, usd: float, calls: int = 1) -> float:
        """Add what a call cost. Returns the day's new total."""
        for _ in range(_ATTEMPTS):
            row, etag = self._read()
            today = self._today()
            history = dict(row.get("history") or {})
            if row.get("day") != today:
                if row.get("day"):
                    history[row["day"]] = round(float(row.get("usd", 0.0)), 6)
                row = {"day": today, "usd": 0.0, "calls": 0}
            row["usd"] = round(float(row.get("usd", 0.0)) + usd, 6)
            row["calls"] = int(row.get("calls", 0)) + calls
            row["history"] = dict(sorted(history.items())[-HISTORY_DAYS:])
            row["cap_usd"] = self.usd_per_day
            try:
                self._store.put(KEY, dumps(row), if_match=etag)
                return row["usd"]
            except Conflict:
                continue
        # Five conflicts in a row means the object is being hammered; the charge is
        # lost rather than the run. Under-counting by one call is the safe direction
        # only because the cap is checked again before the next one.
        return self.spent_today()

    def summary(self) -> dict:
        """Today, the cap, and the recent days — what the deck draws."""
        row, _ = self._read()
        today = self._today()
        return {
            "day": today,
            "usd": float(row.get("usd", 0.0)) if row.get("day") == today else 0.0,
            "calls": int(row.get("calls", 0)) if row.get("day") == today else 0,
            "cap_usd": self.usd_per_day,
            "history": row.get("history") or {},
        }
