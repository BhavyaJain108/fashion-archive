"""What stands between us and the products, and what to do about it.

One word for the wall and one for the next action, decided from the dossier — the rung
outcomes, the last lane's verdict, the field gaps, what the brand costs against what it
should — and never from a brand's name. The mechanical actions the loop takes on its
own; `analyse` is the one place a rule cannot be written by a rule, and goes to the
model.

The order below is the order of certainty: a password is a fact; "unreadable" is the
absence of one, and the least certain word here, which is why it is the one that asks
for a look.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.archive.learn.dossier import Dossier

# What a brand may cost per correct product, against its signature's median, before it
# is worth asking for a cheaper way in.
EXPENSIVE_FACTOR = 3.0
# How many times the loop tries a wall's action before it stops and asks the model.
PATIENCE = 3


class Wall(str, Enum):
    OPEN = "open"  # reads, all core fields
    FIELD_GAP = "field_gap"  # reads, something a shop publishes is not read
    BUSY = "busy"  # the host asked for a moment
    RATE_LIMITED = "rate_limited"  # 429s at the walk's pace
    TLS = "tls"  # refuses Python's handshake
    ADDRESS = "address"  # refuses the address, whatever the handshake
    CHALLENGE = "challenge"  # a script must run first
    GEO = "geo"  # serves one country
    GATED = "gated"  # a password
    UNREADABLE = "unreadable"  # lets us in, nothing readable
    NOT_A_SHOP = "not_a_shop"
    EXPENSIVE = "expensive"  # reads, at a price out of line with its neighbours
    UNKNOWN = "unknown"  # never looked at


class Action(str, Enum):
    NONE = "none"
    ONBOARD = "onboard"
    PACE = "pace"
    CLIMB_T1 = "climb:t1"
    CLIMB_T1P = "climb:t1p"
    CLIMB_T2 = "climb:t2"
    ANALYSE = "analyse"
    CHEAPEN = "cheapen"
    WATCH = "watch"


@dataclass(frozen=True)
class Verdict:
    wall: Wall
    action: Action
    why: str


_REFUSALS = {"waf_403", "tls_blocked", "unreachable", "challenge", "rate_429"}


def classify(
    dossier: Dossier,
    median_cost_per_product: float | None = None,
    proxy_available: bool = False,
    browser_available: bool = True,
) -> Verdict:
    """Read the dossier together and commit to one wall and one action."""
    if dossier.notes and "not a shop" in dossier.notes.lower():
        return Verdict(Wall.NOT_A_SHOP, Action.NONE, dossier.notes)

    rungs = dossier.rung_outcomes()
    lane = dossier.best_lane()
    attempts = int((dossier.wall or {}).get("attempts") or 0)

    if not rungs and not lane:
        return Verdict(Wall.UNKNOWN, Action.ONBOARD, "never probed")

    if "gated" in rungs.values():
        return Verdict(Wall.GATED, Action.WATCH, "a password; no transport opens one")

    if not lane and any(o == "ok" for o in rungs.values()):
        level = next(k for k, o in rungs.items() if o == "ok")
        return Verdict(Wall.OPEN, Action.ONBOARD, f"readable over {level}; not yet read")

    if lane and lane.verdict in ("full", "ok"):
        # A run can pass the gate and still leave a guaranteed field blank on part of
        # the catalogue (Marni: price and photographs missing on 16 of 695), or leave
        # blank a field its neighbours all read (gaps marked unread by the tick). That
        # is not open; it is the next thing to fix.
        gap = _unread_gap(dossier)
        if gap:
            return Verdict(
                Wall.FIELD_GAP,
                Action.ANALYSE,
                f"{gap}: {(dossier.gaps.get(gap) or {}).get('why') or 'published and not read'}",
            )
        return _priced(dossier, lane, median_cost_per_product)
    if lane and lane.verdict == "partial":
        gap = _unread_gap(dossier)
        if gap:
            return Verdict(Wall.FIELD_GAP, Action.ANALYSE, f"{gap} is published and not read")
        return _priced(
            dossier,
            lane,
            median_cost_per_product,
            default_why="reads; the rest is not on the page or not yet read from it",
        )
    if lane and lane.verdict == "busy":
        return Verdict(Wall.BUSY, Action.PACE, lane.note or "the host asked for a moment")
    if lane and lane.verdict == "poor":
        return Verdict(Wall.FIELD_GAP, Action.ANALYSE, "reads, but a core field is blank")

    # No lane reads. What did the rungs say?
    t0, t1, t1p, t2 = rungs.get("t0"), rungs.get("t1"), rungs.get("t1p"), rungs.get("t2")
    http = [o for o in (t0, t1, t1p) if o]
    if any(o == "ok_thin" for o in (t0, t1, t1p, t2)):
        if attempts >= PATIENCE:
            return Verdict(
                Wall.UNREADABLE,
                Action.ANALYSE,
                "let in, nothing readable; the mechanical rungs are spent",
            )
        return Verdict(Wall.UNREADABLE, Action.ANALYSE, "let in, nothing readable")
    if t0 == "rate_429" and not t1:
        return Verdict(Wall.RATE_LIMITED, Action.PACE, "429 at plain HTTP; try again slower")
    if t0 in ("tls_blocked", "waf_403", "unreachable") and not t1:
        return Verdict(Wall.TLS, Action.CLIMB_T1, f"{t0} at plain HTTP; a browser's handshake next")
    if t1 in ("waf_403", "unreachable", "tls_blocked") and not t1p:
        if proxy_available:
            return Verdict(
                Wall.ADDRESS,
                Action.CLIMB_T1P,
                f"{t1} with a browser's handshake; the address is judged — another address next",
            )
        return Verdict(
            Wall.ADDRESS,
            Action.WATCH,
            f"{t1} with a browser's handshake; needs an egress proxy (ARCHIVE_PROXY_URL)",
        )
    if t1p in ("waf_403", "unreachable"):
        return Verdict(
            Wall.GEO if _looks_geo(dossier) else Wall.ADDRESS,
            Action.WATCH,
            "refused from another address too",
        )
    if any(o == "challenge" for o in http) and not t2:
        if browser_available:
            return Verdict(
                Wall.CHALLENGE, Action.CLIMB_T2, "a script must run first; a browser next"
            )
        return Verdict(
            Wall.CHALLENGE, Action.WATCH, "a script must run first; no browser on this worker"
        )
    if t2 in ("challenge", "waf_403"):
        return Verdict(Wall.CHALLENGE, Action.ANALYSE, "the browser did not clear the challenge")
    if http and all(o in _REFUSALS for o in http):
        return Verdict(Wall.ADDRESS, Action.WATCH, "refused at every rung tried")
    return Verdict(Wall.UNREADABLE, Action.ANALYSE, "no lane reads and the rungs do not say why")


def _priced(dossier: Dossier, lane, median: float | None, default_why: str = "reads") -> Verdict:
    per = _cost_per_product(dossier)
    if median and per and per > EXPENSIVE_FACTOR * median:
        return Verdict(
            Wall.EXPENSIVE,
            Action.CHEAPEN,
            f"${per:.4f} per product against ${median:.4f} for its neighbours",
        )
    return Verdict(Wall.OPEN, Action.NONE, default_why)


def _cost_per_product(dossier: Dossier) -> float | None:
    lane = dossier.best_lane()
    if not lane or not lane.products:
        return None
    predicted = dossier.predicted or {}
    per = predicted.get("per_product_usd")
    return float(per) if per is not None else None


def _unread_gap(dossier: Dossier) -> str | None:
    for field, g in dossier.gaps.items():
        if g.get("state") == "unread":
            return field
    return None


def _looks_geo(dossier: Dossier) -> bool:
    for r in dossier.ladder:
        if "geo" in (r.note or "").lower() or "restricted" in (r.note or "").lower():
            return True
    return False
