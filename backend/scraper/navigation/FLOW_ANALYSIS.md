# Dynamic Navigation Explorer - Flow Analysis

## Overview

The dynamic explorer captures navigation states by clicking through menus,
then builds a tree from those states.

## Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 1: EXPLORATION                              │
│                         (dynamic_explorer.py)                               │
└─────────────────────────────────────────────────────────────────────────────┘

explore(url)
    │
    ├──► [1] Load page, dismiss popups
    │
    ├──► [2] Capture initial state (screenshot + ARIA)
    │
    ├──► [3] LLM CALL #1: prompt_top_level()
    │         Input: header ARIA + screenshot
    │         Output: List of top-level nav items (buttons/tabs/links/groups)
    │         Parser: parse_items()
    │
    │         FILTERING: None at LLM level - prompt says to IGNORE utility items
    │         but LLM compliance varies
    │
    ├──► [4] Check for toggle menu (hamburger)
    │         If found → explore_toggle_menu() path
    │         Else → DFS exploration path
    │
    │   ┌─────────────────────────────────────────────────────────────────────┐
    │   │              PATH A: TOGGLE MENU EXPLORATION                        │
    │   └─────────────────────────────────────────────────────────────────────┘
    │   │
    │   ├──► Click toggle menu button
    │   │
    │   ├──► LLM CALL #2: prompt_menu_structure()
    │   │         Input: ARIA of open menu
    │   │         Output: {top_level, subcategories, links}
    │   │         Parser: parse_menu_structure()
    │   │
    │   └──► explore_toggle_menu() loop:
    │             For each top_level:
    │                 Click top_level
    │                 Extract links from ARIA
    │                 FILTER: filter_utility_links()
    │
    │                 LLM CALL #3: prompt_subcategories()
    │                     Input: ARIA + current_path + extracted_links
    │                     Output: expandable items + leaf links + is_product_listing
    │                     Parser: parse_subcategories()
    │
    │                 For each expandable subcategory:
    │                     Click subcategory
    │                     Extract links
    │                     FILTER: filter_utility_links()
    │                     Capture state with new_links
    │
    │   ┌─────────────────────────────────────────────────────────────────────┐
    │   │              PATH B: DFS EXPLORATION                                │
    │   └─────────────────────────────────────────────────────────────────────┘
    │   │
    │   └──► DFS loop (while stack not empty):
    │             Pop path from stack
    │
    │             [For top-level items] Try hover first
    │                 If content revealed → capture without clicking
    │                 FILTER: filter_utility_links()
    │
    │             Navigate to path (click sequence)
    │
    │             LLM CALL #4: prompt_subcategories()
    │                 Input: ARIA + current_path + extracted_links
    │                 Output: expandable items + leaf links + is_product_listing
    │                 Parser: parse_subcategories()
    │
    │                 PRODUCT LISTING DETECTION:
    │                     If LLM returns PAGE_TYPE: LEAF → stop exploring children
    │
    │             Extract links from ARIA
    │             FILTER: filter_utility_links()
    │
    │             Compare to initial state links
    │             new_links = current_links - initial_links
    │
    │             Capture state with new_buttons + new_links
    │
    │             Add children to stack (filtered by siblings)

    │
    │   Returns: list of states + llm_usage


┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 2: TREE BUILDING                            │
│                            (build_tree.py)                                  │
└─────────────────────────────────────────────────────────────────────────────┘

run_dynamic() in extractor.py:
    │
    ├──► find_cross_toplevel_urls(states)
    │         Find URLs appearing in 2+ top-level tabs → filter them out
    │
    ├──► build_tree(states, base_url, filter_urls)
    │         For each state:
    │             Navigate tree to path
    │             Add links to node
    │
    │             FILTERS:
    │             - Skip if URL in filter_urls (cross-toplevel)
    │             - Skip if is_homepage_url()
    │             - Skip if is_product_link() ← ONLY checks /product/, /products/, /p/, /item/
    │
    └──► dedupe_parent_child_links(tree)
              Remove duplicate URLs between parent and children


┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 3: FORMAT CONVERSION                        │
│                            (extractor.py)                                   │
└─────────────────────────────────────────────────────────────────────────────┘

extract_navigation_tree_async():
    │
    ├──► Run static + dynamic in parallel
    │
    ├──► Pick tree with more links
    │
    ├──► convert_to_scraper_format(tree)
    │         Convert links array to children nodes
    │
    └──► strip_homepage_nodes(category_tree, url)
              Remove any homepage nodes
```

## Filtering Points Summary

| Location | Function | What It Filters |
|----------|----------|-----------------|
| dynamic_explorer.py:413 | filter_utility_links() | Cart, login, FAQ, social, etc. by URL/name |
| dynamic_explorer.py:463 | filter_utility_buttons() | Back, close, search, menu, etc. |
| build_tree.py:43 | is_product_link() | URLs with /product/, /products/, /p/, /item/ |
| build_tree.py:33 | is_homepage_url() | Root path URLs |
| build_tree.py:15 | find_cross_toplevel_urls() | URLs appearing in 2+ top-levels |
| extractor.py:234 | strip_homepage_nodes() | Nodes whose URL is homepage |

## LLM Prompts Summary

| # | Function | Purpose | Key Instructions |
|---|----------|---------|------------------|
| 1 | prompt_top_level() | Find main nav items | IGNORE: Search, Cart, Login, About, FAQ, Support |
| 2 | prompt_menu_structure() | Analyze toggle menu | Classify as TOP_LEVEL, SUBCATEGORIES, or LINKS |
| 3 | prompt_subcategories() | Find children | Detect LEAF pages via Filter/Sort controls; exclude products |

## Known Gaps

1. **External domains not filtered** - Links to different domains are kept
2. **Product URL detection too narrow** - Only checks for /product/, /products/
3. **Product name patterns not detected** - Discount labels (-30%), prices ($XX)
4. **LLM compliance varies** - May return products as categories despite instructions
5. **Pagination controls not filtered** - "Load more products" captured as category

---

## Case Study: basketcase_com_co

The extraction produced 32 "categories" but most are actually products:

```json
{
  "name": "-30% Basket Case Beyblade Hoodie Black",
  "url": "https://basketcase-gallery.com/basket-case-beyblade-hoodie-black/"
}
```

### Why Products Slipped Through

| Filter | Check | Result |
|--------|-------|--------|
| **filter_utility_links()** | URL patterns: login, cart, etc. | ✅ PASSED - no match |
| **filter_utility_links()** | Name patterns: login, cart, etc. | ✅ PASSED - no match |
| **filter_utility_links()** | External domain check | ❌ NO CHECK - basketcase-gallery.com != basketcase.com.co |
| **is_product_link()** | `/product/`, `/products/`, `/p/`, `/item/` | ✅ PASSED - URL uses flat slug |
| **is_product_link()** | Product name patterns | ❌ NO CHECK - "-30%", "Hoodie", "T-Shirt" |
| **prompt_subcategories()** | LLM instruction to exclude products | ⚠️ IGNORED - LLM returned them anyway |

### Specific Issues Found

1. **External Domain** (`basketcase-gallery.com` vs source `basketcase.com.co`)
   - Neither `filter_utility_links()` nor `build_tree()` check domain
   - Should filter links to different domains

2. **WooCommerce/WordPress URL Pattern**
   - URL: `/basket-case-beyblade-hoodie-black/`
   - `is_product_link()` only checks `/product/`, `/products/`, etc.
   - Flat slugs bypass the filter entirely

3. **Product Name Patterns** not detected:
   - Discount: `-30%`, `-31%`, `NEW`
   - Product words: `Hoodie`, `T-Shirt`, `Jeans`, `Sneakers`
   - Brand+Product format: `Basket Case Gallery Hoodie Black`

4. **Pagination Controls** captured as links:
   - `"Load more products"` → `basketcase.com.co/"#"`

---

## Proposed Fixes

### Fix 1: Filter External Domains (filter_utility_links)

```python
def filter_utility_links(links: dict, base_domain: str = None) -> dict:
    # Add domain check
    if base_domain:
        from urllib.parse import urlparse
        for name, url in list(links.items()):
            try:
                parsed = urlparse(url)
                if parsed.netloc and parsed.netloc != base_domain:
                    del links[name]  # External domain
            except:
                pass
```

### Fix 2: Expand Product URL Detection (build_tree.py)

```python
def is_product_link(url: str, name: str = "") -> bool:
    """Check if URL/name indicates a product page."""
    url_lower = url.lower()
    name_lower = name.lower()

    # URL patterns
    product_url_patterns = [
        '/product/', '/products/', '/p/', '/item/',
        # WooCommerce often uses: /product-name-slug/
    ]
    if any(p in url_lower for p in product_url_patterns):
        return True

    # Name patterns suggesting individual product
    product_name_patterns = [
        r'^-?\d+%',           # Discount: -30%, 50%
        r'\$\d+',             # Price: $89
        r'\d+\s*(USD|EUR)',   # Currency
    ]
    import re
    for pattern in product_name_patterns:
        if re.search(pattern, name):
            return True

    # Product type words (only if name is long enough to be specific item)
    if len(name.split()) >= 4:  # "Basket Case Beyblade Hoodie Black" = 5 words
        product_words = ['hoodie', 't-shirt', 'tshirt', 'jeans', 'pants',
                        'sneakers', 'dress', 'jacket', 'coat', 'shorts']
        if any(w in name_lower for w in product_words):
            return True

    return False
```

### Fix 3: Add Name Filtering to filter_utility_links

```python
skip_names.extend([
    'load more', 'show more', 'view all',  # Pagination
])

# Product name detection
if re.match(r'^-?\d+%', name):  # Starts with discount
    continue
```

### Fix 4: Strengthen LLM Prompt

Add explicit examples to `prompt_subcategories()`:

```
PRODUCTS TO EXCLUDE (specific items):
- "-30% Brand Name Hoodie Black" ← discount + product name
- "Nike Air Max 90 White" ← brand + model + color
- "Load more products" ← pagination control
```

---

## Implementation Priority

1. **High**: External domain filtering - simple, high impact
2. **High**: Product name pattern detection (discount labels)
3. **Medium**: Expanded URL detection (won't catch all)
4. **Low**: LLM prompt strengthening (compliance varies)

---

## Fix Applied (Feb 2026)

### Root Cause
The `new_links` stored in states came from `extract_links_from_aria()` which captured ALL links.
The LLM returned `leaf_links` (approved category links) but this was **never used** to filter.

```python
# BEFORE: Captured all 70 links including products
links = extract_links_from_aria(aria)
state['new_links'] = links

# llm_links was created but never used to filter!
llm_links = {s['name']: 'link' for s in leaf_links}
```

### Solution
Use LLM-approved links as the source of truth:

```python
# AFTER: Only keep LLM-approved category links
all_links = extract_links_from_aria(aria)
_, leaf_links, _ = parse_subcategories(llm_response)
llm_approved = {link['name'].lower() for link in leaf_links}
approved_links = {name: url for name, url in all_links.items()
                 if name.lower() in llm_approved}
state['new_links'] = approved_links
```

### Files Changed
- `dynamic_explorer.py`: 4 locations where `state['new_links']` is set
  - Toggle menu top-level (line ~1250)
  - Toggle menu subcategory (line ~1324)
  - DFS main loop (line ~1700)
  - DFS hover path (line ~1590)
- `extractor.py`: Fixed tuple unpacking for `dynamic_explore()` return

### Result
- Before: 70 links captured (including products like "-30% Basket Case Hoodie")
- After: 5 links approved by LLM (actual categories: Shop, Hoodie, Jacket, etc.)
