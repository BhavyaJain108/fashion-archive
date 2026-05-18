"""
Collection Count Detection
==========================

Detects the displayed product count on collection pages using a three-stage
fallback: JSON-LD structured data, then a brand-cached CSS selector, then a
vision LLM call. Returns None when the count cannot be determined.

See docs/superpowers/specs/2026-05-14-collection-count-coverage-design.md
"""

import json
from dataclasses import dataclass
from typing import Any, List, Literal, Optional


@dataclass
class CountResult:
    """A detected product count and the stage that produced it."""
    count: int
    source: Literal["jsonld", "cached_selector", "vision"]


_MIN_PLAUSIBLE_COUNT = 1
_MAX_PLAUSIBLE_COUNT = 10_000


def _extract_count_from_jsonld_objects(objects: List[Any]) -> Optional[int]:
    """
    Walk a list of parsed JSON-LD objects looking for a plausible product count.

    Strategy: collect every plausible `numberOfItems` value found anywhere in
    the tree (including inside `@graph`, `mainEntity`, `hasPart`, nested lists),
    then return the LARGEST one. The main product grid is typically larger than
    side sections (related products, breadcrumbs), so max() is a reasonable
    heuristic when multiple ItemLists are present.

    Returns None if no plausible count is found.
    """
    candidates: List[int] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            n = node.get("numberOfItems")
            if isinstance(n, int) and _MIN_PLAUSIBLE_COUNT <= n <= _MAX_PLAUSIBLE_COUNT:
                t = node.get("@type", "")
                if isinstance(t, str) and ("ItemList" in t or "Collection" in t or "Catalog" in t):
                    candidates.append(n)
                elif t == "":
                    candidates.append(n)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for obj in objects:
        _walk(obj)

    if not candidates:
        return None
    return max(candidates)


_JSONLD_QUERY_JS = """
    Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
        .map(s => s.textContent)
        .filter(t => t && t.trim().length > 0)
"""


def _detect_count_from_jsonld(page) -> Optional[int]:
    """
    Stage 1: parse all <script type="application/ld+json"> blocks on the page
    and look for a plausible product count.

    Robust to malformed JSON: silently skips bad blocks rather than raising.
    """
    try:
        script_texts = page.evaluate(_JSONLD_QUERY_JS)
    except Exception:
        return None

    objects: List[Any] = []
    for text in script_texts or []:
        try:
            obj = json.loads(text)
            objects.append(obj)
        except (json.JSONDecodeError, TypeError):
            continue

    return _extract_count_from_jsonld_objects(objects)


import re

_INVALIDATE_AFTER_MISSES = 3


def _detect_count_from_cached_selector(page, brand_instance) -> Optional[int]:
    """
    Stage 2: query the brand's cached CSS selector for the count. Parse the
    first integer from its textContent.

    Increments brand_instance._count_selector_miss_count on failure. After 3
    consecutive misses, clears brand_instance.collection_count_selector so
    Stage 3 (vision) runs again.

    Returns None if no cached selector exists or the lookup failed.
    """
    if not brand_instance:
        return None
    selector = getattr(brand_instance, "collection_count_selector", None)
    if not selector:
        return None

    try:
        text = page.evaluate(
            f"document.querySelector({json.dumps(selector)})?.textContent"
        )
    except Exception:
        text = None

    count = _parse_first_int(text) if isinstance(text, str) else None

    if count is not None and _MIN_PLAUSIBLE_COUNT <= count <= _MAX_PLAUSIBLE_COUNT:
        brand_instance._count_selector_miss_count = 0
        return count

    brand_instance._count_selector_miss_count += 1
    if brand_instance._count_selector_miss_count >= _INVALIDATE_AFTER_MISSES:
        brand_instance.collection_count_selector = None
        brand_instance._count_selector_miss_count = 0
    return None


def _parse_first_int(text: Optional[str]) -> Optional[int]:
    """Return the first integer found in text, or None."""
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None
