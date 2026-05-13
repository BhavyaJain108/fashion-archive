"""
LLM ground-truth extraction.

Two-phase: first identify hideaways (accordions/tabs/'show more' buttons)
that hide product info, then click them open, then run the final
structured extraction over all combined content. Phase A and Phase C are
LLM calls; Phase B is mechanical.

Output is a fully-populated `ProductFields` representing the LLM's best
answer for what's actually on this product page. Cheap methods in the
catalog are later validated by matching their outputs against this.

Cost: ~$0.02-$0.10 per discovery (2 vision calls), paid once per brand.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .memo import PageMemo
from .schema import ProductFields


# Maximum chars of rendered HTML / panel text to include in any LLM prompt.
MAX_HTML_CONTEXT = 30000
MAX_PANEL_TEXT = 4000


@dataclass
class Hideaway:
    """A clickable that the LLM thinks reveals product info."""

    trigger_selector: str   # Playwright selector for the trigger button
    label: str              # Human label ("Composition", "Shipping", ...)
    expected_kind: str      # "material_info" | "specifications" | "delivery" | "tab" | "other"
    panel_selector: Optional[str] = None  # Optional: the element holding the content
    panel_text: Optional[str] = None      # Populated after click-and-capture


@dataclass
class GroundTruthResult:
    """Full output of the discovery LLM passes."""

    product_fields: ProductFields
    hideaways: List[Hideaway] = field(default_factory=list)
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM client (Claude vision; deliberately separate from the cheap-text path
# that runs Qwen, since vision-capable Qwen-VL isn't validated for this prompt
# yet).
# ---------------------------------------------------------------------------

_CLAUDE_MODEL = os.getenv("DISCOVERY_VISION_MODEL", "claude-sonnet-4-20250514")
# Approximate per-token cost for the Claude Sonnet 4 series.
_INPUT_COST_PER_M = 3.0
_OUTPUT_COST_PER_M = 15.0


def _claude_client():
    from anthropic import Anthropic
    return Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))


# ---------------------------------------------------------------------------
# Phase A — identify hideaways
# ---------------------------------------------------------------------------

PHASE_A_TOOL = {
    "name": "report_hideaways",
    "description": (
        "Report interactive elements (accordions, tabs, 'show more' buttons, drawers) "
        "on this product page that probably hide additional product information when "
        "expanded. Only include elements that look like they conceal product info — "
        "not site-wide menus, popups, or marketing carousels."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hideaways": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Visible label of the trigger ('Composition', 'Details', 'Shipping', etc.)",
                        },
                        "trigger_selector": {
                            "type": "string",
                            "description": (
                                "Playwright-compatible selector for the trigger. "
                                "Prefer button:has-text('Label') or stable data-test attributes. "
                                "Avoid auto-generated React class names."
                            ),
                        },
                        "panel_selector": {
                            "type": "string",
                            "description": "Optional: selector for the panel that expands after click.",
                        },
                        "expected_kind": {
                            "type": "string",
                            "enum": ["material_info", "specifications", "delivery", "tab", "other"],
                            "description": "What kind of product info you expect to find inside.",
                        },
                    },
                    "required": ["label", "trigger_selector", "expected_kind"],
                },
            }
        },
        "required": ["hideaways"],
    },
}


def _phase_a_prompt(visible_text_snippet: str, dom_snippet: str) -> str:
    return f"""You are looking at a fashion product page screenshot.
Identify clickable elements (accordions / tabs / "show more" buttons / drawers /
SIZE DROPDOWNS / COLOR PICKERS) that HIDE product information until clicked.

INCLUDE all of these when visible:
- Composition / Materials / Fabric accordion
- Care instructions
- Details / Specifications / Description (when truncated)
- Shipping & Returns / Delivery
- Size & Fit guide
- Multiple tabs of a tabbed widget
- **Size selectors / "Select a size" dropdowns** — VERY IMPORTANT, sizes are
  often hidden behind a dropdown button that must be clicked to reveal options
- Color selectors / dropdowns that hide swatch info
- "Show more" / "Read more" buttons on truncated descriptions

For size and color selectors, use `expected_kind: "tab"` (they're not really
accordions but they need clicking the same way).

Do NOT include:
- Site-wide nav menus, hamburger menus
- Newsletter signups, marketing popups
- Image galleries / carousels (those don't hide text info)
- Cart / wishlist buttons
- Country / currency switchers
- Country-of-origin disclaimers if already visible

For each hideaway, return a Playwright-compatible trigger selector. Prefer:
  button:has-text("Composition")
  button:has-text("Select a size")
  [data-test="accordion-details"]
  [data-region="accordion-shipping"] button
over auto-generated CSS classes.

Visible text snippet for context:
{visible_text_snippet[:3000]}

DOM snippet (interactive elements only):
{dom_snippet[:8000]}

Return all hideaways via the report_hideaways tool."""


def _extract_interactive_dom(html: str) -> str:
    """Grab buttons/accordion-like elements from rendered HTML to give the LLM
    selector context without overflowing the prompt."""
    out = []
    # buttons with text
    for m in re.finditer(r'<button[^>]*>(.*?)</button>', html, re.DOTALL | re.IGNORECASE):
        tag = m.group(0)[:500]
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()[:80]
        if text:
            out.append(f"<button> {text} | {tag[:200]}")
    # elements with role=button / role=tab
    for m in re.finditer(
        r'<(div|a|span)[^>]+role="(button|tab)"[^>]*>(.*?)</\1>', html, re.DOTALL | re.IGNORECASE,
    ):
        text = re.sub(r'<[^>]+>', '', m.group(3)).strip()[:80]
        if text:
            out.append(f'<{m.group(1)} role={m.group(2)}> {text} | {m.group(0)[:200]}')
    # elements that look like accordion triggers
    for m in re.finditer(
        r'<[^>]+(?:data-test|data-component|aria-controls|aria-expanded|class)="[^"]*(?:accordion|toggle|expander|tab|details)[^"]*"[^>]*>',
        html, re.IGNORECASE,
    ):
        out.append(f"[accordion-like] {m.group(0)[:200]}")
    return "\n".join(out[:200])


async def identify_hideaways(memo: PageMemo) -> tuple[List[Hideaway], dict]:
    """Phase A: ask the LLM which interactive elements hide product info."""
    screenshot = await memo.screenshot()
    visible = await memo.visible_text()
    rendered = await memo.rendered_html()
    dom_snippet = _extract_interactive_dom(rendered)

    client = _claude_client()
    response = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=2000,
        tools=[PHASE_A_TOOL],
        tool_choice={"type": "tool", "name": "report_hideaways"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(screenshot).decode("utf-8"),
                }},
                {"type": "text", "text": _phase_a_prompt(visible, dom_snippet)},
            ],
        }],
    )

    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
    }

    hideaways: List[Hideaway] = []
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "report_hideaways":
            for item in block.input.get("hideaways", []):
                hideaways.append(Hideaway(
                    trigger_selector=item.get("trigger_selector", ""),
                    label=item.get("label", ""),
                    expected_kind=item.get("expected_kind", "other"),
                    panel_selector=item.get("panel_selector"),
                ))
            break
    return hideaways, usage


# ---------------------------------------------------------------------------
# Phase B — reveal each hideaway
# ---------------------------------------------------------------------------

async def reveal_hideaways(memo: PageMemo, hideaways: List[Hideaway]) -> None:
    """Click each hideaway in sequence; store the resulting panel text on the
    Hideaway. After all clicks, re-snapshot the page so Phase C sees the
    revealed state (open size dropdowns, expanded accordions, etc.)."""
    for h in hideaways:
        text = await memo.click_and_capture(
            trigger_selector=h.trigger_selector,
            panel_selector=h.panel_selector,
            key=f"{h.label}::{h.trigger_selector}",
        )
        if text:
            h.panel_text = text[:MAX_PANEL_TEXT]
    # Critical: refresh the page artifacts so Phase C sees the post-click DOM
    # and screenshot. Especially needed for size dropdowns that only emit
    # their option list after being opened.
    await memo.refresh_post_interaction()


# ---------------------------------------------------------------------------
# Phase C — final structured extraction
# ---------------------------------------------------------------------------

PHASE_C_TOOL = {
    "name": "extract_e0005_fields",
    "description": "Extract all available E0005 product fields from this product page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "product_title":    {"type": "string"},
            "product_code":     {"type": "string", "description": "Website's internal SKU/product code (not GTIN)."},
            "additional_code_1":{"type": "string", "description": "GTIN-13/UPC/EAN if present."},
            "additional_code_1_type": {"type": "string", "description": "Type of additional_code_1 (GTIN13, UPC, EAN, ASIN, MPN, ...)."},
            "brand":            {"type": "string"},
            "description":      {"type": "string", "description": "Long product description."},
            "specifications":   {"type": "string", "description": "Technical specs / details block, semicolon-joined."},
            "size_info":        {"type": "string", "description": "Comma-separated list of available sizes (XS,S,M,L,XL or 38,40,42,44 etc.)."},
            "color_info":       {"type": "string", "description": "Color name(s) visible. Comma-separated if multiple."},
            "material_info":    {"type": "string", "description": "Fabric composition / materials (e.g. '100% cotton poplin')."},
            "variant_info":     {"type": "string", "description": "Free-form variant axes that aren't size or color."},
            "price":            {"type": "number", "description": "Current price including promotion (the sale price if on sale, else regular)."},
            "full_price":       {"type": "number", "description": "Original / strike-through price when on sale. Equal to price when no discount."},
            "promotion_type":   {"type": "string", "description": "E.g. '20% off', 'BOGO', 'final sale'. Empty if no promotion."},
            "promotion_end_date": {"type": "string", "description": "ISO date if a sale end date is shown."},
            "in_stock":         {"type": "integer", "enum": [0, 1], "description": "1 if any size is in stock, else 0."},
            "quantity":         {"type": "integer", "description": "Stock count if explicitly shown (rare). Often null."},
            "delivery":         {"type": "string", "description": "Shipping/delivery info text from the page."},
            "additional_tags":  {"type": "string", "description": "Badges / banners on the page (e.g. 'New', 'Best Seller', 'Final Sale'). Comma-separated."},
            "additional_content": {"type": "string", "description": "Anything else important not captured above."},
            "main_image_url":   {"type": "string", "description": "Primary product image URL."},
            "all_images":       {"type": "array", "items": {"type": "string"}, "description": "All product image URLs."},
        },
        "required": ["product_title"],
    },
}


def _phase_c_prompt(
    revealed_panels: List[Hideaway],
    rendered_excerpt: str,
    ld_json_blob: Optional[dict],
    visible_text: str,
) -> str:
    panel_lines = []
    for h in revealed_panels:
        if h.panel_text:
            panel_lines.append(f"=== Revealed: {h.label} ({h.expected_kind}) ===\n{h.panel_text}")
    panels_section = "\n\n".join(panel_lines) if panel_lines else "(no hideaways revealed)"
    ld_section = (
        json.dumps(ld_json_blob, indent=2)[:8000]
        if ld_json_blob else "(no LD+JSON Product blob present)"
    )

    return f"""Extract all available E0005 product fields from this product page.

Use the screenshot as primary source. The revealed-panel texts below were
collected by clicking accordions/tabs on the page, so material/composition/
shipping info often lives there. The LD+JSON blob is a structured-data hint
but treat it as secondary — the SCREENSHOT is authoritative for pricing
(esp. sale vs. full price) and stock.

Rules:
- price = the CURRENT price shown to the buyer (sale price if discounted).
- full_price = the strike-through/original price. If no discount visible,
  set full_price equal to price.
- Sizes: comma-separated, in the order they appear on the page.
- in_stock: 1 if at least one size is available; 0 only if every size is
  marked sold out / unavailable.
- Codes: product_code is the brand's internal SKU. GTIN/UPC goes in
  additional_code_1 with additional_code_1_type="GTIN13" etc.
- Leave fields null when the page doesn't show them; don't invent values.
- all_images should be product photos only — no model carousel thumbnails,
  no Instagram embeds, no related-product images.

==== Revealed panel content (from accordions/tabs) ====
{panels_section}

==== LD+JSON Product blob (secondary) ====
{ld_section}

==== Visible text on page (truncated) ====
{visible_text[:6000]}

==== Rendered HTML excerpt (interactive elements) ====
{rendered_excerpt[:6000]}

Return all available fields via the extract_e0005_fields tool."""


async def final_extraction(
    memo: PageMemo,
    hideaways: List[Hideaway],
) -> tuple[ProductFields, dict]:
    """Phase C: structured extraction over screenshot + revealed panels + DOM."""
    screenshot = await memo.screenshot()
    visible = await memo.visible_text()
    rendered = await memo.rendered_html()
    rendered_excerpt = _extract_interactive_dom(rendered)
    ld_json = await memo.ld_json_product()

    client = _claude_client()
    response = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=4000,
        tools=[PHASE_C_TOOL],
        tool_choice={"type": "tool", "name": "extract_e0005_fields"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(screenshot).decode("utf-8"),
                }},
                {"type": "text", "text": _phase_c_prompt(hideaways, rendered_excerpt, ld_json, visible)},
            ],
        }],
    )

    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
    }

    extracted: Dict[str, Any] = {}
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "extract_e0005_fields":
            extracted = block.input
            break

    # Coerce all_images list → JSON string per E0005 schema
    if isinstance(extracted.get("all_images"), list):
        extracted["all_images"] = json.dumps(extracted["all_images"])

    # Drop empties so Pydantic can apply defaults / not store ''.
    cleaned = {k: v for k, v in extracted.items() if v not in (None, "", [], {})}
    product = ProductFields(**cleaned)
    product.itemurl = memo.url
    return product, usage


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

async def extract_ground_truth(memo: PageMemo) -> GroundTruthResult:
    """Run Phase A + B + C and return the assembled ground truth."""
    result = GroundTruthResult(product_fields=ProductFields())

    # Phase A — identify hideaways
    hideaways, a_usage = await identify_hideaways(memo)
    result.hideaways = hideaways
    result.llm_calls += 1
    result.llm_input_tokens += a_usage["input_tokens"]
    result.llm_output_tokens += a_usage["output_tokens"]
    result.notes.append(f"Phase A: identified {len(hideaways)} hideaways")

    # Phase B — reveal each
    if hideaways:
        await reveal_hideaways(memo, hideaways)
        revealed = sum(1 for h in hideaways if h.panel_text)
        result.notes.append(f"Phase B: revealed {revealed}/{len(hideaways)} hideaways")

    # Phase C — final extraction
    product, c_usage = await final_extraction(memo, hideaways)
    result.product_fields = product
    result.llm_calls += 1
    result.llm_input_tokens += c_usage["input_tokens"]
    result.llm_output_tokens += c_usage["output_tokens"]
    result.notes.append("Phase C: extracted E0005 fields")

    # Cost computation
    cost = (result.llm_input_tokens / 1_000_000) * _INPUT_COST_PER_M
    cost += (result.llm_output_tokens / 1_000_000) * _OUTPUT_COST_PER_M
    result.llm_cost_usd = round(cost, 4)

    return result
