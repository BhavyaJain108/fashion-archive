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
import time
from datetime import datetime, timezone
from typing import Any, cast

from backend.archive.domain.recipe import RECIPE_KINDS, Recipe, RecipeBook
from backend.archive.finder import apply_recipes, is_plausible, verify_recipe

MODEL = os.getenv("FINDER_MODEL", "claude-sonnet-5")
_MAX_HTML = 110_000  # chars of trimmed page sent to the model (~28k tokens)
# Cutting the page too short makes the model guess values it cannot see, and a wrong
# prediction kills an otherwise correct rule at verification (live: psylos1 2026-08-30,
# where the size buttons sat past a 60k cut). The cap was 220k, and a heavy page cost
# 17–20 cents a call against 1.5 for a light one. The cap is half that now because
# `prepare_page` first removes what no rule can point at — scripts, styles, SVG paths,
# comments, inline handlers, theme-builder data blobs — and, when the page marks where
# the product is, keeps that region rather than the header, mega-menu and footer
# around it. The size buttons that sat past 60k of raw markup sit well inside 110k of
# trimmed markup; what was cut was never markup a selector lands on.

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
- The HTML below has had scripts, styles, SVG paths, comments and inline handlers
  removed, and may be only the page's product region with its <meta> tags and JSON-LD.
  Your rule is replayed on the WHOLE page as the shop served it, so anchor selectors
  on the product's own containers rather than on being the first match in the page.

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
    prompt = _PROMPT.format(fields=", ".join(missing_fields), url=url, html=prepare_page(html))
    proposed = _to_recipes(client.propose(prompt))

    # Replayed on the page as fetched, never on the trimmed copy: a rule is applied
    # to untrimmed pages for the rest of the brand's life, so that is where it must
    # hold, and a selector the model wrote against the trimmed copy that only works
    # there is exactly what this throws out.
    kept = [r for r in proposed if r.field in missing_fields and _holds_up(r, html)]
    return RecipeBook(domain=domain, learned_at=now, learned_from_url=url, recipes=kept)


# A rule that takes longer than this on the page it was learned from will take as
# long on every product page of the brand, every run. Not worth keeping.
MAX_RULE_SECONDS = 0.25


def _holds_up(r: Recipe, html: str) -> bool:
    """Replay the proposal on its own page: it must reproduce the value it predicted,
    the value must look like the field, and it must do so quickly."""
    started = time.monotonic()
    ok = verify_recipe(r, html) and is_plausible(r.field, apply_recipes(html, [r]).get(r.field, ""))
    return ok and (time.monotonic() - started) <= MAX_RULE_SECONDS


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


# --- what the model is shown ---------------------------------------------------------
#
# The model's job is to point at markup: a CSS selector, a regex over the page, a
# path into the JSON-LD. Everything below removes what none of those can usefully
# point at, so the tokens paid for are the ones a rule can be learned from.

_DROP = re.compile(r"<(script|style|svg|noscript)\b.*?</\1\s*>", re.S | re.I)
_IS_LD = re.compile(r"""<script[^>]*type\s*=\s*["']?application/ld\+json""", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# style="…", every on*="…" handler, and sizes="(min-width…)": presentation and
# behaviour, never a value.
_JUNK_ATTR = re.compile(r"""\s(?:style|on[a-z]+|sizes)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_DATA_ATTR = re.compile(r"""\s(data-[\w:.-]+)\s*=\s*("[^"]*"|'[^']*')""", re.I)
# A srcset is one image at twelve widths. The rule the model writes reads the
# attribute; its "expected" may be the first entry or two, and replay accepts a value
# that begins with what was written — so the first two candidates are all it needs.
_SRCSET = re.compile(r"""\s((?:data-)?srcset)\s*=\s*"([^"]*)\"""", re.I)
_SRCSET_KEEP = 2
# Stylesheets, preloads, icons: the head's plumbing. canonical and alternate stay.
_PLUMBING_LINK = re.compile(
    r"""<link\b[^>]*\brel\s*=\s*["']?(?:stylesheet|preload|modulepreload|preconnect|"""
    r"""dns-prefetch|prefetch|icon|apple-touch-icon|manifest)\b[^>]*>""",
    re.I,
)
_WS = re.compile(r"\s+")
_TAG_END = re.compile(r"\s+(/?>)")
# A data-* value longer than this is kept only if it looks like it is about the
# product: Elementor's data-settings and a theme's data-section-settings are JSON
# about layout; WooCommerce's data-product_variations is the size table.
_LONG_DATA = 120
_PRODUCT_WORDS = (
    "product",
    "variant",
    "size",
    "price",
    "sku",
    "color",
    "colour",
    "image",
    "img",
    "src",
    "gallery",
    "media",
    "stock",
    "avail",
    "option",
    "swatch",
    "inventory",
    "quantity",
    "sold",
)
_URLISH = ("http", "//", ".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")
# Where the product is, when a page says so. Tried in order; the first that is found
# and holds a real amount of markup wins.
_REGION_OPENERS = (
    re.compile(r"<main\b[^>]*>", re.I),
    re.compile(
        r"""<(?:div|section|article|form)\b[^>]*itemtype\s*=\s*["'][^"']*Product["']""", re.I
    ),
    re.compile(
        r"""<(?:div|section|article|form)\b[^>]*\b(?:id|class)\s*=\s*["'][^"']*\b(?:"""
        r"product-single|product-page|product__info|product-detail|product-details|"
        r"product-template|product-main|main-product|product__wrapper|product-container|"
        r"productView|product-view|single-product|pdp"
        r""")\b[^"']*["']""",
        re.I,
    ),
)
_MIN_REGION = 3_000  # a "main" with less than this is an app shell, not the product


def _drop_noise(m: re.Match) -> str:
    return m.group(0) if _IS_LD.match(m.group(0)) else " "


def _data_attr(m: re.Match) -> str:
    name, quoted = m.group(1), m.group(2)
    value = quoted[1:-1]
    if len(value) <= _LONG_DATA:
        return m.group(0)
    lowered = name.lower()
    if any(w in lowered for w in _PRODUCT_WORDS):
        return m.group(0)
    v = value.lower()
    if any(u in v for u in _URLISH):
        return m.group(0)
    return ""


def _srcset(m: re.Match) -> str:
    candidates = [c.strip() for c in m.group(2).split(",") if c.strip()]
    if len(candidates) <= _SRCSET_KEEP:
        return m.group(0)
    return f' {m.group(1)}="{", ".join(candidates[:_SRCSET_KEEP])}"'


def _close_of(html: str, tag: str, start: int) -> int | None:
    """Index just past the closing tag that balances the opener at `start`."""
    step = re.compile(rf"<(/?){tag}\b[^>]*>", re.I)
    depth = 0
    for m in step.finditer(html, start):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()
    return None


def _product_region(html: str) -> str | None:
    for opener in _REGION_OPENERS:
        m = opener.search(html)
        if not m:
            continue
        tag = re.match(r"<([a-z]+)", m.group(0), re.I)
        end = _close_of(html, tag.group(1), m.start()) if tag else None
        if end is not None and end - m.start() >= _MIN_REGION:
            return html[m.start() : end]
    return None


def trim_page(html: str) -> str:
    """The page with everything a rule cannot point at removed. No cap, no cut."""
    out = _COMMENT.sub(" ", html)
    out = _DROP.sub(_drop_noise, out)
    out = _PLUMBING_LINK.sub(" ", out)
    out = _JUNK_ATTR.sub("", out)
    out = _DATA_ATTR.sub(_data_attr, out)
    out = _SRCSET.sub(_srcset, out)
    return _TAG_END.sub(r"\1", _WS.sub(" ", out)).strip()


_HEAD_KEEP = re.compile(r"<(?:title\b[^>]*>.*?</title|meta\b[^>]*)>", re.S | re.I)


def prepare_page(html: str, cap: int = _MAX_HTML) -> str:
    """What the model is sent: the trimmed page, or — when the page marks where the
    product is — the head's meta tags, the JSON-LD and that region, without the
    header, mega-menu and footer around it. Then the cap.

    Always the region when there is one, not only when the page is over the cap:
    a threshold made two pages of nearly the same size cost very different amounts,
    and a rule learned from the region holds on the whole page or is thrown out."""
    trimmed = trim_page(html)
    region = _product_region(trimmed)
    if region is not None:
        outside = trimmed.replace(region, " ", 1)
        head = _HEAD_KEEP.findall(outside)
        ld = [
            m.group(0)
            for m in re.finditer(r"<script\b[^>]*>.*?</script\s*>", outside, re.S | re.I)
            if _IS_LD.match(m.group(0))
        ]
        trimmed = " ".join([*head, *ld[:3], region])
    return trimmed[:cap]


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
            # Forced tool use means the answer is a tool_use block; the others in the
            # union carry no input to read.
            if block.type == "tool_use":
                return cast(dict, block.input)
        return {}


def _default_client(spend=None):
    return _AnthropicClient(spend=spend)
