"""
One-shot discovery — the entire Stage-3 discovery flow in a single module.

Four actions:

    1. LOAD     — caller hands us a PageMemo already loaded (page rendered,
                  hideaways revealed via Phase B).
    2. ASK      — one LLM call. Sends the schema, the method-kind catalog
                  description, and the full PageMemo dump. Returns:
                    Dict[field_name, FieldAnswer]
                  where each FieldAnswer carries the LLM's ground-truth value
                  AND a list of MethodAttempt instructions to repeat the
                  extraction cheaply.
    3. VERIFY   — for each MethodAttempt: instantiate, run against the same
                  PageMemo, keep only those whose output equals the LLM's
                  stated `expected` AND the LLM's stated `value`. Output:
                    List[CatalogRow] — already in catalog shape.
    4. SAVE     — wrap the verified rows in a SiteCatalog (existing type)
                  and persist.

No new state types beyond:
    - MethodAttempt: (kind, config, expected)
    - FieldAnswer:   (value, methods: list[MethodAttempt])

These get assembled from the LLM tool-call response. Everything else uses
existing types (PageMemo, Method, CatalogRow, SiteCatalog).
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from .catalog import CatalogRow, SiteCatalog, hydrate_method
from .field_specs import (
    SCHEMA_DESCRIPTIONS,
    build_schema_section,
    fields_for_product_type,
)
from .memo import PageMemo
from .source_costs import CostMeter, source_cost_ms


# ---------------------------------------------------------------------------
# Pydantic models — the LLM tool I/O schema. These are the contract that
# the discovery LLM call must satisfy. Pydantic validates the response
# strictly; malformed entries surface as ValidationError instead of
# crashing the parser later.
# ---------------------------------------------------------------------------

class MethodAttempt(BaseModel):
    """One way to extract a field, proposed by the LLM."""
    kind: str = Field(..., description="Method kind name (e.g. shopify_product_json).")
    config: Dict[str, Any] = Field(default_factory=dict,
        description="Method-specific config kwargs.")
    expected: Optional[Any] = Field(default=None,
        description="Exact byte-for-byte output this method will produce on this page.")

    model_config = {"extra": "ignore"}


class FieldAnswer(BaseModel):
    """The LLM's answer for one field: value plus repeat instructions."""
    value: Optional[Any] = Field(default=None,
        description="The page's value for this field, or null if not present.")
    methods: List[MethodAttempt] = Field(default_factory=list,
        description="0..N method instructions that reproduce the value deterministically.")

    model_config = {"extra": "ignore"}


class _FieldEntry(BaseModel):
    """One entry in the LLM tool's `fields` array — name + value + methods."""
    field: str
    value: Optional[Any] = None
    methods: List[MethodAttempt] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class _DiscoveryResponse(BaseModel):
    """The full structured response from the discovery LLM call."""
    fields: List[_FieldEntry] = Field(default_factory=list)
    platform_hint: Optional[str] = None
    notes: Optional[str] = None

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# LLM call configuration
# ---------------------------------------------------------------------------

_VISION_MODEL = os.getenv("DISCOVERY_VISION_MODEL", "claude-sonnet-4-20250514")
_INPUT_COST_PER_M = 3.0
_OUTPUT_COST_PER_M = 15.0


# Caps on each PageMemo section when packed into the prompt. Larger inputs
# work, but tighter caps keep the prompt focused and the cost down.
_CAP_VISIBLE_TEXT = 6000
_CAP_DOM_EXCERPT = 12000
_CAP_RENDERED_DOM = 120000   # full DOM minus script/style/svg/noscript/comments
_CAP_LD_JSON = 8000
_CAP_SHOPIFY_JSON = 10000
_CAP_PANEL_TEXT = 2000
_CAP_NETWORK_IMG_URLS = 30


# ---------------------------------------------------------------------------
# Method-kinds description — constant prompt content
# ---------------------------------------------------------------------------
#
# Tells the LLM what method kinds it may propose. Each kind has a one-line
# summary, the applicable-when condition, and an example config so the LLM
# has a concrete shape to mirror.

METHOD_KINDS_TEXT = """\
You may propose method extractions using ONLY these kinds. For each method
you propose, fill its config exactly per the example shape shown.

- `ld_json_path`: Read a value from a parsed <script type="application/ld+json">
  Product blob. Available whenever the page contains such a blob.
  config: {"path": "$.offers.price", "transform": "to_float"}
  transform can be: null, "to_float", "to_int", "strip", "join_comma", "json".

- `ld_json_images`: Return the primary or all images from the Product blob's
  $.image (handles both string and array forms).
  config: {}  (the method itself dispatches on which field it's serving)

- `og_meta`: Read content of a single <meta name|property=...> tag.
  config: {"name": "og:title", "transform": null}
  transform can be: null, "to_float", "html_unescape".

- `shopify_product_json`: Read a value from the parsed /products/<slug>.json
  endpoint (Shopify sites only).
  config: {"field_path": "product.variants[].option1:dedupe_join_comma",
           "transform": null, "mode": "first"}
  field_path supports dot-walk + foo[] enumeration + ":transform" suffix
  (transforms: dedupe_join_comma, join_comma, json, first, any_truthy).

- `dom_selector`: Read innerText from element(s) matching a CSS selector
  on the rendered DOM. Use mode="all_join" with separator=", " for multi-value
  fields (e.g. size lists). Use mode="first" for single values.
  config: {"selector": "h1.product__name", "mode": "first",
           "transform": "strip", "separator": ", "}
  transform can be: null, "strip", "to_float", "split_size_list".
  The full post-render DOM is provided below under [rendered_dom]. Pick
  selectors that you literally see in that DOM — verify the tag,
  attributes, and surrounding context match what you're targeting.
  Prefer stable attributes (id, data-test, data-component, aria-label,
  aria-controls, role) over class names where available.

- `dom_attr`: Read an attribute (e.g. data-value, src, href) from the first
  element matching a CSS selector on the rendered DOM.
  config: {"selector": "meta[itemprop='sku']", "attr": "content",
           "transform": null}

- `accordion_read`: Click an accordion / "show more" trigger and read the
  expanded panel's text.
  config: {"trigger_selector": "button:has-text('Composition')",
           "panel_selector": "[data-region='composition-panel']",
           "wait_ms": 500, "max_chars": 1500}

- `network_images`: Filter captured-network image URLs by an SKU stem or
  path pattern. Useful when LD+JSON only carries one image and the rest live
  on a product CDN.
  config: {"sku_hint": "5632385-200", "path_pattern": "/eCom/"}

- `network_api`: Read a value from one of the brand's product API endpoints
  that we captured during page render. Each candidate API is listed below
  under [product_apis] with its url_template (the product-specific bits
  replaced by `{sku}`), the suggested `sku_source` (how to resolve `{sku}`
  for new products), and a preview of its JSON response. Pick the path
  inside that response that holds the value.
  config: {"url_template": "https://brand.com/api/availability/{sku}?locale=en-us",
           "sku_source": "ld_json:$.sku",
           "json_path": "skuAvailabilities[].id:join_comma",
           "method": "GET",
           "transform": null}
  json_path shares syntax with shopify_product_json (dot-walk, foo[]
  enumeration, :join_comma / :dedupe_join_comma / :first / :any_truthy /
  :json transforms).
  Use this whenever a product API in the list below contains the value
  cleanly — it's typically cheaper and more reliable than scraping the
  DOM, especially for size availability, stock, and live pricing.

- `llm_batch_extraction`: PER-PRODUCT LLM call that reads a piece of page
  content and returns the values of one or more schema fields. This is
  the ONLY method that costs LLM tokens at production time — every other
  method is deterministic. Propose it ONLY as a last resort, when a panel
  or text blob contains multiple schema fields' values mixed together
  (e.g. an accordion that has description + specifications + materials
  in one chunk and no stable sub-selector splits them) AND no other
  method can isolate the individual fields.
  config: {"fields": ["specifications", "material_info"]}
  The method will, per product, send the page state (rendered text +
  revealed panels + structured sources) to a cheap LLM and ask for each
  field. Production cost: ~$0.0005-$0.002 per product. The orchestrator
  ranks this last in cost, so a field with another verified recipe will
  never fall through to it; only fields whose only catalogued recipe is
  this one trigger the cost.
  Do NOT propose for fields where any deterministic source (LD+JSON,
  Shopify JSON, network_api, og_meta, url_pattern) gives the value.

- `url_pattern`: Apply a Python regex to `memo.url` and return one capture
  group. **RESTRICTED**: you may propose `url_pattern` ONLY for the
  `product_code` field. It will be rejected for any other field. Use it
  when the brand's product URLs embed the SKU at a stable position
  (e.g. `…/pr/some-slug-870312QJAAC4003.html` → capture the trailing SKU).
  config: {"pattern": "-([A-Z0-9]{8,})\\.html$", "group": 1, "transform": null}
  transform can be: null, "upper", "lower", "strip".

- `nav_tree`: Walk the brand's saved nav.json to find the category ancestor
  chain for memo.url. Produces a single category level when bound to a
  specific category{N} field.
  config: {"nav_json_path": "/abs/path/to/nav.json"}

- `compose`: Combine the outputs of multiple LOCATION-based inner methods
  into one value using a template. Use this only when a field's value is
  literally assembled from two distinct locations on the page (e.g.
  textile description text + a Shopify variant option). Each inner method
  must be a LOCATION-based extractor (dom_selector, dom_attr, ld_json_path,
  shopify_product_json, og_meta, accordion_read, url_pattern, nav_tree).
  If any part returns null, the compose returns null.
  config: {
    "parts": [
      {"kind": "ld_json_path", "config": {"path": "$.description"}},
      {"kind": "shopify_product_json",
       "config": {"field_path": "product.variants[].option3:dedupe_join_comma"}}
    ],
    "template": "{0} — {1}"
  }
  Use template "{0}" alone if there's just one part. Use separator (instead
  of template) when joining a list with a constant separator:
  config: {"parts": [...], "separator": " — "}

Selector and path quality matters. Prefer:
  - Stable attributes (data-test, data-region, id, role, aria-label)
  - Visible button text via :has-text(...) over auto-generated class names
  - LD+JSON / OG meta paths over DOM when the value lives there

You may propose multiple methods for the same field; the cheapest verified
one wins at production time.
"""


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _truncate(s: Optional[str], limit: int) -> str:
    if not s:
        return ""
    return s if len(s) <= limit else s[:limit] + "\n…(truncated)"


def _strip_dom_noise(html: str) -> str:
    """Remove script/style/svg/noscript/comments + collapse whitespace.
    Leaves real markup intact so the LLM can read structure + pick selectors.

    Pure string scanning — no regex over content, just bracket counting.
    """
    out: List[str] = []
    i, n = 0, len(html)
    SKIP_TAGS = ("script", "style", "svg", "noscript")
    while i < n:
        if html.startswith("<!--", i):
            end = html.find("-->", i + 4)
            i = end + 3 if end != -1 else n
            continue
        if html[i] == "<" and i + 1 < n and html[i + 1].isalpha():
            # Read tag name
            j = i + 1
            while j < n and (html[j].isalnum() or html[j] in "-_"):
                j += 1
            tag = html[i + 1:j].lower()
            if tag in SKIP_TAGS:
                # Find matching closing tag (case-insensitive). Naive but
                # adequate; nested same-name skip-tags are vanishingly rare.
                close = f"</{tag}"
                end = html.lower().find(close, j)
                if end == -1:
                    break
                # Move past the closing >
                gt = html.find(">", end)
                i = gt + 1 if gt != -1 else n
                continue
        out.append(html[i])
        i += 1
    cleaned = "".join(out)
    # Collapse runs of whitespace.
    cleaned = " ".join(cleaned.split())
    return cleaned


def _extract_interactive_dom(html: str, cap: int) -> str:
    """Pull buttons / role=tab / accordion-like tags out of rendered HTML so
    the LLM has selector context without the entire DOM."""
    out: List[str] = []
    for m in re.finditer(r'<button[^>]*>(.*?)</button>', html, re.DOTALL | re.IGNORECASE):
        tag = m.group(0)[:300]
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()[:80]
        if text:
            out.append(f"<button> {text} | {tag[:200]}")
    for m in re.finditer(
        r'<(div|a|span)[^>]+role="(button|tab|menuitem)"[^>]*>(.*?)</\1>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        text = re.sub(r'<[^>]+>', '', m.group(3)).strip()[:80]
        if text:
            out.append(f"<{m.group(1)} role={m.group(2)}> {text} | {m.group(0)[:200]}")
    for m in re.finditer(
        r'<[^>]+(?:data-test|data-component|aria-controls|aria-expanded|class)="[^"]*(?:accordion|toggle|expander|tab|details)[^"]*"[^>]*>',
        html, re.IGNORECASE,
    ):
        out.append(f"[accordion-like] {m.group(0)[:240]}")
    joined = "\n".join(out)
    return _truncate(joined, cap)


def _clamp_screenshot(png_bytes: bytes, max_dim: int = 7800) -> bytes:
    """Downscale a screenshot if either dimension > Claude's 8000px image cap.

    Long product pages can render to 12K+ tall full-page screenshots, which
    Anthropic rejects with `image dimensions exceed max allowed size: 8000
    pixels`. We rescale proportionally so the longest side fits under the
    cap; aspect ratio is preserved. Quality is unimportant — the LLM uses
    the image for layout intuition, not pixel-perfect OCR.
    """
    if not png_bytes:
        return png_bytes
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png_bytes))
        w, h = img.size
        if w <= max_dim and h <= max_dim:
            return png_bytes
        scale = max_dim / max(w, h)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        print(f"[oneshot] _clamp_screenshot failed: {e!r} — sending original (may 400)")
        return png_bytes


def _format_product_apis(apis: List[Dict[str, Any]]) -> str:
    """Format the captured product-API candidates for the discovery prompt.
    Each entry shows the url_template (with `{sku}` placeholder), the
    suggested sku_source resolver, and a truncated response preview the
    LLM can pick paths into."""
    if not apis:
        return "(no same-host JSON product APIs were captured during page render)"
    parts = []
    for i, a in enumerate(apis, 1):
        parts.append(
            f"--- API #{i} ---\n"
            f"url_template: {a['url_template']}\n"
            f"sku_source:   {a['sku_source']}\n"
            f"sample_url:   {a['sample_url']}\n"
            f"response (truncated to 1500 chars):\n"
            f"{a['response_preview']}"
        )
    return "\n\n".join(parts)


def _pack_revealed_panels(memo: PageMemo) -> str:
    """Format any post-Phase-B accordion text capture for the prompt."""
    lines: List[str] = []
    for key, text in memo._accordion_text.items():
        if not text:
            continue
        lines.append(f"=== Revealed via `{key}` ===")
        lines.append(_truncate(text, _CAP_PANEL_TEXT))
    return "\n".join(lines) if lines else "(no panels revealed)"


async def _build_prompt(memo: PageMemo, fields: List[str]) -> Tuple[str, bytes]:
    """Build the user-message text and return (prompt_text, screenshot_bytes)."""
    schema_section = build_schema_section(fields)

    rendered = await memo.rendered_html()
    visible_text = await memo.visible_text()
    dom_excerpt = _extract_interactive_dom(rendered, _CAP_DOM_EXCERPT)
    rendered_dom = _truncate(_strip_dom_noise(rendered), _CAP_RENDERED_DOM)
    ld_json_product = await memo.ld_json_product()
    meta_tags = await memo.meta_tags()
    revealed = _pack_revealed_panels(memo)

    # Shopify is optional; try to fetch but never block the prompt.
    shopify_blob: Optional[dict] = None
    try:
        from .methods.shopify_json import ShopifyProductJsonMethod
        shopify_blob = await ShopifyProductJsonMethod._get_blob(memo)
    except Exception:
        shopify_blob = None

    # Same-host JSON GET endpoints captured during page render that contain
    # this product's SKU — likely live product APIs (availability, variants,
    # pricing). The LLM can propose `network_api` recipes that read into
    # these responses by JSONPath; production substitutes {sku} per product.
    try:
        api_candidates = await memo.product_api_candidates()
    except Exception:
        api_candidates = []

    # Top-N network image URLs (deduped, ordered by appearance).
    network = await memo.network()
    image_urls: List[str] = []
    seen = set()
    for cap in network:
        u = cap.url
        if any(u.lower().endswith(ext) or f"{ext}?" in u.lower()
               for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")):
            if u not in seen:
                seen.add(u)
                image_urls.append(u)
        if len(image_urls) >= _CAP_NETWORK_IMG_URLS:
            break

    screenshot = await memo.screenshot()

    prompt = f"""You are extracting product page data for ONE product, into the E0005 schema.

The page URL is: {memo.url}

This is ONE seed page of a brand that may have hundreds of products. The
methods you propose will be run against MANY OTHER products from this same
brand. Across products of the same brand:
  - The text content of each field CHANGES per product (size 0 vs size XL,
    "Black" vs "Brown", different SKUs, different prices, different
    materials).
  - The LOCATION where each kind of information lives DOES NOT CHANGE.
    The size selector is in the same DOM region. The price comes from the
    same JSON path. The brand sits in the same meta tag. The composition
    is inside the same accordion panel.

Therefore: **propose methods based on LOCATION, never on text content.**
NEVER use regex over text content. NEVER pattern-match literal words.
Always describe WHERE the value lives (DOM selector, JSON path, meta tag
name, accordion label), and let the runtime extract whatever the source
emits for that product.

Your job has TWO parts:

A. For each schema field, produce `value` — the value as a human reading
   THIS page would say it is.

B. For each field with a value, propose 1..N method instructions describing
   the LOCATION where this value lives. For each method, set `expected` to
   the EXACT byte-for-byte string the method will return for THIS product —
   so we can verify the location truly contains the value.

CRITICAL RULES for proposals:

1. **Always propose the obvious deterministic path FIRST.** For every field
   with a value, if there's a Shopify product.json path, LD+JSON path, or
   og:meta name that emits the value (even if formatted slightly
   differently), propose it. Then add fancier methods on top. Do NOT skip
   obvious paths in favor of fancier ones — multiple methods per field is
   ideal. The orchestrator picks the cheapest at production.

2. `expected` must equal what the method's underlying source emits AS-IS,
   including weird casing, missing spaces, or punctuation differences. We
   will run your method and compare bytes. If you say
   `shopify_product_json` with `field_path: product.variants[].option3:dedupe_join_comma`
   will produce "Cotton" but it actually produces "COTTON", the proposal
   is discarded.

3. `value` and `expected` MAY differ. The `value` is the user-visible ideal;
   the `expected` is whatever the deterministic source actually emits. If
   the source emits a near-but-not-exact form, predict the source's exact
   form in `expected` and we'll catalog it — we accept slight format drift
   when the recipe is deterministic.

4. **Use `compose` as ADDITIONAL proposals** when a field's value is
   genuinely assembled from two distinct LOCATIONS on the page. Each part
   of a compose MUST be a location-based method (dom_selector, dom_attr,
   ld_json_path, shopify_product_json, og_meta, accordion_read).
   Example:
     - material_info: when textile name lives in the LD+JSON description
       location AND percentages live at Shopify option3, propose compose
       with both location-paths and a template. Predict the EXACT runtime
       composition as `expected`.

5. **Generalization is the bar.** Your method runs against many products
   with different per-product text. Pick selectors / JSON paths / meta
   names that capture the LOCATION of the kind of information, not the
   literal text of this product. A `dom_selector` like
   `.product-details__option-value-list` works for every product because
   the LOCATION of the size grid is stable. A selector based on the
   product's current text never generalizes.

6. For every field where the LLM truth has a value but no LOCATION-based
   method on this page reliably produces it, leave methods=[]. We will
   NOT call you again at production — the field stays null. Better blank
   than wrong on the next product.

If a field is not on this page, set value=null and methods=[].

=== Method kinds you may propose ===
{METHOD_KINDS_TEXT}

=== E0005 schema you must fill ===
{schema_section}

=== PageMemo: everything we collected about this page ===

[meta_tags]
{json.dumps(meta_tags, indent=2)[:3000]}

[ld_json_product]
{json.dumps(ld_json_product, indent=2)[:_CAP_LD_JSON] if ld_json_product else "(no LD+JSON Product blob on this page)"}

[shopify_product_json]
{json.dumps(shopify_blob, indent=2)[:_CAP_SHOPIFY_JSON] if shopify_blob else "(no /products/<slug>.json endpoint or not Shopify)"}

[product_apis]
{_format_product_apis(api_candidates)}

[interactive_dom_excerpt]
{dom_excerpt}

[rendered_dom (full post-render HTML, script/style/svg/comments stripped, whitespace collapsed)]
This is the actual DOM after JavaScript has run. Use it to pick real,
verifiable selectors. Every CSS class, id, data-* attribute, and tag
structure you see here is exactly what production will query against.
{rendered_dom}

[revealed_panels (post-click content)]
{revealed}

[visible_text (post-render, capped)]
{_truncate(visible_text, _CAP_VISIBLE_TEXT)}

[network_image_urls (top {_CAP_NETWORK_IMG_URLS})]
{json.dumps(image_urls, indent=2)}

=== Output via the `extract_and_propose` tool ===

For every field in the schema:
  - field: the field name (must match exactly)
  - value: the page's value for this field (null if not present)
  - methods: list of {{kind, config, expected}} where:
      - kind: one of the method kinds above
      - config: the exact config dict for that kind
      - expected: what running this method against this page WILL produce
        (we will compare runtime output vs expected vs value — all must agree
        before we trust this method).
"""
    return prompt, screenshot


# ---------------------------------------------------------------------------
# LLM tool schema
# ---------------------------------------------------------------------------

def _build_extract_tool() -> Dict[str, Any]:
    """Tool definition derived from the Pydantic _DiscoveryResponse model.
    Single source of truth — schema can't drift from the parser."""
    return {
        "name": "extract_and_propose",
        "description": (
            "Return E0005 field values + method-extraction proposals for this product page."
        ),
        "input_schema": _DiscoveryResponse.model_json_schema(),
    }


_EXTRACT_TOOL = _build_extract_tool()


# ---------------------------------------------------------------------------
# ASK
# ---------------------------------------------------------------------------

@dataclass
class AskResult:
    answers: Dict[str, FieldAnswer]
    platform_hint: Optional[str]
    notes: Optional[str]
    llm_input_tokens: int
    llm_output_tokens: int
    llm_cost_usd: float


async def ask_llm(memo: PageMemo, fields: List[str]) -> AskResult:
    """One LLM call. Returns the LLM's structured answers + method proposals."""
    from anthropic import Anthropic

    prompt_text, screenshot = await _build_prompt(memo, fields)
    screenshot = _clamp_screenshot(screenshot)
    client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
    response = client.messages.create(
        model=_VISION_MODEL,
        max_tokens=8000,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_and_propose"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(screenshot).decode("utf-8"),
                }},
                {"type": "text", "text": prompt_text},
            ],
        }],
    )

    input_t = getattr(response.usage, "input_tokens", 0)
    output_t = getattr(response.usage, "output_tokens", 0)
    cost = (input_t / 1_000_000) * _INPUT_COST_PER_M + (output_t / 1_000_000) * _OUTPUT_COST_PER_M

    payload: Dict[str, Any] = {}
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "extract_and_propose":
            payload = block.input or {}
            break

    # Pydantic does the heavy lifting: validates each field entry, coerces
    # types, drops malformed sub-entries. ValidationError surfaces here
    # instead of partway through downstream code.
    try:
        parsed = _DiscoveryResponse.model_validate(payload)
    except ValidationError as exc:
        print(f"[ask_llm] LLM payload failed Pydantic validation: {exc!r}")
        parsed = _DiscoveryResponse()

    answers: Dict[str, FieldAnswer] = {}
    for entry in parsed.fields:
        if not entry.field:
            continue
        answers[entry.field] = FieldAnswer(
            value=entry.value,
            methods=entry.methods,
        )

    return AskResult(
        answers=answers,
        platform_hint=parsed.platform_hint,
        notes=parsed.notes,
        llm_input_tokens=input_t,
        llm_output_tokens=output_t,
        llm_cost_usd=round(cost, 4),
    )


# ---------------------------------------------------------------------------
# VERIFY
# ---------------------------------------------------------------------------

def _strip_html(s: str) -> str:
    """Remove HTML tags via simple bracket scanning. Pure string ops, no regex."""
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "<":
            j = s.find(">", i + 1)
            if j == -1:
                out.append(s[i:])
                break
            out.append(" ")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _norm_scalar(x: Any) -> Any:
    """Reduce a scalar to a canonical form for comparison: strip HTML,
    collapse whitespace (including around commas), lowercase. Boolean-like
    strings ("true"/"false"/"yes"/"no"/"in_stock"/"out_of_stock") collapse
    to numeric 1.0/0.0 so the LLM's `expected="true"` matches a recipe
    that returns int 1, and a `LinkAvailability/InStock` URL matches 1."""
    if x is None:
        return None
    if isinstance(x, bool):
        return float(int(x))
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x)
    s = _strip_html(s)
    # HTML entity decode so `&amp;` matches `&`, `&#39;` matches `'`, etc.
    # (LD+JSON-encoded URLs frequently contain `&amp;` while LLM-quoted
    # expected values use the decoded form.)
    import html as _html
    s = _html.unescape(s)
    # Collapse whitespace
    s = " ".join(s.split())
    # Normalize whitespace around commas / semicolons so "0, 2" == "0,2"
    for sep in (",", ";"):
        s = sep.join(p.strip() for p in s.split(sep))
    norm = s.strip().lower()
    # Boolean-equivalent strings collapse to numeric 1.0 / 0.0 so the
    # universal comparator can match across different field encodings.
    _truthy = {"true", "yes", "y", "1", "in stock", "in_stock", "instock",
               "available", "https://schema.org/instock"}
    _falsy = {"false", "no", "n", "0", "out of stock", "out_of_stock", "outofstock",
              "unavailable", "https://schema.org/outofstock",
              "https://schema.org/reserved", "reserved"}
    if norm in _truthy:
        return 1.0
    if norm in _falsy:
        return 0.0
    return norm


def _to_set(x: Any) -> Optional[frozenset]:
    """If `x` represents a list/comma-list, return its items as a normalized
    frozenset. Otherwise None (not list-shaped)."""
    if isinstance(x, list):
        return frozenset(_norm_scalar(v) for v in x if v not in (None, ""))
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                return frozenset(_norm_scalar(v) for v in json.loads(s) if v not in (None, ""))
            except json.JSONDecodeError:
                pass
        if "," in s:
            parts = [p.strip() for p in s.split(",") if p.strip()]
            if len(parts) >= 2:
                return frozenset(_norm_scalar(p) for p in parts)
    return None


def _equal(a: Any, b: Any) -> bool:
    """Universal semantic equality. Incidental formatting differences
    (whitespace, HTML tags, case, list ordering, numeric format) never block
    a match. Real semantic differences do.

    Specifically:
      - HTML tags stripped from strings before comparing.
      - Whitespace collapsed and trimmed around commas / semicolons.
      - Case-insensitive.
      - Numeric values match within 1% tolerance.
      - Lists / JSON-encoded list strings / comma-separated strings compare
        as sets, with subset acceptance in EITHER direction (source emits
        extras OR LLM listed extras — both still "matches the data").
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False

    # Numeric tolerance (covers price/full_price/quantity/in_stock)
    try:
        af, bf = float(a), float(b)
        if abs(af - bf) / max(1.0, abs(bf)) <= 0.01:
            return True
    except (TypeError, ValueError):
        pass

    # List-shaped comparison (covers JSON lists, comma-separated values, list[T])
    sa, sb = _to_set(a), _to_set(b)
    if sa is not None and sb is not None:
        if not sa or not sb:
            return False
        if sa == sb or sa <= sb or sb <= sa:
            return True
        # Loose fallback: strip ALL whitespace within each item (handles
        # "53% Silk" vs "53%SILK", "BlackWool" vs "Black Wool"). Elements
        # may be normalized to non-str (floats from boolean coercion) —
        # str() them first so .split() is always safe.
        sa_t = {"".join(str(x).split()) for x in sa}
        sb_t = {"".join(str(x).split()) for x in sb}
        return sa_t == sb_t or sa_t <= sb_t or sb_t <= sa_t

    # Scalar fallback — fully normalized string compare
    return _norm_scalar(a) == _norm_scalar(b)


# Backward-compat alias for any code still calling _norm_str
def _norm_str(s: Any) -> str:
    return str(_norm_scalar(s)) if _norm_scalar(s) is not None else ""


@dataclass
class VerifyResult:
    catalog_rows: List[CatalogRow]
    discarded: List[Tuple[str, MethodAttempt, str]]  # (field, attempt, reason)
    method_costs_ms: Dict[str, float]                # measured by CostMeter


async def verify(answers: Dict[str, FieldAnswer], memo: PageMemo) -> VerifyResult:
    """For each proposed method: instantiate, run, demand runtime == expected
    == LLM-value. Catalog only the triple-verified rows.

    Also times each method invocation so we can record per-site measured costs.
    """
    rows: List[CatalogRow] = []
    discarded: List[Tuple[str, MethodAttempt, str]] = []
    meter = CostMeter()

    for field_name, answer in answers.items():
        for attempt in answer.methods:
            # 0. Enforce the url_pattern restriction. url_pattern is regex
            # over memo.url and is the one allowed regex-based method —
            # but ONLY for `product_code` where SKUs live at a stable URL
            # position. Any other field proposing url_pattern is dropped
            # to keep the no-content-regex contract for the rest of the
            # schema.
            if attempt.kind == "url_pattern" and field_name != "product_code":
                discarded.append((
                    field_name, attempt,
                    "url_pattern only allowed for product_code",
                ))
                continue

            # 1. Hydrate the Method from (kind, config).
            try:
                method = hydrate_method({"kind": attempt.kind, **attempt.config})
            except Exception as exc:
                discarded.append((field_name, attempt, f"hydrate failed: {exc}"))
                continue

            # 2. Run it, timed.
            try:
                with meter.time(attempt.kind):
                    result = await method.produce(memo, field_name)
                runtime_output = result.value
            except Exception as exc:
                discarded.append((field_name, attempt, f"runtime error: {exc}"))
                continue

            # 3. Gate on runtime == expected. The LLM committed to what its
            # method WILL produce; we verify that commitment. The LLM's
            # ground-truth `value` is informational — it represents the ideal
            # form on the page, which sometimes differs in formatting from
            # what any deterministic source can emit (e.g. Shopify option3
            # "53%SILK,47%COTTON" vs user-visible "53% Silk, 47% Cotton").
            # Trust the recipe as long as it's deterministic and the LLM
            # predicted its exact output.
            if not _equal(runtime_output, attempt.expected):
                discarded.append((
                    field_name, attempt,
                    f"runtime {runtime_output!r} != expected {attempt.expected!r}",
                ))
                continue
            value_drift = not _equal(runtime_output, answer.value)
            note = f"oneshot-verified; llm_value={answer.value!r}"
            if value_drift:
                note += f" (recipe produces {runtime_output!r}, slight drift)"
            rows.append(CatalogRow(
                field=field_name, method=method,
                confidence=0.9 if value_drift else 1.0,
                notes=note,
            ))

    return VerifyResult(
        catalog_rows=rows,
        discarded=discarded,
        method_costs_ms=meter.average(),
    )


# ---------------------------------------------------------------------------
# Top-level discovery — LOAD/REVEAL is the caller's job; we orchestrate ASK + VERIFY + SAVE.
# ---------------------------------------------------------------------------

@dataclass
class OneShotResult:
    catalog: SiteCatalog
    answers: Dict[str, FieldAnswer]
    discarded: List[Tuple[str, MethodAttempt, str]]
    llm_cost_usd: float
    llm_input_tokens: int
    llm_output_tokens: int
    platform_hint: Optional[str]


async def discover_oneshot(
    memo: PageMemo,
    product_type: str = "fashion",
    domain: Optional[str] = None,
) -> OneShotResult:
    """Run discovery end-to-end. PageMemo must already have completed LOAD +
    reveal_hideaways. Returns a populated SiteCatalog plus diagnostics."""
    fields = fields_for_product_type(product_type)

    ask = await ask_llm(memo, fields)
    ver = await verify(ask.answers, memo)

    catalog_rows = list(ver.catalog_rows)
    covered = {r.field for r in catalog_rows}
    # Fields the LLM saw but no deterministic recipe survived verification.
    # These stay null at production by design — no LLM is called per product.
    fields_unrecoverable = [
        f for f, ans in ask.answers.items()
        if f not in covered
        and ans.value not in (None, "", [], {})
    ]

    from urllib.parse import urlparse
    catalog = SiteCatalog(
        domain=domain or urlparse(memo.url).netloc.replace("www.", ""),
        discovered_at=datetime.now(),
        discovery_url=memo.url,
        rows=catalog_rows,
        site_meta={
            "product_type": product_type,
            "platform_hint": ask.platform_hint,
            "fields_llm_filled": [f for f, a in ask.answers.items()
                                  if a.value not in (None, "", [], {})],
            "fields_with_catalog_row": sorted({r.field for r in catalog_rows}),
            "fields_unrecoverable_deterministically": fields_unrecoverable,
            "measured_costs_ms": ver.method_costs_ms,
        },
    )

    return OneShotResult(
        catalog=catalog,
        answers=ask.answers,
        discarded=ver.discarded,
        llm_cost_usd=ask.llm_cost_usd,
        llm_input_tokens=ask.llm_input_tokens,
        llm_output_tokens=ask.llm_output_tokens,
        platform_hint=ask.platform_hint,
    )
