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


import base64
import logging

logger = logging.getLogger(__name__)


def _detect_count_from_vision(page, category_name: str, brand_instance, llm_handler) -> Optional[int]:
    """
    Stage 3: screenshot the top of the page and ask the vision LLM for the
    count. On high-confidence responses with a non-null selector, cache the
    selector on brand_instance for cheap reuse on subsequent categories.

    Returns the count, or None if the LLM couldn't find one.
    """
    from prompts.collection_count_detection import CollectionCountResponse, get_prompt

    try:
        screenshot_bytes = page.screenshot(
            clip={"x": 0, "y": 0, "width": 1280, "height": 900},
            type="png",
        )
    except Exception as e:
        logger.warning(f"Screenshot failed for vision count detection: {e}")
        return None

    image_b64 = base64.standard_b64encode(screenshot_bytes).decode("ascii")
    prompt = get_prompt(category_name)

    try:
        result = llm_handler.call_with_image(
            prompt=prompt,
            image_b64=image_b64,
            media_type="image/png",
            max_tokens=1000,
            operation="collection_count_detection",
        )
    except Exception as e:
        logger.warning(f"Vision LLM call failed: {e}")
        return None

    if not result.get("success"):
        return None

    response_text = result.get("response", "")
    parsed = _parse_vision_response(response_text)
    if parsed is None:
        return None

    count = parsed.count
    if count is None or not (_MIN_PLAUSIBLE_COUNT <= count <= _MAX_PLAUSIBLE_COUNT):
        return None

    if brand_instance and parsed.selector and parsed.confidence == "high":
        brand_instance.collection_count_selector = parsed.selector
        brand_instance._count_selector_miss_count = 0

    return count


def _parse_vision_response(response_text: str):
    """Parse the LLM response into a CollectionCountResponse. Returns None on failure."""
    from prompts.collection_count_detection import CollectionCountResponse

    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

    try:
        data = json.loads(text)
        return CollectionCountResponse(**data)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"Failed to parse vision response: {e}; response was: {response_text[:200]}")
        return None


def detect_collection_count(page, category_name: str, brand_instance, llm_handler) -> Optional[CountResult]:
    """
    Three-stage collection count detection.

    Stage 1: JSON-LD structured data (free, instant).
    Stage 2: Brand-cached CSS selector (free if cache hit).
    Stage 3: Vision LLM screenshot of the page (paid; caches a selector for next time).

    Returns CountResult(count, source) or None if the count is honestly unknown.
    """
    n = _detect_count_from_jsonld(page)
    if n is not None:
        return CountResult(count=n, source="jsonld")

    n = _detect_count_from_cached_selector(page, brand_instance)
    if n is not None:
        return CountResult(count=n, source="cached_selector")

    n = _detect_count_from_vision(page, category_name, brand_instance, llm_handler)
    if n is not None:
        return CountResult(count=n, source="vision")

    return None
