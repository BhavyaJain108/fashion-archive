"""The fleet's ceiling, and the two pools under it.

Continuous scraping is a rate; learning is a burst. They want different controls, so
the ceiling is split:

    recurring      keeping every brand fresh at its cadence — predictable after two
                   cycles, and the number that grows with the roster
    discretionary  probes, proxy sweeps, the model's analyses, first full reads — the
                   money poured into a wall, which must never eat the baseline

The ceiling is derived from the roster's own shape rather than picked: the sum of every
brand's predicted daily cost at its cheapest known lane (the baseline), times a
multiplier. It moves for the right reasons — more brands, bigger catalogues, more
brands stuck on paid rungs — and the headroom above 1× is the discretionary pool.

When the recurring pool would be exceeded the answer is to stretch cadences, not to
drop brands: freshness degrades, visibly, and coverage never does.

A third pool sits beside the ceiling rather than under it:

    onboarding     a brand's first read — the finder's calls to learn where its fields
                   live, paid once — so a wave of new brands neither eats the day's
                   recurring allowance nor is stopped by it. `ONBOARD_DAILY_USD`.

One object, `control/budget.json`, conditionally written like the finder's cap, so two
workers charging at once both land.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads

KEY = "control/budget.json"
HISTORY_DAYS = 90
_ATTEMPTS = 5
DEFAULT_MULTIPLIER = 1.5
# The share of the ceiling that is the recurring pool; the rest is discretionary.
# 1/multiplier puts the baseline exactly in the recurring pool.
POOLS = ("recurring", "discretionary", "onboarding")


class BudgetSpent(RuntimeError):
    """The pool is gone for today. Raised before the spend, never after."""


def multiplier() -> float:
    try:
        return float(os.environ.get("ARCHIVE_BUDGET_MULTIPLIER", "") or DEFAULT_MULTIPLIER)
    except ValueError:
        return DEFAULT_MULTIPLIER


def onboarding_usd() -> float:
    """What a day of first reads may spend on the finder, set aside from the ceiling."""
    try:
        return float(os.environ.get("ONBOARD_DAILY_USD", "") or 5.0)
    except ValueError:
        return 5.0


def _floor_usd() -> float:
    """A ceiling below which the day never goes, so an empty roster or a zero-priced
    world still lets the loop probe. ARCHIVE_BUDGET_FLOOR_USD."""
    try:
        return float(os.environ.get("ARCHIVE_BUDGET_FLOOR_USD", "") or 5.0)
    except ValueError:
        return 5.0


class FleetBudget:
    def __init__(self, store: ObjectStore, clock=None):
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _today(self) -> str:
        return self._clock().date().isoformat()

    def _read(self) -> tuple[dict, str | None]:
        found = self._store.get(KEY)
        return (loads(found[0]), found[1]) if found else ({}, None)

    def _fresh(self, row: dict) -> dict:
        """The row for today, rolling yesterday into history when the day turned."""
        today = self._today()
        if row.get("day") == today:
            return row
        history = dict(row.get("history") or {})
        if row.get("day"):
            history[row["day"]] = {
                "recurring": round(
                    float((row.get("pools") or {}).get("recurring", {}).get("spent", 0.0)), 6
                ),
                "discretionary": round(
                    float((row.get("pools") or {}).get("discretionary", {}).get("spent", 0.0)), 6
                ),
                "onboarding": round(
                    float((row.get("pools") or {}).get("onboarding", {}).get("spent", 0.0)), 6
                ),
                "ceiling": row.get("ceiling_usd_day"),
            }
        return {
            "day": today,
            "multiplier": row.get("multiplier") or multiplier(),
            "baseline_usd_day": row.get("baseline_usd_day") or 0.0,
            "ceiling_usd_day": row.get("ceiling_usd_day") or _floor_usd(),
            "pools": {
                "recurring": {
                    "spent": 0.0,
                    "cap": (row.get("pools") or {}).get("recurring", {}).get("cap", 0.0),
                },
                "discretionary": {
                    "spent": 0.0,
                    "cap": (row.get("pools") or {}).get("discretionary", {}).get("cap", 0.0),
                },
                "onboarding": {"spent": 0.0, "cap": onboarding_usd()},
            },
            "by_brand": {},
            "stretch": 1.0,
            "history": dict(sorted(history.items())[-HISTORY_DAYS:]),
            "brands": row.get("brands") or 0,
        }

    def refresh(self, predicted_by_brand: dict[str, float]) -> dict:
        """Recompute the baseline and ceiling from every brand's predicted daily cost."""
        baseline = round(sum(float(v) for v in predicted_by_brand.values()), 6)
        m = multiplier()
        ceiling = max(baseline * m, _floor_usd())
        recurring_cap = max(baseline, ceiling / m)
        for _ in range(_ATTEMPTS):
            row, etag = self._read()
            row = self._fresh(row)
            row.update(
                {
                    "multiplier": m,
                    "baseline_usd_day": baseline,
                    "ceiling_usd_day": round(ceiling, 6),
                    "brands": len(predicted_by_brand),
                    "predicted_by_brand": {
                        k: round(float(v), 6) for k, v in predicted_by_brand.items()
                    },
                    "refreshed_at": self._clock().isoformat(timespec="seconds"),
                }
            )
            row["pools"]["recurring"]["cap"] = round(recurring_cap, 6)
            row["pools"]["discretionary"]["cap"] = round(ceiling - recurring_cap, 6)
            row["pools"].setdefault("onboarding", {"spent": 0.0})["cap"] = onboarding_usd()
            try:
                self._store.put(KEY, dumps(row), if_match=etag)
                return row
            except Conflict:
                continue
        raise Conflict(f"{KEY}: still changing under us")

    def charge(self, domain: str, pool: str, usd: float) -> dict:
        """Add what a piece of work cost, to its pool and to the brand's line."""
        if pool not in POOLS:
            raise ValueError(f"no pool {pool!r}")
        for _ in range(_ATTEMPTS):
            row, etag = self._read()
            row = self._fresh(row)
            p = row["pools"].setdefault(pool, {"spent": 0.0, "cap": 0.0})
            p["spent"] = round(float(p.get("spent", 0.0)) + float(usd), 6)
            by = row.setdefault("by_brand", {})
            line = by.setdefault(domain, {"recurring": 0.0, "discretionary": 0.0})
            line[pool] = round(float(line.get(pool, 0.0)) + float(usd), 6)
            try:
                self._store.put(KEY, dumps(row), if_match=etag)
                return row
            except Conflict:
                continue
        raise Conflict(f"{KEY}: still changing under us")

    def allow(self, pool: str, estimate_usd: float = 0.0) -> bool:
        row = self._fresh(self._read()[0])
        p = row["pools"].get(pool) or {}
        if pool == "onboarding":
            cap = onboarding_usd()  # its own number, never derived from the ceiling
        else:
            cap = float(p.get("cap") or 0.0)
            if cap <= 0:
                # No ceiling computed yet: the floor is the allowance.
                cap = _floor_usd()
        return float(p.get("spent", 0.0)) + estimate_usd <= cap

    def check(self, pool: str, estimate_usd: float = 0.0) -> None:
        if not self.allow(pool, estimate_usd):
            row = self._fresh(self._read()[0])
            p = row["pools"].get(pool) or {}
            raise BudgetSpent(
                f"{pool}: ${p.get('spent', 0.0):.2f} of ${p.get('cap', 0.0):.2f} spent today"
            )

    def stretch_factor(self, projected_recurring_usd_day: float | None = None) -> float:
        """How much cadences must stretch for the recurring day to fit its pool. 1.0 fits."""
        row = self._fresh(self._read()[0])
        cap = float(row["pools"]["recurring"].get("cap") or 0.0)
        projected = (
            float(projected_recurring_usd_day)
            if projected_recurring_usd_day is not None
            else float(row.get("baseline_usd_day") or 0.0)
        )
        if cap <= 0 or projected <= cap:
            return 1.0
        return round(projected / cap, 3)

    def set_stretch(self, factor: float) -> None:
        for _ in range(_ATTEMPTS):
            row, etag = self._read()
            row = self._fresh(row)
            row["stretch"] = round(float(factor), 3)
            try:
                self._store.put(KEY, dumps(row), if_match=etag)
                return
            except Conflict:
                continue

    def summary(self) -> dict:
        row = self._fresh(self._read()[0])
        pools = row["pools"]
        pools.setdefault("onboarding", {"spent": 0.0, "cap": onboarding_usd()})
        # The ceiling's own pools. Onboarding is set aside from it and reported beside it.
        spent = float(pools["recurring"]["spent"]) + float(pools["discretionary"]["spent"])
        return {
            "day": row["day"],
            "multiplier": row.get("multiplier"),
            "baseline_usd_day": row.get("baseline_usd_day"),
            "ceiling_usd_day": row.get("ceiling_usd_day"),
            "spent_usd": round(spent, 6),
            "onboarding_usd_day": onboarding_usd(),
            "pools": pools,
            "by_brand": row.get("by_brand") or {},
            "predicted_by_brand": row.get("predicted_by_brand") or {},
            "stretch": row.get("stretch", 1.0),
            "brands": row.get("brands", 0),
            "history": row.get("history") or {},
            "refreshed_at": row.get("refreshed_at"),
        }
