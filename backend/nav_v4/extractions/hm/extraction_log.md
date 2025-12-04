# H&M Navigation Extraction Log

## Site Information
- **URL**: https://www2.hm.com/en_us/index.html
- **Extraction Date**: 2025-12-04

## Extraction Process

### Step 1: Initial Page Load
- Navigated to https://www2.hm.com/en_us/index.html
- Encountered cookie consent dialog, accepted cookies
- SMS signup popup appeared multiple times, dismissed with Escape key

### Step 2: Network Request Analysis
- Listed network requests filtered by fetch/xhr
- Found `/en_us/apis/navigation/v1/carousel-data.json` endpoint
- This endpoint only contains featured carousel items, not full navigation

### Step 3: Embedded Data Discovery
- Checked for `__NEXT_DATA__` (Next.js) - **FOUND**
- H&M uses Next.js framework
- Navigation data embedded in hydration payload

### Step 4: Data Location
- Path: `window.__NEXT_DATA__.props.pageProps.headerData.menuItems`
- Data is an array of top-level department objects
- Each object has recursive `children` array for subcategories

### Step 5: Data Structure Analysis
- Each category has:
  - `nodeId`, `nodeName` (display name)
  - `href` (relative URL path)
  - `parentNodeId`, `trackingLabel`, `trackingData`
  - `inActive`, `hideWebNav`, `skipMenu` (filtering flags)
  - `group` (menu section grouping)
  - `highlighted` (for sale items)
  - `children` (recursive array)

## Results
- **Total Categories**: 1,495
- **Depth Distribution**:
  - Level 1: 6 categories (Women, Men, Kids, Home, Beauty, Sale)
  - Level 2: 47 categories
  - Level 3: 268 categories
  - Level 4: 216 categories
  - Level 5: 550 categories
  - Level 6: 354 categories
  - Level 7: 54 categories

## Key Findings
1. Next.js site with navigation in `__NEXT_DATA__` hydration payload
2. No separate API call needed - data available on page load
3. Recursive `children` structure up to 7 levels deep
4. URLs are relative paths - prepend `https://www2.hm.com`
5. Much deeper hierarchy than typical fashion sites (7 levels vs 3-4)
