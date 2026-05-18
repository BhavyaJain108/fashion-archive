"""
URL Pruning Prompt
==================

Second-pass LLM call: when the per-lineage classifier returns MORE product
URLs than the page actually displays, this prompt asks the LLM to identify
which (if any) of those candidates are CONTAMINATION from a different
product category — typically variant/swatch links that share a DOM lineage
with real product cards but point to items in other collections.

Critically, this prompt does NOT slug-match the candidates against the
category name. Many brand categories are PROPRIETARY GROUPINGS (themed
drops, capsules, collabs, "best sellers", "new arrivals", seasonal lines)
whose product slugs do not contain the category name — a slug-match
strategy catastrophically over-prunes them. Instead, the LLM is asked to:

  1. Decide whether the category is a PRODUCT TYPE or a PROPRIETARY GROUPING
     (using the nav path and category name).
  2. Look for OBVIOUS cross-category contamination (e.g. a bikini slug on
     a hoodies page).
  3. Default to KEEP unless contamination is clearly identifiable.

Trigger condition (in the caller):
    extracted_count > expected_count

Inputs to the LLM:
    - The category name and optional navigation path
    - The expected_count (what the page itself displays)
    - ALL candidate URLs (no sampling — the question is exactly which ones
      look like contamination)

Output:
    - PruneDecision.indices_to_keep — a subset of indices from the input list
    - reasoning — one sentence on the pruning logic
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PruneDecision(BaseModel):
    """Structured output for the prune-to-expected-count call."""
    category_kind: str = Field(
        description=(
            "Either 'product_type' or 'proprietary_grouping'. "
            "product_type = category name describes a physical clothing type "
            "(hoodies, dresses, jackets, bikinis). "
            "proprietary_grouping = a themed drop, capsule, collab, seasonal "
            "line, curated list ('best sellers', 'new arrivals'), or any "
            "brand-specific name that contains mixed product types."
        )
    )
    indices_to_keep: List[int] = Field(
        description=(
            "Indices (0-based) of the URLs that belong here. Default to "
            "keeping ALL indices unless you can clearly identify specific "
            "candidates as cross-category contamination. For proprietary "
            "groupings you will usually keep every index — slug names do not "
            "tell you whether a URL belongs to a drop or collection."
        )
    )
    reasoning: str = Field(
        description=(
            "One sentence: (a) what category_kind you decided this is and why, "
            "(b) what (if anything) you removed and why."
        )
    )


def get_prompt(category_name: str,
               candidates: List[Dict],
               expected_count: int,
               nav_path: Optional[str] = None,
               page_url: Optional[str] = None) -> str:
    """
    Build the pruning prompt.

    Args:
        category_name: The leaf category name (e.g. "Hoodies", "RASCAL").
        candidates: List of dicts, each {"url": str, "link_text": str}.
            Index in this list is what the LLM will return.
        expected_count: How many products the page actually displays.
        nav_path: Full navigation path if known (e.g. "Women > Tops > Hoodies"
            or "Shop By Drop > RASCAL").
        page_url: The category page URL, for context.
    """
    nav_line = f"- Full nav path: {nav_path}\n" if nav_path else ""
    page_url_line = f"- Page URL: {page_url}\n" if page_url else ""

    # Format candidates with their indices and link text.
    lines = []
    for i, c in enumerate(candidates):
        url = c.get("url", "")
        text = (c.get("link_text") or "").strip()[:80]
        if text:
            lines.append(f"[{i:>3}] {url}\n      text: \"{text}\"")
        else:
            lines.append(f"[{i:>3}] {url}")
    candidates_block = "\n".join(lines)

    extra = len(candidates) - expected_count

    return f"""
The first-pass lineage classifier returned more candidate product URLs than this page displays. Decide whether any of them are CONTAMINATION from a different product category, and prune only those. Do NOT prune based on slug-matching the category name — many categories are proprietary groupings whose products do not have the category name in their URL.

**Context:**
- Category: {category_name}
{nav_line}{page_url_line}- Page displays: {expected_count} products
- Candidates from classifier: {len(candidates)}
- Excess: {extra}

---

**Step 1 — Decide what kind of category this is.**

The category "{category_name}" is one of two things:

(a) **product_type** — the name describes a physical clothing type. Examples: Hoodies, T-Shirts, Dresses, Jackets, Bikinis, Sweatpants, Shorts, Accessories.
   - Slugs of products in this category WILL plausibly describe that type.

(b) **proprietary_grouping** — a themed drop, capsule, collab, seasonal/promotional line, curated list, or brand sub-line. Examples: "RASCAL", "FALLEN", "Best Sellers", "Latest Drops", "SS24", "Artist X Brand Collab", "Old English", "Just Restocked", "3 FOR 2 INTIMATES".
   - Products in these contain MIXED clothing types.
   - Slugs WILL NOT contain the category name. The brand uses proprietary product names instead.
   - The nav path is often a strong hint: "Shop By Drop", "Collections", "Collabs" parents almost always indicate proprietary groupings.

Use the category name and nav path to decide. If you're not sure, default to **proprietary_grouping** — it's much safer (it almost never over-prunes).

---

**Step 2 — Identify contamination.**

Contamination = a URL that almost certainly belongs to a DIFFERENT specific product category on this site, included here only because of a shared DOM lineage (typically swatch/variant links on product cards).

**For product_type categories**, contamination looks like slugs describing a clearly different physical type. Examples:
- On a "Hoodies" page: slugs containing "bikini", "shorts", "g-string", "boxer", "skirt" are contamination.
- On a "Bikinis" page: slugs containing "hoodie", "jacket", "tracksuit" are contamination.
- Be conservative — only reject when the slug VERY clearly describes a different type.

**For proprietary_grouping categories**, you CANNOT use slug-matching. Drops contain mixed types — a slug like "fallen-faux-fur-rhinestone-zip-hoodie" on a RASCAL page might or might not be contamination; you have no reliable way to tell from the slug alone.
- Default: keep all candidates.
- Only reject if you can identify a URL whose slug clearly belongs to a different *named drop or collection* — e.g. on a RASCAL drop page, a slug starting with "named-classics-..." is suspicious because "Named Classics" is a different named line.
- When in doubt, KEEP.

---

**Step 3 — Output indices.**

**Default bias is to KEEP every index.** Only return a smaller subset if you can name specific candidates as contamination per the rules above. It is far better to ship slightly over `expected_count` than to ship zero or near-zero.

The `expected_count` is a hint about how many products the page shows visually — it is NOT a target. The first-pass classifier may legitimately exceed it because variant swatches contribute URLs to the same products (which get deduped downstream), or because the page count widget was slightly off.

**Candidates:**

{candidates_block}

---

**Reasoning format:**
- Start by naming the `category_kind` ("product_type" or "proprietary_grouping") and the one-clause justification.
- Then describe what you removed (or "kept all") with the specific slug pattern that signaled contamination.

Examples of good reasoning:
- "product_type (Hoodies — physical clothing type); rejected indices 12, 14, 19 because slugs contained 'bikini' and 'g-string', clearly different category."
- "proprietary_grouping (RASCAL — themed drop under 'Shop By Drop'); kept all 29 candidates because drop products have proprietary names and no slug clearly belongs to a different named line."
- "proprietary_grouping (Best Sellers — curated list); kept all candidates."
""".strip()


def get_response_model():
    return PruneDecision
