# Collection Count & Coverage Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect the displayed product count on collection pages and use it as a ground-truth signal to (a) hint the LLM classifier, (b) invalidate stale lineage memory, and (c) verify post-extraction coverage with retries.

**Architecture:** Three-stage count detection (JSON-LD → cached selector → vision LLM) wired into `_scroll_and_extract_links`. Count flows through `classify_product_links` as `expected_count`, gating the lineage-memory cache and shaping the LLM prompt. After classification, `extract_urls_from_category` runs a coverage check that triggers up to 2 retries on LOW coverage or 1 re-classification on HIGH. A per-brand summary table is the user's verification surface.

**Tech Stack:** Python 3, Playwright (sync API), Anthropic SDK (vision), pydantic for structured LLM output. Spec: `docs/superpowers/specs/2026-05-14-collection-count-coverage-design.md`.

**Working directory:** `/Users/bhavyajain/Code/fashion_archive/.claude/worktrees/nifty-meitner-35601f` (all paths below are relative to this).

---

## File Structure

**New files:**
- `backend/scraper/count_detection.py` — All count-detection logic (`CountResult`, `detect_collection_count`, the three stage functions). Kept in its own file so `url_extractor.py` doesn't grow further and the count logic stays self-contained.
- `backend/scraper/prompts/collection_count_detection.py` — Vision LLM prompt + pydantic response model (mirrors existing prompt files).
- `backend/scraper/tests/test_count_detection.py` — Unit tests for JSON-LD walker and cached-selector logic (no Playwright; uses fake page objects).
- `backend/scraper/tests/fixtures/jsonld_samples.py` — Synthetic JSON-LD fixtures (well-formed `ItemList`, nested `CollectionPage`, malformed JSON, missing fields).

**Modified files:**
- `backend/scraper/brand.py` — Add `collection_count_selector` and `_count_selector_miss_count` attributes.
- `backend/scraper/url_extractor.py` — Add `expected_count`/`expected_count_source`/`coverage_status`/`coverage_retries` to `URLExtractionResult`; call `detect_collection_count` in `_scroll_and_extract_links`; add `expected_count` parameter to `classify_product_links` with memory-gate logic; add coverage check + retry loop to `extract_urls_from_category`.
- `backend/scraper/prompts/url_classification.py` — Accept and use `expected_count` in the prompt.
- `backend/stages/urls.py` — Print brand-level coverage summary table at the end of stage 2.

---

## Conventions used throughout this plan

**Running tests** — From the worktree root: `cd backend && python -m pytest scraper/tests/test_count_detection.py -v`. The repo's other tests are run with `python <test_file>.py` (legacy pattern) — for new unit tests we use pytest.

**Commits** — Frequent, one logical change each. Use a `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` trailer.

**Imports added in each task** — Always show the new `import` lines explicitly in the code blocks; don't assume they're already present.

**`brand_instance` may be None** — The classifier and `_scroll_and_extract_links` are called from tests with `brand_instance=None`. Always guard `brand_instance` accesses with `if brand_instance:`.

---

## Task 1: Add Brand attributes for count-selector caching

**Files:**
- Modify: `backend/scraper/brand.py` (around line 145, after pagination cache block)

- [ ] **Step 1: Write a failing test**

Create `backend/scraper/tests/test_count_detection.py`:

```python
"""Unit tests for collection count detection."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brand import Brand


def test_brand_has_collection_count_selector_attribute():
    """New attributes should exist on Brand with correct defaults."""
    b = Brand("https://example.com")
    assert b.collection_count_selector is None
    assert b._count_selector_miss_count == 0


if __name__ == "__main__":
    test_brand_has_collection_count_selector_attribute()
    print("✅ all passed")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `AttributeError: 'Brand' object has no attribute 'collection_count_selector'`

- [ ] **Step 3: Add attributes to Brand**

In `backend/scraper/brand.py`, find the block:

```python
        # Pagination cache: reuse pagination pattern across categories
        self.pagination_pattern: Optional[Dict] = None  # {url_pattern, pagination_type} from first detection
        self._pagination_lock = threading.Lock()
```

Immediately after `self._pagination_lock = threading.Lock()`, insert:

```python
        # Collection count selector cache: reuse across categories.
        # _count_selector_miss_count tracks consecutive failed lookups for 3-strike invalidation.
        self.collection_count_selector: Optional[str] = None
        self._count_selector_miss_count: int = 0
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `✅ all passed`

- [ ] **Step 5: Commit**

```bash
git add backend/scraper/brand.py backend/scraper/tests/test_count_detection.py
git commit -m "$(cat <<'EOF'
Add collection_count_selector cache attributes to Brand

Brand instances now carry a cached CSS selector for the displayed
product count plus a miss counter for 3-strike cache invalidation.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Define `CountResult` dataclass

**Files:**
- Create: `backend/scraper/count_detection.py`

- [ ] **Step 1: Add failing test for the dataclass**

Append to `backend/scraper/tests/test_count_detection.py`:

```python
def test_count_result_dataclass():
    """CountResult should be a frozen-ish dataclass with count and source."""
    from count_detection import CountResult
    r = CountResult(count=47, source="jsonld")
    assert r.count == 47
    assert r.source == "jsonld"


if __name__ == "__main__":
    test_brand_has_collection_count_selector_attribute()
    test_count_result_dataclass()
    print("✅ all passed")
```

- [ ] **Step 2: Run, expect fail**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `ModuleNotFoundError: No module named 'count_detection'`

- [ ] **Step 3: Create `count_detection.py` with `CountResult`**

Create `backend/scraper/count_detection.py`:

```python
"""
Collection Count Detection
==========================

Detects the displayed product count on collection pages using a three-stage
fallback: JSON-LD structured data, then a brand-cached CSS selector, then a
vision LLM call. Returns None when the count cannot be determined.

See docs/superpowers/specs/2026-05-14-collection-count-coverage-design.md
"""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class CountResult:
    """A detected product count and the stage that produced it."""
    count: int
    source: Literal["jsonld", "cached_selector", "vision"]
```

- [ ] **Step 4: Run, expect pass**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `✅ all passed`

- [ ] **Step 5: Commit**

```bash
git add backend/scraper/count_detection.py backend/scraper/tests/test_count_detection.py
git commit -m "$(cat <<'EOF'
Add CountResult dataclass and count_detection module skeleton

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: JSON-LD walker (pure function, fully unit-testable)

**Files:**
- Create: `backend/scraper/tests/fixtures/__init__.py` (empty)
- Create: `backend/scraper/tests/fixtures/jsonld_samples.py`
- Modify: `backend/scraper/count_detection.py`
- Modify: `backend/scraper/tests/test_count_detection.py`

- [ ] **Step 1: Create fixtures**

Create `backend/scraper/tests/fixtures/__init__.py` (empty file).

Create `backend/scraper/tests/fixtures/jsonld_samples.py`:

```python
"""Synthetic JSON-LD samples for testing the count walker."""

FLAT_ITEMLIST = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    "numberOfItems": 47,
}

NESTED_COLLECTION_PAGE = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    "name": "Hoodies",
    "mainEntity": {
        "@type": "ItemList",
        "numberOfItems": 32,
        "itemListElement": [],
    },
}

TWO_ITEMLISTS_PICK_LARGEST = [
    {"@type": "ItemList", "numberOfItems": 5, "name": "Related"},
    {"@type": "ItemList", "numberOfItems": 47, "name": "Main grid"},
]

GRAPH_WITH_ITEMLIST = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "BreadcrumbList", "itemListElement": []},
        {"@type": "ItemList", "numberOfItems": 12},
    ],
}

MISSING_NUMBEROFITEMS = {
    "@type": "ItemList",
    "itemListElement": [{"@type": "Product"}, {"@type": "Product"}],
}

IMPLAUSIBLE_COUNT = {
    "@type": "ItemList",
    "numberOfItems": 999999,
}

NEGATIVE_COUNT = {
    "@type": "ItemList",
    "numberOfItems": -3,
}

NOT_AN_ITEMLIST = {
    "@type": "Product",
    "name": "Hoodie",
    "offers": {"@type": "Offer", "price": "47.00"},
}
```

- [ ] **Step 2: Add failing tests for the walker**

Append to `backend/scraper/tests/test_count_detection.py`:

```python
def test_jsonld_walker_flat_itemlist():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import FLAT_ITEMLIST
    assert _extract_count_from_jsonld_objects([FLAT_ITEMLIST]) == 47


def test_jsonld_walker_nested_collection_page():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import NESTED_COLLECTION_PAGE
    assert _extract_count_from_jsonld_objects([NESTED_COLLECTION_PAGE]) == 32


def test_jsonld_walker_picks_largest_when_multiple():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import TWO_ITEMLISTS_PICK_LARGEST
    assert _extract_count_from_jsonld_objects(TWO_ITEMLISTS_PICK_LARGEST) == 47


def test_jsonld_walker_graph_array():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import GRAPH_WITH_ITEMLIST
    assert _extract_count_from_jsonld_objects([GRAPH_WITH_ITEMLIST]) == 12


def test_jsonld_walker_no_numberofitems_returns_none():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import MISSING_NUMBEROFITEMS
    assert _extract_count_from_jsonld_objects([MISSING_NUMBEROFITEMS]) is None


def test_jsonld_walker_implausible_count_returns_none():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import IMPLAUSIBLE_COUNT, NEGATIVE_COUNT
    assert _extract_count_from_jsonld_objects([IMPLAUSIBLE_COUNT]) is None
    assert _extract_count_from_jsonld_objects([NEGATIVE_COUNT]) is None


def test_jsonld_walker_unrelated_schema_returns_none():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import NOT_AN_ITEMLIST
    assert _extract_count_from_jsonld_objects([NOT_AN_ITEMLIST]) is None


def test_jsonld_walker_handles_empty_list():
    from count_detection import _extract_count_from_jsonld_objects
    assert _extract_count_from_jsonld_objects([]) is None


if __name__ == "__main__":
    test_brand_has_collection_count_selector_attribute()
    test_count_result_dataclass()
    test_jsonld_walker_flat_itemlist()
    test_jsonld_walker_nested_collection_page()
    test_jsonld_walker_picks_largest_when_multiple()
    test_jsonld_walker_graph_array()
    test_jsonld_walker_no_numberofitems_returns_none()
    test_jsonld_walker_implausible_count_returns_none()
    test_jsonld_walker_unrelated_schema_returns_none()
    test_jsonld_walker_handles_empty_list()
    print("✅ all passed")
```

- [ ] **Step 3: Run, expect fail**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `ImportError: cannot import name '_extract_count_from_jsonld_objects'`

- [ ] **Step 4: Implement the walker**

Append to `backend/scraper/count_detection.py`:

```python
from typing import Any, List, Optional

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
            # Check this node for numberOfItems
            n = node.get("numberOfItems")
            if isinstance(n, int) and _MIN_PLAUSIBLE_COUNT <= n <= _MAX_PLAUSIBLE_COUNT:
                # Only count it if this node looks like an ItemList-ish thing.
                # The @type check avoids false positives from unrelated schemas
                # that happen to have a numberOfItems property.
                t = node.get("@type", "")
                if isinstance(t, str) and ("ItemList" in t or "Collection" in t or "Catalog" in t):
                    candidates.append(n)
                elif t == "":
                    # Untyped object with numberOfItems — accept conservatively
                    candidates.append(n)
            # Recurse into all values
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
```

- [ ] **Step 5: Run, expect pass**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `✅ all passed`

- [ ] **Step 6: Commit**

```bash
git add backend/scraper/count_detection.py backend/scraper/tests/test_count_detection.py backend/scraper/tests/fixtures/
git commit -m "$(cat <<'EOF'
Add JSON-LD walker for collection count detection

Walks parsed JSON-LD objects looking for ItemList/Collection/Catalog
nodes with a plausible numberOfItems value. Returns the largest
plausible count found, or None.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: JSON-LD stage function (parses script tags, calls the walker)

**Files:**
- Modify: `backend/scraper/count_detection.py`
- Modify: `backend/scraper/tests/test_count_detection.py`

- [ ] **Step 1: Add failing tests using a fake page**

Append to `backend/scraper/tests/test_count_detection.py`:

```python
class _FakePage:
    """A minimal page stand-in for testing the JSON-LD stage."""
    def __init__(self, jsonld_strings):
        self._jsonld_strings = jsonld_strings

    def evaluate(self, _js):
        # Return what page.evaluate would return: a list of textContent strings
        return self._jsonld_strings


def test_jsonld_stage_returns_count_for_well_formed():
    from count_detection import _detect_count_from_jsonld
    page = _FakePage(['{"@type":"ItemList","numberOfItems":47}'])
    assert _detect_count_from_jsonld(page) == 47


def test_jsonld_stage_returns_none_when_no_scripts():
    from count_detection import _detect_count_from_jsonld
    page = _FakePage([])
    assert _detect_count_from_jsonld(page) is None


def test_jsonld_stage_skips_malformed_json():
    from count_detection import _detect_count_from_jsonld
    page = _FakePage([
        'not valid json {',
        '{"@type":"ItemList","numberOfItems":24}',
    ])
    assert _detect_count_from_jsonld(page) == 24


def test_jsonld_stage_returns_none_when_only_malformed():
    from count_detection import _detect_count_from_jsonld
    page = _FakePage(['not valid', '{also not valid'])
    assert _detect_count_from_jsonld(page) is None


if __name__ == "__main__":
    test_brand_has_collection_count_selector_attribute()
    test_count_result_dataclass()
    test_jsonld_walker_flat_itemlist()
    test_jsonld_walker_nested_collection_page()
    test_jsonld_walker_picks_largest_when_multiple()
    test_jsonld_walker_graph_array()
    test_jsonld_walker_no_numberofitems_returns_none()
    test_jsonld_walker_implausible_count_returns_none()
    test_jsonld_walker_unrelated_schema_returns_none()
    test_jsonld_walker_handles_empty_list()
    test_jsonld_stage_returns_count_for_well_formed()
    test_jsonld_stage_returns_none_when_no_scripts()
    test_jsonld_stage_skips_malformed_json()
    test_jsonld_stage_returns_none_when_only_malformed()
    print("✅ all passed")
```

- [ ] **Step 2: Run, expect fail**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `ImportError: cannot import name '_detect_count_from_jsonld'`

- [ ] **Step 3: Implement `_detect_count_from_jsonld`**

Append to `backend/scraper/count_detection.py`:

```python
import json

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
```

- [ ] **Step 4: Run, expect pass**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `✅ all passed`

- [ ] **Step 5: Commit**

```bash
git add backend/scraper/count_detection.py backend/scraper/tests/test_count_detection.py
git commit -m "$(cat <<'EOF'
Add JSON-LD stage: query script tags and parse for product count

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Cached-selector stage with 3-strike invalidation

**Files:**
- Modify: `backend/scraper/count_detection.py`
- Modify: `backend/scraper/tests/test_count_detection.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/scraper/tests/test_count_detection.py`:

```python
class _FakePageWithSelector(_FakePage):
    """Fake page that returns a textContent value for a queryable selector."""
    def __init__(self, selector_text):
        super().__init__([])
        self._selector_text = selector_text  # dict {selector: text} or None

    def evaluate(self, js):
        # If js looks like a querySelector with JSON.stringify(selector), return mapped text
        if 'querySelector' in js:
            # Tests build pages keyed by the selector; return whatever was registered.
            return self._selector_text
        return []


def test_cached_selector_returns_count_when_text_has_number():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector("47 products")
    assert _detect_count_from_cached_selector(page, b) == 47
    assert b._count_selector_miss_count == 0


def test_cached_selector_returns_none_when_no_selector():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    page = _FakePageWithSelector("47 products")
    assert _detect_count_from_cached_selector(page, b) is None


def test_cached_selector_increments_miss_count_on_no_text():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector(None)
    assert _detect_count_from_cached_selector(page, b) is None
    assert b._count_selector_miss_count == 1


def test_cached_selector_invalidates_after_three_misses():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector(None)
    for _ in range(3):
        _detect_count_from_cached_selector(page, b)
    assert b.collection_count_selector is None  # invalidated
    assert b._count_selector_miss_count == 0  # reset


def test_cached_selector_returns_none_for_implausible_number():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector("999999 reviews")
    assert _detect_count_from_cached_selector(page, b) is None
    assert b._count_selector_miss_count == 1
```

Also extend the `__main__` block with these 5 new test calls (mirroring earlier pattern).

- [ ] **Step 2: Run, expect fail**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `ImportError: cannot import name '_detect_count_from_cached_selector'`

- [ ] **Step 3: Implement**

Append to `backend/scraper/count_detection.py`:

```python
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
        # The fake-page test stubs evaluate() so it returns text directly.
        # In production this is the textContent of the matched element or None.
        text = page.evaluate(
            f"document.querySelector({json.dumps(selector)})?.textContent"
        )
    except Exception:
        text = None

    count = _parse_first_int(text) if isinstance(text, str) else None

    if count is not None and _MIN_PLAUSIBLE_COUNT <= count <= _MAX_PLAUSIBLE_COUNT:
        brand_instance._count_selector_miss_count = 0
        return count

    # Miss: increment and possibly invalidate
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
```

- [ ] **Step 4: Run, expect pass**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `✅ all passed`

- [ ] **Step 5: Commit**

```bash
git add backend/scraper/count_detection.py backend/scraper/tests/test_count_detection.py
git commit -m "$(cat <<'EOF'
Add cached-selector stage with 3-strike cache invalidation

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Vision LLM prompt module

**Files:**
- Create: `backend/scraper/prompts/collection_count_detection.py`

- [ ] **Step 1: Create the prompt module**

Create `backend/scraper/prompts/collection_count_detection.py`:

```python
"""
Collection Count Detection Prompt
=================================

Vision LLM prompt for identifying the displayed product count on a
collection page. Returns the count (or null) plus a reusable CSS
selector that yields the count, plus a confidence label.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class CollectionCountResponse(BaseModel):
    """Structured output for collection count vision detection."""
    count: Optional[int] = Field(
        description="Total products displayed in this collection. Null if no count is visible."
    )
    selector: Optional[str] = Field(
        description="CSS selector that reliably yields the count element on this site, "
                    "e.g. '.collection-count', '[data-product-count]', '.results-count'. "
                    "Null if you cannot identify a stable, reusable selector."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Your confidence in the detected count."
    )
    reasoning: str = Field(
        description="Brief: where on the page the count was found, or why it wasn't found."
    )


def get_prompt(category_name: str) -> str:
    """Generate the vision prompt for collection count detection."""
    return f"""
You are looking at the top of an e-commerce collection page for the category "{category_name}".

Your task: identify the total number of products this collection contains, as displayed on the page.

Look for:
- A number next to or near the page title (e.g., "Hoodies (47)")
- A count badge anywhere visible (e.g., "47 products", "47 items", "47 styles", "47 results")
- "Showing X of Y" or "X–Y of Z" text — the Z is the total
- Sort/filter bars often contain the total count

Ignore:
- Prices, discount percentages, sizes, ratings, review counts
- "Free shipping over $X" messaging
- Numbers in promotional banners

Return:
- count: the integer total, or null if no such count is visible
- selector: a CSS selector that would reliably yield this count element on other category pages of this same site (so we can reuse it). Null if no stable selector is apparent.
- confidence: "high" if you're certain, "medium" if the count is plausible but ambiguous, "low" if you're guessing.
- reasoning: one sentence on where you saw the count (or why you couldn't).
""".strip()
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd backend && python -c "from scraper.prompts.collection_count_detection import CollectionCountResponse, get_prompt; print(get_prompt('Hoodies')[:80])"
```

Expected: prints the first 80 characters of the prompt.

- [ ] **Step 3: Commit**

```bash
git add backend/scraper/prompts/collection_count_detection.py
git commit -m "$(cat <<'EOF'
Add vision LLM prompt for collection count detection

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Vision stage function (screenshot + LLM call)

**Files:**
- Modify: `backend/scraper/count_detection.py`
- Modify: `backend/scraper/tests/test_count_detection.py`

This stage uses a real LLM and Playwright in production, so we test it with mocks. We assert that the function correctly parses the LLM response, caches the selector when confidence is high, and handles failures.

- [ ] **Step 1: Add failing tests with a fake LLM handler**

Append to `backend/scraper/tests/test_count_detection.py`:

```python
class _FakeLLMHandler:
    """Captures the call and returns a canned response dict."""
    def __init__(self, canned_response):
        self._canned = canned_response
        self.last_prompt = None
        self.last_image_b64 = None

    def call_with_image(self, prompt, image_b64, media_type="image/png",
                        max_tokens=8000, operation="vision_call"):
        self.last_prompt = prompt
        self.last_image_b64 = image_b64
        return self._canned


class _FakePageScreenshot:
    """Fake page with a screenshot() method returning bytes."""
    def screenshot(self, **kwargs):
        return b"\x89PNG\r\n\x1a\nfake-screenshot-bytes"


def test_vision_stage_returns_count_and_caches_selector_on_high_confidence():
    from count_detection import _detect_count_from_vision
    from brand import Brand
    b = Brand("https://example.com")
    llm = _FakeLLMHandler({
        "success": True,
        "response": '{"count":47,"selector":".collection-count","confidence":"high","reasoning":"saw it"}',
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })
    page = _FakePageScreenshot()

    count = _detect_count_from_vision(page, "Hoodies", b, llm)
    assert count == 47
    assert b.collection_count_selector == ".collection-count"


def test_vision_stage_does_not_cache_on_medium_confidence():
    from count_detection import _detect_count_from_vision
    from brand import Brand
    b = Brand("https://example.com")
    llm = _FakeLLMHandler({
        "success": True,
        "response": '{"count":47,"selector":".count","confidence":"medium","reasoning":"maybe"}',
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })
    page = _FakePageScreenshot()

    count = _detect_count_from_vision(page, "Hoodies", b, llm)
    assert count == 47
    assert b.collection_count_selector is None  # not cached


def test_vision_stage_returns_none_when_llm_returns_null_count():
    from count_detection import _detect_count_from_vision
    from brand import Brand
    b = Brand("https://example.com")
    llm = _FakeLLMHandler({
        "success": True,
        "response": '{"count":null,"selector":null,"confidence":"low","reasoning":"no count visible"}',
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })
    page = _FakePageScreenshot()

    count = _detect_count_from_vision(page, "Hoodies", b, llm)
    assert count is None
    assert b.collection_count_selector is None


def test_vision_stage_returns_none_on_llm_failure():
    from count_detection import _detect_count_from_vision
    from brand import Brand
    b = Brand("https://example.com")
    llm = _FakeLLMHandler({"success": False, "error": "API error"})
    page = _FakePageScreenshot()

    count = _detect_count_from_vision(page, "Hoodies", b, llm)
    assert count is None
```

Add these test calls to the `__main__` block.

- [ ] **Step 2: Run, expect fail**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `ImportError: cannot import name '_detect_count_from_vision'`

- [ ] **Step 3: Implement**

Append to `backend/scraper/count_detection.py`:

```python
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
    # Import here to avoid circular import at module load time
    from prompts.collection_count_detection import CollectionCountResponse, get_prompt

    # Screenshot the top viewport region
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

    # Cache the selector only if we're confident in it
    if brand_instance and parsed.selector and parsed.confidence == "high":
        brand_instance.collection_count_selector = parsed.selector
        brand_instance._count_selector_miss_count = 0

    return count


def _parse_vision_response(response_text: str):
    """Parse the LLM response into a CollectionCountResponse. Returns None on failure."""
    from prompts.collection_count_detection import CollectionCountResponse

    text = response_text.strip()
    # The LLM may wrap JSON in markdown code fences — strip them.
    if text.startswith("```"):
        # remove first fence line and trailing fence
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

    try:
        data = json.loads(text)
        return CollectionCountResponse(**data)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"Failed to parse vision response: {e}; response was: {response_text[:200]}")
        return None
```

- [ ] **Step 4: Run, expect pass**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `✅ all passed`

- [ ] **Step 5: Commit**

```bash
git add backend/scraper/count_detection.py backend/scraper/tests/test_count_detection.py
git commit -m "$(cat <<'EOF'
Add vision LLM stage for collection count detection

Screenshots the top viewport, sends to Claude with structured prompt,
parses JSON response, caches the selector when LLM is highly confident.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Public `detect_collection_count` orchestrator

**Files:**
- Modify: `backend/scraper/count_detection.py`
- Modify: `backend/scraper/tests/test_count_detection.py`

- [ ] **Step 1: Add failing tests for the orchestrator**

Append to `backend/scraper/tests/test_count_detection.py`:

```python
class _StagedFakePage:
    """Fake page that responds differently depending on what's queried."""
    def __init__(self, jsonld_texts=None, selector_text=None):
        self._jsonld = jsonld_texts or []
        self._selector_text = selector_text

    def evaluate(self, js):
        if 'application/ld+json' in js:
            return self._jsonld
        if 'querySelector' in js:
            return self._selector_text
        return None

    def screenshot(self, **kwargs):
        return b"\x89PNG\r\n\x1a\nfake"


def test_orchestrator_returns_jsonld_result_when_available():
    from count_detection import detect_collection_count, CountResult
    from brand import Brand
    b = Brand("https://example.com")
    page = _StagedFakePage(jsonld_texts=['{"@type":"ItemList","numberOfItems":47}'])
    llm = _FakeLLMHandler({"success": False})
    result = detect_collection_count(page, "Hoodies", b, llm)
    assert result == CountResult(count=47, source="jsonld")


def test_orchestrator_falls_through_to_cached_selector():
    from count_detection import detect_collection_count, CountResult
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _StagedFakePage(jsonld_texts=[], selector_text="32 items")
    llm = _FakeLLMHandler({"success": False})
    result = detect_collection_count(page, "Tops", b, llm)
    assert result == CountResult(count=32, source="cached_selector")


def test_orchestrator_falls_through_to_vision():
    from count_detection import detect_collection_count, CountResult
    from brand import Brand
    b = Brand("https://example.com")
    page = _StagedFakePage(jsonld_texts=[], selector_text=None)
    llm = _FakeLLMHandler({
        "success": True,
        "response": '{"count":18,"selector":".c","confidence":"high","reasoning":"x"}',
        "usage": {"input_tokens": 50, "output_tokens": 10},
    })
    result = detect_collection_count(page, "THORN", b, llm)
    assert result == CountResult(count=18, source="vision")


def test_orchestrator_returns_none_when_all_stages_miss():
    from count_detection import detect_collection_count
    from brand import Brand
    b = Brand("https://example.com")
    page = _StagedFakePage(jsonld_texts=[], selector_text=None)
    llm = _FakeLLMHandler({
        "success": True,
        "response": '{"count":null,"selector":null,"confidence":"low","reasoning":"none"}',
        "usage": {"input_tokens": 50, "output_tokens": 10},
    })
    assert detect_collection_count(page, "Mystery", b, llm) is None
```

Add these test calls to the `__main__` block.

- [ ] **Step 2: Run, expect fail**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `ImportError: cannot import name 'detect_collection_count'`

- [ ] **Step 3: Implement orchestrator**

Append to `backend/scraper/count_detection.py`:

```python
def detect_collection_count(page, category_name: str, brand_instance, llm_handler) -> Optional[CountResult]:
    """
    Three-stage collection count detection.

    Stage 1: JSON-LD structured data (free, instant).
    Stage 2: Brand-cached CSS selector (free if cache hit).
    Stage 3: Vision LLM screenshot of the page (paid; caches a selector for next time).

    Returns CountResult(count, source) or None if the count is honestly unknown.
    """
    # Stage 1
    n = _detect_count_from_jsonld(page)
    if n is not None:
        return CountResult(count=n, source="jsonld")

    # Stage 2
    n = _detect_count_from_cached_selector(page, brand_instance)
    if n is not None:
        return CountResult(count=n, source="cached_selector")

    # Stage 3
    n = _detect_count_from_vision(page, category_name, brand_instance, llm_handler)
    if n is not None:
        return CountResult(count=n, source="vision")

    return None
```

- [ ] **Step 4: Run, expect pass**

```bash
cd backend && python scraper/tests/test_count_detection.py
```

Expected: `✅ all passed`

- [ ] **Step 5: Commit**

```bash
git add backend/scraper/count_detection.py backend/scraper/tests/test_count_detection.py
git commit -m "$(cat <<'EOF'
Add detect_collection_count orchestrator (JSON-LD → selector → vision)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Extend `URLExtractionResult` with coverage fields

**Files:**
- Modify: `backend/scraper/url_extractor.py:130-158`

This task only adds fields with safe defaults. No behavior changes. We verify with an existing test that nothing regresses.

- [ ] **Step 1: Modify `URLExtractionResult` dataclass**

In `backend/scraper/url_extractor.py`, find the dataclass:

```python
@dataclass
class URLExtractionResult:
    """Result of URL extraction for a single category"""
    category_url: str
    category_name: str
    product_urls: List[ProductURL] = field(default_factory=list)
    pages_processed: int = 1
    extraction_time: float = 0.0
    llm_filtering_stats: Dict = field(default_factory=dict)
    llm_usage: Dict = field(default_factory=lambda: {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0
    })
    errors: List[str] = field(default_factory=list)
    discovery_info: Dict = field(default_factory=dict)  # Scroll/extraction stats
```

Insert these new fields after `discovery_info`:

```python
    # Coverage tracking (added 2026-05-14)
    expected_count: Optional[int] = None
    expected_count_source: Optional[str] = None  # "jsonld" | "cached_selector" | "vision" | None
    coverage_status: str = "unknown"             # "ok" | "low" | "high" | "unknown"
    coverage_retries: int = 0
```

Then update the `to_dict` method (in the same class) — replace the existing return with:

```python
    def to_dict(self) -> Dict:
        return {
            "category_url": self.category_url,
            "category_name": self.category_name,
            "product_urls": [url.to_dict() for url in self.product_urls],
            "pages_processed": self.pages_processed,
            "extraction_time": self.extraction_time,
            "llm_filtering_stats": self.llm_filtering_stats,
            "llm_usage": self.llm_usage,
            "errors": self.errors,
            "expected_count": self.expected_count,
            "expected_count_source": self.expected_count_source,
            "coverage_status": self.coverage_status,
            "coverage_retries": self.coverage_retries,
        }
```

If `Optional` isn't already imported in this file, add to the existing typing import line:

```python
from typing import Optional  # add to existing typing imports
```

- [ ] **Step 2: Verify the file imports cleanly**

```bash
cd backend && python -c "from scraper.url_extractor import URLExtractionResult; r = URLExtractionResult('u', 'n'); print(r.coverage_status, r.expected_count)"
```

Expected: `unknown None`

- [ ] **Step 3: Commit**

```bash
git add backend/scraper/url_extractor.py
git commit -m "$(cat <<'EOF'
Extend URLExtractionResult with coverage tracking fields

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Call `detect_collection_count` in `_scroll_and_extract_links`

**Files:**
- Modify: `backend/scraper/url_extractor.py:321-468` (return Dict adds `count_result`)

- [ ] **Step 1: Modify `_scroll_and_extract_links` to call detection**

In `backend/scraper/url_extractor.py`, the `_scroll_and_extract_links` function returns a dict at the end of its `try` block. We need to call `detect_collection_count` after the scroll loop completes and include the result.

First, add this import at the top of the file (with the other imports):

```python
from count_detection import detect_collection_count, CountResult
```

Then, find the place in `_scroll_and_extract_links` where the function returns its final dict (search for `"links": all_links,` near the end of the function — should be around line 460). Just before that final return, add:

```python
            # Detect collection count from the page (after scroll/load-more completed)
            count_result: Optional[CountResult] = None
            category_name_arg = (
                brand_instance.brand_id if brand_instance and getattr(brand_instance, "brand_id", None)
                else "this collection"
            )
            try:
                if brand_instance and getattr(brand_instance, "llm_handler", None):
                    count_result = detect_collection_count(
                        page,
                        category_name_arg,
                        brand_instance,
                        brand_instance.llm_handler,
                    )
                    if count_result:
                        _log(f"   🔢 Collection count detected: {count_result.count} (source: {count_result.source})")
                    else:
                        _log(f"   🔢 Collection count: not displayed")
            except Exception as e:
                _log(f"   ⚠️  Count detection error (non-fatal): {e}")
                count_result = None
```

Then modify the return statement at the end of the function. Find:

```python
    return {
        "links": all_links,
        "discovery_info": discovery_info
    }
```

Replace with:

```python
    return {
        "links": all_links,
        "discovery_info": discovery_info,
        "count_result": count_result,
    }
```

**Important:** the variable `count_result` must be initialized to `None` BEFORE the try/finally that wraps page navigation, so the final return doesn't `NameError` on the failure path. Find the line:

```python
        try:
            # Navigate to page
```

Immediately before the `try:`, add:

```python
        count_result: Optional[CountResult] = None  # populated after scroll completes
```

- [ ] **Step 2: Smoke-test imports**

```bash
cd backend && python -c "from scraper.url_extractor import _scroll_and_extract_links; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 3: Commit**

```bash
git add backend/scraper/url_extractor.py
git commit -m "$(cat <<'EOF'
Call detect_collection_count after scroll in _scroll_and_extract_links

The detected count is attached to the result dict for downstream
classification and coverage checking. Failures are logged but
non-fatal — count remains None when detection breaks.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Plumb `expected_count` through `_extract_urls_from_single_page` and into the result

**Files:**
- Modify: `backend/scraper/url_extractor.py` (`_extract_urls_from_single_page` and `extract_urls_from_category`)

- [ ] **Step 1: Update `_extract_urls_from_single_page` to surface the count**

In `_extract_urls_from_single_page` (around line 654), find:

```python
        # Scroll and extract all links (skip pagination detection on pages 2+ to avoid wasted LLM calls)
        result = _scroll_and_extract_links(page_url, brand_instance, skip_pagination_detection=skip_pagination_detection)
        links = result.get("links", [])
        discovery_info = result.get("discovery_info", {})
```

After `discovery_info = ...`, add:

```python
        count_result = result.get("count_result")  # may be None
        expected_count = count_result.count if count_result else None
        expected_count_source = count_result.source if count_result else None
```

Then find the call to `classify_product_links`:

```python
        # Classify links to filter products
        classification = classify_product_links(links, page_url, category_name, brand_instance)
```

Change to pass `expected_count`:

```python
        # Classify links to filter products
        classification = classify_product_links(
            links, page_url, category_name, brand_instance,
            expected_count=expected_count,
        )
```

Finally, find the return dict at the end of `_extract_urls_from_single_page`:

```python
        return {
            "product_urls": product_urls,
            "pagination_detected": discovery_info.get("pagination_detected") if not skip_pagination_detection else None,
            "extraction_time": extraction_time,
            "stats": stats,
            "discovery_info": discovery_info
        }
```

Add the two new fields:

```python
        return {
            "product_urls": product_urls,
            "pagination_detected": discovery_info.get("pagination_detected") if not skip_pagination_detection else None,
            "extraction_time": extraction_time,
            "stats": stats,
            "discovery_info": discovery_info,
            "expected_count": expected_count,
            "expected_count_source": expected_count_source,
        }
```

- [ ] **Step 2: Update `extract_urls_from_category` to record count on the result**

In `extract_urls_from_category` (around line 886), find:

```python
        result.product_urls.extend(page1_urls)
        result.llm_filtering_stats = page1_result.get("stats", {})
        result.discovery_info = page1_result.get("discovery_info", {})
```

After those three lines, add:

```python
        result.expected_count = page1_result.get("expected_count")
        result.expected_count_source = page1_result.get("expected_count_source")
```

- [ ] **Step 3: Smoke-test imports**

```bash
cd backend && python -c "from scraper.url_extractor import extract_urls_from_category; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 4: Commit**

```bash
git add backend/scraper/url_extractor.py
git commit -m "$(cat <<'EOF'
Plumb expected_count from scroll result through classifier and into URLExtractionResult

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Update `url_classification.py` prompt to use `expected_count`

**Files:**
- Modify: `backend/scraper/prompts/url_classification.py`

- [ ] **Step 1: Change the prompt signature and body**

In `backend/scraper/prompts/url_classification.py`, find the `get_prompt` function. Update its signature and add the count block.

Find:

```python
def get_prompt(page_url: str, category_name: str, links: List[Dict]) -> str:
```

Change to:

```python
def get_prompt(page_url: str, category_name: str, links: List[Dict], expected_count: Optional[int] = None) -> str:
```

At the top of the file, ensure `Optional` is imported:

```python
from typing import Dict, List, Optional
```

Inside `get_prompt`, after the existing `links_list` is built but **before** the f-string return, add:

```python
    count_hint = ""
    if expected_count is not None:
        count_hint = f"""
**Expected collection count: {expected_count} products** (detected from page display)

Use this as a quantitative anchor for your classification:
- The main product grid's lineage should contain approximately {expected_count} links (within ±20%).
- A lineage with substantially fewer links is most likely a side section (hero, featured, recommendations).
- A lineage with substantially more links is most likely a navigation pattern.
- Approve lineages that together sum to roughly {expected_count}, not more.
"""
```

Then insert `{count_hint}` into the return f-string immediately after the existing "Total links to analyze" / "Links marked [CAROUSEL]" block. Find the section that looks like:

```python
- Total links to analyze: {len(links)}
- Links marked [CAROUSEL]: {carousel_count} (these are inside slider/carousel containers)
```

Just after the `[CAROUSEL]` line, insert `{count_hint}` (a placeholder for the conditional block):

```python
- Total links to analyze: {len(links)}
- Links marked [CAROUSEL]: {carousel_count} (these are inside slider/carousel containers)
{count_hint}
```

- [ ] **Step 2: Verify imports & quick sanity check**

```bash
cd backend && python -c "
from scraper.prompts.url_classification import get_prompt
p1 = get_prompt('https://example.com', 'Hoodies', [{'url':'/p/1','lineage':'a','link_text':'t','in_carousel':False}])
p2 = get_prompt('https://example.com', 'Hoodies', [{'url':'/p/1','lineage':'a','link_text':'t','in_carousel':False}], expected_count=47)
assert 'Expected collection count' not in p1
assert 'Expected collection count: 47' in p2
print('prompt OK')
"
```

Expected: `prompt OK`

- [ ] **Step 3: Commit**

```bash
git add backend/scraper/prompts/url_classification.py
git commit -m "$(cat <<'EOF'
Add expected_count hint to URL classification prompt

When count is known, the prompt instructs the LLM to use it as a
quantitative anchor for which lineages are the main product grid.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Add `expected_count` parameter + memory-gate to `classify_product_links`

**Files:**
- Modify: `backend/scraper/url_extractor.py` (`classify_product_links`, around line 469)

This is the consequential change that fixes the 27-zero-result-categories bug.

- [ ] **Step 1: Change function signature**

Find:

```python
def classify_product_links(
    links: List[Dict],
    page_url: str,
    category_name: str,
    brand_instance=None
) -> Dict[str, Any]:
```

Change to:

```python
def classify_product_links(
    links: List[Dict],
    page_url: str,
    category_name: str,
    brand_instance=None,
    expected_count: Optional[int] = None,
) -> Dict[str, Any]:
```

- [ ] **Step 2: Add memory-gate logic after the lineage grouping**

After the section that builds `known_approved_links`, `known_rejected_links`, and `unknown_lineage_links` (search for `_log(f"   ✅ Pre-approved:`), there is currently this structure:

```python
    _log(f"   ✅ Pre-approved: {len(known_approved_links)} links ({len([l for l in lineage_groups if l in approved_lineages])} lineages)")
    _log(f"   ❌ Pre-rejected: {len(known_rejected_links)} links ({len([l for l in lineage_groups if l in rejected_lineages])} lineages)")
    _log(f"   ❓ Unknown: {len(unknown_lineage_links)} links need classification")
```

Immediately after those three log lines, add the gate:

```python
    # Memory-gate: if expected_count is known and pre-approved memory wildly
    # disagrees with it, distrust memory for this category and re-classify the
    # approved links as unknown.
    force_reclassify_memory = False
    if expected_count is not None and known_approved_links:
        approved_total = len(known_approved_links)
        low_threshold = expected_count * 0.8
        high_threshold = expected_count * 1.3
        if approved_total < low_threshold or approved_total > high_threshold:
            force_reclassify_memory = True
            _log(
                f"   ⚠️  Lineage memory disagrees with expected count "
                f"({approved_total} approved vs {expected_count} expected); re-classifying."
            )
            # Move approved links into the unknown pool for fresh classification
            unknown_lineage_links.extend(known_approved_links)
            known_approved_links = []
```

- [ ] **Step 3: Pass `expected_count` into the prompt call**

Search within `classify_product_links` for the call to `get_prompt(`. It currently looks like:

```python
            prompt = get_prompt(page_url, category_name, sample_links)
```

Change to:

```python
            prompt = get_prompt(page_url, category_name, sample_links, expected_count=expected_count)
```

- [ ] **Step 4: Include re-classify signal in returned stats**

Find the `stats` dictionary that's built at the end of `classify_product_links` (search for `"newly_approved_lineages"` or the final `return { ... "stats": stats }`). Add `force_reclassify_memory` to the stats:

If there's an existing `stats = { ... }` block:

```python
    stats = {
        # ... existing keys ...
        "memory_disagreed_with_count": force_reclassify_memory,
    }
```

If `stats` doesn't already exist as a single dict (it may be built inline in the return), find the return dict and add the key directly.

- [ ] **Step 5: Smoke test**

```bash
cd backend && python -c "
from scraper.url_extractor import classify_product_links
# Empty links list, no LLM — should return cleanly
result = classify_product_links([], 'https://example.com/c', 'Hoodies', brand_instance=None, expected_count=47)
print('classify ok, keys:', list(result.keys()))
"
```

Expected: `classify ok, keys: [...]` (no exception).

- [ ] **Step 6: Commit**

```bash
git add backend/scraper/url_extractor.py
git commit -m "$(cat <<'EOF'
Add expected_count param and memory-gate to classify_product_links

When pre-approved lineage memory disagrees with the page's displayed
count (outside 80%-130% of expected), we move approved links back to
the unknown pool and re-classify with the LLM. This prevents stale
memory from masking real products on later categories.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Coverage check and retry loop in `extract_urls_from_category`

**Files:**
- Modify: `backend/scraper/url_extractor.py` (`extract_urls_from_category`, around line 886)

- [ ] **Step 1: Add coverage check after page 1 + multi-page extraction completes**

In `extract_urls_from_category`, find the deduplication block:

```python
        # Deduplicate URLs
        seen = set()
        unique_urls = []
        for url in result.product_urls:
            if url.url not in seen:
                seen.add(url.url)
                unique_urls.append(url)
        result.product_urls = unique_urls
```

Immediately AFTER this dedup block (so coverage is measured against the deduped count), and BEFORE `result.extraction_time = ...`, insert:

```python
        # Coverage check against detected page count
        result.coverage_status = _classify_coverage(
            extracted=len(result.product_urls),
            expected=result.expected_count,
        )

        # LOW coverage: retry scroll + classify up to 2x
        if result.coverage_status == "low" and result.expected_count is not None:
            for retry_n in range(2):
                _log(f"   🔁 LOW coverage ({len(result.product_urls)} / {result.expected_count}); retry {retry_n+1}/2...")
                retry_result = _extract_urls_from_single_page(
                    category_url, category_url, category_name, 1, brand_instance,
                    skip_pagination_detection=True,
                )
                additional_urls = retry_result.get("product_urls", [])

                # Merge & dedupe
                seen_urls = {u.url for u in result.product_urls}
                for url in additional_urls:
                    if url.url not in seen_urls:
                        result.product_urls.append(url)
                        seen_urls.add(url.url)

                result.coverage_retries += 1
                result.coverage_status = _classify_coverage(
                    extracted=len(result.product_urls),
                    expected=result.expected_count,
                )
                if result.coverage_status == "ok":
                    break

        # HIGH coverage handling is left as-is for now: we log but do not
        # auto-strip. The brand-level summary will surface HIGH status to the
        # user for manual review. (Re-classification with a strict ceiling is
        # a follow-up if real HIGH cases emerge in practice.)
```

- [ ] **Step 2: Add the `_classify_coverage` helper above `extract_urls_from_category`**

Find the line that begins `def extract_urls_from_category(`. Immediately before that `def`, add:

```python
def _classify_coverage(extracted: int, expected: Optional[int]) -> str:
    """
    Return one of: "ok", "low", "high", "unknown".

    - unknown: no page count was detected.
    - low: extracted < expected - max(2, expected*0.2)
    - high: extracted > expected + max(3, expected*0.3)
    - ok: within tolerance
    """
    if expected is None:
        return "unknown"
    tol_low = max(2, int(expected * 0.2))
    tol_high = max(3, int(expected * 0.3))
    if extracted < expected - tol_low:
        return "low"
    if extracted > expected + tol_high:
        return "high"
    return "ok"
```

- [ ] **Step 3: Smoke test the helper**

```bash
cd backend && python -c "
from scraper.url_extractor import _classify_coverage
assert _classify_coverage(47, 47) == 'ok'
assert _classify_coverage(27, 47) == 'low'
assert _classify_coverage(80, 47) == 'high'
assert _classify_coverage(45, 47) == 'ok'
assert _classify_coverage(0, None) == 'unknown'
assert _classify_coverage(5, 5) == 'ok'
assert _classify_coverage(2, 5) == 'low'
print('coverage helper ok')
"
```

Expected: `coverage helper ok`

- [ ] **Step 4: Commit**

```bash
git add backend/scraper/url_extractor.py
git commit -m "$(cat <<'EOF'
Add coverage check + LOW-coverage retry to extract_urls_from_category

After dedup, compare extracted count to expected page count. On LOW
coverage (≥20% short), re-run scroll + classification up to 2x. HIGH
coverage is logged but not auto-corrected.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Per-category log additions (count + coverage)

**Files:**
- Modify: `backend/stages/urls.py` (the worker function that builds `log_lines` and returns `{"urls": urls, "logs": ..., ...}`, around lines 100–220)

The worker function builds a list of `log_lines` strings, then joins them. We append our count/coverage lines into that list, and add four new keys to the returned dict so the parent thread can surface them in the summary.

- [ ] **Step 1: Add count detection line near the top of the log**

In the worker function (the one that calls `extract_urls_from_category` and builds `log_lines`), find the first few `log_lines.append(...)` calls. Right after the section that logs the category URL and basic header info but **before** the line `log_lines.append(f"Pre-approved (from memory): ...")`, insert:

```python
        # Collection count detection
        if result.expected_count is not None:
            log_lines.append(f"Page count detection: {result.expected_count} (source: {result.expected_count_source})")
        else:
            log_lines.append("Page count detection: null (no count displayed)")
        log_lines.append("")
```

- [ ] **Step 2: Add coverage status block near the bottom**

Find the existing block:

```python
        log_lines.append("")
        log_lines.append("=" * 40)
        log_lines.append("PRODUCT URLs")
        log_lines.append("=" * 40)
        for url in urls:
            log_lines.append(f"  - {url}")
```

Immediately **before** that block (so coverage shows up above the list of URLs), insert:

```python
        log_lines.append("")
        log_lines.append("=" * 40)
        log_lines.append("COVERAGE")
        log_lines.append("=" * 40)
        if result.expected_count is not None:
            status_icon = {"ok": "✓", "low": "⚠ low", "high": "⚠ high"}.get(result.coverage_status, "?")
            log_lines.append(f"Expected: {result.expected_count}")
            log_lines.append(f"Extracted: {len(urls)}")
            log_lines.append(f"Status: {status_icon}")
            if result.coverage_retries > 0:
                log_lines.append(f"Retries: {result.coverage_retries}")
        else:
            log_lines.append("Status: n/a (page count unknown)")
```

- [ ] **Step 3: Surface the four count fields in the worker's return dict**

In the same function, find the success return:

```python
        return {
            "urls": urls,
            "logs": "\n".join(log_lines),
            "extraction_time": extraction_time,
            "llm_usage": llm_usage
        }
```

Add the four new keys:

```python
        return {
            "urls": urls,
            "logs": "\n".join(log_lines),
            "extraction_time": extraction_time,
            "llm_usage": llm_usage,
            "expected_count": result.expected_count,
            "expected_count_source": result.expected_count_source,
            "coverage_status": result.coverage_status,
            "coverage_retries": result.coverage_retries,
        }
```

And in the error return (the `except Exception as e:` block):

```python
        return {
            "urls": [],
            "logs": "\n".join(log_lines),
            "extraction_time": 0.0,
            "llm_usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
            "error": str(e),
            "expected_count": None,
            "expected_count_source": None,
            "coverage_status": "unknown",
            "coverage_retries": 0,
        }
```

- [ ] **Step 4: Smoke-test imports**

```bash
cd backend && python -c "from stages import urls; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 5: Commit**

```bash
git add backend/stages/urls.py
git commit -m "$(cat <<'EOF'
Add count detection and coverage status to per-category logs

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Brand-level coverage summary table

**Files:**
- Modify: `backend/stages/urls.py` (at the end of `extract_urls`)

- [ ] **Step 1: Locate the end-of-stage summary location**

Find the `extract_urls` function and the area where it prints the final summary (look for a section that prints results after all categories are done — often after the dedupe-by-path block). This is where we'll add the coverage table.

- [ ] **Step 2: Add the summary printer**

Add this helper function at the top level of `backend/stages/urls.py` (after the existing helpers like `dedupe_urls_by_path`):

```python
def print_coverage_summary(results: List[Dict], url_map: Dict[str, List[str]]) -> str:
    """
    Build a brand-level URL extraction coverage summary table.

    Args:
        results: list of {"name": str, "url": str, "count": int, ...} entries
                 in extraction order, each carrying coverage metadata.
        url_map: {category_url: [product_urls]} after dedupe.

    Returns:
        The summary text (also printed to stdout).
    """
    lines = []
    lines.append("\n" + "─" * 65)
    lines.append("URL EXTRACTION COVERAGE SUMMARY")
    lines.append("─" * 65)
    lines.append(f"{'Category':<28}{'Page':>6}{'Found':>8}  Status")
    lines.append("─" * 65)

    ok = warn = unknown = 0
    for r in results:
        name = (r.get("name") or "")[:27]
        page_count = r.get("expected_count")
        found = r.get("count", 0)
        status = r.get("coverage_status", "unknown")
        retries = r.get("coverage_retries", 0)

        page_str = str(page_count) if page_count is not None else "n/a"
        if status == "ok":
            symbol = "✓"
            ok += 1
        elif status == "low":
            symbol = f"⚠ low" + (f" (after {retries} retries)" if retries else "")
            warn += 1
        elif status == "high":
            symbol = "⚠ high"
            warn += 1
        else:
            symbol = "—"
            unknown += 1

        lines.append(f"{name:<28}{page_str:>6}{found:>8}  {symbol}")

    lines.append("─" * 65)
    lines.append(
        f"Total: {ok}/{len(results)} ok | {warn} warning(s) | {unknown} page-count unknown"
    )
    text = "\n".join(lines)
    print(text)
    return text
```

- [ ] **Step 3: Populate coverage info on `results` entries in stages/urls.py**

In `extract_urls` in `backend/stages/urls.py`, find the success path (around line 530):

```python
                # Apply results to all leaves that share this URL
                for leaf in leaves_for_future:
                    url_map[leaf["url"]] = urls
                    all_urls.update(urls)
                    dedup_note = f" (deduped from {raw_count})" if removed_count > 0 else ""
                    results.append({"name": leaf["name"], "count": len(urls), "raw_count": raw_count, "error": None})
                    category_logs[leaf["name"]] = logs
```

Change the `results.append(...)` line to pull the new fields from `result_data`:

```python
                    results.append({
                        "name": leaf["name"],
                        "count": len(urls),
                        "raw_count": raw_count,
                        "error": None,
                        "expected_count": result_data.get("expected_count"),
                        "expected_count_source": result_data.get("expected_count_source"),
                        "coverage_status": result_data.get("coverage_status", "unknown"),
                        "coverage_retries": result_data.get("coverage_retries", 0),
                    })
```

Also in the failure path (around line 547):

```python
                    results.append({"name": leaf["name"], "count": 0, "error": str(e)})
```

Change to:

```python
                    results.append({
                        "name": leaf["name"],
                        "count": 0,
                        "error": str(e),
                        "expected_count": None,
                        "expected_count_source": None,
                        "coverage_status": "unknown",
                        "coverage_retries": 0,
                    })
```

- [ ] **Step 4: Call the summary printer at the end of `extract_urls`**

Near the end of `extract_urls`, just before the final return, add:

```python
    print_coverage_summary(results, url_map)
```

- [ ] **Step 5: Also do the same in the streaming path**

In `backend/stages/streaming.py`, the streaming URL producer also produces results. Find the place where it finalizes (search for `save_urls(`). Just before that call, accumulate the same fields onto its result list and call `print_coverage_summary` from the same module:

```python
from stages.urls import print_coverage_summary
print_coverage_summary(coverage_results, url_map)
```

(`coverage_results` is whatever the streaming path builds; if it doesn't already build per-category dicts, build them at the point where each category finishes, with the four count-related fields.)

- [ ] **Step 6: Smoke test**

```bash
cd backend && python -c "
from stages.urls import print_coverage_summary
r = [
    {'name': 'Hoodies', 'count': 47, 'expected_count': 47, 'coverage_status': 'ok', 'coverage_retries': 0},
    {'name': 'Tops', 'count': 30, 'expected_count': 32, 'coverage_status': 'low', 'coverage_retries': 2},
    {'name': 'Mystery', 'count': 12, 'expected_count': None, 'coverage_status': 'unknown', 'coverage_retries': 0},
]
print_coverage_summary(r, {})
"
```

Expected: a table with 3 rows, totals line showing `1 ok | 1 warning(s) | 1 page-count unknown`.

- [ ] **Step 7: Commit**

```bash
git add backend/stages/urls.py backend/stages/streaming.py
git commit -m "$(cat <<'EOF'
Add brand-level URL extraction coverage summary table

Printed at the end of stage 2 in both the non-streaming and streaming
pipelines. This is the primary verification surface for the user.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: End-to-end smoke test

**Files:**
- No code changes — this is a manual verification step.

- [ ] **Step 1: Run stage 2 against namedcollective**

```bash
cd backend && python pipeline.py urls namedcollective_com
```

- [ ] **Step 2: Inspect the printed coverage summary**

The summary table will appear at the end of stage 2 output. Verify it contains:
- One row per category
- Page counts for most categories (likely sourced from `jsonld` for the Shopify storefront, otherwise `vision`)
- Status icons (✓ / ⚠ / —)
- Total line at the bottom

- [ ] **Step 3: Spot-check the failing categories from the previous run**

The previous run had 27 zero-result categories. After this change:
- Some should be ✓ (real categories where memory had been wrong)
- Some should still be `—` (page count unknown — these are the "Account Login" / "My Wishlist" style URLs we filter out in nav)
- Anything that's `⚠ low` is worth a deeper look at the per-category log under `extractions/namedcollective_com/logs/`

- [ ] **Step 4: Hand off to user for verification**

The user is the ground-truth verifier. Present the summary table and ask: "Does this match what you expect for namedcollective?" If they spot problems, those become the inputs for the next iteration.

---

## Done criteria

- [ ] All implementation tasks (1–16) committed; Task 17 is a manual smoke test, no commit.
- [ ] `python scraper/tests/test_count_detection.py` passes.
- [ ] Stage 2 run against namedcollective prints the coverage summary table.
- [ ] No regression on brands without page counts (their categories show `—` status, behavior identical to today).
- [ ] User has reviewed the summary and confirmed it's directionally correct.
