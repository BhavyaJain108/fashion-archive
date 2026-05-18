"""
LLM-proposed cheap-method fallback.

After Discovery has enumerated all known structured sources (LD+JSON paths,
OG meta names, accordion-from-Phase-A) and identified which fields still
have no cheap reproducer, this module asks the LLM-vision pass:

  "For each of these uncovered fields, look at the rendered DOM and tell
   me a CSS selector that would extract the value the page actually shows."

The LLM has already extracted the ground-truth value in Phase C, so it
knows what should come out. It just needs to find the selector that
produces it.

Each proposed selector is then validated: run it against the live
PageMemo, check the output matches ground truth, add to catalog if so.

This is the 3rd LLM call in discovery (after Phase A hideaway ID +
Phase C extraction). Cost adds ~$0.02-$0.04 per brand.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .catalog import CatalogRow, MethodResult
from .ground_truth import _CLAUDE_MODEL, _claude_client, _extract_interactive_dom
from .memo import PageMemo
from .methods.accordion_read import AccordionReadMethod
from .methods.dom_selector import DomAttrMethod, DomSelectorMethod
from .schema import ProductFields


PROPOSE_TOOL = {
    "name": "propose_dom_methods",
    "description": (
        "For each requested E0005 field, return a CSS selector that extracts "
        "the field's value from the rendered DOM (or report that it isn't "
        "reachable via DOM)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "description": "The E0005 field name being addressed.",
                        },
                        "method_kind": {
                            "type": "string",
                            "enum": ["dom_selector", "dom_attr", "accordion_read", "none"],
                            "description": (
                                "dom_selector: read innerText from CSS-selected element(s). "
                                "dom_attr: read a specific attribute (e.g. data-value). "
                                "accordion_read: click trigger then read panel. "
                                "none: field can't be extracted via DOM (mark and move on)."
                            ),
                        },
                        "selector": {
                            "type": "string",
                            "description": (
                                "Playwright-compatible CSS selector. For dom_selector / dom_attr, "
                                "this is the target element. For accordion_read, this is the panel. "
                                "Required unless method_kind=none."
                            ),
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["first", "all_join"],
                            "description": "dom_selector mode. 'all_join' for multi-value fields like sizes.",
                        },
                        "separator": {
                            "type": "string",
                            "description": "Join separator when mode=all_join (e.g. ', ').",
                        },
                        "transform": {
                            "type": "string",
                            "enum": ["strip", "to_float", "to_int", "split_size_list"],
                            "description": "Optional value transform.",
                        },
                        "attr": {
                            "type": "string",
                            "description": "Attribute name when method_kind=dom_attr.",
                        },
                        "trigger_selector": {
                            "type": "string",
                            "description": "Click trigger when method_kind=accordion_read.",
                        },
                    },
                    "required": ["field", "method_kind"],
                },
            }
        },
        "required": ["proposals"],
    },
}


def _propose_prompt(
    fields_with_truth: Dict[str, Any],
    dom_excerpt: str,
) -> str:
    field_lines = []
    for f, v in fields_with_truth.items():
        sval = json.dumps(v) if not isinstance(v, str) else v
        if len(sval) > 200:
            sval = sval[:200] + "…"
        field_lines.append(f"- `{f}` = {sval}")
    fields_text = "\n".join(field_lines)

    return f"""For each of the following E0005 fields, the LLM ground-truth value is
already known (shown below). Your job: find a CSS selector + method that
extracts that same value from the rendered DOM, so we can reproduce the
extraction on future products without an LLM call.

Use the screenshot to spot WHERE the value is shown on the page, then
examine the DOM excerpt to find a stable selector for that element.

Selector quality criteria:
- Stable: prefer data-* attributes, semantic roles, button:has-text("Label")
  patterns over auto-generated class names like .c-xY3Z.
- Specific enough to only match the target element, not the wrong one.
- Compatible with Playwright's locator engine.

Method kinds:
- `dom_selector`: simple innerText read. Use `mode="all_join"` when the
  field has multiple parts (e.g. size_info needs all size buttons joined).
- `dom_attr`: read a specific attribute (when value is in `data-value` etc.).
- `accordion_read`: click a trigger then read its panel — used when content
  is hidden behind an accordion. Provide both `selector` (panel) and
  `trigger_selector` (the click target).
- `none`: declare this field is NOT reachable via the DOM (rare; only use
  for fields where the value is purely visual/computed, e.g. in_stock
  derived from button states).

Fields needing a method:
{fields_text}

DOM excerpt (interactive + structural elements):
{dom_excerpt[:12000]}

Return one proposal per field via the propose_dom_methods tool."""


async def propose_methods_for_uncovered_fields(
    memo: PageMemo,
    gt: ProductFields,
    uncovered_fields: List[str],
) -> Tuple[List[Tuple[str, Any]], Dict[str, Any]]:
    """Ask the LLM to propose DOM methods for fields no cheap method covered.

    Returns:
        (proposals, usage) where proposals is a list of (field_name,
        Method instance) and usage is the LLM token+cost dict.
    """
    if not uncovered_fields:
        return [], {"input_tokens": 0, "output_tokens": 0}

    # Build the {field: truth_value} payload for the prompt.
    fields_with_truth = {}
    for f in uncovered_fields:
        v = getattr(gt, f, None)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        fields_with_truth[f] = v
    if not fields_with_truth:
        return [], {"input_tokens": 0, "output_tokens": 0}

    screenshot = await memo.screenshot()
    rendered = await memo.rendered_html()
    dom_excerpt = _extract_interactive_dom(rendered)

    client = _claude_client()
    response = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=3000,
        tools=[PROPOSE_TOOL],
        tool_choice={"type": "tool", "name": "propose_dom_methods"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(screenshot).decode("utf-8"),
                }},
                {"type": "text", "text": _propose_prompt(fields_with_truth, dom_excerpt)},
            ],
        }],
    )
    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
    }

    proposals: List[Tuple[str, Any]] = []
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "propose_dom_methods":
            for p in block.input.get("proposals", []):
                method = _build_method(p)
                if method is not None:
                    proposals.append((p["field"], method))
            break
    return proposals, usage


def _build_method(proposal: Dict[str, Any]) -> Optional[Any]:
    """Build a concrete Method instance from one LLM proposal dict."""
    kind = proposal.get("method_kind")
    if kind == "none" or not kind:
        return None
    if kind == "dom_selector":
        sel = proposal.get("selector")
        if not sel:
            return None
        return DomSelectorMethod(
            selector=sel,
            mode=proposal.get("mode", "first"),
            transform=proposal.get("transform"),
            separator=proposal.get("separator", ", "),
        )
    if kind == "dom_attr":
        sel = proposal.get("selector")
        attr = proposal.get("attr")
        if not sel or not attr:
            return None
        return DomAttrMethod(selector=sel, attr=attr, transform=proposal.get("transform"))
    if kind == "accordion_read":
        panel = proposal.get("selector")
        trigger = proposal.get("trigger_selector")
        if not panel or not trigger:
            return None
        return AccordionReadMethod(trigger_selector=trigger, panel_selector=panel)
    return None
