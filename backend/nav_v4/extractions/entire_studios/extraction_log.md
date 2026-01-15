# Entire Studios Navigation Extraction Log

## Site Information
- **URL**: https://www.entirestudios.com/
- **Extraction Date**: 2025-12-04

## Extraction Process

### Step 1: Initial Page Load
- Navigated to https://www.entirestudios.com/
- Minimalist homepage with only 4 main navigation links
- Very clean, design-focused site

### Step 2: Platform Identification
- Custom built site (not Shopify, not Next.js)
- No `__NEXT_DATA__` or `__PRELOADED_STATE__`
- No embedded JSON scripts
- Simple DOM-based navigation

### Step 3: Navigation Structure Discovery
- Homepage shows 4 top-level links: aw25, uniform, ss25, archive
- Clicked into aw25 collection to see subcategories
- Found category filters via `?tag=` URL parameter

### Step 4: Category Structure
- **Top-level collections**:
  - aw25 (Autumn/Winter 2025)
  - uniform (Sleepwear line)
  - ss25 (Spring/Summer 2025)
  - archive (Sale items)

- **Subcategories** (under collections):
  - outerwear
  - tops
  - bottoms
  - dresses
  - knitwear
  - denim
  - leather
  - suiting

## Results
- **Extraction Method**: dom
- **Total Categories**: ~15
- **Max Depth**: 2
- **Requires Interaction**: No

## Key Findings
1. Very minimalist brand with flat navigation
2. Custom-built site, no common framework detected
3. Categories filtered via URL query parameters (?tag=)
4. Simple DOM extraction - no API or embedded data needed
5. Brand focuses on seasonal collections (AW25, SS25) and a uniform line
