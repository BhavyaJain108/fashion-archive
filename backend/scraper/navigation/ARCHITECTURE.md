# Navigation Scraper Architecture

## Purpose

Extract product category navigation trees from fashion websites. Given a URL like `https://www.eckhauslatta.com`, produce a structured tree:

```
Women
├── Clothing
│   ├── Dresses → /women/dresses
│   └── Tops → /women/tops
└── Shoes
    └── Heels → /women/heels
Men
└── Shirts → /men/shirts
```

## High-Level Flow

```
1. Navigate to site
2. Dismiss popups (cookies, newsletter, etc.)
3. Open navigation menu (hamburger or hover)
4. Capture ARIA diff (what became visible)
5. Detect tabs (Women, Men, Kids) if present
6. DFS exploration:
   a. Click/hover expandable element
   b. Capture ARIA diff
   c. Extract links and new expandables
   d. Add to stack, continue until exhausted
7. Build category tree and return results
```

## Entry Points

### Primary: `NavExplorer` (step_explorer.py)

Step-by-step exploration with full control:

```python
from scraper.navigation.step_explorer import NavExplorer

explorer = NavExplorer(page)
await explorer.setup(url)

# Explore step by step
while explorer.has_next():
    result = await explorer.step()
    print(f"Found: {result.revealed_links}")

# Get results
categories = explorer.categories  # {path: url}
explorer.print_tree()
```

### Legacy: `explore_all_tabs()` (dynamic_explorer.py)

Automatic exploration (5000-line monolith, being deprecated):

```python
from scraper.navigation.dynamic_explorer import explore_all_tabs
results = await explore_all_tabs(page, tabs, base_url, menu_result)
```

## Key Concepts

### ARIA as Source of Truth

ARIA snapshots capture what's **visible** on the page:
- Only visible elements appear in snapshot
- Opening a menu = new ARIA lines appear
- Closing a menu = those lines disappear

```python
aria_before = await page.locator('body').aria_snapshot()
# ... interact ...
aria_after = await page.locator('body').aria_snapshot()

# The diff IS what became visible
new_lines = [l for l in aria_after.split('\n') if l not in aria_before]
```

### Menu Detection via ARIA Diff

When we click a menu button:
1. Capture ARIA before click
2. Click the button
3. Capture ARIA after click
4. The diff = the menu content

No need to search DOM by text - the diff tells us exactly what appeared.

### Button Relationship Classification

Buttons near links can be:
- **EXPANDS**: Button reveals more of the nearby link's category (e.g., ">" next to "Shoes")
- **SEPARATE**: Button is its own category (e.g., "Sale" button)

We use LLM with **Pydantic structured outputs** to classify:
```python
class ButtonClassification(BaseModel):
    expands: list[int]  # 1-indexed pair numbers that EXPAND

# Batch call - one LLM call for all pairs
result = await classify_button_relationships_batch([
    ("See More", "Dresses"),
    ("Lingerie", "Shoes"),  # Different categories
])
# Result: {"See More": "EXPANDS", "Lingerie": "SEPARATE"}
```

**Why Pydantic?** Free-text LLM responses are unreliable to parse. The LLM might say "1. THESE ARE SEPARATE" and naive regex extracts "1" as an EXPANDS case. Structured outputs guarantee the response format.

### Preventing Infinite Loops

Same-named buttons can create infinite paths:
```
Menu > Lingerie > Lingerie > Lingerie > ...
```

Prevention:
1. Skip consecutive duplicates (`path[-1] == item['name']`)
2. Check both `explored` set AND `stack` before adding
3. Different branches can have same names (`Women > Sale` vs `Men > Sale`)

### CSS-Based Utility Filtering

**Problem:** Navigation menus contain utility elements (language selectors, help links, account buttons) mixed with actual product categories. We need to filter these out.

**Solution:** Group elements by their parent's CSS class, ask LLM which groups are utility.

```
Menu ARIA contains:
  - NEW IN, Clothing, Shoes, Accessories (CSS: _75qWlu)
  - Deutsch, English, Help, Newsletter (CSS: Rt7sMf)

LLM: "Group 2 is utility (language/help)" → exclude Rt7sMf
```

#### Critical Design Decision: ARIA→DOM Direct Mapping

**The Wrong Approach (what we tried first):**
1. Parse ARIA → get element names
2. Scan DOM independently with `querySelectorAll` → group by CSS
3. Match ARIA names to DOM names by text

**Why it failed:**
- ARIA gives `"English, Current language"` (accessible name)
- DOM `textContent.trim()` gives `"English"`
- Text mismatch → element not filtered → utility element leaks through

**The Right Approach:**
1. Parse ARIA → get elements with name + role
2. For EACH element, use `page.get_by_role(role, name=name)` → find exact element → get CSS
3. Group by CSS → LLM excludes → filter

```python
# Direct lookup - same element ARIA found
locator = page.get_by_role('button', name='English, Current language')
css_class = await locator.evaluate('el => el.parentElement.className')
# css_class = "Rt7sMf" → matches exclusion → filtered out
```

**Key insight:** We already have the element identifier from ARIA (role + name). Use Playwright's `get_by_role()` which matches ARIA's accessible name. Don't do a separate DOM scan that might find different elements.

#### Implementation: `extraction/nav_elements.py`

```python
async def _get_css_for_elements(page, elements, menu_selector):
    """Get CSS class for each ARIA element by locating it directly."""
    for el in elements:
        role = el.get('aria_role', el['type'])
        locator = page.get_by_role(role, name=el['name'])
        css_class = await locator.evaluate('el => el.parentElement.className')
        el['css_class'] = css_class
```

Flow:
1. `_parse_aria_with_hierarchy()` → elements with name, type, aria_role
2. `_get_css_for_elements()` → add css_class to each element
3. Group by css_class → `_exclude_utility_groups()` (LLM)
4. Filter: if `el['css_class'] in excluded_groups` → remove

### Menu State Management

`MenuContext` tracks:
- `base_url`: URL to return to if navigated away
- `menu_container_selector`: CSS selector for menu element
- `menu_aria`: ARIA content of the menu

After each interaction:
1. Check if content still visible (ARIA diff)
2. Check if URL changed
3. If lost: reset to base URL, reopen menu via cached selector

## Current Module Structure

```
backend/scraper/navigation/
├── step_explorer.py        # PRIMARY - Step-by-step explorer
├── dynamic_explorer.py     # LEGACY - Monolith being extracted
├── llm_popup_dismiss.py    # Popup dismissal with LLM
├── popup_selectors.py      # CSS selectors for common popups
│
├── aria/                   # ARIA utilities
│   ├── diff.py             # get_new_content, hover_revealed_content
│   └── elements.py         # find_expandable_elements, extract_buttons_from_aria
│
├── extraction/             # Element extraction with filtering
│   ├── links.py            # extract_links_from_aria
│   └── nav_elements.py     # CSS-based filtering (ARIA→DOM direct mapping)
│
├── llm/                    # LLM utilities
│   ├── classification.py   # Button classification with Pydantic structured outputs
│   ├── prompts.py          # Prompt templates
│   ├── parsers.py          # Response parsers
│   └── client.py           # LLM wrapper with usage tracking
│
├── menu/                   # Menu utilities
│   ├── context.py          # MenuContext
│   └── cache.py            # Menu button caching
│
├── interaction/            # (TO CREATE)
│
├── output/                 # Output formatting
│   └── tree.py             # NavTree class
│
└── debug.ipynb             # Test notebook
```

## Known Issues & Refactoring Plan

### Issue 1: Duplicate Functions

Functions exist in BOTH `dynamic_explorer.py` AND extracted modules:

| Function | In dynamic_explorer | In module | Status |
|----------|---------------------|-----------|--------|
| `extract_links_from_aria()` | :3833 | extraction/links.py | DUPLICATE |
| `filter_utility_links()` | :877 | extraction/links.py | DUPLICATE |
| `get_new_content()` | :3302 | aria/diff.py | DIVERGENT (different impl) |
| `hover_revealed_content()` | :2157 | aria/diff.py | DUPLICATE |
| `MenuContext` | :37 | menu/context.py | DUPLICATE |
| `find_expandable_elements()` | :3467 | aria/elements.py | DIFFERENT versions |

**Action**: step_explorer.py imports from dynamic_explorer. Need to switch to modules.

### Issue 2: Functions That Should Move

```
TO aria/elements.py:
  - find_expandable_elements()     (from dynamic_explorer:3467)

TO aria/diff.py:
  - get_content_diff()             (from dynamic_explorer:3332)
  - compute_aria_diff()            (from dynamic_explorer)

TO llm/classification.py (NEW):
  - classify_button_relationship() (from dynamic_explorer:3549)
  - identify_main_menu_group()     (from dynamic_explorer:3415)
  - identify_tabs_with_llm()       (from dynamic_explorer:1530)

TO menu/opening.py (NEW):
  - open_menu_and_capture()        (from dynamic_explorer:1307)
  - find_menu_container()          (from dynamic_explorer:1030)
  - find_menu_from_aria_diff()     (from dynamic_explorer:1099)
  - reopen_menu_fast()             (from dynamic_explorer:242)

TO menu/tabs.py (NEW):
  - find_tabs_in_dom()             (from dynamic_explorer:1614)
  - group_buttons_by_css()         (from dynamic_explorer:3370)

TO interaction/clicking.py (NEW):
  - click_button()                 (from dynamic_explorer:1860)
  - hover_and_check()              (from dynamic_explorer:2195)
  - find_back_button()             (from dynamic_explorer:2776)
```

### Issue 3: step_explorer.py Imports

Currently imports 20+ functions from dynamic_explorer:
```python
from scraper.navigation.dynamic_explorer import (
    open_menu_and_capture,
    find_expandable_elements,
    extract_links_from_aria,      # Should be: extraction/links.py
    filter_utility_links,         # Should be: extraction/links.py
    get_new_content,              # Should be: aria/diff.py
    MenuContext,                  # Should be: menu/context.py
    # ... 15 more
)
```

## Target Module Structure

```
backend/scraper/navigation/
├── step_explorer.py            # Main explorer class
│
├── aria/
│   ├── diff.py                 # ARIA diffing: get_new_content, get_content_diff
│   └── elements.py             # Element extraction: find_expandable_elements
│
├── extraction/
│   └── links.py                # Link extraction: extract_links_from_aria
│
├── menu/
│   ├── context.py              # MenuContext dataclass
│   ├── opening.py              # Menu opening: open_menu_and_capture
│   ├── tabs.py                 # Tab detection: find_tabs_in_dom
│   └── cache.py                # Menu button caching
│
├── interaction/
│   ├── clicking.py             # click_button, hover_and_check
│   └── navigation.py           # find_back_button, check_and_restore_menu
│
├── llm/
│   ├── classification.py       # classify_button_relationship, identify_tabs
│   ├── prompts.py              # Prompt templates
│   ├── parsers.py              # Response parsers
│   └── client.py               # LLM wrapper
│
├── output/
│   └── tree.py                 # NavTree, print_tree
│
├── llm_popup_dismiss.py        # Popup handling
└── debug.ipynb                 # Testing
```

## Design Decisions

### Why ARIA snapshots?
- Consistent structured representation across sites
- Only captures VISIBLE content (hidden elements excluded)
- Includes accessibility labels (better than raw HTML)
- Captures dynamic content state

### Why ARIA diff instead of DOM scanning?
- Diff tells us exactly what appeared (no guessing)
- No need to scan 100+ elements to find menu
- Works regardless of DOM structure
- Fast: O(lines) vs O(elements)

### Why LLM for button classification?
- Text patterns are unreliable (">" vs "See More" vs icon)
- Semantic understanding needed
- Cache per indent level = 1 LLM call per depth, not per button

### Why cache at indent level?
- Buttons at same depth behave consistently on a site
- First ">" at indent 6 → all ">" at indent 6 are EXPANDS
- Reduces LLM calls from O(buttons) to O(depth)

### Why Pydantic structured outputs for LLM?
- **Problem:** Free-text parsing is fragile. LLM says "1. THESE ARE SEPARATE" and regex extracts "1" as an EXPANDS case.
- **Solution:** Define Pydantic schema, use tool_use/structured output. LLM returns `{"expands": []}` guaranteed.
- **Benefit:** No parsing code, no regex, no edge cases. Schema IS the contract.

### Why ARIA→DOM direct mapping (not separate DOM scan)?
- **Problem:** CSS filtering needs each element's CSS class. Initial approach: scan DOM with `querySelectorAll`, group by CSS, match to ARIA by text.
- **Failure mode:** ARIA name `"English, Current language"` vs DOM `textContent.trim()` = `"English"`. Text mismatch → filter fails.
- **Solution:** For each ARIA element, use `page.get_by_role(role, name=name)` to find THE SAME element. Get its CSS directly.
- **Key insight:** We already have identifiers (role + accessible name). Don't cast a new net - use what ARIA gave us.

### Why CSS grouping for utility detection?
- **Observation:** Navigation items share CSS styling. Utility items (language, help, account) have different styling.
- **Approach:** Group elements by parent CSS class → LLM identifies which groups are utility → filter.
- **Alternative rejected:** Keyword filtering ("Deutsch", "English", "Help") is fragile. "English" could be a product line name.
- **LLM advantage:** Semantic understanding. Group with ["Deutsch", "English", "日本語"] is obviously language selector.

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Menu closes unexpectedly | Popup dismissal clicked "Close" | Use `menu_is_open=True` |
| Infinite loop A > A > A | Same button appears in diff | Skip consecutive duplicates |
| Adding duplicates to stack | Not checking stack, only explored | Check both sets |
| 110 elements scanned | Searching DOM by role | Use ARIA diff directly |
| "Winter Winter" in logs | Text-based element search | Removed, use ARIA structure |
| networkidle timeout | Site has constant analytics | Use `load` + fixed timeout |

## Usage

### Step-by-Step Exploration

```python
from scraper.navigation.step_explorer import NavExplorer

explorer = NavExplorer(page)
result = await explorer.setup("https://example.com")

if result['success']:
    print(f"Found {result['tabs']} tabs, {result['expandables']} expandables")

    while explorer.has_next():
        step = await explorer.step()
        if step.success:
            print(f"  Links: {list(step.revealed_links.keys())}")

    explorer.print_tree()
```

### Accessing Results

```python
# All categories as flat dict
categories = explorer.categories  # {"Women > Dresses": "/women/dresses", ...}

# Current state
explorer.show_state()  # Shows stack, explored count, current item
```
