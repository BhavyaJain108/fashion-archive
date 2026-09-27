"""The tick that walks the fleet and does the mechanical part unattended.

One pass, on a cadence, from the daemon or by hand:

    1. every brand on the roster has a dossier; a brand without one is onboarded —
       probed up the ladder, signed, classified, planned, sample-read, verdicted — with
       each step written to the dossier as it happens, so the deck can watch
    2. every dossier is classified: a wall and a next action
    3. the mechanical actions are taken: a rung climbed, a brand paced or watched;
       the analyses queued for the model are made while the discretionary pool allows
    4. a proposal goes through the gate; a recipe that passes lands (a plan is written
       for the brand, the recipe is filed under its signature); code that passes is
       written to a branch or, without a way to push, filed for a person to apply
    5. every brand's predicted cost is refreshed from its lane and cadences, the fleet
       budget from those, the cadence stretch from the budget, and the signature map
       and the baseline from the dossiers

Everything the tick decides it also writes down, in the dossier of the brand concerned
and in control/learning.json for the fleet, so "what did the loop do last night" is a
read and not a reconstruction.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from backend.archive.access.bench import sweep
from backend.archive.access.strategy import get as get_strategy
from backend.archive.capability import probe_brand
from backend.archive.domain.brand import (
    Brand,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    ScrapePlan,
    TransportLevel,
)
from backend.archive.learn import analyst as analyst_mod
from backend.archive.learn.budget import BudgetSpent, FleetBudget
from backend.archive.learn.dossier import Analysis, Dossier, DossierStore, RuleApplied, now_iso
from backend.archive.learn.gate import Baseline, prove
from backend.archive.learn.meter import Meter, Prices, predict, today
from backend.archive.learn.recipes import Discover, Fetch, LaneRecipe
from backend.archive.learn.signature import Signature, signature_of
from backend.archive.learn.walls import Action, classify
from backend.archive.planner import compose_plan
from backend.archive.roster import app_roster, load_roster
from backend.archive.scheduler import Scheduler
from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads
from backend.archive.transport import for_level, proxy_url

LEARNING = "control/learning.json"
SIGNATURES = "control/signatures.json"
RECIPES = "recipes/lanes/"
PROPOSALS = "learn/proposals/"
# Brands onboarded per tick, so a roster of a hundred new brands does not hold the
# tick for an hour; the rest are next tick's.
ONBOARD_PER_TICK = int(os.environ.get("LEARN_ONBOARD_PER_TICK", "4") or 4)
ANALYSES_PER_TICK = int(os.environ.get("LEARN_ANALYSES_PER_TICK", "3") or 3)
# Analyses one brand may have in a week: a wall that three looks did not open wants a
# person, not a fourth look.
ANALYSES_PER_BRAND_PER_WEEK = 3
# How long a watched wall waits before it is asked again.
WATCH_DAYS = 7
# Where the model's code proposals go when the worker can push: a branch per proposal.
GIT_PUSH_URL = os.environ.get("ARCHIVE_GIT_PUSH_URL", "").strip()


def _log_default(msg: str) -> None:
    print(msg, flush=True)


class Loop:
    def __init__(
        self,
        store: ObjectStore,
        catalog,
        brands_path: Path | None = None,
        analyst=None,  # a client with .propose(prompt) -> dict; None means no model
        browser_available: bool = False,
        prices: Prices | None = None,
        log=_log_default,
        transport_factory=for_level,
        clock=None,
    ):
        self.store = store
        self.catalog = catalog
        self.dossiers = DossierStore(store)
        self.budget = FleetBudget(store)
        self.baseline = Baseline(store)
        self.scheduler = Scheduler(store)
        self.brands_path = brands_path
        self.analyst = analyst
        self.browser_available = browser_available
        self.prices = prices or Prices.from_env()
        self.log = log
        self.transport_factory = transport_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # --- onboarding: the stepper -----------------------------------------------------------

    def onboard(self, domain: str, name: str | None = None) -> Dossier:
        """Probe, sign, classify, plan, read a sample, verdict — each step written as it
        happens. Idempotent: onboarding a brand again re-runs the steps and appends."""
        ds = self.dossiers
        meter = Meter(prices=self.prices)
        started = time.monotonic()
        ds.onboarding_start(domain, name=name)
        brand = self._brand(domain, name)
        try:
            # 1. probe, up the ladder, recording every rung
            ds.onboarding_step(domain, "probe", "running", "asking the shop, cheapest rung first")
            cap, rungs = self._climb(domain, meter)
            for r in rungs:
                ds.rung(
                    domain,
                    r["level"],
                    r["outcome"],
                    r.get("statuses", []),
                    r.get("seconds", 0.0),
                    r.get("note", ""),
                )
            ds.onboarding_step(
                domain,
                "probe",
                "done",
                ", ".join(f"{r['level']} {r['outcome']}" for r in rungs) or "no answer at any rung",
            )
            # 2. signature
            ds.onboarding_step(domain, "signature", "running")
            sig = signature_of(cap, rungs) if cap is not None else Signature(defence="address")
            ds.set_signature(domain, sig.key, why="from the probe")
            ds.onboarding_step(domain, "signature", "done", sig.key)
            # 3. wall
            ds.onboarding_step(domain, "wall", "running")
            d = ds.load(domain)
            verdict = (
                classify(
                    d, proxy_available=bool(proxy_url()), browser_available=self.browser_available
                )
                if d
                else None
            )
            if verdict:
                ds.set_wall(domain, verdict.wall.value, verdict.action.value, verdict.why)
                ds.onboarding_step(
                    domain,
                    "wall",
                    "done",
                    f"{verdict.wall.value} → {verdict.action.value}: {verdict.why}",
                )
            # 4. plan
            ds.onboarding_step(domain, "plan", "running")
            plan = None
            if cap is not None:
                plan = compose_plan(cap, browser=self.browser_available)
                if plan.status != "ready":
                    recipe = self._recipe_for(sig.key)
                    if recipe is not None:
                        plan = recipe_plan(domain, recipe, cap.transport)
                        ds.rule(
                            domain,
                            RuleApplied(
                                id=recipe.id,
                                signature=recipe.signature,
                                kind="recipe",
                                description=recipe.description,
                                at=now_iso(),
                                status=recipe.status,
                            ),
                        )
                self.catalog.save_plan(plan)
                ds.onboarding_step(domain, "plan", "done", f"{plan.composition} ({plan.status})")
            else:
                ds.onboarding_step(
                    domain, "plan", "skipped", "nothing answered, so nothing to plan"
                )
            # 5. first read — a sample, the way the capability matrix measures a brand
            ds.onboarding_step(domain, "first-read", "running")
            if plan is not None and plan.status == "ready":
                report = self._sample(brand, cap, plan, meter)
                ds.lane(
                    domain,
                    report.lane,
                    report.verdict,
                    report.catalog_size,
                    report.fill,
                    report.note,
                )
                self.baseline.record(domain, report.verdict, report.fill, report.lane)
                ds.set_gaps(domain, gaps_from_fill(report.fill))
                ds.onboarding_step(
                    domain,
                    "first-read",
                    "done",
                    f"{report.verdict}: {report.catalog_size or 0:,} products found, {report.sampled} read",
                )
            else:
                ds.onboarding_step(domain, "first-read", "skipped", "no lane is ready")
            # 6. verdict
            d = ds.load(domain)
            verdict = (
                classify(
                    d, proxy_available=bool(proxy_url()), browser_available=self.browser_available
                )
                if d
                else None
            )
            if verdict:
                ds.set_wall(domain, verdict.wall.value, verdict.action.value, verdict.why)
                ds.onboarding_step(
                    domain,
                    "verdict",
                    "done",
                    f"{verdict.wall.value} — next: {verdict.action.value}",
                )
            self._predict(domain)
        except Exception as e:  # noqa: BLE001 — a failed onboarding is a fact, not a crash
            ds.onboarding_step(domain, "verdict", "failed", f"{type(e).__name__}: {e}"[:300])
            self.log(
                f"{domain} onboarding failed: {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}"
            )
        finally:
            meter.wall_seconds = time.monotonic() - started
            meter.probes = 1
            self._charge(domain, "discretionary", meter)
        return ds.load(domain)  # type: ignore[return-value]

    def _brand(self, domain: str, name: str | None) -> Brand:
        known = self.catalog.get_brand(domain)
        if known:
            return known
        return Brand(domain=domain, homepage_url=f"https://{domain}", display_name=name)

    def _strategies(self):
        names = ["httpx", "cffi:chrome142"]
        if proxy_url():
            names.append("cffi:chrome142@proxy")
        if self.browser_available:
            names.append("playwright")
        return [s for s in (get_strategy(n) for n in names) if s.available]

    def _climb(self, domain: str, meter: Meter):
        """Up the shelf until a rung reads the shop. Returns (best capability, rungs)."""
        results = sweep([domain], self._strategies(), retry_pause=1.0)
        rungs = []
        best = None
        for r in results:
            level = get_strategy(r.strategy).level.value
            rungs.append(
                {
                    "level": level,
                    "strategy": r.strategy,
                    "outcome": r.outcome.value,
                    "statuses": r.statuses,
                    "seconds": r.seconds,
                    "note": r.note,
                }
            )
            meter.track(_Ledger(level, r.requests))
            if (
                best is None
                and r.capability is not None
                and (r.usable or r.capability.password_gated)
            ):
                best = r.capability.model_copy(
                    update={
                        "transport": TransportLevel(level)
                        if level != "t0"
                        else r.capability.transport
                    }
                )
        if best is None:
            # nothing read; keep the last capability that answered at all, for the evidence
            for r in reversed(results):
                if r.capability is not None:
                    best = r.capability
                    break
        return best, rungs

    def _sample(self, brand: Brand, cap, plan: ScrapePlan, meter: Meter):
        transport = meter.track(
            self.transport_factory(
                plan.transport if plan.transport != TransportLevel.T4 else TransportLevel.T0
            )
        )
        try:
            return probe_brand(
                brand,
                transport,
                sample=5,
                browser=self.browser_available,
                prober=lambda d, t: cap,
                composer=lambda c, browser=False: plan,
                transport_factory=lambda level: meter.track(self.transport_factory(level)),
            )
        finally:
            closer = getattr(transport, "close", None)
            if callable(closer):
                closer()

    # --- the tick ----------------------------------------------------------------------------

    def tick(self) -> dict:
        started = self._clock()
        summary: dict = {
            "at": started.isoformat(timespec="seconds"),
            "onboarded": [],
            "actions": [],
            "analyses": [],
            "landed": [],
            "errors": [],
        }
        roster = {e.domain: e for e in load_roster(self.brands_path, store=self.store)}
        shown = {e.domain for e in app_roster(self.brands_path, store=self.store)}
        have = set(self.dossiers.domains())

        # 1. onboard what has no dossier, a few per tick, shown brands first
        missing = sorted(roster.keys() - have, key=lambda d: (d not in shown, d))
        for domain in missing[:ONBOARD_PER_TICK]:
            try:
                self.onboard(domain, name=roster[domain].name)
                summary["onboarded"].append(domain)
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"{domain}: onboard: {type(e).__name__}: {e}"[:200])

        # 2 + 3. classify and act
        dossiers = self.dossiers.load_all()
        medians = self._median_cost_per_product(dossiers)
        analyses_left = ANALYSES_PER_TICK
        for d in dossiers:
            if d.domain not in roster:
                continue
            try:
                sig = Signature.parse(d.signature) if d.signature else None
                median = medians.get(sig.key) if sig else None
                v = classify(
                    d,
                    median,
                    proxy_available=bool(proxy_url()),
                    browser_available=self.browser_available,
                )
                self.dossiers.set_wall(d.domain, v.wall.value, v.action.value, v.why)
                acted = self._act(d, v, analyses_left)
                if acted:
                    summary["actions"].append(
                        {
                            "domain": d.domain,
                            "wall": v.wall.value,
                            "action": v.action.value,
                            "did": acted,
                        }
                    )
                    if v.action in (Action.ANALYSE, Action.CHEAPEN) and acted.startswith(
                        "analysed"
                    ):
                        analyses_left -= 1
                        summary["analyses"].append(d.domain)
                        if "landed" in acted:
                            summary["landed"].append(d.domain)
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"{d.domain}: {type(e).__name__}: {e}"[:200])
                self.log(
                    f"{d.domain}: tick failed: {type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}"
                )

        # 5. predictions, budget, stretch, map, status
        predicted: dict[str, float] = {}
        for d in self.dossiers.load_all():
            if d.domain in roster:
                p = self._predict(d.domain, d)
                if p:
                    predicted[d.domain] = float(p.get("per_day_usd") or 0.0)
        budget = self.budget.refresh(predicted)
        stretch = self.budget.stretch_factor(sum(predicted.values()))
        self.budget.set_stretch(stretch)
        summary["budget"] = {
            "baseline_usd_day": budget.get("baseline_usd_day"),
            "ceiling_usd_day": budget.get("ceiling_usd_day"),
            "stretch": stretch,
        }
        self._write_map()
        summary["seconds"] = round((self._clock() - started).total_seconds(), 1)
        self._write_status(summary)
        return summary

    def _act(self, d: Dossier, v, analyses_left: int) -> str | None:
        action = v.action
        if action == Action.NONE:
            return None
        if action == Action.ONBOARD:
            self.onboard(d.domain, name=d.name)
            return "onboarded"
        if action in (Action.CLIMB_T1, Action.CLIMB_T1P, Action.CLIMB_T2):
            return self._climb_one(d, action)
        if action == Action.PACE:
            # The scheduler already stands a busy host down; the dossier records that
            # the loop saw it and did not escalate.
            self.dossiers.attempted(d.domain)
            return "paced"
        if action == Action.WATCH:
            last = (d.wall or {}).get("attempted_at") or (d.wall or {}).get("since") or ""
            if last and (self._clock() - _aware(last)).days < WATCH_DAYS:
                return None
            self.dossiers.attempted(d.domain)
            self.onboard(d.domain, name=d.name)
            return "re-probed after a week's watch"
        if action in (Action.ANALYSE, Action.CHEAPEN):
            if self.analyst is None:
                return "analysis wanted; no model configured"
            if analyses_left <= 0:
                return "analysis wanted; this tick's allowance is spent"
            if self._analyses_this_week(d) >= ANALYSES_PER_BRAND_PER_WEEK:
                return "analysis wanted; this brand's week is spent — needs a person"
            try:
                self.budget.check("discretionary", analyst_mod.ESTIMATE_USD)
            except BudgetSpent as e:
                return f"analysis wanted; {e}"
            kind = "cheapen" if action == Action.CHEAPEN else ("failure" if _reads(d) else "brand")
            a = self.analyse(d.domain, kind=kind)
            if a.status == "landed":
                return f"analysed and landed {a.id}"
            if a.status == "branched":
                return f"analysed; code on a branch {a.id}"
            return f"analysed: {a.status}"
        return None

    def _climb_one(self, d: Dossier, action: Action) -> str:
        name = {
            Action.CLIMB_T1: "cffi:chrome142",
            Action.CLIMB_T1P: "cffi:chrome142@proxy",
            Action.CLIMB_T2: "playwright",
        }[action]
        strategy = get_strategy(name)
        if not strategy.available:
            self.dossiers.attempted(d.domain)
            return f"{name} is not available on this worker"
        meter = Meter(prices=self.prices)
        results = sweep([d.domain], [strategy], retry_pause=1.0)
        r = results[0]
        level = strategy.level.value
        self.dossiers.rung(d.domain, level, r.outcome.value, r.statuses, r.seconds, r.note)
        self.dossiers.attempted(d.domain)
        meter.track(_Ledger(level, r.requests))
        meter.probes = 1
        self._charge(d.domain, "discretionary", meter)
        if r.usable and r.capability is not None:
            cap = r.capability.model_copy(update={"transport": strategy.level})
            plan = compose_plan(cap, browser=self.browser_available)
            self.catalog.save_plan(plan)
            self.dossiers.set_signature(
                d.domain,
                signature_of(cap, [rr.model_dump() for rr in d.ladder]).key,
                why=f"read over {level}",
            )
            self.dossiers.event(
                d.domain,
                "plan",
                f"{level} reads it; plan {plan.composition} written",
                composition=plan.composition,
            )
            self.scheduler.run_now(d.domain)
            return f"climbed to {level}: readable; plan written and the brand is due"
        return f"climbed to {level}: {r.outcome.value}"

    # --- analysis and landing --------------------------------------------------------------

    def analyse(self, domain: str, kind: str = "brand", extra: str = "") -> Analysis:
        """One question to the model about one brand, then the gate."""
        d = self.dossiers.open(domain)
        pages = self._capture_pages(d)
        neighbours = self._neighbours(d)
        rules = [r.model_dump() for r in self._recipes()]
        spend = analyst_mod.Spend(analyst_mod.INPUT_RATE, analyst_mod.OUTPUT_RATE)
        client = self.analyst if self.analyst is not None else analyst_mod.default_client(spend)
        a = analyst_mod.analyse(
            kind, d, pages, neighbours, rules, client=client, spend=spend, extra=extra
        )
        meter = Meter(prices=self.prices)
        meter.note_llm(a.usd, calls=1, tokens=spend.input_tokens + spend.output_tokens)
        self._charge(domain, "discretionary", meter)
        self.dossiers.analysis(domain, a)
        if a.status != "proposed":
            return a
        # what the model said about the shape and the gaps is recorded whatever the gate says
        p = a.proposal
        try:
            if isinstance(p.get("signature"), dict):
                sig = Signature(**p["signature"])
                self.dossiers.set_signature(domain, sig.key, why=f"the model's reading ({a.id})")
            gaps = {
                g["field"]: {"state": g["state"], "why": g.get("why", "")}
                for g in p.get("gaps") or []
                if isinstance(g, dict) and g.get("field")
            }
            if gaps:
                self.dossiers.set_gaps(domain, gaps)
        except Exception as e:  # noqa: BLE001
            self.log(f"{domain}: could not record the model's signature/gaps: {e}")
        lane = p.get("lane") or {}
        if lane.get("kind") == "recipe" and lane.get("recipe"):
            a = self._land_recipe(domain, d, a, lane["recipe"], pages)
        elif lane.get("kind") == "code" and lane.get("code"):
            a = self._file_code(domain, a, lane["code"])
        else:
            a.status = "rejected"
            a.gate = {
                "passed": False,
                "note": lane.get("why_not_cheaper") or "the model proposed no lane",
            }
        self.dossiers.analysis(domain, a)
        return a

    def _land_recipe(
        self, domain: str, d: Dossier, a: Analysis, recipe_dict: dict, pages: dict[str, str]
    ) -> Analysis:
        sig = d.signature or "custom·closed·none·none·none·none"
        try:
            recipe = LaneRecipe(
                id=f"{sig.replace('·', '-')}-{a.id}",
                signature=sig,
                description=str(recipe_dict.get("description") or "")[:200],
                discover=Discover(**(recipe_dict.get("discover") or {})),
                fetch=Fetch(**(recipe_dict.get("fetch") or {})),
                learned_from=domain,
                at=now_iso(),
            )
        except Exception as e:  # noqa: BLE001 — a malformed recipe is a rejected proposal
            a.status = "rejected"
            a.gate = {"passed": False, "note": f"malformed recipe: {e}"[:300]}
            return a
        problems = recipe.check()
        if problems:
            a.status = "rejected"
            a.gate = {"passed": False, "note": "; ".join(problems)}
            return a
        brand = self._brand(domain, d.name)
        transport = self.transport_factory(TransportLevel.T1)
        meter = Meter(prices=self.prices)
        meter.track(transport)
        try:
            neighbour_brands = [
                self._brand(n.domain, n.name) for n in self._neighbours(d) if not _reads(n)
            ][:3]
            result = prove(
                recipe,
                brand,
                transport,
                pages=pages,
                neighbour_brands=neighbour_brands,
                transport_factory=lambda: meter.track(self.transport_factory(TransportLevel.T1)),
            )
        finally:
            closer = getattr(transport, "close", None)
            if callable(closer):
                closer()
            self._charge(domain, "discretionary", meter)
        a.gate = result.as_dict()
        if not result.passed:
            a.status = "rejected"
            self.dossiers.event(
                domain,
                "gate",
                f"proposal {a.id} failed the gate",
                **{"steps": [s.get("step") for s in result.steps]},
            )
            return a
        # land: file the recipe, write the plan, record the lane, the brand is due
        recipe.brands = [domain]
        self._save_recipe(recipe)
        plan = recipe_plan(domain, recipe, TransportLevel.T1)
        self.catalog.save_plan(plan)
        self.catalog.set_brand_state(domain, "scoped")
        self.dossiers.lane(
            domain,
            plan.composition,
            result.verdict,
            result.products,
            result.fill,
            "landed by the gate",
        )
        self.baseline.record(domain, result.verdict, result.fill, plan.composition)
        self.dossiers.rule(
            domain,
            RuleApplied(
                id=recipe.id,
                signature=recipe.signature,
                kind="recipe",
                description=recipe.description,
                at=now_iso(),
                status="provisional",
            ),
        )
        self._append_learning(domain, a)
        try:
            self.scheduler.run_now(domain)
        except Exception:  # noqa: BLE001 — the plan is written; the schedule catches up
            pass
        a.status = "landed"
        return a

    def _file_code(self, domain: str, a: Analysis, code: dict) -> Analysis:
        """The model's code proposal: onto a branch when the worker can push, else filed
        under learn/proposals/ for `cli learn apply`."""
        files = code.get("files") or []
        test = code.get("test")
        record = {
            "id": a.id,
            "domain": domain,
            "summary": code.get("summary"),
            "files": files,
            "test": test,
            "at": now_iso(),
            "branch": None,
        }
        if GIT_PUSH_URL:
            branch = f"learn/{re.sub(r'[^a-z0-9]+', '-', domain)}-{a.id}"
            try:
                _push_branch(
                    branch,
                    files + ([test] if test else []),
                    f"learn({domain}): {code.get('summary') or a.id}",
                )
                record["branch"] = branch
                a.status = "branched"
            except Exception as e:  # noqa: BLE001
                record["push_error"] = f"{type(e).__name__}: {e}"[:300]
                a.status = "proposed"
        self.store.put(f"{PROPOSALS}{a.id}.json", dumps(record))
        a.gate = {
            "passed": None,
            "note": "code: not run by the gate; "
            + ("on a branch" if record["branch"] else "filed for a person"),
        }
        return a

    def apply_code(self, proposal_id: str, root: Path) -> list[str]:
        """Write a filed code proposal into a working tree. Returns the paths written."""
        found = self.store.get(f"{PROPOSALS}{proposal_id}.json")
        if not found:
            raise KeyError(proposal_id)
        record = loads(found[0])
        written = []
        for f in (record.get("files") or []) + ([record["test"]] if record.get("test") else []):
            path = root / f["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f["content"])
            written.append(str(path))
        return written

    def proposals(self) -> list[dict]:
        keys = sorted(self.store.list(PROPOSALS), reverse=True)
        out = []
        for k in keys[:50]:
            got = self.store.get(k)
            if got:
                row = loads(got[0])
                row["files"] = [
                    {"path": f["path"], "bytes": len(f.get("content") or "")}
                    for f in row.get("files") or []
                ]
                out.append(row)
        return out

    def _append_learning(self, domain: str, a: Analysis) -> None:
        text = (a.proposal or {}).get("learning")
        if not text:
            return
        key = "learn/learnings.jsonl"
        found = self.store.get(key)
        body = found[0].decode() if found else ""
        body += (
            json.dumps({"at": now_iso(), "domain": domain, "analysis": a.id, "text": text}) + "\n"
        )
        self.store.put(key, body.encode())

    # --- recipes on file ----------------------------------------------------------------------

    def _recipes(self) -> list[LaneRecipe]:
        out = []
        for k in self.store.list(RECIPES):
            got = self.store.get(k)
            if got:
                try:
                    out.append(LaneRecipe(**loads(got[0])))
                except Exception:  # noqa: BLE001
                    continue
        return out

    def _save_recipe(self, recipe: LaneRecipe) -> None:
        self.store.put(f"{RECIPES}{recipe.id}.json", dumps(recipe.model_dump()))

    def _recipe_for(self, signature: str) -> LaneRecipe | None:
        """A landed recipe for this exact signature, confirmed before provisional."""
        matches = [r for r in self._recipes() if r.signature == signature and r.status != "retired"]
        matches.sort(key=lambda r: (r.status != "confirmed", -len(r.brands)))
        return matches[0] if matches else None

    # --- what the model is shown -----------------------------------------------------------------

    def _capture_pages(self, d: Dossier) -> dict[str, str]:
        """The homepage and one product-ish page, fetched over the best rung that answered,
        saved with the dossier so the gate can replay without the network."""
        pages: dict[str, str] = {}
        level = TransportLevel.T1
        for r in d.ladder:
            if r.outcome in ("ok", "ok_thin"):
                level = (
                    TransportLevel(r.level) if r.level in ("t0", "t1", "t1p") else TransportLevel.T1
                )
                break
        t = self.transport_factory(level)
        meter = Meter(prices=self.prices)
        meter.track(t)
        try:
            home = t.get(f"https://{d.domain}/")
            if home.status_code == 200:
                pages[f"https://{d.domain}/"] = home.text
                self.dossiers.save_page(d.domain, f"https://{d.domain}/", home.text, kind="home")
            product = _product_link(home.text if home.status_code == 200 else "", d.domain)
            if product:
                page = t.get(product)
                if page.status_code == 200:
                    pages[product] = page.text
                    self.dossiers.save_page(d.domain, product, page.text, kind="product")
            for path in ("/sitemap.xml", "/products.json?limit=1", "/robots.txt"):
                r = t.get(f"https://{d.domain}{path}")
                if r.status_code == 200 and len(r.text) < 200_000:
                    pages[f"https://{d.domain}{path}"] = r.text[:20_000]
        except Exception as e:  # noqa: BLE001
            self.log(f"{d.domain}: capturing pages: {type(e).__name__}: {e}")
        finally:
            closer = getattr(t, "close", None)
            if callable(closer):
                closer()
            self._charge(d.domain, "discretionary", meter)
        return pages

    def _neighbours(self, d: Dossier, n: int = 6) -> list[Dossier]:
        if not d.signature:
            return []
        me = Signature.parse(d.signature)
        others = [o for o in self.dossiers.load_all() if o.domain != d.domain and o.signature]
        others.sort(key=lambda o: -me.likeness(Signature.parse(o.signature or "")))
        return others[:n]

    def _analyses_this_week(self, d: Dossier) -> int:
        cutoff = self._clock().timestamp() - 7 * 86_400
        return sum(1 for a in d.analyses if _aware(a.at).timestamp() >= cutoff)

    # --- money ------------------------------------------------------------------------------------

    def _charge(self, domain: str, pool: str, meter: Meter) -> None:
        snap = meter.snapshot()
        try:
            self.dossiers.meter_add(domain, today(), snap)
            if snap.get("usd"):
                self.budget.charge(domain, pool, snap["usd"])
        except Exception as e:  # noqa: BLE001 — the meter must never fail the work
            self.log(f"{domain}: meter: {type(e).__name__}: {e}")

    def _predict(self, domain: str, d: Dossier | None = None) -> dict | None:
        d = d or self.dossiers.load(domain)
        if d is None:
            return None
        lane = d.best_lane()
        row = self.scheduler.row(domain) or {}
        measured = None
        recent = sorted(d.meter)[-14:]
        runs = sum(d.meter[k].runs for k in recent)
        if runs:
            measured = sum(d.meter[k].usd for k in recent) / runs
        p = predict(
            products=lane.products or 0 if lane else 0,
            composition=lane.composition if lane else None,
            cadence_seconds=row.get("cadence_seconds"),
            sweep_seconds=row.get("sweep_seconds"),
            prices=self.prices,
            measured_per_check_usd=measured,
        )
        self.dossiers.set_predicted(domain, p)
        return p

    def _median_cost_per_product(self, dossiers: list[Dossier]) -> dict[str, float]:
        by_sig: dict[str, list[float]] = {}
        for d in dossiers:
            per = (d.predicted or {}).get("per_product_usd")
            if d.signature and per:
                by_sig.setdefault(d.signature, []).append(float(per))
        out = {}
        for k, vals in by_sig.items():
            vals.sort()
            out[k] = vals[len(vals) // 2]
        return out

    # --- the map and the status ------------------------------------------------------------------

    def _write_map(self) -> dict:
        clusters: dict[str, dict] = {}
        recipes = self._recipes()
        for d in self.dossiers.load_all():
            key = d.signature or "unsigned"
            c = clusters.setdefault(
                key,
                {
                    "signature": key,
                    "brands": [],
                    "verdicts": {},
                    "walls": {},
                    "per_product_usd": [],
                    "rules": [],
                },
            )
            lane = d.best_lane()
            verdict = lane.verdict if lane else "none"
            c["brands"].append(
                {
                    "domain": d.domain,
                    "name": d.name,
                    "verdict": verdict,
                    "wall": (d.wall or {}).get("type"),
                    "per_day_usd": (d.predicted or {}).get("per_day_usd"),
                }
            )
            c["verdicts"][verdict] = c["verdicts"].get(verdict, 0) + 1
            wall = (d.wall or {}).get("type") or "unknown"
            c["walls"][wall] = c["walls"].get(wall, 0) + 1
            per = (d.predicted or {}).get("per_product_usd")
            if per:
                c["per_product_usd"].append(float(per))
        for r in recipes:
            cluster = clusters.get(r.signature)
            if cluster is not None:
                cluster["rules"].append(
                    {
                        "id": r.id,
                        "description": r.description,
                        "status": r.status,
                        "brands": r.brands,
                    }
                )
        for c in clusters.values():
            vals = sorted(c.pop("per_product_usd"))
            c["median_per_product_usd"] = vals[len(vals) // 2] if vals else None
            c["count"] = len(c["brands"])
        row = {"at": now_iso(), "clusters": sorted(clusters.values(), key=lambda c: -c["count"])}
        self.store.put(SIGNATURES, dumps(row))
        return row

    def _write_status(self, summary: dict) -> None:
        found = self.store.get(LEARNING)
        row: dict = loads(found[0]) if found else {}
        history = list(row.get("history") or [])[-30:]
        history.append(
            {k: v for k, v in summary.items() if k != "errors"}
            | {"errors": len(summary.get("errors") or [])}
        )
        row.update({"last": summary, "history": history, "at": now_iso()})
        try:
            self.store.put(LEARNING, dumps(row))
        except Conflict:
            pass

    def status(self) -> dict:
        found = self.store.get(LEARNING)
        return loads(found[0]) if found else {}


# --- helpers -------------------------------------------------------------------------------------


class _Ledger:
    """A transport-shaped stand-in so the meter can count a sweep's requests by level."""

    def __init__(self, level: str, requests: int):
        self.level = level
        self.ledger = [{"url": "", "status": 0, "bytes": 0} for _ in range(int(requests or 0))]


def _reads(d: Dossier) -> bool:
    lane = d.best_lane()
    return lane is not None and lane.verdict in ("full", "partial", "ok")


def recipe_plan(domain: str, recipe: LaneRecipe, transport: TransportLevel) -> ScrapePlan:
    return ScrapePlan(
        domain=domain,
        transport=transport
        if transport in (TransportLevel.T0, TransportLevel.T1, TransportLevel.T1P)
        else TransportLevel.T1,
        discovery=DiscoveryChannel.RECIPE,
        fetch=FetchChannel.RECIPES,
        change_signal=ChangeSignal.PER_ITEM,
        status="ready",
        fingerprinted_at=now_iso(),
        recipe=recipe.model_dump(),
        currency=recipe.fetch.currency,
    )


def gaps_from_fill(fill: dict[str, float]) -> dict[str, dict]:
    """What a blank in each field means, by the audit's classes. A guaranteed field
    (title, price, stock, images...) blank on every product is *unread*: the shop sells
    it, so a blank is ours to fix. An editorial, variant or tag field blank is *unsought*:
    the page may carry it and nothing has read the page for it yet — worth a look, not a
    wall. Derived fields, barcodes and grocery fields blank are *absent*: nobody chases
    them. The model's own reading, when asked, overrides this."""
    from backend.archive.audit import (
        A_GUARANTEED,
        B_EDITORIAL,
        C_VARIANT,
        F_TAXONOMY,
        H_TAGS,
    )
    from backend.archive.domain.product import E0005_FIELDS

    sought = set(B_EDITORIAL) | set(C_VARIANT) | set(H_TAGS) | {F_TAXONOMY[0]}
    out = {}
    for f in E0005_FIELDS:
        v = fill.get(f)
        if v:
            out[f] = {"state": "read", "why": f"{v:.0%} of the sample"}
        elif f in A_GUARANTEED:
            out[f] = {
                "state": "unread",
                "why": "blank on every sampled product — guaranteed by the sale, so ours",
            }
        elif f in sought:
            out[f] = {"state": "unsought", "why": "blank; the page has not been read for it"}
        else:
            out[f] = {"state": "absent", "why": "derived, a code, or not apparel — not chased"}
    return out


_PRODUCT_HREF = re.compile(
    r'href="((?:https?://[^"/]+)?/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:products?|shop|item|p)/[^"#?]+)"',
    re.I,
)


def _product_link(html: str, domain: str) -> str | None:
    m = _PRODUCT_HREF.search(html or "")
    if not m:
        return None
    link = m.group(1)
    return link if link.startswith("http") else f"https://{domain}{link}"


def _aware(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _push_branch(branch: str, files: list[dict], message: str) -> None:
    """Write the files on a fresh branch of a shallow clone and push it."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "clone", "--depth", "1", GIT_PUSH_URL, tmp], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", tmp, "checkout", "-b", branch], check=True, capture_output=True
        )
        for f in files:
            path = Path(tmp) / f["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f["content"])
            subprocess.run(["git", "-C", tmp, "add", f["path"]], check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-C",
                tmp,
                "-c",
                "user.name=archive-learn",
                "-c",
                "user.email=learn@archive",
                "commit",
                "-m",
                message,
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", tmp, "push", "-u", "origin", branch], check=True, capture_output=True
        )
