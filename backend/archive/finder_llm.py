"""Learn rules for fields the free channels missed — one LLM call per brand (S4).

The model only *proposes*. Every proposal is replayed against the same page and thrown
away unless it reproduces the value the model predicted (finder.verify_recipe). So a
wrong guess costs nothing but a discarded rule.

The call uses forced tool use, so the model returns a validated object rather than prose
we have to dig JSON out of. Cost shape: one call per brand, made once during calibration.
psylos1 has 7,339 products and theoutnet 80,048 — one call covers all of them.
"""

import os
import pathlib
import re
from datetime import datetime, timezone
from typing import Any, cast

from backend.archive.domain.recipe import RECIPE_KINDS, Recipe, RecipeBook
from backend.archive.finder import apply_recipes, is_plausible, verify_recipe

MODEL = os.getenv("FINDER_MODEL", "claude-sonnet-5")
_MAX_HTML = 220000  # chars of stripped page sent to the model (~55k tokens)
# Cutting the page too short makes the model guess values it cannot see, and a wrong
# prediction kills an otherwise correct rule at verification (live: psylos1 2026-08-30,
# where the size buttons sat past a 60k cut).

# The shape the model must return. Enforced by the API, not by parsing.
RECIPE_TOOL = {
    "name": "report_extraction_rules",
    "description": "Report one extraction rule per field you located on the page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "recipes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "description": "the missing field this rule fills",
                        },
                        "kind": {"type": "string", "enum": list(RECIPE_KINDS)},
                        "expression": {
                            "type": "string",
                            "description": "CSS selector, regex with one group, or dotted JSON-LD path",
                        },
                        "attribute": {
                            "type": ["string", "null"],
                            "description": "attribute name, for css_attr / css_all_attr only",
                        },
                        "expected": {
                            "type": "string",
                            "description": "exactly what this rule produces on THIS page; it is replayed and the rule is dropped if it does not match",
                        },
                    },
                    "required": ["field", "kind", "expression", "expected"],
                },
            }
        },
        "required": ["recipes"],
    },
}

_PROMPT = """Here is one product page from an online shop. These fields could not be read
from its structured data:

MISSING FIELDS: {fields}

For each one, find where the value lives in this HTML and report a rule that extracts it.

Guidance:
- Prefer a CSS selector over a regex.
- Prefer a PARTIAL class match over a full class name. Build tools generate hashed classes
  like "desktop-module__dEfP7G__sizeBtn" that change on every deploy, so
  [class*="sizeBtn"] survives where the full name does not.
- size_info: return the size LABELS in the order shown, e.g. "EU 39, EU 40, EU 41".
  Use css_all_text or css_all_attr so every size is captured, not just the first.
- size_availability: one entry PER SIZE, in the same order as size_info, so the two lists
  line up. A page rarely writes this as text — it is usually an attribute on the same
  elements the sizes come from: disabled, aria-disabled, data-available, or a class such
  as [class*="soldOut"]. Use css_all_attr on those elements. A single "Sold out" badge
  for the whole product is NOT this field; omit it instead.
- main_image_url / all_images: the product's own gallery images, as URLs. A page also
  carries images of OTHER products (related items, recently viewed) and site furniture
  (logos, payment icons) — a rule that sweeps those in is wrong. Target the gallery
  container and use css_all_attr on src, srcset or data-src.
- Never return the heading that labels a field ("Fabrics & Materials", "Select size") —
  find the value underneath it.
- Never return the product title or its description for anything except description.
- "expected" must be exactly what your rule produces on THIS page. It is replayed and the
  rule is discarded when it does not match, so do not guess.
- When a css_all_text or css_all_attr rule collects a long list — a gallery of image URLs,
  say — you may give just the FIRST one or two entries in "expected", in order, comma
  separated. The replay accepts a value that begins with what you wrote. Report the rule;
  do not omit the field because writing out every entry would be unwieldy.
- Omit any field that genuinely is not on this page. An omitted field is fine. A wrong
  rule is not.

PAGE URL: {url}

HTML:
{html}
"""


def learn_recipes(
    html: str, url: str, domain: str, missing_fields: list[str], client=None, spend=None
) -> RecipeBook:
    """One call. Returns only the rules that survived replay against this page."""
    now = datetime.now(timezone.utc).isoformat()
    if not missing_fields:
        return RecipeBook(domain=domain, learned_at=now, learned_from_url=url)

    client = client or _default_client(spend)
    prompt = _PROMPT.format(
        fields=", ".join(missing_fields), url=url, html=_strip(html)[:_MAX_HTML]
    )
    proposed = _to_recipes(client.propose(prompt))

    kept = [
        r
        for r in proposed
        if r.field in missing_fields
        and verify_recipe(r, html)
        and is_plausible(r.field, apply_recipes(html, [r]).get(r.field, ""))
    ]
    return RecipeBook(domain=domain, learned_at=now, learned_from_url=url, recipes=kept)


def _to_recipes(payload) -> list[Recipe]:
    """Tolerate anything: the API guarantees the schema, but a fake or a failure may not."""
    if not isinstance(payload, dict):
        return []
    out = []
    for item in payload.get("recipes") or []:
        if not isinstance(item, dict) or item.get("kind") not in RECIPE_KINDS:
            continue
        try:
            out.append(Recipe(**item))
        except Exception:
            continue
    return out


_DROP = re.compile(r"<(script|style|svg|noscript)\b.*?</\1>", re.S | re.I)


def _strip(html: str) -> str:
    """Drop scripts/styles, but keep JSON-LD — it is a legal place for a rule to point."""
    keep = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>.*?</script>', html, re.S | re.I
    )
    return _DROP.sub(" ", html) + "\n".join(keep[:3])


def _env_value(*names: str) -> str | None:
    """Environment first, then config/.env — parsed here so the package stays standalone."""
    for n in names:
        if os.getenv(n):
            return os.getenv(n)
    env_file = pathlib.Path(__file__).resolve().parents[2] / "config" / ".env"
    if not env_file.exists():
        return None
    found = None
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        if "=" not in line:
            if line.startswith("sk-ant-") and "CLAUDE_API_KEY" in names:
                found = line
            continue
        name, _, value = line.partition("=")
        if name.strip() in names:
            found = value.strip().strip("\"'") or found  # last assignment wins, as in a shell
    return found


def _workspace_id() -> str | None:
    """Identity-linked keys must say which workspace the request acts in."""
    return _env_value("ANTHROPIC_WORKSPACE_ID", "CLAUDE_WORKSPACE_ID")


def _api_key() -> str | None:
    return _env_value("CLAUDE_API_KEY", "ANTHROPIC_API_KEY")


class _AnthropicClient:
    """Forced tool use: the model must answer in the schema, so there is no parsing step."""

    def __init__(self, model: str = MODEL, spend=None):
        import anthropic

        key = _api_key()
        if not key:
            raise RuntimeError("No API key. Put CLAUDE_API_KEY=... in config/.env or export it.")
        workspace = _workspace_id()
        headers = {"anthropic-workspace-id": workspace} if workspace else None
        self._c = anthropic.Anthropic(api_key=key, default_headers=headers)
        self._model = model
        # What this call cost, as the API reports it rather than as we guess it.
        self._spend = spend

    def propose(self, prompt: str) -> dict:
        # The tool and the forced choice are plain dicts by design — the schema above is
        # the readable statement of what the model must answer — so they are handed to
        # the SDK's typed overloads as-is.
        msg = self._c.messages.create(
            model=self._model,
            max_tokens=2000,
            tools=cast(Any, [RECIPE_TOOL]),
            tool_choice=cast(Any, {"type": "tool", "name": RECIPE_TOOL["name"]}),
            messages=[{"role": "user", "content": prompt}],
        )
        usage = getattr(msg, "usage", None)
        if self._spend is not None and usage is not None:
            self._spend.add(
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
            )
        for block in msg.content:
            if getattr(block, "type", "") == "tool_use":
                return block.input
        return {}


def _default_client(spend=None):
    return _AnthropicClient(spend=spend)
