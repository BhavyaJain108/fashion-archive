# Collection Count & Coverage Verification — Design

**Date**: 2026-05-14
**Status**: Approved for implementation planning
**Scope**: Stage 2 (URL extraction) — `backend/scraper/url_extractor.py` and adjacent modules

## Problem

The Stage 2 URL extractor produces incomplete and contaminated results:

- Many categories return far fewer product URLs than the site displays (e.g. 27 of 47 hoodies).
- 27 of 37 categories in the most recent `namedcollective.com` run returned zero URLs despite the page loading correctly.
- A small set of products (5 hero items + 1 related item on `namedcollective.com`) appears in every category, even ones they don't belong to.

Diagnosis: the lineage-based classifier in `classify_product_links` has no ground-truth signal for "how many products should this category have?". Once lineage memory (`brand_instance.approved_url_lineages` / `rejected_url_lineages`) is seeded from early categories, later categories trust it blindly — even when memory's answer doesn't match the page.

## Solution overview

Detect the **collection count** (number of products the page itself displays) and use it as a ground-truth signal at three points:

1. **Hint to the LLM classifier** — tell it how many products to expect.
2. **Lineage-memory gate** — invalidate memory when its answer doesn't match the count.
3. **Coverage check** — after extraction, compare extracted count against page count and retry / warn.

The count is treated as an optional signal. If a page doesn't display one, behavior is identical to today — no regressions on brands without counts.

## Architecture

```
_scroll_and_extract_links(page_url, brand_instance)
├── scroll / load-more (unchanged)
├── detect_collection_count(page, brand_instance)        ← NEW
└── _extract_links_from_current_state(page, page_url)

classify_product_links(links, page_url, category_name,
                       brand_instance, expected_count)   ← expected_count is NEW
├── group by lineage (unchanged)
├── lineage-memory check
│   └── if expected_count known: validate memory against it ← NEW
├── if memory disagrees with count → force LLM re-classify  ← NEW
├── LLM call with count hint in prompt                      ← NEW
└── return product_links + stats (stats now include count info)

extract_urls_from_category(...)
├── (existing scroll + classify)
└── coverage check: extracted vs expected                ← NEW
    └── on LOW → retry scroll/load-more, up to 2x
    └── on HIGH → re-classify with stricter prompt, once
```

## Components

### 1. `detect_collection_count(page, brand_instance) -> Optional[CountResult]`

New function in `url_extractor.py`. Three stages, stop at first success:

#### Stage 1 — JSON-LD structured data (free, instant)

Read all `<script type="application/ld+json">` blocks. Parse JSON (ignore malformed). Walk the object tree looking for:
- `@type: ItemList` with `numberOfItems`
- `@type: CollectionPage` with nested `ItemList` / `OfferCatalog`
- `mainEntity.numberOfItems` / `hasPart.numberOfItems`

If a plausible integer is found (`1 ≤ N ≤ 10_000`), return `CountResult(count=N, source="jsonld")`.

Implementation detail: use a small recursive walker — many sites nest the count two or three levels deep. Stop at first hit.

#### Stage 2 — Cached brand selector (free after first call)

If `brand_instance.collection_count_selector` is set (a CSS selector string), query it on the current page:

```python
text = page.evaluate(f"document.querySelector({json.dumps(selector)})?.textContent")
```

Parse the **first integer** from `text`. Sanity-check `1 ≤ N ≤ 10_000`. If valid → return `CountResult(count=N, source="cached_selector")`.

If the selector returns nothing or an implausible number on three consecutive categories, **invalidate the cache** (`brand_instance.collection_count_selector = None`) so Stage 3 runs fresh next time.

#### Stage 3 — Vision LLM (one-time per brand when 1 & 2 miss)

Take a screenshot of the top viewport:

```python
screenshot = page.screenshot(
    clip={"x": 0, "y": 0, "width": 1280, "height": 900},
    type="png"
)
```

Send to LLM with prompt (see `prompts/collection_count_detection.py`):

> "This is the top of an e-commerce collection page for category '{category_name}'. What is the total number of products displayed in this collection? Look for a number near the page title, in a count badge, or in 'Showing X of Y' text. If no count is visible, return null.
>
> Also return: what CSS selector on this page reliably yields this number? (e.g. `.collection-count`, `[data-product-count]`, `.results-count`). Return null if you can't identify a stable one."

Pydantic response:

```python
class CollectionCountResult(BaseModel):
    count: Optional[int] = Field(description="Total products in this collection, or null if not displayed")
    selector: Optional[str] = Field(description="CSS selector that yields the count, or null if not identifiable")
    confidence: Literal["high", "medium", "low"]
    reasoning: str = Field(description="Brief: where on the page the count was found")
```

If `count` is null → return `None` from `detect_collection_count`.
If `count` is non-null and `confidence == "high"` and `selector` is non-null → cache it: `brand_instance.collection_count_selector = selector`.
Return `CountResult(count, source="vision")`.

#### Return type

```python
@dataclass
class CountResult:
    count: int
    source: Literal["jsonld", "cached_selector", "vision"]
```

`detect_collection_count` returns `Optional[CountResult]`. `None` means honestly unknown.

### 2. `Brand` instance addition

Add one attribute:

```python
self.collection_count_selector: Optional[str] = None
self._count_selector_miss_count: int = 0  # for cache invalidation after 3 consecutive misses
```

Existing pagination-pattern caching is the model — same idea, same lock pattern if needed.

### 3. `classify_product_links` — count-aware classification

New parameter: `expected_count: Optional[int] = None`.

#### Lineage-memory gate

After computing `known_approved_links`, `known_rejected_links`, `unknown_lineage_links`:

```python
if expected_count is not None:
    approved_total = len(known_approved_links)
    if approved_total < expected_count * 0.8:
        # Memory under-shoots — likely missing real products
        # Move all known_approved_links into unknown_lineage_links and re-classify
        force_full_reclassify = True
    elif approved_total > expected_count * 1.3:
        # Memory over-shoots — likely contamination
        force_full_reclassify = True
    else:
        force_full_reclassify = False
else:
    force_full_reclassify = False
```

When `force_full_reclassify` is true: send all links (capped at the 50-sample budget) to the LLM, ignoring memory for this category. Still update memory after with the fresh decisions.

#### Prompt addition

In `prompts/url_classification.py`, append before the closing instructions:

```
**Expected collection count: {expected_count} products** (from page display)

Use this as a quantitative anchor:
- The main product grid's lineage should contain approximately {expected_count} links (within ±20%)
- A lineage with substantially fewer links is likely a side section (hero, featured, recommendations)
- A lineage with substantially more links is likely a navigation pattern
- Approve lineages that together sum to roughly {expected_count}, not more
```

This block is only added when `expected_count is not None`. When unknown, the prompt is unchanged.

### 4. Coverage check — retry & warn

After `classify_product_links` completes for a category (in `extract_urls_from_category`):

```python
if expected_count is not None:
    extracted = len(result.product_urls)
    tolerance_low = max(2, int(expected_count * 0.2))
    tolerance_high = max(3, int(expected_count * 0.3))

    if extracted < expected_count - tolerance_low:
        # LOW coverage — re-scroll/load-more AND re-classify, up to 2 retries
        # Each retry: keep page open, scroll to bottom again, click load-more if present,
        # re-extract links, re-run classify_product_links (memory now warm).
        for retry in range(2):
            additional_links = re_scroll_and_extract(page, ...)
            new_classification = classify_product_links(additional_links, ..., expected_count)
            extracted = len(merge(result.product_urls, new_classification.product_links))
            if extracted >= expected_count - tolerance_low:
                break
        # Final status logged

    elif extracted > expected_count + tolerance_high:
        # HIGH coverage — likely contamination
        # Re-run classifier once with stricter prompt: count is a hard ceiling.
        # No re-scroll; we already have too many links, the problem is classification.
        stricter_result = classify_product_links(
            all_links, ..., expected_count, strict_ceiling=True
        )
```

Status is captured in `URLExtractionResult.coverage_status: Literal["ok", "low", "high", "unknown"]`.

### 5. Observable output

#### Per-category log additions

`logs/<category-slug>.log` already exists in the non-streaming path. Add at the top:

```
Page count detection: 47 (source: jsonld)
```
or
```
Page count detection: 47 (source: vision, selector cached: ".collection-count")
```
or
```
Page count detection: null (no count displayed)
```

At the bottom, before `PRODUCT URLs`:

```
========================================
COVERAGE
========================================
Expected: 47
Extracted: 47
Status: ✓ ok
```

For LOW/HIGH cases, include retry trace:
```
Status: ⚠ low (after 2 retries: 27 → 35 → 35)
```

#### Brand-level summary

New at the end of stage 2 (printed to stdout, also saved to `metrics.txt`):

```
URL EXTRACTION COVERAGE SUMMARY — <domain>
─────────────────────────────────────────────────────
Category              Page  Found  Status
─────────────────────────────────────────────────────
Hoodies                47    47    ✓
Tops                   32    32    ✓
Activewear             12    12    ✓
Shop Our Sh!t          76    74    ⚠ -2 (within tolerance)
THORN                  18    15    ⚠ low — retried 2x
Bikinis & Swimsuits   n/a   29    — (page count unknown)
─────────────────────────────────────────────────────
Total: 35/37 categories ok | 1 warning | 1 unknown
```

This is the primary verification surface — the user reads this table after a run to spot issues.

#### `URLExtractionResult` schema additions

```python
@dataclass
class URLExtractionResult:
    # existing fields ...
    expected_count: Optional[int] = None
    expected_count_source: Optional[str] = None  # "jsonld" | "cached_selector" | "vision"
    coverage_status: str = "unknown"             # "ok" | "low" | "high" | "unknown"
    coverage_retries: int = 0
```

## Tolerances

| Threshold | Value | Rationale |
|---|---|---|
| LOW coverage trigger | `extracted < expected - max(2, expected*0.2)` | ±20% with a 2-product minimum so small categories (count=5) don't trigger from a single missing item |
| HIGH coverage trigger | `extracted > expected + max(3, expected*0.3)` | Asymmetric vs LOW: extra items above grid-size are more suspicious than missing ones. Note this tolerance (1.3x for the final check) is slightly looser than the memory-gate threshold (1.3x for re-classification) — they happen to use the same multiplier so memory-gate and coverage-check fire consistently. |
| Cached selector miss → invalidate | 3 consecutive categories | Single misses can be transient (a page in a weird state); 3 means the selector is broken |
| Vision LLM confidence to cache selector | "high" only | Don't poison the cache with low-confidence selectors |

## What this design explicitly does NOT change

- **Lineage system (`getLineage` JS)** — depth, format, what classes are included. The count signal is hypothesized to be sufficient. If the count doesn't fix it, lineage gets revisited as a separate spec.
- **`isInCarousel` patterns** — left as the original short list.
- **Cross-category deduplication** — not introduced. Products legitimately appear in multiple categories; multi-category presence is not a contamination signal.
- **`max_url_workers`** — unchanged (the lineage-memory gate is the real fix for the parallel-race symptom).
- **Stage 1 (nav extraction)** and **stage 3 (product extraction)** — unaffected. This is a stage 2 change.

## Failure modes & honesty

- **Stage 1 finds an `ItemList` for a different list** (e.g. a "Related Products" carousel's JSON-LD): possible. Mitigation: prefer the `ItemList` with the highest `numberOfItems` value, since the main grid is typically larger than side sections. If still wrong, the coverage check will trigger HIGH and we'll log it.
- **Vision LLM returns a wrong selector**: cached on a real-looking but unstable selector. Mitigation: 3-strike cache invalidation. If the selector returns garbage 3 times in a row, we throw it out.
- **Page renders the count after async hydration**: scroll happens after page load, so by the time `detect_collection_count` runs, hydration is typically done. If a brand still has races, the count will be null → graceful degradation.
- **Page lies about its count** (e.g. "Showing 24 of 87" but only 30 products actually exist): we'll over-retry on LOW. Cap of 2 retries prevents loops. Final status surfaces the mismatch.

## Out-of-scope follow-ups

These would be separate specs if needed:

- Lineage system deepening / semantic anchors (only if count signal proves insufficient)
- Brand-level count-source telemetry (which stage hit, how often)
- Coverage status feeding back into stage 3 (skip product extraction for HIGH-coverage categories?)

## Implementation order (sketch — full plan in next phase)

1. JSON-LD detection + tests (no LLM, cheapest, gives early wins)
2. `URLExtractionResult` schema additions + per-category log additions (observability before behavior change)
3. Vision LLM prompt + `detect_collection_count` Stage 3 + caching
4. Stage 2 selector lookup + miss-count invalidation
5. `classify_product_links` accepts `expected_count`, adds memory gate
6. URL classification prompt update
7. Coverage retry logic in `extract_urls_from_category`
8. Brand-level summary table

## Testing

- The user is the final ground-truth verifier — they will run the pipeline against `namedcollective.com` and read the summary table.
- Add `namedcollective` to `tests/brands.json` with category URLs (no expected counts needed — the page-count detection is what we're testing). The test passes if (a) page count detection returns a non-null result for ≥80% of categories, and (b) coverage status is `ok` for ≥80% of categories.
- Unit tests for JSON-LD walker against synthetic fixtures (`ItemList`, nested `CollectionPage`, malformed JSON, missing field).
- Integration test for the memory-gate behavior: seed `brand_instance.approved_url_lineages` with stale data, run a category whose count doesn't match, assert that LLM is called and memory is refreshed.
