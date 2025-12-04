# Navigation Discovery System - Design Document

## Goal

Extract all product categorizations from fashion brand websites by getting navigation links from their menus - whatever form the menu takes.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    DISCOVERY PHASE                          │
│                  (LLM + Chrome DevTools MCP)                │
│                                                             │
│  1. Navigate to site                                        │
│  2. Check for API (PRIORITY #1)                            │
│  3. If no API, explore DOM and write extraction script      │
│  4. Validate extraction works on fresh page                 │
│  5. Save method_summary.json                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    method_summary.json
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   EXTRACTION PHASE                          │
│                (Deterministic - No LLM)                     │
│                                                             │
│  1. Read method_summary.json                                │
│  2. If API: fetch and parse                                 │
│  3. If DOM: execute pre_actions + extraction_script         │
│  4. Save navigation_tree.json                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Method Priority (CRITICAL)

The LLM MUST check for extraction methods in this order:

### Priority 1: API Endpoint
- Check `list_network_requests` for XHR/fetch calls
- Look for endpoints like `/categories`, `/navigation`, `/menu`
- If found, extraction is just: `fetch(url).then(r => r.json())`
- **Examples**: Zara (`/us/en/categories?ajax=true`)

### Priority 2: Embedded JSON
- Check for `window.__NEXT_DATA__` (Next.js sites)
- Check for `window.__PRELOADED_STATE__` (Redux)
- Check for `<script id="...">` with JSON data
- **Examples**: H&M, Uniqlo

### Priority 3: DOM Extraction
- Only if API and embedded data don't exist
- Requires interaction (hover/click) to reveal menu
- Script reads visible DOM elements
- **Examples**: Eckhaus Latta, Acne Studios

---

## Key Technical Constraints

### 1. MCP Snapshot vs Real DOM

The MCP `take_snapshot` returns **accessibility tree** attributes, NOT actual HTML:

| Snapshot Shows | Real DOM |
|----------------|----------|
| `haspopup="menu"` | `aria-haspopup="menu"` or nothing |
| `button "Open menu"` | `<a aria-label="Open menu">` |
| `expandable` | `aria-expanded="false"` |

**Rule**: ALWAYS use `evaluate_script` to get real CSS selectors:
```javascript
() => {
  const el = document.querySelector('...');
  return {
    selector: el.getAttribute('aria-label')
      ? `${el.tagName.toLowerCase()}[aria-label="${el.getAttribute('aria-label')}"]`
      : null
  };
}
```

### 2. Viewport Consistency

MCP browser and Playwright MUST use same viewport to ensure:
- Same elements are visible
- Same responsive breakpoints apply
- Mobile-only elements don't break extraction

**Standard viewport**: 1280x800 (desktop)

### 3. Visibility Check

When finding elements for `pre_extraction_actions`, verify they're visible:
```javascript
() => {
  const el = document.querySelector('...');
  const style = getComputedStyle(el);
  return style.display !== 'none' && style.visibility !== 'hidden';
}
```

### 4. Fresh Page Validation

Before saving, the LLM MUST:
1. Reload the page (`navigate_page` with `type: "reload"`)
2. Execute the full extraction flow from scratch
3. Verify non-empty results

---

## method_summary.json Schema

```json
{
  "brand": "brand_name",
  "url": "https://...",

  // Method type determines extraction approach
  "method": "api" | "embedded_json" | "dom",

  // For API method
  "api_endpoint": "/us/en/categories?ajax=true",
  "api_parser": "function parseCategories(data) { ... }",

  // For DOM method
  "pre_extraction_actions": [
    {"action": "hover" | "click", "selector": "a[aria-label='...']"}
  ],
  "extraction_script": "function extractNavigation() { ... }",

  // Metadata
  "top_level_categories": ["Women", "Men", ...],
  "stats": {"total_categories": N, "max_depth": N},
  "notes": "Brief description"
}
```

---

## Discovery Flow (Detailed)

### Phase 1: Check for API

```
1. Navigate to URL
2. Wait for page load
3. Call list_network_requests(resourceTypes: ["xhr", "fetch"])
4. Look for requests containing:
   - "categories", "navigation", "menu" in URL
   - Response content-type: application/json
5. If found:
   - Get full response with get_network_request
   - Verify it contains navigation data
   - Write api_parser function
   - DONE - save and finish
```

### Phase 2: Check for Embedded Data

```
1. Call evaluate_script to check:
   - window.__NEXT_DATA__?.props?.pageProps
   - window.__PRELOADED_STATE__
   - document.querySelectorAll('script[type="application/json"]')
2. If navigation data found:
   - Write parser to extract from that location
   - DONE - save and finish
```

### Phase 3: DOM Extraction

```
1. Take snapshot, find menu trigger
2. Use evaluate_script to get REAL CSS selector (not snapshot attrs)
3. Perform action (hover/click) to reveal menu
4. Take snapshot to see navigation
5. Write extraction_script that:
   - Does NOT include interactions (those go in pre_extraction_actions)
   - Just reads visible DOM
   - Returns [{name, url, children}]
6. Test with evaluate_script
7. Reload page and test full flow
8. DONE - save and finish
```

---

## Extraction Script Rules

1. **No interactions inside script** - hover/click go in `pre_extraction_actions`
2. **Use querySelectorAll** - simple CSS selectors, not complex logic
3. **Filter duplicates** - use Set to track seen URLs
4. **Handle hierarchy** - if subcategories exist, nest them
5. **Return consistent format**:
```javascript
[{
  name: "Category Name",
  url: "https://..." | null,
  children: [/* recursive */]
}]
```

---

## Testing Strategy

Before deploying changes, test on representative brands:

| Brand | Method | Complexity |
|-------|--------|------------|
| Zara | API | Simple - clean JSON endpoint |
| H&M | Embedded | Medium - Next.js data |
| Eckhaus Latta | DOM + Hover | Medium - hover to reveal |
| Acne Studios | DOM + Click | Complex - click + state classes |

All 4 must pass extraction after any code change.

---

## Error Handling

1. **API not found**: Proceed to embedded data check
2. **No embedded data**: Proceed to DOM extraction
3. **Menu not visible**: Try common triggers (hover on "Shop", click hamburger)
4. **Script returns empty**: Log error, don't save as success
5. **Max turns reached**: Save partial progress with `success: false`

---

## Cost Optimization

1. **Check API first** - cheapest extraction method
2. **Limit turns** - 20 max, should complete in 10-15
3. **Cache system prompt** - use prompt caching
4. **Truncate large responses** - 8000 char limit on tool results

---

## Files

```
nav_v4/
├── discover_navigation.py   # LLM agent - discovers extraction method
├── extract_navigation.py    # Deterministic - runs extraction
├── extractions/
│   └── {brand}/
│       ├── method_summary.json    # How to extract
│       ├── navigation_tree.json   # Extracted data
│       └── discovery_metrics.json # Cost/time tracking
└── DESIGN.md                # This document
```
