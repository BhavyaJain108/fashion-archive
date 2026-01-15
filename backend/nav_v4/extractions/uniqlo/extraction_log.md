# Uniqlo Navigation Extraction Log

## Site Information
- **URL**: https://www.uniqlo.com/us/en/
- **Extraction Date**: 2025-12-04

## Extraction Process

### Step 1: Initial Page Load
- Navigated to https://www.uniqlo.com/us/en/
- Page timed out but still loaded successfully
- Observed tabs: WOMEN, MEN, KIDS, BABY

### Step 2: API Endpoint Testing
- Tried common API endpoints:
  - `/us/api/commerce/v5/en/category/tree` - returned error status
  - `/us/api/commerce/v5/en/categories` - returned error status
  - `/us/api/commerce/v5/en/navigation` - returned error status
- APIs appear to require authentication or specific headers

### Step 3: Menu Interaction
- Clicked "Menu / Product Search" button to open navigation panel
- Observed category buttons: Outerwear, T-Shirts, Sweaters, Bottoms, etc.
- Clicked "Outerwear" to see subcategories: Down Jackets, Jackets & Parkas, Coats, etc.

### Step 4: Embedded Data Discovery
- Checked window objects - no `__NEXT_DATA__`
- Found `__PRELOADED_STATE__` (Redux store) in script tags
- Located `taxonomies` object in Redux state

### Step 5: Data Structure Analysis
- Redux state path: `window.__PRELOADED_STATE__.taxonomies`
- Structure uses **inverse hierarchy** with `parents` arrays:
  - `genders`: [{id, name, genderKey}]
  - `classes`: [{id, name, key, parents: [gender]}]
  - `categories`: [{id, name, key, parents: [gender, class]}]
  - `subcategories`: [{id, name, key, parents: [gender, class, category]}]

### Step 6: URL Pattern Discovery
- Category URLs follow pattern: `/{genderKey}/{classKey}/{categoryKey}`
- Example: `/us/en/women/outerwear-and-blazers/down-jackets-and-coats`

## Results
- **Total Categories**: 2,036
- **Level Distribution**:
  - Level 1 (Genders): 4 (WOMEN, MEN, KIDS, BABY)
  - Level 2 (Classes): 39 (Outerwear, T-Shirts, Sweaters, etc.)
  - Level 3 (Categories): 172 (Down Jackets & Coats, Jackets & Parkas, etc.)
  - Level 4 (Subcategories): 1,825 (Seamless, Ultra Warm, PUFFTECH, etc.)

## Key Findings
1. Uses Redux store (`__PRELOADED_STATE__`) for state management
2. Taxonomy data uses inverse parent references, not children arrays
3. Tree must be reconstructed by grouping items by parent IDs
4. API endpoints exist but require specific context/headers
5. Very deep subcategory structure (1825 items at level 4)
