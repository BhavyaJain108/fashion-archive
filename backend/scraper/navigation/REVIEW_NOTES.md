# Navigation Scraper Review Notes

## Core Purpose
**Goal:** Visit a fashion website, analyze whatever menu structure it has, and extract all product categories from the navigation.

The system must handle diverse menu patterns:
- Desktop mega-menus (hover to reveal)
- Mobile hamburger menus (click to toggle)
- Accordion menus (click to expand sections)
- Tab-based navigation (click tabs to switch panels)
- Direct link navigation (no expansion, just links)
- Hybrid approaches (mix of above)

---

## Key Constraints

### Technical Constraints
1. **ARIA snapshots** - Primary method for understanding page structure (Playwright's accessibility tree)
2. **LLM token limits** - Must truncate ARIA to ~8000-15000 chars
3. **Dynamic content** - Menus may load via JavaScript, need wait strategies
4. **Popups/overlays** - Cookie banners, newsletter popups block navigation
5. **Mobile vs Desktop** - Different menu structures at different viewport widths

### Business Constraints
1. **Fashion sites only** - Can make assumptions about category names (Women, Men, Shoes, Bags, etc.)
2. **Product categories only** - Must filter out utility links (Cart, Login, FAQ, etc.)
3. **Cost efficiency** - Minimize LLM calls while maintaining accuracy

---

## Design Decisions Log

### Decision 1: Two Extractors (Static vs Dynamic)
- **Static:** Single LLM call on raw links - fast, cheap, works for simple sites
- **Dynamic:** Interactive exploration with clicks/hovers - handles complex menus
- **Why both:** Some sites need interaction, others don't. Run both, pick best result.

### Decision 2: ARIA over DOM
- ARIA snapshots give semantic structure (buttons, tabs, links with roles)
- Cleaner than raw HTML, includes accessibility labels
- Limitation: Can be verbose, needs truncation

### Decision 3: Header-first ARIA
- `header` element ARIA is cleaner than full `body`
- Avoids popup/cookie/country selector noise
- Fallback to body if header empty

---

## Function Review Status

| # | Function | Lines | Status | Keep/Modify/Remove | Notes |
|---|----------|-------|--------|-------------------|-------|
| 1 | `_get_llm_handler()` | 34-39 | Reviewed | | Singleton for LLM |
| 2 | `_track_llm_result()` | 41-46 | Reviewed | | Usage tracking |
| 3 | `prompt_top_level()` | 53-83 | In Review | | First LLM prompt |
| 4 | `prompt_menu_structure()` | 86-118 | Pending | | Hamburger menu analysis |
| 5 | `prompt_subcategories()` | 121-214 | Pending | | Subcategory extraction |
| 6 | `parse_subcategories()` | 217-264 | Pending | | Parse LLM response |
| 7 | `parse_menu_structure()` | 267-302 | Pending | | Parse menu structure |
| 8 | `parse_items()` | 305-337 | Pending | | Parse items list |
| 9 | `extract_buttons_from_aria()` | 344-387 | Pending | | Extract buttons |
| 10 | `extract_links_from_aria()` | 390-431 | Pending | | Extract links |
| 11 | `filter_utility_links()` | 434-481 | Pending | | Filter non-product links |
| 12 | `filter_utility_buttons()` | 484-513 | Pending | | Filter utility buttons |
| 13 | `element_exists()` | 520-537 | Pending | | Check element visibility |
| 14 | `click_button()` | 540-630 | Pending | | Click by name |
| 15 | `hover_revealed_content()` | 633-663 | Pending | | Check hover reveals |
| 16 | `hover_and_check()` | 666-752 | Pending | | Hover + capture state |
| 17 | `find_menu_container()` | 755-777 | Pending | | Find menu container |
| 18 | `open_menu()` | 780-831 | Pending | | Open hamburger menu |
| 19 | `is_hamburger_menu_open()` | 834-888 | Pending | | Check menu state |
| 20 | `find_back_button()` | 889-927 | Pending | | Find back button |
| 21 | `click_back_at_level()` | 930-959 | Pending | | Click back at level |
| 22 | `try_click_with_url_check()` | 962-996 | Pending | | Click + check navigation |
| 23 | `navigate_to_path()` | 999-1187 | Pending | | DFS path navigation |
| 24 | `capture_state()` | 1194-1232 | Pending | | Capture current state |
| 25 | `expand_all_collapsed()` | 1238-1286 | Pending | | Expand accordions |
| 26 | `explore_toggle_menu()` | 1289-1397 | Pending | | Hamburger menu explore |
| 27 | `explore()` | 1404-1902 | Pending | | Main entry point |
| 28 | `main()` | 1910-1992 | Pending | | CLI entry |

---

## Potential Module Structure

```
backend/scraper/navigation/
├── __init__.py
├── extractor.py              # Orchestrator (existing)
├── dynamic_explorer.py       # Complex menu exploration (refactor target)
├── static_extractor.py       # Simple link extraction (refactor target)
├── core/
│   ├── __init__.py
│   ├── constants.py          # Timeouts, skip lists, selectors
│   ├── types.py              # Data classes for state, results
│   └── llm_utils.py          # LLM handler, tracking, prompts
├── aria/
│   ├── __init__.py
│   ├── extractor.py          # extract_links, extract_buttons
│   ├── filters.py            # filter_utility_links, filter_utility_buttons
│   └── parser.py             # Parse LLM responses
├── browser/
│   ├── __init__.py
│   ├── actions.py            # click_button, hover_and_check
│   ├── navigation.py         # navigate_to_path, find_back_button
│   └── menu.py               # open_menu, is_hamburger_menu_open
└── strategies/
    ├── __init__.py
    ├── dfs_explorer.py       # DFS-based menu exploration
    └── toggle_menu.py        # Hamburger/accordion exploration
```

---

## Questions to Answer During Review

1. Which functions are actually used vs dead code?
2. Which prompts are effective vs need refinement?
3. What's the minimum set of functions needed?
4. Where are the failure modes / edge cases?
5. What timeouts/selectors are site-specific vs universal?

---

## Notes from Review

### Viewport Size Strategy
**Use mobile viewport (768x900)** - Most fashion sites show hamburger menus at mobile widths, which are easier to scrape than desktop mega-menus:
- Hamburger menus have a single toggle button
- Menu content appears in a predictable drawer/panel
- No complex hover states to manage
- Desktop mega-menus require hover coordination across multiple elements

### Menu Detection: Combined LLM Approach

**Problem:** Hamburger menu buttons are inconsistent across sites:
- Some have `data-menu-drawer` attributes
- Some are just `<button>shop</button>` with no menu keywords
- Some are `<a>` tags styled as buttons
- Some have no text (icon-only)

**Solution:** Two-phase extraction + single LLM call:

1. **Phase 1: Extract candidates (fast, free)**
   - `find_menu_elements()` - scans HTML for elements with menu-related attributes (data-menu, class*=nav, etc.)
   - `extract_header_buttons()` - gets ALL visible buttons and links (no filtering by container)

2. **Phase 2: LLM identification (one call)**
   - Send both lists to LLM in one prompt
   - LLM responds with `C0` (candidate index), `B2` (button index), or `NONE`
   - Avoids hardcoded selectors that break across sites

3. **Phase 3: Fallback selectors**
   - Only used if LLM fails
   - Common patterns like `.hamburger`, `[aria-label*="menu"]`

### Hover vs Click Strategy

**Problem:** Different sites behave differently:
- Eckhaus Latta: hover opens menu, click navigates to product page
- Uniqlo: click navigates to menu page (intentional)
- Most sites: click toggles menu open/closed

**Solution:** Try hover first, then click:

```
try_hover_then_click(element):
    1. Capture ARIA before
    2. Hover element
    3. Check for SUBSTANTIAL diff (not just any diff)
    4. If hover revealed 5+ nav items → use hover
    5. If hover didn't work → click
```

**Why "substantial diff"?** Popups can trigger small ARIA diffs. A real menu has many links/buttons. We require at least 5 new lines containing "link" or "button" to count as menu content.

### ARIA Diff for Menu Detection

**Problem:** How to know where menu content starts in ARIA? Can't use hardcoded patterns (sites vary too much).

**Solution:** Compare ARIA before/after opening menu:

```
open_menu_and_capture(page):
    1. Capture before_aria (menu closed)
    2. Open menu
    3. Capture after_aria (menu open)
    4. Diff to find new content
    5. Return menu_aria (truncated to just new content)
```

**Benefits:**
- No hardcoded patterns
- Works for any site
- Tells us exactly where menu content starts
- Can detect if menu closed (diff disappears)

### Menu State Management

**Keeping menu open:** After opening the menu, we never want to close it accidentally. The ARIA diff approach helps:
- Store the "first new line" that appeared when menu opened
- If that line disappears from ARIA, menu probably closed
- `ensure_menu_open()` can detect this and reopen

**MenuContext pattern:** To track menu state across interactions:

```python
@dataclass
class MenuContext:
    before_aria: str       # ARIA before menu opened
    base_url: str          # URL to return to if we navigate away
    menu_start_line: str   # First new line (for fast check)

# Create context from open_menu_and_capture() result
menu_ctx = MenuContext.from_menu_result(result, base_url)

# Pass to interactions - they auto-check/restore menu
await click_button(page, "Women", menu_ctx=menu_ctx)
await hover_and_check(page, "Shoes", menu_ctx=menu_ctx)
```

**Fast check:** `check_and_restore_menu()` first does a string search for `menu_start_line` in current ARIA (fast). Only if that fails does it do full ARIA diff and reopen.

### Top-Level Tab Detection (LLM + Geometric Verification)

**Problem:** After opening the menu, how do we detect which elements are top-level category tabs (Men, Women, Shoes)?

- **Uniqlo:** Uses proper ARIA `tablist` with `tab "women"`, `tab "men"`
- **Axel Arigato:** Uses `button "Men"`, `button "Women"` (no tab role)
- Some sites use links, others use divs with click handlers
- Element type doesn't matter - LLM handles it

**Solution:** Two-step approach combining LLM vision with geometric verification:

**Step 1: LLM identifies tab names** (`identify_tabs_with_llm`)
```
- Send screenshot + menu ARIA to LLM
- Ask: "What are the top-level category tab names?"
- LLM returns: ["Women", "Men", "Kids"]
```

**Step 2: Find tabs in DOM** (`find_tabs_in_dom`)
```
- Find all elements matching those text names
- Group by Y position (horizontal alignment)
- Pick the row with most matching tabs
- Deduplicate (nested elements have same text)
- Look up ARIA role for each tab
```

**Why this works:**
- LLM sees the visual and identifies tabs by appearance (no element type assumptions)
- Geometric check disambiguates duplicates (tab "Women" vs subcategory "Women")
- The one in horizontal row with other tabs is the right one
- Returns role from ARIA so we can click with `get_by_role()`

**Final output:**
```python
{
    'tabs': [
        {'text': 'Women', 'role': 'tab', 'x': 24, 'y': 64},
        {'text': 'Men', 'role': 'tab', 'x': 252, 'y': 64},
    ],
    'row_y': 64
}
```

### Key Implementation Details

1. **Button extraction includes `<a>` tags** - Many sites use links styled as buttons for nav
2. **Text length filter (50 chars)** - Skip long content links, keep short nav buttons
3. **LLM max_tokens=50 for menu ID** - Response is just `MENU: B2`, no need for more
4. **Wait 400-500ms after interactions** - Menu animations need time
5. **5+ nav items = real menu** - Threshold to distinguish menu from popup
6. **Tab detection uses Y-position grouping** - Elements at same Y = horizontal row

### CSS-Based Utility Filtering

**Problem:** Menu contains utility elements (language selector, help links) mixed with navigation. Need to filter them out.

**Failed approach:** Keyword filtering ("Deutsch", "English", "Help"). Fragile - "English" could be a product line.

**Solution:** CSS grouping + LLM.

```
Elements grouped by parent CSS class:
  Group 1 (_75qWlu): NEW IN, Clothing, Shoes, Accessories
  Group 2 (Rt7sMf): Deutsch, English, Help, Newsletter

LLM: "Group 2 is utility" → exclude Rt7sMf group
```

**Critical bug we encountered:** ARIA gives accessible name `"English, Current language"`. DOM `textContent.trim()` gives `"English"`. If we scan DOM separately to get CSS, we get different text → match fails → utility element leaks through.

**Solution:** Don't scan DOM separately. For each ARIA element, use `page.get_by_role(role, name=name)` which matches by accessible name (same as ARIA). Get CSS from that exact element.

```python
# ARIA found: button "English, Current language"
locator = page.get_by_role('button', name='English, Current language')
css = await locator.evaluate('el => el.parentElement.className')
# Correctly gets Rt7sMf → filtered out
```

### Pydantic Structured LLM Outputs

**Problem:** Parsing free-text LLM responses is fragile.

Example failure:
```
LLM response: "LOOKING AT EACH PAIR:
1. BUTTON "LINGERIE" NEAR LINK "SKIRTS" - THESE ARE SEPARATE"

Naive regex: re.findall(r'\d+', response) → ['1']
Result: Incorrectly marks pair 1 as EXPANDS
```

**Solution:** Use Pydantic models with `LLMHandler.call(response_model=...)`:

```python
class ButtonClassification(BaseModel):
    expands: list[int]  # 1-indexed pairs that EXPAND

result = llm.call(prompt, response_model=ButtonClassification)
# Guaranteed: {"expands": []} or {"expands": [2, 5]}
```

No parsing code. Schema IS the contract.

### Test Brands (10 sites covering different patterns)

| Brand | Pattern | Notes |
|-------|---------|-------|
| entire_studios | Simple nav | Button with text "shop" |
| prod_bldg | Hamburger | `.mobile-menu__button` class |
| named_collective | Accordion | `.site-header__button` class |
| alexander_mcqueen | Mega-menu | Complex hover states |
| balenciaga | Artistic nav | Unusual/minimal |
| zalando_kids | Deep tree | German locale, massive categories |
| uniqlo | Click-nav | Menu is separate page |
| aelfric_eden | Messy nav | `[data-menu-drawer]` attribute |
| eckhaus_latta | Hover menu | Click navigates, hover opens |
| axel_arigato | Clean nav | Scandinavian design |

---

## Debug Notebook

Located at `backend/scraper/navigation/debug.ipynb`

**Structure:**
1. Setup + imports + `reload_modules()`
2. Start browser (768x900 viewport)
3. Brand list (comment/uncomment to select)
4. Main test loop - runs all brands, opens menu, shows ARIA diff
5. Tab detection test - detects top-level category tabs using geometric layout
6. LLM usage tracking
7. Browser cleanup

**Key feature:** `reload_modules()` - edit source files and pick up changes without restarting notebook

---

## Tab Exploration Strategy

### Philosophy

**Core Principle:** Minimize LLM calls while maximizing extraction accuracy.

We achieve this through:
1. **Diff-based extraction** - Only send NEW content to LLM, not the full ARIA repeatedly
2. **Mode detection** - Detect if site pre-loads everything vs reveals on click, choose strategy accordingly
3. **Position-based caching** - Cache back button position after first detection, reuse without LLM
4. **Level skipping** - After 5 consecutive items at a level with no children, skip LLM for rest

### Decision Tree

```
┌─────────────────────────────────────────────────────────────────┐
│                        START: Site loaded                        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. Open hamburger menu                                          │
│     - Capture ARIA before/after                                  │
│     - LLM identifies menu button (1 call)                        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Detect top-level tabs                                        │
│     - LLM identifies tab names from screenshot (1 call)          │
│     - Find tabs in DOM with geometric verification (0 calls)     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
         ┌──────────────────────┴──────────────────────┐
         │                                             │
         ▼                                             ▼
┌─────────────────┐                         ┌─────────────────┐
│   Has tabs?     │                         │   No tabs       │
│   (Women, Men)  │                         │   (flat menu)   │
└────────┬────────┘                         └────────┬────────┘
         │                                           │
         ▼                                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. FOR EACH TAB (or root if no tabs):                           │
│     Click tab (URL change allowed here)                          │
│     Capture tab ARIA                                             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. MODE DETECTION: Click first expandable element               │
│     Compare ARIA before vs after                                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
                ▼                               ▼
┌───────────────────────┐           ┌───────────────────────┐
│  NO DIFF              │           │  DIFF EXISTS          │
│  (pre-loaded site)    │           │  (show/hide site)     │
└───────────┬───────────┘           └───────────┬───────────┘
            │                                   │
            ▼                                   ▼
┌───────────────────────┐           ┌───────────────────────┐
│  BULK MODE            │           │  DFS MODE             │
│  - 1 LLM call total   │           │  - 1 LLM call per     │
│  - Extract all cats   │           │    interaction        │
│    in one shot        │           │  - Only send DIFF     │
│  - No navigation      │           │  - Navigate tree      │
│    needed             │           │                       │
└───────────────────────┘           └───────────────────────┘

```

### DFS Mode: Detailed Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  DFS: While stack not empty                                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Pop item from stack                                             │
│  Capture ARIA_BEFORE                                             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  TRY HOVER first (Eckhaus Latta pattern)                         │
│  Check if new content appeared                                   │
└─────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
                ▼                               ▼
┌───────────────────────┐           ┌───────────────────────┐
│  HOVER REVEALED       │           │  HOVER DIDN'T WORK    │
│  content              │           │  Try CLICK            │
└───────────┬───────────┘           └───────────┬───────────┘
            │                                   │
            │                                   ▼
            │                       ┌───────────────────────┐
            │                       │  Element visible?     │
            │                       └───────────┬───────────┘
            │                                   │
            │                       ┌───────────┴───────────┐
            │                       │                       │
            │                       ▼                       ▼
            │           ┌───────────────────┐   ┌───────────────────┐
            │           │  YES: Click it    │   │  NO: Try back btn │
            │           └─────────┬─────────┘   └─────────┬─────────┘
            │                     │                       │
            │                     │             ┌─────────┴─────────┐
            │                     │             ▼                   ▼
            │                     │   ┌─────────────────┐ ┌─────────────────┐
            │                     │   │ Cached position │ │ Find with       │
            │                     │   │ → click coords  │ │ find_back_btn() │
            │                     │   └────────┬────────┘ └────────┬────────┘
            │                     │            │                   │
            │                     │            └─────────┬─────────┘
            │                     │                      │
            │                     │                      ▼
            │                     │            ┌─────────────────────┐
            │                     │            │ Still not visible?  │
            │                     │            │ → RESET MENU        │
            │                     │            │   (goto base_url,   │
            │                     │            │    reopen menu,     │
            │                     │            │    click tab)       │
            │                     │            └─────────────────────┘
            │                     │
            │                     ▼
            │           ┌───────────────────────────────────────────┐
            │           │  CHECK URL CHANGE                         │
            │           │  (Only tabs can change URL)               │
            │           └───────────────────────────────────────────┘
            │                     │
            │         ┌───────────┴───────────┐
            │         │                       │
            │         ▼                       ▼
            │ ┌───────────────────┐ ┌───────────────────┐
            │ │ URL SAME          │ │ URL CHANGED       │
            │ │ Continue          │ │ Record as link    │
            │ └─────────┬─────────┘ │ Reset menu        │
            │           │           │ Continue          │
            │           │           └───────────────────┘
            │           │
            └───────────┴───────────────┐
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Capture ARIA_AFTER                                              │
│  DIFF = get_new_content(ARIA_BEFORE, ARIA_AFTER)                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
                ▼                               ▼
┌───────────────────────┐           ┌───────────────────────┐
│  DIFF is empty        │           │  DIFF has content     │
│  → Leaf node          │           │  → Has children       │
│  → Continue to next   │           └───────────┬───────────┘
└───────────────────────┘                       │
                                                ▼
                                ┌───────────────────────────────────┐
                                │  LLM: Analyze DIFF only           │
                                │  (NOT full ARIA)                  │
                                │  → What's expandable?             │
                                │  → What's a leaf link?            │
                                └───────────────────────────────────┘
                                                │
                                                ▼
                                ┌───────────────────────────────────┐
                                │  Add expandable items to stack    │
                                │  Record leaf links as categories  │
                                │  Continue DFS                     │
                                └───────────────────────────────────┘
```

### URL Change Rules

| Context | URL Change | Action |
|---------|------------|--------|
| Clicking tab (top-level) | ALLOWED | Continue normally |
| Clicking subcategory | NOT ALLOWED | Record as leaf link, reset menu |
| Any other element | NOT ALLOWED | Reset menu, continue |

**Why?** Tabs switch panels within the menu. Subcategories navigate to product listing pages. If a subcategory changes URL, it's a leaf node (product page), not a expandable category.

### Back Button Strategy

```
1. Check cached position (x, y)
   └─ If exists → click at coordinates → done

2. Check cached selector for this level
   └─ If exists → try locator → if visible → done

3. Try hardcoded selectors (find_back_button)
   └─ Patterns: [aria-label*="back"], button:has-text("back"), etc.
   └─ If found → cache position + selector → done

4. Last resort: RESET MENU
   └─ goto(base_url)
   └─ open_menu()
   └─ click(tab)
   └─ rebuild path from current_path
```

**Position caching:** After finding a back button once, we store `(x, y)` coordinates. Subsequent clicks use `page.mouse.click(x, y)` which works regardless of button text/label changes.

### LLM Call Summary

| Phase | LLM Calls | What |
|-------|-----------|------|
| Menu button detection | 1 | Identify hamburger button |
| Tab detection | 1 | Identify tab names from screenshot |
| **Per tab (BULK mode)** | 1 | Extract all categories at once |
| **Per tab (DFS mode)** | N | One per click, but only sends DIFF |

**Optimization:** In DFS mode, if 5 consecutive items at a level have no children, we skip LLM calls for remaining items at that level.

### Site Pattern Detection

| Pattern | How to Detect | Strategy |
|---------|---------------|----------|
| Pre-loaded | Click element → no ARIA diff | BULK: 1 LLM call for entire tab |
| Show/hide | Click element → ARIA diff appears | DFS: LLM call per interaction, diff only |
| Hover menus | Hover → ARIA diff appears | Use hover instead of click |
| Link-only | No buttons/tabs, just links | Extract links directly, no LLM |

### Functions

| Function | Purpose |
|----------|---------|
| `get_new_content(before, after)` | Extract ARIA diff |
| `find_expandable_elements(aria)` | Find buttons/menuitems/tabs (not links) |
| `bulk_extract_tab(page, tab, aria)` | One-shot LLM extraction |
| `dfs_explore_tab(page, tab, aria)` | DFS with diff-only LLM |
| `explore_tab(page, tab)` | Auto-detect mode, call bulk or dfs |
| `explore_all_tabs(page, tabs)` | Main entry: loop through all tabs |

