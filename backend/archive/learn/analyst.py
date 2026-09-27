"""The model, at the three places a rule cannot be written by a rule.

    brand          a shop the mechanical rungs got into and found nothing readable in:
                   what kind of site is it, where are the products, how is one read
    failure        a brand that read and stopped, or reads worse than it did: what changed
    consolidation  several provisional rules on brands of one shape: the one rule

Every call gets the same discipline the finder has: forced tool use, so the answer is a
validated object and never prose; a proposal, never a landing — the gate decides; and
the cost taken from the API's own usage. The bundle the model reads is the brand's own
pages (trimmed the way the finder trims them), the dossier's ladder and signature, the
dossiers of the nearest shops by signature, and the catalogue of rules that exist — so
it proposes the *narrowest* rule that explains what it sees, and reaches for a recipe
over code whenever a connector that exists can be told what to do.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, cast

from backend.archive.finder_llm import _api_key, _workspace_id, prepare_page
from backend.archive.learn.dossier import Analysis, Dossier
from backend.archive.learn.recipes import DISCOVER_KINDS, FETCH_KINDS, FIELDS
from backend.archive.learn.signature import DEFENCES, FEEDS, LOCALES, PAGES, PLATFORMS, SITEMAPS
from backend.archive.observe import Spend

MODEL = os.getenv("ANALYST_MODEL", "claude-opus-5")
# $ per million tokens for the analyst's model; the finder's rates are Sonnet's.
INPUT_RATE = float(os.getenv("ANALYST_INPUT_RATE", "5.0"))
OUTPUT_RATE = float(os.getenv("ANALYST_OUTPUT_RATE", "25.0"))
# What one analysis is expected to cost, for the budget check made before the call.
ESTIMATE_USD = 0.60
_PAGE_CAP = 60_000  # chars per page in the bundle; two pages and the rest fit well inside

_SIGNATURE_SCHEMA = {
    "type": "object",
    "properties": {
        "platform": {"type": "string", "enum": list(PLATFORMS)},
        "feed": {"type": "string", "enum": list(FEEDS)},
        "sitemap": {"type": "string", "enum": list(SITEMAPS)},
        "page": {"type": "string", "enum": list(PAGES)},
        "defence": {"type": "string", "enum": list(DEFENCES)},
        "locale": {"type": "string", "enum": list(LOCALES)},
    },
    "required": ["platform", "feed", "sitemap", "page", "defence", "locale"],
    "additionalProperties": False,
}

_RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "discover": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(DISCOVER_KINDS)},
                "url": {"type": ["string", "null"]},
                "items": {"type": ["string", "null"]},
                "url_template": {"type": ["string", "null"]},
                "prefix": {"type": ["string", "null"]},
                "page_param": {"type": ["string", "null"]},
                "link_pattern": {"type": ["string", "null"]},
            },
            "required": [
                "kind",
                "url",
                "items",
                "url_template",
                "prefix",
                "page_param",
                "link_pattern",
            ],
            "additionalProperties": False,
        },
        "fetch": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(FETCH_KINDS)},
                "url_template": {"type": ["string", "null"]},
                "root": {"type": ["string", "null"]},
                "fields": {
                    "type": "object",
                    "properties": {f: {"type": "string"} for f in FIELDS},
                    "additionalProperties": False,
                },
                "in_stock_when": {"type": ["string", "null"]},
                "currency": {"type": ["string", "null"]},
            },
            "required": ["kind", "url_template", "root", "fields", "in_stock_when", "currency"],
            "additionalProperties": False,
        },
    },
    "required": ["description", "discover", "fetch"],
    "additionalProperties": False,
}

PROPOSAL_TOOL = {
    "name": "report_analysis",
    "description": "Report what kind of shop this is, what stands in the way, and how to read it.",
    # Not strict: the schema's enums and nesting compile to a grammar the API refuses as
    # too large. The proposal is checked on our side instead — a recipe is parsed as a
    # LaneRecipe and a signature as a Signature before anything is written.
    "input_schema": {
        "type": "object",
        "properties": {
            "signature": _SIGNATURE_SCHEMA,
            "wall": {
                "type": "string",
                "enum": [
                    "open",
                    "field_gap",
                    "rate_limited",
                    "tls",
                    "address",
                    "challenge",
                    "geo",
                    "gated",
                    "unreadable",
                    "not_a_shop",
                    "expensive",
                ],
            },
            "reasoning": {
                "type": "string",
                "description": "what you saw, in a few sentences: the evidence, then the conclusion",
            },
            "confidence": {"type": "number"},
            "lane": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["recipe", "code", "none"]},
                    "recipe": {"anyOf": [_RECIPE_SCHEMA, {"type": "null"}]},
                    "code": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "summary": {"type": "string"},
                                    "files": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "path": {"type": "string"},
                                                "content": {"type": "string"},
                                            },
                                            "required": ["path", "content"],
                                            "additionalProperties": False,
                                        },
                                    },
                                    "test": {
                                        "type": "object",
                                        "properties": {
                                            "path": {"type": "string"},
                                            "content": {"type": "string"},
                                        },
                                        "required": ["path", "content"],
                                        "additionalProperties": False,
                                    },
                                },
                                "required": ["summary", "files", "test"],
                                "additionalProperties": False,
                            },
                            {"type": "null"},
                        ]
                    },
                    "why_not_cheaper": {
                        "type": "string",
                        "description": "why no cheaper rung or existing connector reads this shop",
                    },
                },
                "required": ["kind", "recipe", "code", "why_not_cheaper"],
                "additionalProperties": False,
            },
            "gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "state": {"type": "string", "enum": ["absent", "unread"]},
                        "why": {"type": "string"},
                    },
                    "required": ["field", "state", "why"],
                    "additionalProperties": False,
                },
            },
            "learning": {
                "type": "string",
                "description": "one paragraph for LEARNINGS.md: the brand, the date, the evidence, the rule — general, never a branch on a brand name",
            },
        },
        "required": ["signature", "wall", "reasoning", "confidence", "lane", "gaps", "learning"],
        "additionalProperties": False,
    },
}

_SYSTEM = """You are the analyst of a fashion-archive scraper. It reads product catalogues from
independent shops over a ladder of transports (plain HTTP; a browser's TLS handshake; the
same through an egress proxy; a real browser) and a set of lanes (a Shopify feed; per-product
JSON; a WooCommerce Store API; a sitemap plus JSON-LD on the page; a Gatsby site's page-data;
a lane recipe, which is discovery + fetch described as data and run by an existing connector).

Your job, given one shop the mechanical rungs could not read, is the same as the person who
built this system did by hand: look at the actual pages, say what kind of site it is, say
what stands between us and the products, and propose the NARROWEST way to read it that
explains what you see — a recipe wherever a connector that exists can be told what to do,
code only when no existing connector shape fits, "none" when the shop has nothing to read.

Rules you must keep:
- Never propose anything that branches on a brand's name. A rule is about a shape.
- Prefer the cheapest rung that works: a JSON endpoint over a page, a page over a browser.
- Report exactly what you saw. A field you cannot see is "absent" if the shop plainly does
  not publish it, "unread" if it is there and no rule reads it.
- A recipe's paths are dotted, [n] indexes, [*] fans out. Templates take {domain}, {url},
  {handle}, and any key of the item discovery found the product in.
- Placeholders (no price, no photograph, unavailable) are not products.
- Be concrete in "learning": the evidence and the rule, one paragraph, the way a lab
  notebook is written."""


class _Client:
    def __init__(self, model: str = MODEL, spend: Spend | None = None):
        import anthropic

        key = _api_key()
        if not key:
            raise RuntimeError("No API key. Put ANTHROPIC_API_KEY in the environment.")
        workspace = _workspace_id()
        headers = {"anthropic-workspace-id": workspace} if workspace else None
        self._c = anthropic.Anthropic(api_key=key, default_headers=headers)
        self._model = model
        self._spend = spend

    def propose(self, prompt: str) -> dict:
        msg = self._c.messages.create(
            model=self._model,
            max_tokens=16000,
            system=_SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            tools=cast(Any, [PROPOSAL_TOOL]),
            tool_choice=cast(Any, {"type": "tool", "name": PROPOSAL_TOOL["name"]}),
            messages=[{"role": "user", "content": prompt}],
        )
        usage = getattr(msg, "usage", None)
        if self._spend is not None and usage is not None:
            self._spend.add(
                getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0
            )
        for block in msg.content:
            if block.type == "tool_use":
                return cast(dict, block.input)
        return {}


def default_client(spend: Spend | None = None) -> _Client:
    return _Client(spend=spend)


# --- the bundle --------------------------------------------------------------------------


def bundle(
    kind: str,
    dossier: Dossier,
    pages: dict[str, str],
    neighbours: list[Dossier],
    rules: list[dict],
    extra: str = "",
) -> str:
    """What the model reads. Pages trimmed as the finder trims them; the rest as facts."""
    parts = [
        f"KIND OF QUESTION: {kind}",
        f"BRAND: {dossier.domain} ({dossier.name or dossier.domain})",
    ]
    if dossier.signature:
        parts.append(f"SIGNATURE SO FAR: {dossier.signature}")
    if dossier.wall:
        parts.append(f"WALL SO FAR: {dossier.wall.get('type')} — {dossier.wall.get('why')}")
    if dossier.ladder:
        parts.append(
            "LADDER (rung: outcome, statuses):\n"
            + "\n".join(
                f"  {r.level}: {r.outcome} {r.statuses[:8]} {r.note}".rstrip()
                for r in dossier.ladder[-8:]
            )
        )
    if dossier.lanes:
        parts.append(
            "LANES TRIED:\n"
            + "\n".join(
                f"  {lane.composition}: {lane.verdict}, {lane.products} products; fill {json.dumps(lane.fill)[:300]}"
                for lane in dossier.lanes[-6:]
            )
        )
    if dossier.gaps:
        parts.append("GAPS: " + json.dumps(dossier.gaps)[:1500])
    if dossier.analyses:
        last = dossier.analyses[-1]
        parts.append(f"LAST ANALYSIS ({last.status}): {last.reasoning[:600]}")
        if last.gate:
            parts.append("ITS GATE: " + json.dumps(last.gate)[:1200])
    if neighbours:
        parts.append(
            "NEAREST SHOPS BY SIGNATURE (what reads them):\n"
            + "\n".join(_neighbour_line(n) for n in neighbours[:6])
        )
    if rules:
        parts.append(
            "RULES THAT EXIST (signature → description):\n"
            + "\n".join(f"  {r.get('signature')}: {r.get('description')}" for r in rules[:20])
        )
    if extra:
        parts.append(extra)
    for url, html in list(pages.items())[:3]:
        parts.append(f"PAGE {url}\n{prepare_page(html, cap=_PAGE_CAP)}")
    parts.append(
        "Answer with report_analysis. Propose a recipe wherever one can express the lane; "
        "give every field path you can see in the data; say what is absent and what is unread."
    )
    return "\n\n".join(parts)


def _neighbour_line(n: Dossier) -> str:
    lane = n.best_lane()
    return (
        f"  {n.domain}: {n.signature}; lane {lane.composition if lane else '-'}"
        f" → {lane.verdict if lane else '-'}; wall {(n.wall or {}).get('type')}"
    )


def analyse(
    kind: str,
    dossier: Dossier,
    pages: dict[str, str],
    neighbours: list[Dossier],
    rules: list[dict],
    client=None,
    spend: Spend | None = None,
    extra: str = "",
) -> Analysis:
    """One call. Returns the proposal as an Analysis, status "proposed" — or "failed" with
    the reason, never an exception, so a bad answer is a fact in the dossier."""
    spend = spend or Spend(INPUT_RATE, OUTPUT_RATE)
    client = client or default_client(spend)
    prompt = bundle(kind, dossier, pages, neighbours, rules, extra)
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ident = f"{at[:10]}-{secrets.token_hex(3)}"
    try:
        answer = client.propose(prompt)
    except Exception as e:  # noqa: BLE001 — the failure is recorded, not raised
        return Analysis(
            id=ident,
            at=at,
            kind=kind,
            status="failed",
            reasoning=f"{type(e).__name__}: {e}"[:400],
            usd=spend.usd,
        )
    if not isinstance(answer, dict) or not answer.get("lane"):
        return Analysis(
            id=ident,
            at=at,
            kind=kind,
            status="failed",
            reasoning="the model returned no proposal",
            usd=spend.usd,
        )
    return Analysis(
        id=ident,
        at=at,
        kind=kind,
        status="proposed",
        reasoning=str(answer.get("reasoning") or "")[:2000],
        proposal={k: v for k, v in answer.items() if k != "reasoning"},
        usd=spend.usd,
    )
