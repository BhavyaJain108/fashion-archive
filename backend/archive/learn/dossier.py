"""Everything known about one brand, unbounded and dated.

The brand-level understanding used to evaporate: a `notes:` string in brands.yml, a
plan's `tried` list, a Capability's evidence that lived for one probe, a LEARNINGS
entry about a rule rather than a brand. The dossier is the one place all of it goes,
appended and never pruned — the store is a bucket, space is not the constraint — so
the next probe, the next run, the analyst and the deck all read the same record.

    dossiers/<domain>.json              the record
    dossiers/<domain>/pages/<sha>.html  pages captured for analysis, referenced not inlined

Observations live here. Rules live elsewhere, keyed by signature, and the dossier only
says which ones were applied to this brand and what they changed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads

PREFIX = "dossiers/"
_ATTEMPTS = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Event(BaseModel):
    at: str
    kind: str
    text: str
    facts: dict[str, Any] = Field(default_factory=dict)


class Rung(BaseModel):
    at: str
    level: str  # t0 | t1 | t1p | t2 | a strategy name
    outcome: str  # access.outcome.Outcome value
    statuses: list[int] = Field(default_factory=list)
    seconds: float = 0.0
    note: str = ""


class Lane(BaseModel):
    at: str
    composition: str
    verdict: str  # capability verdict or run verdict
    products: int | None = None
    fill: dict[str, float] = Field(default_factory=dict)
    note: str = ""


class Analysis(BaseModel):
    id: str
    at: str
    kind: str  # brand | failure | consolidation
    status: str = "proposed"  # proposed | landed | branched | rejected | failed
    reasoning: str = ""
    proposal: dict[str, Any] = Field(default_factory=dict)
    gate: dict[str, Any] | None = None
    usd: float = 0.0


class RuleApplied(BaseModel):
    id: str
    signature: str
    kind: str  # recipe | code | builtin
    description: str
    at: str
    status: str = "provisional"  # provisional | confirmed | retired
    learning: str | None = None  # LEARNINGS.md entry, e.g. "17"


class MeterDay(BaseModel):
    requests: dict[str, int] = Field(default_factory=dict)  # by level
    bytes: dict[str, int] = Field(default_factory=dict)
    proxy_requests: int = 0
    browser_seconds: float = 0.0
    llm_calls: int = 0
    llm_tokens: int = 0
    llm_usd: float = 0.0
    wall_seconds: float = 0.0
    runs: int = 0
    probes: int = 0
    usd: float = 0.0  # everything above, priced


class Step(BaseModel):
    name: str
    status: str = "pending"  # pending | running | done | failed | skipped
    at: str | None = None
    text: str = ""


class Onboarding(BaseModel):
    started_at: str
    finished_at: str | None = None
    steps: list[Step] = Field(default_factory=list)


class Dossier(BaseModel):
    domain: str
    name: str | None = None
    created_at: str
    updated_at: str
    signature: str | None = None
    signature_history: list[dict[str, Any]] = Field(default_factory=list)
    wall: dict[str, Any] | None = None
    ladder: list[Rung] = Field(default_factory=list)
    lanes: list[Lane] = Field(default_factory=list)
    # field -> {"state": "absent" | "unread" | "read", "why": str, "at": str}
    gaps: dict[str, dict[str, Any]] = Field(default_factory=dict)
    meter: dict[str, MeterDay] = Field(default_factory=dict)  # day -> what it cost
    predicted: dict[str, Any] = Field(default_factory=dict)
    analyses: list[Analysis] = Field(default_factory=list)
    rules: list[RuleApplied] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    pages: dict[str, dict[str, Any]] = Field(default_factory=dict)  # sha -> {url, at, kind}
    onboarding: Onboarding | None = None
    notes: str | None = None

    # --- what the record says, read together --------------------------------------

    def latest_rung(self, level: str) -> Rung | None:
        for r in reversed(self.ladder):
            if r.level == level:
                return r
        return None

    def rung_outcomes(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in self.ladder:
            out[r.level] = r.outcome
        return out

    def best_lane(self) -> Lane | None:
        """The last lane that read products, else the last lane tried."""
        for lane in reversed(self.lanes):
            if lane.verdict in ("full", "partial", "ok"):
                return lane
        return self.lanes[-1] if self.lanes else None

    def cost(self, days: int = 1) -> float:
        keys = sorted(self.meter)[-days:]
        return round(sum(self.meter[k].usd for k in keys), 6)

    def open_analyses(self) -> list[Analysis]:
        return [a for a in self.analyses if a.status == "proposed"]


class DossierStore:
    """Reads and writes dossiers. Every write is read-modify-write under an etag so two
    workers appending to one brand's record both land."""

    def __init__(self, store: ObjectStore):
        self._store = store

    @staticmethod
    def key(domain: str) -> str:
        return f"{PREFIX}{domain}.json"

    def load(self, domain: str) -> Dossier | None:
        found = self._store.get(self.key(domain))
        if not found:
            return None
        return Dossier(**loads(found[0]))

    def domains(self) -> list[str]:
        keys = self._store.list(PREFIX)
        return sorted(
            k[len(PREFIX) : -5] for k in keys if k.endswith(".json") and "/" not in k[len(PREFIX) :]
        )

    def load_all(self) -> list[Dossier]:
        names = self.domains()
        if not names:
            return []
        with ThreadPoolExecutor(max_workers=min(16, len(names))) as pool:
            got = list(pool.map(self.load, names))
        return [d for d in got if d is not None]

    def open(self, domain: str, name: str | None = None) -> Dossier:
        """The dossier, created if this is the first time the brand is looked at."""
        found = self.load(domain)
        if found:
            if name and not found.name:
                found.name = name
                self.save(found)
            return found
        d = Dossier(domain=domain, name=name, created_at=now_iso(), updated_at=now_iso())
        d.events.append(Event(at=d.created_at, kind="opened", text="dossier opened"))
        self.save(d)
        return d

    def save(self, dossier: Dossier) -> None:
        dossier.updated_at = now_iso()
        self._store.put(self.key(dossier.domain), dumps(dossier.model_dump()))

    def update(
        self, domain: str, change: Callable[[Dossier], None], name: str | None = None
    ) -> Dossier:
        """Apply `change` to the current record and write it back; retried on a conflict."""
        key = self.key(domain)
        for _ in range(_ATTEMPTS):
            found = self._store.get(key)
            if found:
                dossier, etag = Dossier(**loads(found[0])), found[1]
            else:
                dossier, etag = (
                    Dossier(domain=domain, name=name, created_at=now_iso(), updated_at=now_iso()),
                    None,
                )
                dossier.events.append(
                    Event(at=dossier.created_at, kind="opened", text="dossier opened")
                )
            change(dossier)
            dossier.updated_at = now_iso()
            try:
                self._store.put(key, dumps(dossier.model_dump()), if_match=etag)
                return dossier
            except Conflict:
                continue
        raise Conflict(f"{key}: still changing under us after {_ATTEMPTS} attempts")

    # --- the appends everything else makes ------------------------------------------

    def event(self, domain: str, kind: str, text: str, **facts) -> None:
        self.update(
            domain,
            lambda d: d.events.append(Event(at=now_iso(), kind=kind, text=text, facts=facts)),
        )

    def rung(
        self, domain: str, level: str, outcome: str, statuses=(), seconds=0.0, note=""
    ) -> None:
        def change(d: Dossier) -> None:
            d.ladder.append(
                Rung(
                    at=now_iso(),
                    level=level,
                    outcome=outcome,
                    statuses=list(statuses),
                    seconds=round(float(seconds), 3),
                    note=note,
                )
            )
            d.events.append(
                Event(
                    at=now_iso(),
                    kind="rung",
                    text=f"asked over {level}: {outcome}" + (f" — {note}" if note else ""),
                    facts={"level": level, "outcome": outcome},
                )
            )

        self.update(domain, change)

    def lane(
        self, domain: str, composition: str, verdict: str, products=None, fill=None, note=""
    ) -> None:
        def change(d: Dossier) -> None:
            d.lanes.append(
                Lane(
                    at=now_iso(),
                    composition=composition,
                    verdict=verdict,
                    products=products,
                    fill=dict(fill or {}),
                    note=note,
                )
            )
            d.events.append(
                Event(
                    at=now_iso(),
                    kind="lane",
                    text=f"{composition}: {verdict}"
                    + (f", {products:,} products" if products is not None else "")
                    + (f" — {note}" if note else ""),
                    facts={"composition": composition, "verdict": verdict},
                )
            )

        self.update(domain, change)

    def set_signature(self, domain: str, key: str, why: str = "") -> None:
        def change(d: Dossier) -> None:
            if d.signature == key:
                return
            d.signature_history.append(
                {"at": now_iso(), "from": d.signature, "to": key, "why": why}
            )
            d.signature = key
            d.events.append(
                Event(at=now_iso(), kind="signature", text=f"signature: {key}", facts={"key": key})
            )

        self.update(domain, change)

    def set_wall(self, domain: str, wall: str, action: str, why: str) -> None:
        def change(d: Dossier) -> None:
            prev = d.wall or {}
            if prev.get("type") == wall and prev.get("action") == action:
                prev["why"] = why
                prev["seen_at"] = now_iso()
                d.wall = prev
                return
            d.wall = {
                "type": wall,
                "action": action,
                "why": why,
                "since": now_iso(),
                "seen_at": now_iso(),
                "attempts": 0,
            }
            d.events.append(
                Event(
                    at=now_iso(),
                    kind="wall",
                    text=f"wall: {wall} → {action} ({why})",
                    facts={"wall": wall, "action": action},
                )
            )

        self.update(domain, change)

    def attempted(self, domain: str) -> None:
        def change(d: Dossier) -> None:
            if d.wall:
                d.wall["attempts"] = int(d.wall.get("attempts") or 0) + 1
                d.wall["attempted_at"] = now_iso()

        self.update(domain, change)

    def set_gaps(self, domain: str, gaps: dict[str, dict[str, Any]]) -> None:
        def change(d: Dossier) -> None:
            for field, g in gaps.items():
                d.gaps[field] = {**g, "at": now_iso()}

        self.update(domain, change)

    def meter_add(self, domain: str, day: str, delta: dict[str, Any]) -> None:
        """Add one run's, probe's or analysis's resources to the day's line."""

        def change(d: Dossier) -> None:
            line = d.meter.get(day) or MeterDay()
            for level, n in (delta.get("requests") or {}).items():
                line.requests[level] = line.requests.get(level, 0) + int(n)
            for level, n in (delta.get("bytes") or {}).items():
                line.bytes[level] = line.bytes.get(level, 0) + int(n)
            line.proxy_requests += int(delta.get("proxy_requests") or 0)
            line.browser_seconds = round(
                line.browser_seconds + float(delta.get("browser_seconds") or 0), 3
            )
            line.llm_calls += int(delta.get("llm_calls") or 0)
            line.llm_tokens += int(delta.get("llm_tokens") or 0)
            line.llm_usd = round(line.llm_usd + float(delta.get("llm_usd") or 0), 6)
            line.wall_seconds = round(line.wall_seconds + float(delta.get("wall_seconds") or 0), 3)
            line.runs += int(delta.get("runs") or 0)
            line.probes += int(delta.get("probes") or 0)
            line.usd = round(line.usd + float(delta.get("usd") or 0), 6)
            d.meter[day] = line

        self.update(domain, change)

    def set_predicted(self, domain: str, predicted: dict[str, Any]) -> None:
        self.update(domain, lambda d: d.predicted.update({**predicted, "at": now_iso()}))

    def analysis(self, domain: str, analysis: Analysis) -> None:
        def change(d: Dossier) -> None:
            for i, a in enumerate(d.analyses):
                if a.id == analysis.id:
                    d.analyses[i] = analysis
                    break
            else:
                d.analyses.append(analysis)
                d.events.append(
                    Event(
                        at=analysis.at,
                        kind="analysis",
                        text=f"the model looked ({analysis.kind}): {analysis.reasoning[:160]}",
                        facts={"id": analysis.id, "kind": analysis.kind},
                    )
                )

        self.update(domain, change)

    def rule(self, domain: str, rule: RuleApplied) -> None:
        def change(d: Dossier) -> None:
            for i, r in enumerate(d.rules):
                if r.id == rule.id:
                    d.rules[i] = rule
                    return
            d.rules.append(rule)
            d.events.append(
                Event(
                    at=rule.at,
                    kind="rule",
                    text=f"rule applied: {rule.description}",
                    facts={"id": rule.id},
                )
            )

        self.update(domain, change)

    # --- onboarding, the stepper the deck watches -----------------------------------

    STEPS = ("probe", "signature", "wall", "plan", "first-read", "verdict")

    def onboarding_start(self, domain: str, name: str | None = None) -> None:
        def change(d: Dossier) -> None:
            if name and not d.name:
                d.name = name
            d.onboarding = Onboarding(
                started_at=now_iso(), steps=[Step(name=s) for s in self.STEPS]
            )
            d.events.append(Event(at=now_iso(), kind="onboarding", text="onboarding started"))

        self.update(domain, change, name=name)

    def onboarding_step(self, domain: str, name: str, status: str, text: str = "") -> None:
        def change(d: Dossier) -> None:
            if d.onboarding is None:
                d.onboarding = Onboarding(
                    started_at=now_iso(), steps=[Step(name=s) for s in self.STEPS]
                )
            for step in d.onboarding.steps:
                if step.name == name:
                    step.status, step.at, step.text = status, now_iso(), text
            if status in ("done", "failed", "skipped"):
                d.events.append(
                    Event(at=now_iso(), kind=f"onboarding:{name}", text=text or f"{name}: {status}")
                )
            if name == self.STEPS[-1] and status in ("done", "failed", "skipped"):
                d.onboarding.finished_at = now_iso()

        self.update(domain, change)

    # --- pages captured for the analyst ---------------------------------------------

    def save_page(self, domain: str, url: str, html: str, kind: str = "product") -> str:
        sha = hashlib.sha1(html.encode("utf-8", "replace")).hexdigest()[:16]
        self._store.put(f"{PREFIX}{domain}/pages/{sha}.html", html.encode("utf-8", "replace"))
        self.update(
            domain,
            lambda d: d.pages.__setitem__(
                sha, {"url": url, "at": now_iso(), "kind": kind, "bytes": len(html)}
            ),
        )
        return sha

    def load_page(self, domain: str, sha: str) -> str | None:
        found = self._store.get(f"{PREFIX}{domain}/pages/{sha}.html")
        return found[0].decode("utf-8", "replace") if found else None
