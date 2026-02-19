# Navigation Module Index

Quick reference for all modules. Read this first before editing.

## Main Files

### `step_explorer.py` (PRIMARY)
Step-by-step navigation explorer. Main entry point.
```
NavExplorer class:
  - setup(url) → navigate, dismiss popups, open menu, detect tabs
  - step() → click/hover one item, capture diff, extract links/expandables
  - advance() → mark current as explored, move to next
  - get_results() → return categories dict
```

### `dynamic_explorer.py` (LEGACY - being extracted)
5000-line monolith. Functions still here:
- `open_menu_and_capture()` - open menu, capture ARIA diff
- `find_menu_container()` - find menu element
- `extract_links_with_hierarchy()` - extract links grouped by parent
- `click_button()` - find and click by role/text
- `hover_and_check()` - hover and check if content revealed
- `find_back_button()` - detect back/close button
- `identify_tabs_with_llm()` - LLM identifies tab names
- `find_tabs_in_dom()` - find tabs with geometric verification
- `group_buttons_by_css()` - group buttons by CSS class
- `identify_main_menu_group()` - LLM identifies main menu buttons

---

## aria/ - ARIA Parsing

### `aria/elements.py`
Element extraction from ARIA snapshots.
```python
find_expandable_elements(aria) → [{name, role, nearby_link, indent}]
  # Finds buttons/tabs that might reveal content
  # nearby_link: link found near button (for LLM classification)
  # indent: ARIA indent level (for caching)

extract_buttons_from_aria(aria) → set of button names
extract_elements_from_aria(aria) → set of element names
find_role_in_aria(aria, text) → role string
```

### `aria/diff.py`
ARIA diffing utilities.
```python
get_new_content(before, after) → str  # Lines that appeared
get_content_diff(before, after) → {added, removed, added_count, removed_count, is_replacement}
hover_revealed_content(before, after) → (bool, reason)  # Did hover reveal content?
is_menu_still_open(aria, start_line) → bool
```

---

## extraction/ - Element Extraction

### `extraction/links.py`
Link extraction and filtering.
```python
extract_links_from_aria(aria) → {name: url}
filter_utility_links(links) → {name: url}  # Remove cart, login, etc.
filter_utility_buttons(buttons) → filtered set/dict
```

### `extraction/nav_elements.py`
**CSS-based element extraction with utility filtering.**

Core concept: Parse ARIA for elements, get CSS class for each via direct DOM lookup, group by CSS, LLM excludes utility groups, filter.

```python
# Main entry point
extract_and_filter_nav_elements(page, aria, menu_selector) → {
    'elements': [{'name', 'type', 'url', 'css_class', ...}],
    'excluded_groups': set()
}

# Internal functions
_parse_aria_with_hierarchy(aria) → [{'name', 'type', 'aria_role', 'parent', ...}]
  # Parse ARIA snapshot, track parent-child via indentation

_get_css_for_elements(page, elements, menu_selector) → elements with css_class
  # For each element, page.get_by_role(role, name) → get parent CSS class
  # KEY: Direct ARIA→DOM mapping, not separate DOM scan

_exclude_utility_groups(css_groups) → set of excluded group names
  # LLM identifies which CSS groups are utility (language, help, etc.)

_mark_expandable_links(page, elements, menu_selector) → elements
  # Check if links have chevron/arrow icons → mark as expandable
```

**Why direct mapping?** See ARCHITECTURE.md "Why ARIA→DOM direct mapping"

---

## menu/ - Menu State

### `menu/context.py`
Menu state tracking.
```python
@dataclass
MenuContext:
    before_aria: str      # ARIA before menu opened
    base_url: str         # URL to return to
    menu_start_line: str  # First new line (for open check)
    boundary_marker: str  # Landmark after menu

    @classmethod
    from_menu_result(result, base_url) → MenuContext
```

---

## llm/ - LLM Utilities

### `llm/client.py`
LLM wrapper with usage tracking.
```python
get_llm_handler() → LLMHandler
track_llm_result(result) → None
get_llm_usage() → {input_tokens, output_tokens}
call_llm(prompt, max_tokens) → result dict
```

### `llm/classification.py`
LLM-based classification with **Pydantic structured outputs**.

```python
# Pydantic models for guaranteed response format
class ButtonClassification(BaseModel):
    expands: list[int]  # 1-indexed pair numbers that EXPAND

class SingleButtonClassification(BaseModel):
    expands: bool  # True if button expands the link's category

# Batch classification (preferred - one LLM call for all pairs)
classify_button_relationships_batch(pairs) → {button_name: 'EXPANDS' | 'SEPARATE'}
  # pairs = [(button_name, nearby_link), ...]
  # Uses LLMHandler.call() with response_model=ButtonClassification

# Single classification (legacy)
classify_button_relationship(button_name, link_name) → 'EXPANDS' | 'SEPARATE'
```

**Why Pydantic?** Free-text LLM parsing is fragile. "1. THESE ARE SEPARATE" → regex extracts "1" as EXPANDS. Structured outputs guarantee format.

### `llm/prompts.py`
Prompt templates for various LLM tasks.

### `llm/parsers.py`
Response parsing utilities.

---

## Other Files

### `llm_popup_dismiss.py`
Popup dismissal with LLM.
```python
dismiss_popups_with_llm(page, max_attempts, menu_is_open) → None
  # menu_is_open=True prevents closing the menu by accident
```

### `popup_selectors.py`
CSS selectors for common popups.

---

## Import Pattern

```python
# In step_explorer.py:

# Extraction
from scraper.navigation.extraction.links import extract_links_from_aria, filter_utility_links

# ARIA
from scraper.navigation.aria.elements import find_expandable_elements
from scraper.navigation.aria.diff import get_new_content, get_content_diff

# Menu
from scraper.navigation.menu.context import MenuContext

# LLM
from scraper.navigation.llm.classification import classify_button_relationship

# Still in dynamic_explorer (to extract):
from scraper.navigation.dynamic_explorer import (
    open_menu_and_capture,
    click_button,
    hover_and_check,
    # ... etc
)
```

---

## Key Concepts

1. **ARIA diff = menu content**: When menu opens, the diff shows what became visible
2. **Button classification**: LLM determines if button expands parent or is separate category
3. **Indent caching**: Buttons at same indent level behave consistently → cache LLM result
4. **Consecutive duplicate prevention**: Skip if `path[-1] == item['name']` (prevents A > A > A)
5. **Stack deduplication**: Check both `explored` and `stack` before adding
6. **ARIA→DOM direct mapping**: Use `get_by_role(role, name)` to find the exact element ARIA identified. Don't scan DOM separately (text mismatch issues).
7. **CSS grouping for utility detection**: Elements with same parent CSS class are grouped. LLM identifies utility groups (language, help). Filter by css_class.
8. **Pydantic structured outputs**: LLM returns structured data, not free text. No parsing required.
