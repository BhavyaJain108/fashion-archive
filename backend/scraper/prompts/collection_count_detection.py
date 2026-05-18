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
        description="Total products displayed in this collection. Null if no count is visible."
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
        description="Brief: where on the page the count was found, or why it wasn't found."
    )


def get_prompt(category_name: str) -> str:
    """Generate the vision prompt for collection count detection."""
    return f"""
You are looking at the top of an e-commerce collection page for the category "{category_name}".

Your task: identify the total number of products this collection contains, as displayed on the page.

Look for:
- A number next to or near the page title (e.g., "Hoodies (47)")
- A count badge anywhere visible (e.g., "47 products", "47 items", "47 styles", "47 results")
- "Showing X of Y" or "X–Y of Z" text — the Z is the total
- Sort/filter bars often contain the total count

Ignore:
- Prices, discount percentages, sizes, ratings, review counts
- "Free shipping over $X" messaging
- Numbers in promotional banners

Return:
- count: the integer total, or null if no such count is visible
- selector: a CSS selector that would reliably yield this count element on other category pages of this same site (so we can reuse it). Null if no stable selector is apparent.
- confidence: "high" if you're certain, "medium" if the count is plausible but ambiguous, "low" if you're guessing.
- reasoning: one sentence on where you saw the count (or why you couldn't).
""".strip()
