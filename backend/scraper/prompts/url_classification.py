"""
URL Classification Prompt
=========================

Classifies LINEAGES from a category page as product / navigation / featured /
recommendation / utility / other. The LLM provides per-lineage reasoning. The
classifier then collects every link belonging to a lineage classified as
'product'.

This replaces the older "classify these 50 sample links by index" framing
because the system's actual decision is per-lineage (a lineage's class
propagates to every link sharing it), and the per-sample wrapper hid that
decision from the model.
"""

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class LineageDecision(BaseModel):
    """One classification decision for one DOM lineage on the page."""
    lineage_id: str = Field(
        description="The ID label used in the prompt (e.g. 'L1', 'L2'). MUST match an ID from the prompt."
    )
    classification: Literal["product", "navigation", "featured", "recommendation", "utility", "other"] = Field(
        description=(
            "product: main category product detail pages | "
            "navigation: site nav / header / footer / menu / category links | "
            "featured: small hero or featured section, usually <10 links, often appears on every page | "
            "recommendation: 'you may also like', related/cross-sell sections | "
            "utility: cart, login, account, wishlist, search | "
            "other: anything else not fitting the above"
        )
    )
    reasoning: str = Field(
        description="One sentence on WHY this lineage got this classification. Reference the count, sample URLs, or DOM path."
    )


class URLClassification(BaseModel):
    """Structured output for URL classification"""
    overall_analysis: str = Field(
        description="2-3 sentences summarizing your approach: which lineages you identified as the main product grid, how the approved lineage counts sum against expected_count, and any borderline calls."
    )
    lineage_decisions: List[LineageDecision] = Field(
        description="ONE decision per lineage in the prompt. Every lineage in the prompt MUST appear here exactly once."
    )
    confidence: Literal["High", "Medium", "Low"] = Field(description="Your confidence in this classification overall.")


def get_prompt(page_url: str, category_name: str,
               lineage_info: List[Dict],
               expected_count: Optional[int] = None,
               total_page_links: Optional[int] = None) -> str:
    """
    Generate the per-lineage URL classification prompt.

    Args:
        page_url: The category page URL
        category_name: Human-readable category name
        lineage_info: One entry per lineage on the page (in the order the LLM
            will see them). Each dict has:
                - id:              short label, e.g. "L1", "L2"
                - lineage:         DOM lineage string
                - count:           number of links sharing this lineage
                - carousel_count:  how many of those are inside a carousel
                - samples:         list of {url, link_text} (1-3 representative)
        expected_count: If known, the displayed product count on the page.
        total_page_links: Total link count across all lineages.

    Returns:
        Formatted prompt string. The LLM is expected to return one
        LineageDecision per lineage_info entry, referencing each by `id`.
    """
    expected_str = f"{expected_count}" if expected_count is not None else "unknown"

    # Build the per-lineage block. Each lineage is fully self-contained: its
    # ID, its count, its carousel ratio, its DOM path, and 1-3 example URLs
    # with their link text. This is what the LLM classifies — one decision
    # per block.
    lineage_blocks = []
    for info in lineage_info:
        lid = info["id"]
        lineage_str = info["lineage"]
        count = info["count"]
        carousel_count = info.get("carousel_count", 0)
        samples = info.get("samples", [])

        carousel_str = ""
        if count > 0:
            carousel_pct = round(100 * carousel_count / count)
            carousel_str = f"  Carousel ratio: {carousel_count}/{count} ({carousel_pct}%)\n"

        sample_str = ""
        for s in samples:
            url = s.get("url", "")
            text = (s.get("link_text") or "").strip()[:60]
            sample_str += f"    - {url}\n"
            if text:
                sample_str += f"        text: \"{text}\"\n"

        # Truncate very long lineage strings to keep the prompt readable
        display_lineage = lineage_str if len(lineage_str) <= 200 else lineage_str[:197] + "..."

        lineage_blocks.append(
            f"[{lid}] count={count} on full page\n"
            f"  DOM path: {display_lineage}\n"
            f"{carousel_str}"
            f"  Sample URLs:\n"
            f"{sample_str.rstrip() if sample_str else '    (no samples)'}"
        )

    lineage_section = "\n\n".join(lineage_blocks)

    count_hint = ""
    if expected_count is not None:
        count_hint = f"""
**Expected collection count: {expected_count} products** (read from the page itself).

Use this as a quantitative anchor:
- The main product grid is whichever lineage(s) collectively contain ~{expected_count} links.
- The sum of `count` over your `product`-classified lineages should be close to {expected_count} (±20%).
- A small lineage (count << {expected_count}) sitting next to the main grid is usually `featured` or `recommendation`, not `product`.
- A very large lineage (count >> {expected_count}) is usually `navigation` (categories, menus).
"""

    return f"""
You are classifying the DOM **lineages** present on an e-commerce category page so the scraper can collect every product detail URL for "{category_name}".

**Context:**
- Page URL: {page_url}
- Category: {category_name}
- Total links found on the page: {total_page_links if total_page_links is not None else "unknown"}
- Number of distinct lineages: {len(lineage_info)}
- Expected products on this page: {expected_str}
{count_hint}
**What is a "lineage":** the DOM ancestry path of an `<a>` tag (the tag itself + 2 of its parents, with their CSS classes). Links sharing the same lineage are rendered by the same template — they're the same KIND of link (all product cards, all nav items, etc.). Your decision on a lineage is applied to every link sharing it.

**Classification categories (pick exactly one per lineage):**
- `product`          — main category product detail pages (what we want to collect)
- `navigation`      — site nav, headers, footers, menus, category links
- `featured`        — small hero/promo/featured-product section (often the same products on every page)
- `recommendation` — "you may also like" / related / cross-sell sections
- `utility`         — cart, wishlist, login, account, search, etc.
- `other`           — anything else not fitting above

**Heuristics:**
- A lineage's `count` is the strongest signal. The product grid will be the one whose count matches the expected product count.
- Product URLs usually contain `/products/`, `/product/`, `/p/`, `/item/`, `/shop/` and the link text reads like a product name (not a category or button).
- Carousel ratio of 100% on a SMALL lineage (e.g. 5-8 links) → almost always `featured`.
- Carousel ratio of 100% on a LARGE lineage matching expected_count → `product` (some sites render the main grid inside a swiper).
- Same product can appear in multiple lineages (image link + name link + quick-view): if two lineages have count ≈ expected_count, both are likely `product` lineages targeting different parts of the same card.

**Lineages on this page:**

{lineage_section}

**Output requirements:**
- Return ONE `LineageDecision` per lineage above. Every lineage_id from the list MUST appear in your response exactly once. Do not skip any.
- Each `reasoning` is one sentence — reference the count, the carousel ratio, the URL pattern, or what the sample URLs suggest.
- After listing all per-lineage decisions, write `overall_analysis` summarizing which lineages you classified as `product` and how their counts sum against the expected count of {expected_str}.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return URLClassification
