"""
Discovery agent — one Claude conversation that fills the E0005 schema for
a brand by interacting with the page through tools.

The agent has five tools:

    look()                          refreshed view of the page state
    click(selector)                 click an element, see what got revealed
    read_dom(selector, attr, mode)  read text/attr from the live DOM
    read_source(kind, path)         read from ld_json | shopify_json | og_meta | url
    answer(field, value, steps)     emit one field's answer + the recipe

The agent loops until it has called `answer` for every required field, or
hits the turn budget. For each `answer`, `steps` is the deterministic
recipe — what production replays without any LLM, every time.

Output: Dict[field_name, FieldAnswer] in the same shape `ask_llm`
produced, so downstream (verify + SiteCatalog assembly) is unchanged.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from .field_specs import build_schema_section
from .memo import PageMemo
from .oneshot import FieldAnswer, MethodAttempt


# ---------------------------------------------------------------------------
# Pydantic models — agent step actions
# ---------------------------------------------------------------------------

class Step(BaseModel):
    """One deterministic action in a field's recipe.

    The agent emits these as part of `answer(field, value, steps)`. The
    verify pass translates each Step into a `Method` and runs it; only
    recipes whose replay reproduces `value` are cataloged.
    """
    action: str  # "read_source" | "read_dom" | "click"
    # read_source / url
    source: Optional[str] = None        # "ld_json" | "shopify_json" | "og_meta" | "url"
    path: Optional[str] = None
    # read_dom
    selector: Optional[str] = None
    attr: Optional[str] = None
    mode: Optional[str] = None          # "first" | "all_join"
    separator: Optional[str] = None
    transform: Optional[str] = None

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Tool schemas (passed to Claude)
# ---------------------------------------------------------------------------

_LOOK_TOOL = {
    "name": "look",
    "description": "Return a refreshed view of the current page: visible text, "
                   "key structured sources (LD+JSON, Shopify product.json if any, "
                   "meta tags). Use this whenever you want to re-orient.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_CLICK_TOOL = {
    "name": "click",
    "description": "Click an element on the live page. Returns what newly "
                   "appeared (text that wasn't visible before the click). Use "
                   "this to open accordions, dialogs, dropdowns. The click "
                   "happens against the rendered page — state persists across "
                   "calls.",
    "input_schema": {
        "type": "object",
        "properties": {"selector": {"type": "string",
                                    "description": "CSS selector for the element to click."}},
        "required": ["selector"],
    },
}

_READ_DOM_TOOL = {
    "name": "read_dom",
    "description": "Read text or an attribute from a CSS selector on the live DOM.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "attr": {"type": ["string", "null"],
                     "description": "If set, read this attribute. Otherwise read innerText."},
            "mode": {"type": "string", "enum": ["first", "all_join"],
                     "description": "first → first match. all_join → all matches joined."},
            "separator": {"type": ["string", "null"],
                          "description": "Join separator for mode=all_join. Default ', '."},
        },
        "required": ["selector"],
    },
}

_READ_SOURCE_TOOL = {
    "name": "read_source",
    "description": "Read from a structured source. Sources:\n"
                   "  ld_json:       path is JSONPath in the @type=Product blob (e.g. $.offers.price)\n"
                   "  shopify_json:  path is field_path syntax (e.g. product.variants[].option1:dedupe_join_comma)\n"
                   "  og_meta:       path is the meta name/property (e.g. og:title)\n"
                   "  url:           path is a Python regex with one capture group, applied to the page URL. "
                   "ONLY VALID for the product_code field — discarded for any other field.",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {"type": "string",
                       "enum": ["ld_json", "shopify_json", "og_meta", "url"]},
            "path": {"type": "string"},
        },
        "required": ["source", "path"],
    },
}

_ANSWER_TOOL = {
    "name": "answer",
    "description": "Emit your final answer for ONE field — value plus the "
                   "deterministic steps (recipe) to reproduce it. After all "
                   "fields you can answer have been emitted, call done().",
    "input_schema": {
        "type": "object",
        "properties": {
            "field": {"type": "string"},
            "value": {"description": "The value for this field, or null if not present."},
            "steps": {
                "type": "array",
                "description": "Ordered list of actions to reproduce `value`. "
                               "For a single read this is one Step; for a click+read "
                               "it's two Steps in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["read_source", "read_dom", "click"]},
                        "source": {"type": ["string", "null"]},
                        "path": {"type": ["string", "null"]},
                        "selector": {"type": ["string", "null"]},
                        "attr": {"type": ["string", "null"]},
                        "mode": {"type": ["string", "null"]},
                        "separator": {"type": ["string", "null"]},
                        "transform": {"type": ["string", "null"]},
                    },
                    "required": ["action"],
                },
            },
        },
        "required": ["field", "value", "steps"],
    },
}

_DONE_TOOL = {
    "name": "done",
    "description": "End discovery. Call once after every field you can answer has been emitted.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_ALL_TOOLS = [_LOOK_TOOL, _CLICK_TOOL, _READ_DOM_TOOL, _READ_SOURCE_TOOL, _ANSWER_TOOL, _DONE_TOOL]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_CAP_TEXT = 4000
_CAP_LD_JSON = 6000
_CAP_SHOPIFY = 6000


async def _tool_look(memo: PageMemo) -> Dict[str, Any]:
    page = memo._page
    visible = ""
    if page is not None:
        try:
            visible = await page.inner_text("body")
        except Exception:
            visible = await memo.visible_text()
    else:
        visible = await memo.visible_text()
    ld_blob = await memo.ld_json_product()
    meta = await memo.meta_tags()
    shopify_blob = None
    try:
        from .methods.shopify_json import ShopifyProductJsonMethod
        shopify_blob = await ShopifyProductJsonMethod._get_blob(memo)
    except Exception:
        pass
    return {
        "url": memo.url,
        "visible_text": visible[:_CAP_TEXT],
        "ld_json_product": (json.dumps(ld_blob)[:_CAP_LD_JSON] if ld_blob else None),
        "shopify_product_json": (json.dumps(shopify_blob)[:_CAP_SHOPIFY] if shopify_blob else None),
        "meta_tags": meta,
    }


async def _tool_click(memo: PageMemo, selector: str) -> Dict[str, Any]:
    """Click a selector. Return the text that newly appeared on the page.

    Snapshots body text pre- and post-click, returns the diff. No filtering
    by region/role/aria — wherever the new text appeared, return it.
    """
    page = memo._page
    if page is None:
        return {"ok": False, "error": "no page"}
    try:
        pre = await page.inner_text("body")
    except Exception:
        pre = ""
    pre_url = page.url
    try:
        loc = page.locator(selector).first
        if await loc.count() == 0:
            return {"ok": False, "error": "selector matches no element"}
        if not await loc.is_visible():
            return {"ok": False, "error": "element not visible"}
        await loc.click(timeout=2500)
    except Exception as e:
        return {"ok": False, "error": f"click failed: {type(e).__name__}: {e}"}
    await page.wait_for_timeout(250)
    try:
        await page.wait_for_load_state("networkidle", timeout=1500)
    except Exception:
        pass
    if page.url != pre_url:
        try:
            await page.go_back(timeout=4000, wait_until="domcontentloaded")
        except Exception:
            pass
        return {"ok": False, "error": f"click navigated to {page.url}, reverted"}
    try:
        post = await page.inner_text("body")
    except Exception:
        post = ""
    pre_lines = set(l.strip() for l in pre.split("\n") if l.strip())
    new = [l for l in post.split("\n") if l.strip() and l.strip() not in pre_lines]
    revealed = "\n".join(new)[:_CAP_TEXT]
    return {"ok": True, "revealed_text": revealed, "revealed_chars": len("\n".join(new))}


async def _tool_read_dom(memo: PageMemo, selector: str, attr: Optional[str] = None,
                         mode: str = "first", separator: Optional[str] = None) -> Dict[str, Any]:
    page = memo._page
    if page is None:
        return {"ok": False, "error": "no page"}
    sep = separator if separator is not None else ", "
    try:
        loc = page.locator(selector)
        n = await loc.count()
        if n == 0:
            return {"ok": True, "value": None, "match_count": 0}
        if mode == "all_join":
            values: List[str] = []
            for i in range(min(n, 40)):
                el = loc.nth(i)
                v = (await el.get_attribute(attr) if attr else await el.inner_text(timeout=1500))
                if v:
                    values.append(str(v).strip())
            return {"ok": True, "value": sep.join(values), "match_count": n}
        else:
            el = loc.first
            v = await el.get_attribute(attr) if attr else await el.inner_text(timeout=1500)
            return {"ok": True, "value": (v.strip() if isinstance(v, str) else v), "match_count": n}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _tool_read_source(memo: PageMemo, source: str, path: str) -> Dict[str, Any]:
    try:
        if source == "ld_json":
            from .methods.ld_json import LdJsonPathMethod
            m = LdJsonPathMethod(path)
            r = await m.produce(memo, "_probe_")
            return {"ok": True, "value": r.value}
        if source == "shopify_json":
            from .methods.shopify_json import ShopifyProductJsonMethod
            m = ShopifyProductJsonMethod(path)
            r = await m.produce(memo, "_probe_")
            return {"ok": True, "value": r.value}
        if source == "og_meta":
            from .methods.og_meta import OgMetaMethod
            m = OgMetaMethod(path)
            r = await m.produce(memo, "_probe_")
            return {"ok": True, "value": r.value}
        if source == "url":
            from .methods.url_pattern import UrlPatternMethod
            m = UrlPatternMethod(path)
            r = await m.produce(memo, "_probe_")
            return {"ok": True, "value": r.value}
        return {"ok": False, "error": f"unknown source {source!r}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Steps → MethodAttempt translation
# ---------------------------------------------------------------------------

def _steps_to_attempt(steps: List[Step], value: Any) -> Optional[MethodAttempt]:
    """Translate the agent's `steps` list into a single MethodAttempt that
    the existing `verify` pass can execute and compare against `value`.

    - 1 step  read_source         → LdJsonPathMethod / ShopifyProductJsonMethod / OgMetaMethod / UrlPatternMethod
    - 1 step  read_dom (no attr)  → dom_selector
    - 1 step  read_dom (attr=...) → dom_attr
    - N steps ending in read_dom  → accordion_read (click(s) then read)
    """
    if not steps:
        return None
    last = steps[-1]
    clicks = [s for s in steps[:-1] if s.action == "click" and s.selector]

    if len(steps) == 1 and last.action == "read_source":
        if not last.source or not last.path:
            return None
        kind_map = {"ld_json": "ld_json_path", "shopify_json": "shopify_product_json",
                    "og_meta": "og_meta", "url": "url_pattern"}
        kind = kind_map.get(last.source)
        if not kind:
            return None
        if kind == "ld_json_path":
            cfg = {"path": last.path}
            if last.transform: cfg["transform"] = last.transform
        elif kind == "shopify_product_json":
            cfg = {"field_path": last.path}
            if last.transform: cfg["transform"] = last.transform
        elif kind == "og_meta":
            cfg = {"name": last.path}
            if last.transform: cfg["transform"] = last.transform
        else:  # url_pattern
            cfg = {"pattern": last.path}
            if last.transform: cfg["transform"] = last.transform
        return MethodAttempt(kind=kind, config=cfg, expected=value)

    if last.action == "read_dom" and last.selector:
        cfg: Dict[str, Any] = {"selector": last.selector}
        if last.mode: cfg["mode"] = last.mode
        if last.separator: cfg["separator"] = last.separator
        if last.transform: cfg["transform"] = last.transform
        if clicks:
            # accordion_read: outermost click is trigger; the read selector is the panel.
            trig = clicks[0].selector
            return MethodAttempt(
                kind="accordion_read",
                config={"trigger_selector": trig, "panel_selector": last.selector,
                        "wait_ms": 500, "max_chars": 1500},
                expected=value,
            )
        if last.attr:
            cfg["attr"] = last.attr
            return MethodAttempt(kind="dom_attr", config=cfg, expected=value)
        return MethodAttempt(kind="dom_selector", config=cfg, expected=value)

    return None


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

_MODEL = os.getenv("DISCOVERY_VISION_MODEL", "claude-sonnet-4-20250514")
_INPUT_COST = 3.0
_OUTPUT_COST = 15.0
_MAX_TURNS = 40


@dataclass
class AgentResult:
    answers: Dict[str, FieldAnswer]
    trace: List[Dict[str, Any]] = dc_field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    turns_used: int = 0
    stop_reason: str = ""


_SYSTEM = """You are a deterministic-recipe discovery agent.

You are looking at ONE seed product page for a brand. The recipes you emit \
will be replayed against MANY OTHER products of the same brand at production \
time — no LLM in the loop. Your job: for each field in the requested schema, \
find the value AND emit the most stable deterministic recipe (the `steps`) \
that reproduces it.

Hard rules:
  - Recipes are LOCATION-based, not content-based. Selectors must work for \
    other products of this brand where the literal text will differ.
  - You may use the `url` source ONLY for `product_code`. The verifier will \
    discard a `url` step on any other field.
  - For each field you can find, call `answer(field, value, steps)` exactly once. \
    For fields not present on the page, call `answer(field, value=null, steps=[])`.
  - When done with every field, call `done()`.
  - Prefer the cheapest source that yields the value: read_source > read_dom > click+read_dom.
  - You can click as many times as needed to reveal hidden content. The page \
    state persists between calls — close opened modals (click trigger again, or \
    Escape — but you can't press keys, so re-click) when you're done with them.
"""


async def discover(memo: PageMemo, fields: List[str], max_turns: int = _MAX_TURNS) -> AgentResult:
    """Run the discovery agent until done() or turn budget hit."""
    from anthropic import Anthropic

    # Initial user message: schema + screenshot. The agent decides everything else.
    schema_section = build_schema_section(fields)
    screenshot = await memo.screenshot()

    initial_user = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.b64encode(screenshot).decode("utf-8")}},
        {"type": "text", "text":
            f"URL: {memo.url}\n\n"
            f"Required schema fields:\n{schema_section}\n\n"
            "Use the tools to inspect the page (look / read_source / read_dom / click) "
            "and emit one `answer` per field. Call `done` when finished."},
    ]

    messages: List[Dict[str, Any]] = [{"role": "user", "content": initial_user}]
    answers: Dict[str, FieldAnswer] = {}
    trace: List[Dict[str, Any]] = []
    input_tokens = output_tokens = 0
    done_called = False
    stop_reason = ""

    client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
    fields_set = set(fields)

    for turn in range(max_turns):
        try:
            resp = client.messages.create(
                model=_MODEL,
                max_tokens=4000,
                system=_SYSTEM,
                tools=_ALL_TOOLS,
                messages=messages,
            )
        except Exception as e:
            stop_reason = f"api_error: {e!r}"
            break

        input_tokens += getattr(resp.usage, "input_tokens", 0)
        output_tokens += getattr(resp.usage, "output_tokens", 0)

        # Collect every tool_use from this response; we must reply to ALL of them.
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            stop_reason = f"no_tool_use (response: {resp.stop_reason})"
            break

        # Append assistant message verbatim.
        messages.append({"role": "assistant", "content": resp.content})

        # Execute each tool, build a tool_result reply.
        tool_results: List[Dict[str, Any]] = []
        for tu in tool_uses:
            name = tu.name
            args = tu.input or {}
            result_payload: Any = None
            try:
                if name == "look":
                    result_payload = await _tool_look(memo)
                elif name == "click":
                    result_payload = await _tool_click(memo, args.get("selector", ""))
                elif name == "read_dom":
                    result_payload = await _tool_read_dom(
                        memo,
                        args.get("selector", ""),
                        args.get("attr"),
                        args.get("mode") or "first",
                        args.get("separator"),
                    )
                elif name == "read_source":
                    result_payload = await _tool_read_source(memo, args.get("source", ""), args.get("path", ""))
                elif name == "answer":
                    field_name = args.get("field")
                    value = args.get("value")
                    steps_raw = args.get("steps") or []
                    try:
                        steps = [Step.model_validate(s) for s in steps_raw if isinstance(s, dict)]
                    except ValidationError as ve:
                        result_payload = {"ok": False, "error": f"steps validation failed: {ve}"}
                        steps = []
                    if field_name and field_name in fields_set:
                        attempt = _steps_to_attempt(steps, value) if steps else None
                        methods = [attempt] if attempt else []
                        answers[field_name] = FieldAnswer(value=value, methods=methods)
                        result_payload = {"ok": True, "recorded": field_name,
                                          "method_kind": (attempt.kind if attempt else None)}
                    else:
                        result_payload = {"ok": False, "error": f"unknown field {field_name!r}"}
                elif name == "done":
                    done_called = True
                    result_payload = {"ok": True}
                else:
                    result_payload = {"ok": False, "error": f"unknown tool {name!r}"}
            except Exception as e:
                result_payload = {"ok": False, "error": f"tool exception: {type(e).__name__}: {e}"}

            trace.append({"turn": turn, "tool": name, "args": args, "result": result_payload})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result_payload, ensure_ascii=False, default=str),
            })

        messages.append({"role": "user", "content": tool_results})

        if done_called:
            stop_reason = "done"
            break
        # Auto-stop if every field has been answered.
        if fields_set.issubset(answers.keys()):
            stop_reason = "all_fields_answered"
            break
    else:
        stop_reason = "turn_budget"

    cost = (input_tokens / 1e6) * _INPUT_COST + (output_tokens / 1e6) * _OUTPUT_COST
    return AgentResult(
        answers=answers, trace=trace,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=round(cost, 4), turns_used=turn + 1, stop_reason=stop_reason,
    )
