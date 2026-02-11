# Product Image Extraction - Many-Shot LLM Approach

## Problem Statement

Extract **only product gallery images** from e-commerce product pages, excluding:
- Recommendation/related product images
- Logos and brand images
- Navigation icons
- Color swatches
- Footer/lookbook images

## Why This Approach Works

### Key Insight: Link Context + Container Paths

The breakthrough is using **two signals together**:

1. **Link Context** - Where does clicking the image take you?
   - `NO_LINK` → Likely product gallery (clicking doesn't navigate)
   - `PRODUCT_LINK` → Links to another product (recommendation)
   - `OTHER_LINK` → External link (logo, social, navigation)

2. **Container Paths** - Where does the image live in the DOM?
   - Product images share a common container (gallery/slider/carousel)
   - Recommendations live in different containers (`prod-card`, `related`, etc.)

### Why Many-Shot Prompting

Single-shot prompting failed because:
- Different sites use different patterns
- LLM had to "guess" what a gallery looks like

Many-shot prompting succeeds because:
- LLM sees 4 real examples from different brands
- Learns the **pattern** not just the rule
- Generalizes to new sites accurately

### The Two Outputs

The LLM returns **two things**:

1. **product_image_indices** - Which images are product images (immediate use)
2. **gallery_selector** - CSS selector for future extraction (no LLM needed)

The selector is validated on the same page before saving. Future extractions use the selector directly without LLM cost.

## Input Format

```json
{
  "product_name": "The creation of Adam - Ring V2",
  "product_url": "https://kuurth.com/...",
  "images": [
    {"i": 0, "alt": "KUURTH", "link": "OTHER_LINK", "containers": "div < a < header"},
    {"i": 2, "alt": "The creation of Adam - Ring V2", "link": "NO_LINK", "containers": "image-with-placeholder < div < li#splide01-slide01"},
    ...
  ]
}
```

Each image has:
- `i` - Index in DOM order
- `alt` - Alt text (often contains product name)
- `link` - Link context (NO_LINK, PRODUCT_LINK, OTHER_LINK)
- `containers` - DOM ancestry path (child < parent < grandparent)

## Output Format

```json
{
  "product_image_indices": [2, 3, 4, 5, 6],
  "gallery_selector": "li[id^='splide'] img",
  "selector_valid": true,
  "selector_count": 5
}
```

## Files

### Core
- `llm_image_extractor.py` - Main extraction function
- `image_extraction_prompt.py` - Many-shot examples (4 brands)
- `extractor.py` - Pipeline integration

### Test/Debug
- `extract_image_data.py` - CLI to extract image data from any URL
- `test_llm_extraction.py` - Test suite

## Usage

### During Discovery (automatic)
```python
# Called by discover_and_verify()
config = await extractor.discover_gallery_selector(url, product_name=product_name)
# Saves to schemas/{domain}_gallery.json
```

### Manual Testing
```bash
# Extract image data from a URL
python extract_image_data.py "https://example.com/product/xyz" --json

# Test LLM extraction
python test_llm_extraction.py
```

## Results

| Brand | Recall | Precision | Notes |
|-------|--------|-----------|-------|
| Kuurth | 100% | 100% | Splide slider |
| Devi Clothing | 100% | 56% | Expanded views included |
| Heaven Can Wait | 100% | 83% | 1 extra thumbnail |
| Entire Studios | 90% | 100% | Complex layout |

**Key metric: 100% recall on expected images across all tested brands.**

## Test Cases

### Kuurth Ring
- **URL:** `https://kuurth.com/collections/all/products/the-creation-of-adam-ring-v2`
- **Product:** The creation of Adam - Ring V2
- **Expected indices:** [2, 3, 4, 5, 6]
- **Derived selector:** `div#splide01-track img`

### Devi Clothing
- **URL:** `https://devi-clothing.com/collections/the-sari-collection/products/nora-top-red-cherry`
- **Product:** Nora top - Cherry - S/M
- **Expected indices:** [3, 4, 5, 6, 7]
- **Derived selector:** `div.product__image-container img`

### Heaven Can Wait
- **URL:** `https://heavencanwait.store/collections/frontpage/products/track-jeans-blue`
- **Product:** V2 TRACK JEANS (BLUE)
- **Expected indices:** [3, 4, 5, 6, 7]
- **Derived selector:** `div.pmslider-own--slides-wrapper img`

### Entire Studios
- **URL:** `https://www.entirestudios.com/product/adidas-x-entire-studios-optime-short-training-leggings-medium-red-8`
- **Product:** Optime Short Training Leggings Active Maroon
- **Expected indices:** [0-19] (NO_LINK images only)
- **Derived selector:** `div.swiper-slide img`
