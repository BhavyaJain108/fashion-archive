"""
Collection Count Detection Prompt
=================================

Vision LLM prompt for identifying the displayed product count on a
collection page. Returns the count (or null) plus a reusable CSS
selector that yields the count, plus a confidence label.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class CollectionCountResponse(BaseModel):
    """Structured output for collection count vision detection."""
    count: Optional[int] = Field(
        description=(
            "Total products displayed in this collection. "
            "Use 0 if the collection is visibly empty (e.g. 'No products in this "
            "collection', 'Sorry, no items found', or no product cards in the main "
            "grid). "
            "Use null only when you genuinely can't tell."
        )
    )
    selector: Optional[str] = Field(
        description="CSS selector that reliably yields the count element on this site, "
                    "e.g. '.collection-count', '[data-product-count]', '.results-count'. "
                    "Null if you cannot identify a stable, reusable selector."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Your confidence in the detected count."
    )
    reasoning: str = Field(
        description="Brief: where on the page the count was found, why it's empty, or why it wasn't found."
    )


def get_prompt(category_name: str) -> str:
    """Generate the vision prompt for collection count detection."""
    return f"""
You are looking at the top of an e-commerce collection page for the category "{category_name}".

Your task has two parts.

---

**Part 1 — Are there product cards in the MAIN product grid?**

E-commerce pages typically render the catalog as a "main grid" — a uniform multi-row grid of product cards (image + name + price), usually the largest section on the page, often laid out 3-5 cards wide.

These are NOT the main grid (ignore them):
- Horizontal carousels / swipers (cards on a single scrollable row)
- Sections under headings like "You might also like", "Community Faves", "Featured", "Recommended", "Trending", "Best Sellers", "Recently Viewed", "Complete the Look"
- Hero banners or promotional cards

**If the main grid has ZERO product cards** — whether because the page shows an empty-state message, or because the grid area is just absent / says nothing — return **count: 0**. This holds regardless of what appears in carousels or recommendations elsewhere on the page.

**If the main grid has product cards visible**, move to Part 2.

---

**Part 2 — Find the displayed total count.**

Look for an explicit count of products on this page:
- A number next to or near the page title (e.g., "Hoodies (47)")
- A count badge anywhere visible (e.g., "47 products", "47 items", "47 styles", "47 results")
- "Showing X of Y" or "X–Y of Z" text — the Z is the total
- Sort/filter bars often contain the total count

If no count widget is visible but the main grid clearly has cards, you may count the cards yourself (only the ones in the main grid, not in carousels) and return that — but mark `confidence: "medium"`.

Ignore:
- Prices, discount percentages, sizes, ratings, review counts
- "Free shipping over $X" / promotional banners
- Numbers in carousel / featured / recommendation sections

---

**Return:**
- `count`: the integer total, 0 for visibly-empty main grids, or null only if you genuinely can't tell.
- `selector`: a CSS selector that would reliably yield the count element on other category pages of this same site. Null if no stable selector is apparent, or the collection is empty, or you counted cards yourself.
- `confidence`: "high" if you read it off an explicit count widget, "medium" if you counted cards visually or the count is ambiguous, "low" if you're guessing.
- `reasoning`: one sentence — where you saw the count, why the main grid is empty, or why you couldn't tell.
""".strip()
