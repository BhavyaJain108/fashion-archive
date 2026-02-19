"""
LLM prompt templates for navigation extraction.
"""


def prompt_top_level(header_aria: str, body_aria: str = None) -> str:
    """Prompt to identify top-level navigation items."""
    # Use header ARIA (focused, no popup/cookie/country junk) as primary source.
    # Fall back to body ARIA only if header ARIA is empty.
    source = header_aria if header_aria and len(header_aria) > 100 else body_aria
    if not source:
        source = header_aria or body_aria or ""

    return f"""Identify the main navigation items on this fashion website.

ARIA snapshot:
{source[:5000]}

Look for:
- Category buttons/tabs: Women, Men, Kids, Home, Sale, New
- Product category links: Shop All, Clothing, Shoes, etc.

IGNORE:
- Search, Cart, Account, Login, Language/Country selectors
- Social links, About, Contact, FAQ, Footer links

List ONLY the main navigation items:

ITEMS:
- BUTTON: NameHere
- TAB: NameHere
- LINK: NameHere | /url/path
"""


def prompt_menu_structure(aria: str) -> str:
    """Prompt to analyze menu structure after opening a toggle/hamburger menu."""
    return f"""Look at this ARIA snapshot of an OPEN navigation menu.

Identify the menu structure - what are the TOP-LEVEL categories vs SUBCATEGORIES.

ARIA:
{aria[:8000]}

RESPOND EXACTLY LIKE THIS:

TOP_LEVEL:
- TAB: Women
- TAB: Men

SUBCATEGORIES:
- TAB: Handbags
- TAB: Shoes
- TAB: Ready-to-Wear

LINKS:
- LINK: New in | /url/path
- LINK: Sale | /url/path

RULES:
- TOP_LEVEL = main category selectors (Women, Men, Kids, etc.) - usually in a "Categories" tablist
- SUBCATEGORIES = product type selectors that SWITCH content (Handbags, Shoes, Clothing, etc.) - tabs that don't navigate
- LINKS = items that have a /url: and will NAVIGATE to a new page - DO NOT put these in SUBCATEGORIES
- IMPORTANT: If an item has "/url:" in the ARIA, it's a LINK not a TAB - put it in LINKS section
- Use TAB if ARIA shows "tab" without URL, BUTTON if "button" without URL
- IGNORE: Search, Cart, Login, Account, Country selectors, Close buttons
- IGNORE: Social links, FAQ, About, Legal, Newsletter
"""


def prompt_subcategories(aria: str, current_path: list, extracted_links: dict = None) -> str:
    """Prompt to identify subcategories at the current navigation path."""
    path_str = " > ".join(current_path)

    # Format extracted links for the prompt
    links_section = ""
    if extracted_links:
        links_list = [f"  - {name} → {url}" for name, url in list(extracted_links.items())[:30]]
        links_section = f"""
EXTRACTED LINKS ON THIS PAGE:
{chr(10).join(links_list)}
"""

    return f"""PURPOSE: We're building a navigation tree for a fashion site. We need to find all category paths.

CURRENT PATH: {path_str}
{links_section}
TASK: First determine if this is a PRODUCT LISTING page or a NAVIGATION page.

HOW TO IDENTIFY A PRODUCT LISTING PAGE (LEAF):
Look at the EXTRACTED LINKS above. If you see ANY of these patterns, it's a LEAF page:

1. Filter/sort controls: "Filter", "Filter and sort", "Filters", "Refine", "Sort", "Sort by", "Clear"

2. Individual PRODUCT links - these have specific patterns:
   - Long descriptive names with color/size: "Tokyo Dad Jeans | Baggy, Wide-Leg Metal Black"
   - Names with color in parentheses: "STITCH WINGS ZIP HOODIE BLACK (DETACHABLE WINGS)"
   - Names with material/variant: "Oversized Cotton Hoodie - Washed Black"
   - Multiple similar items (same product, different colors): seeing 3+ links that are variants of same item
   - Product names are usually 4+ words describing a specific item

3. Category links look DIFFERENT - they are short, generic names:
   - "Hoodies", "Tops", "Jackets", "Shoes", "Bags" (1-2 words)
   - "New Arrivals", "Best Sellers", "Sale" (collection names)

CRITICAL RULE: If EXTRACTED LINKS contains MOSTLY long product names (4+ words with colors/sizes/variants), this is a LEAF page. Don't be fooled by a few category buttons in the header - look at the LINKS.

RESPOND WITH THIS FORMAT:

First line MUST be one of:
PAGE_TYPE: LEAF
PAGE_TYPE: HAS_CATEGORIES

If PAGE_TYPE: LEAF, stop there. Don't list any items.

If PAGE_TYPE: HAS_CATEGORIES, find EXPANDABLE elements and LINKS to category pages:

CLASSIFICATION - Based on ARIA ROLE, not the name:
- EXPANDABLE: role=button, role=tab, role=menuitem → we click these to explore
- LINK: role=link → we record the URL but don't click

IMPORTANT - INDENTATION SHOWS HIERARCHY:
- In ARIA, indentation indicates parent/child nesting.
- Only list items that are CHILDREN of the current path.
- If current path is "Men", only list items INDENTED UNDER Men's expanded region.
- Do NOT list sibling items at the same level (e.g., "Women" is a sibling of "Men", not a child).
- Example: If you see:
    - button "Men" [expanded]:
      - button "Shoes"      ← CHILD of Men (indented under)
      - button "Clothing"   ← CHILD of Men (indented under)
    - button "Women":       ← SIBLING of Men (same level, not indented under)
  Then Shoes and Clothing are children of Men, but Women is NOT.

IMPORTANT:
- Look at the actual ARIA role, not what the name suggests.
- "Ready-to-wear" with role=menuitem is EXPANDABLE, not a LINK.
- Include ALL buttons, tabs, and menuitems that are CHILDREN of current path.
- Menus often have one item already selected (usually the first) - include it too.

EXPANDABLE:
- BUTTON: ExactName
- TAB: ExactName
- MENUITEM: ExactName

LINKS:
- LINK: ExactName

EXCLUDE from both sections:
- Individual product links (specific items like "Blue Cotton Dress $89", "Nike Air Max")
- Utility links (Cart, Login, Search, About Us, Contact, FAQ)
- Filter/facet options (color names, size names, price ranges)
- Sort options
- Pagination controls

CONSTRAINTS:
- Classify by ARIA role, not by name
- Only include CHILDREN of the current path, not siblings or parent items
- Ignore utility controls: Back, Close, Search, Cart, Menu, Login, Account
- Use exact names from the ARIA
- If you see filters/sort controls, respond with PAGE_TYPE: LEAF

ARIA SNAPSHOT:
{aria[:6000]}
"""


def prompt_identify_menu_button(menu_candidates: list[dict], all_buttons: list[dict]) -> str:
    """
    Prompt to ask LLM which element (if any) is the menu toggle.
    Combines menu candidates (elements with menu-related attributes) and all buttons.
    """
    # Format menu candidates (high confidence - have menu keywords in attributes)
    candidates_list = []
    for i, c in enumerate(menu_candidates):
        text = c.get('text', '').strip()[:30]
        selector = c.get('selector', '')
        score = c.get('menuScore', 0)
        candidates_list.append(f"  [C{i}] selector=\"{selector}\" text=\"{text}\" score={score}")

    candidates_str = "\n".join(candidates_list) if candidates_list else "  (none found)"

    # Format all buttons
    buttons_list = []
    for i, btn in enumerate(all_buttons):
        text = btn.get('text', '').strip()[:30]
        aria = btn.get('aria_label', '')
        tag = btn.get('tag', 'button')
        buttons_list.append(f"  [B{i}] <{tag}> text=\"{text}\" aria-label=\"{aria}\"")

    buttons_str = "\n".join(buttons_list) if buttons_list else "  (none found)"

    return f"""Find the MAIN NAVIGATION MENU toggle on this fashion website.

MENU CANDIDATES (elements with menu-related attributes):
{candidates_str}

ALL BUTTONS:
{buttons_str}

RULES:
- We want the button that opens the main product navigation (Women, Men, Shop, etc.)
- Common labels: "Menu", "Shop", "Browse", "Navigation", hamburger icon (☰)
- Prefer MENU CANDIDATES if they look right (they have menu keywords in HTML)
- IGNORE: Search, Cart, Account, Login, Language, Currency, Country, Close, Wishlist

RESPOND WITH EXACTLY ONE LINE:
- Menu candidate: MENU: C[number]
- Button: MENU: B[number]
- No menu found: MENU: NONE

Examples:
MENU: C0
MENU: B2
MENU: NONE
"""


def prompt_bulk_extract(tab_name: str, aria: str) -> str:
    """Prompt for extracting all categories from a tab in one shot."""
    return f"""This is the "{tab_name}" section of a fashion website's navigation menu.
The site shows all categories at once (no hidden content).

Extract ALL product category links visible in this menu section.
Include both parent categories and subcategories.

ARIA SNAPSHOT:
{aria[:12000]}

RESPOND IN THIS EXACT FORMAT:
CATEGORIES:
- CategoryName: /url/path
- CategoryName: /url/path
- ParentCategory > SubCategory: /url/path

Only include product categories (clothing, shoes, accessories, etc).
Skip utility links (cart, account, search, etc).
"""
