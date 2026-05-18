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
