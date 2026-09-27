"""No proposal lands without proof.

Three proofs, in order, each cheaper than the next and each recorded whether it passed:

    replay      the recipe over the pages captured for the analysis, no network — the
                hermetic test every landed rule carries
    live        the recipe on the brand that taught it: products found, a sample read,
                the core fields filled
    neighbours  the recipe on every other brand of the same signature that is not
                already reading — it must read there too, or the signature is finer
                than the rule, and the rule is provisional at best

And a baseline: the last known verdict and core fill per brand. A change that drops a
brand's verdict or its core fill is a regression, whatever else it improved. The gate
is what makes "let the model land its own rules" safe: a wrong proposal fails here
rather than reaching the fleet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.archive.capability import CORE_FIELDS, classify
from backend.archive.connectors.base import ChannelBlocked, SkipProduct
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRef
from backend.archive.learn.recipes import LaneRecipe, RecipeConnector
from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads
from backend.archive.verify import field_fill_rates

BASELINE = "control/baseline.json"
SAMPLE = 5
# The core fill a proof must reach on a sample, and the drop a baseline compare tolerates.
CORE_MIN = 0.8
DROP_TOLERANCE = 0.05


@dataclass
class GateResult:
    passed: bool
    steps: list[dict] = field(default_factory=list)
    products: int = 0
    verdict: str = "untested"
    fill: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "steps": self.steps,
            "products": self.products,
            "verdict": self.verdict,
            "fill": self.fill,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


class _Canned:
    """A transport that answers from captured pages and nothing else."""

    level = "t0"

    def __init__(self, pages: dict[str, str]):
        self._pages = pages
        self.ledger: list[dict] = []

    def get(self, url: str):
        body = self._pages.get(url)
        self.ledger.append(
            {"url": url, "status": 200 if body is not None else 404, "bytes": len(body or "")}
        )
        return _Resp(url, 200 if body is not None else 404, body or "")


class _Resp:
    def __init__(self, url: str, status: int, text: str):
        self.url, self.status_code, self.text = url, status, text
        self.headers: dict = {}

    @property
    def content(self) -> bytes:
        return self.text.encode()

    def json(self):
        import json

        return json.loads(self.text)


def sample_read(
    recipe: LaneRecipe, brand: Brand, transport, sample: int = SAMPLE
) -> tuple[int, list, list[str]]:
    """Discover, then read a spread of `sample` products. (found, records, errors)."""
    connector = RecipeConnector(recipe, limit=None)
    refs = connector.discover(brand, transport)
    picked = _spread(refs, sample)
    records, errors = [], []
    for ref in picked:
        try:
            records.append(connector.fetch(ref, transport))
        except SkipProduct as e:
            errors.append(str(e)[:120])
        except Exception as e:  # noqa: BLE001 — the failure is the finding
            errors.append(f"{type(e).__name__}: {e}"[:120])
    return len(refs), records, errors


def _spread(refs: list[ProductRef], n: int) -> list[ProductRef]:
    if len(refs) <= n:
        return list(refs)
    step = len(refs) / n
    return [refs[int(i * step)] for i in range(n)]


def core_fill(records) -> float:
    fill = field_fill_rates(records)
    return min(fill.get(f, 0.0) for f in CORE_FIELDS) if fill else 0.0


def replay(recipe: LaneRecipe, brand: Brand, pages: dict[str, str]) -> dict:
    """The hermetic proof: the recipe over captured pages."""
    if not pages:
        return {"step": "replay", "passed": None, "note": "no pages captured; nothing to replay"}
    try:
        found, records, errors = sample_read(recipe, brand, _Canned(pages), sample=SAMPLE)
    except ChannelBlocked as e:
        # Discovery asked for a page nobody captured (a sitemap, a feed): the canned
        # transport cannot answer, which proves nothing either way.
        return {
            "step": "replay",
            "passed": None,
            "note": f"discovery needs a page that was not captured: {e}"[:200],
        }
    except Exception as e:  # noqa: BLE001
        return {"step": "replay", "passed": False, "note": f"{type(e).__name__}: {e}"[:200]}
    if not records:
        # Discovery may replay from a captured sitemap while no product page was
        # captured: nothing read is nothing proved, not a failure.
        return {
            "step": "replay",
            "passed": None,
            "found": found,
            "read": 0,
            "note": "no captured page read as a product",
            "errors": errors[:3],
        }
    ok = core_fill(records) >= CORE_MIN
    return {
        "step": "replay",
        "passed": ok,
        "found": found,
        "read": len(records),
        "core_fill": round(core_fill(records), 2) if records else 0.0,
        "errors": errors[:3],
    }


def live(recipe: LaneRecipe, brand: Brand, transport, sample: int = SAMPLE) -> dict:
    """The recipe on the brand itself, over the network."""
    try:
        found, records, errors = sample_read(recipe, brand, transport, sample=sample)
    except Exception as e:  # noqa: BLE001
        return {"step": "live", "passed": False, "note": f"{type(e).__name__}: {e}"[:200]}
    fill = {k: round(v, 2) for k, v in field_fill_rates(records).items()} if records else {}
    verdict = classify(fill) if records else "blocked"
    ok = found > 0 and bool(records) and core_fill(records) >= CORE_MIN
    return {
        "step": "live",
        "passed": ok,
        "found": found,
        "read": len(records),
        "verdict": verdict,
        "core_fill": round(core_fill(records), 2) if records else 0.0,
        "fill": fill,
        "errors": errors[:3],
    }


def neighbours(recipe: LaneRecipe, brands: list[Brand], transport_factory, sample: int = 3) -> dict:
    """The recipe on the other brands of its signature. Every one must read."""
    rows = []
    for b in brands:
        t = transport_factory()
        try:
            found, records, errors = sample_read(recipe, b, t, sample=sample)
            rows.append(
                {
                    "domain": b.domain,
                    "found": found,
                    "read": len(records),
                    "core_fill": round(core_fill(records), 2) if records else 0.0,
                    "passed": found > 0 and bool(records) and core_fill(records) >= CORE_MIN,
                }
            )
        except Exception as e:  # noqa: BLE001
            rows.append(
                {"domain": b.domain, "passed": False, "note": f"{type(e).__name__}: {e}"[:160]}
            )
        finally:
            closer = getattr(t, "close", None)
            if callable(closer):
                closer()
    return {
        "step": "neighbours",
        "passed": all(r.get("passed") for r in rows) if rows else None,
        "brands": rows,
    }


def prove(
    recipe: LaneRecipe,
    brand: Brand,
    transport,
    pages: dict[str, str] | None = None,
    neighbour_brands: list[Brand] | None = None,
    transport_factory=None,
) -> GateResult:
    """All three proofs, stopping at the first that fails."""
    steps = [replay(recipe, brand, pages or {})]
    if steps[-1]["passed"] is False:
        return GateResult(False, steps)
    steps.append(live(recipe, brand, transport))
    if not steps[-1]["passed"]:
        return GateResult(False, steps, verdict=steps[-1].get("verdict", "blocked"))
    live_step = steps[-1]
    if neighbour_brands and transport_factory is not None:
        steps.append(neighbours(recipe, neighbour_brands, transport_factory))
        if steps[-1]["passed"] is False:
            return GateResult(
                False,
                steps,
                products=live_step["found"],
                verdict=live_step["verdict"],
                fill=live_step["fill"],
            )
    return GateResult(
        True,
        steps,
        products=live_step["found"],
        verdict=live_step["verdict"],
        fill=live_step["fill"],
    )


# --- the baseline ------------------------------------------------------------------------


class Baseline:
    """The last known verdict and core fill per brand; what a change is compared to."""

    def __init__(self, store: ObjectStore):
        self._store = store

    def _read(self) -> tuple[dict, str | None]:
        found = self._store.get(BASELINE)
        return (loads(found[0]), found[1]) if found else ({}, None)

    def all(self) -> dict:
        return self._read()[0].get("brands", {})

    def get(self, domain: str) -> dict | None:
        return self.all().get(domain)

    def record(
        self, domain: str, verdict: str, fill: dict[str, float], composition: str | None
    ) -> None:
        core = min((fill.get(f, 0.0) for f in CORE_FIELDS), default=0.0) if fill else 0.0
        for _ in range(5):
            row, etag = self._read()
            brands = row.setdefault("brands", {})
            brands[domain] = {
                "verdict": verdict,
                "core_fill": round(core, 3),
                "composition": composition,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            try:
                self._store.put(BASELINE, dumps(row), if_match=etag)
                return
            except Conflict:
                continue

    def regressed(self, domain: str, verdict: str, fill: dict[str, float]) -> str | None:
        """Why this reading is worse than the baseline, or None when it is not."""
        base = self.get(domain)
        if not base:
            return None
        order = {"full": 3, "partial": 2, "poor": 1}
        was, now = order.get(base.get("verdict", ""), 0), order.get(verdict, 0)
        if was and now < was:
            return f"verdict {base.get('verdict')} → {verdict}"
        core = min((fill.get(f, 0.0) for f in CORE_FIELDS), default=0.0) if fill else 0.0
        if core + DROP_TOLERANCE < float(base.get("core_fill") or 0.0):
            return f"core fill {base.get('core_fill')} → {round(core, 2)}"
        return None
