"""
URL Classification Prompt
=========================

Classifies links from a category page as product links vs navigation/recommendations/utility.
Uses URL patterns, DOM lineage, and link text for classification.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class URLClassification(BaseModel):
    """Structured output for URL classification"""
    analysis: str = Field(description="Reasoning for identifying which links are genuine product links vs navigation/recommendations")
    product_link_indices: List[int] = Field(description="List of indices (0-indexed) of links that are genuine product links")
    confidence: str = Field(description="High/Medium/Low confidence in this classification")


def get_prompt(page_url: str, category_name: str, links: List[Dict],
               expected_count: Optional[int] = None,
               total_page_links: Optional[int] = None,
               lineage_counts: Optional[Dict[str, int]] = None) -> str:
    """
    Generate URL classification prompt.

    Args:
        page_url: The category page URL
        category_name: Human-readable category name
        links: SAMPLE list of link dicts shown to the LLM. Each dict has
            {url, lineage, link_text, position_index, in_carousel}.
        expected_count: If known, the displayed product count on the page —
            used as a quantitative anchor for lineage coverage.
        total_page_links: Total number of links found across the WHOLE page
            (before sampling). Critical context: without this, the LLM thinks
            the sample size is the entire page and reasons incorrectly about
            missing products / lazy loading.
        lineage_counts: {lineage_string: count_on_page}. Lets the LLM see
            "approving lineage X means approving 60 links" so it can target
            ~expected_count coverage via lineage selection, not link selection.

    Returns:
        Formatted prompt string
    """
    # Format links for display
    links_list = ""
    carousel_count = sum(1 for l in links if l.get('in_carousel'))
    for i, link in enumerate(links):
        url = link.get('url', '')
        lineage = link.get('lineage', 'unknown')
        text = link.get('link_text', '').strip()[:50]  # Truncate long text
        carousel_flag = " [CAROUSEL]" if link.get('in_carousel') else ""
        links_list += f"{i}. URL: {url}{carousel_flag}\n   Lineage: {lineage}\n   Text: \"{text}\"\n\n"

    # Sampling context — this is the critical framing that prevents the LLM
    # from reasoning "I only see 50 links so the page must be lazy-loaded".
    sample_context = ""
    if total_page_links is not None and total_page_links > len(links):
        sample_context = (
            f"- Samples shown below: {len(links)} (a representative subset; one "
            f"or more per lineage)\n"
            f"- Total links on the full page: {total_page_links}\n"
            f"- **Your classification of each sample propagates to EVERY link "
            f"with the same lineage on the full page.** Approving one link with "
            f"lineage X approves all links with lineage X (potentially dozens).\n"
        )
    else:
        sample_context = f"- Total links to analyze: {len(links)}\n"

    # Per-lineage breakdown — gives the LLM the numbers it needs to do
    # coverage math against expected_count.
    lineage_breakdown = ""
    if lineage_counts:
        # Sort by count descending so the biggest patterns are visible first
        sorted_lineages = sorted(lineage_counts.items(), key=lambda kv: -kv[1])
        lines = ["**Lineage breakdown** (DOM lineage → number of links on full page):"]
        for lin, n in sorted_lineages:
            # Truncate lineage strings to keep the prompt readable
            display_lin = lin if len(lin) <= 120 else lin[:117] + "..."
            lines.append(f"  - [{n:>3} links] {display_lin}")
        lineage_breakdown = "\n".join(lines) + "\n"

    count_hint = ""
    if expected_count is not None:
        count_hint = f"""
**Expected collection count: {expected_count} products** (detected from page display)

Use this as a quantitative anchor — **think in lineages, not individual links**:
- The main product grid is whichever lineage(s) collectively contain ~{expected_count} links.
- Approve lineages so their total link count ≈ {expected_count} (within ±20%).
- A lineage with substantially fewer links than {expected_count} is likely a side section (hero, featured, recommendations) — exclude unless it's clearly part of the main grid.
- A lineage with substantially more links than {expected_count} is likely a navigation/utility pattern — exclude.
- DO NOT reject a lineage just because the single sample looks ambiguous: check its link count against {expected_count} first.
"""

    return f"""
You are analyzing links extracted from an e-commerce category page to identify which **lineage patterns** correspond to product detail pages.

**Context:**
- Page URL: {page_url}
- Category: {category_name}
{sample_context}- Links marked [CAROUSEL]: {carousel_count} (inside slider/carousel containers)
{count_hint}
{lineage_breakdown}
**Goal:** Identify which links are genuine product detail pages for "{category_name}". Because each lineage will be applied to all links sharing it, your effective decision is per-lineage, not per-link.

**Sample Links (index, URL, DOM lineage, link text):**
{links_list.strip()}

**Classification Instructions:**
1. Identify links that lead to PRODUCT DETAIL PAGES — individual product pages where you can view/buy a specific product.

2. **Think in lineages first.** For each lineage in the breakdown:
   - Look at its link count vs the expected collection count.
   - Look at one or two representative samples from that lineage.
   - Decide: is this the main product grid, a side section, or navigation?

3. INCLUDE as product links:
   - Links with URL patterns like /products/, /p/, /item/, /shop/, /product-detail/
   - Links in product grid/listing containers (look for "product", "item", "card" in lineage)
   - Links where text looks like a product name

4. EXCLUDE (not product links):
   - Category/collection navigation links (e.g., /collections/, /category/, /c/)
   - Utility links (cart, wishlist, login, account, search)
   - Footer/header navigation links
   - "View All", "See More", "Load More" type links
   - Recommendation section links if clearly separated from main grid
   - Social media, policy pages, contact links
   - Pagination links (page numbers, next/prev)
   - **Small carousel/featured sections**: a lineage with only a few links among many non-carousel product links is likely a featured section, not the main grid.

5. **[CAROUSEL] flag interpretation**:
   - If MOST links are [CAROUSEL]: the carousel IS the main product display — INCLUDE.
   - If only a FEW links are [CAROUSEL] (small lineage, e.g. 5-10 links): these are usually featured/hero products on every page — EXCLUDE.

6. **Coverage check** (do this before returning):
   - Sum the link counts of the lineages you're approving.
   - The sum should be close to {{expected_count or "the expected product count"}}.
   - If your sum is much lower, you're missing a product lineage — reconsider rejected lineages whose link count is in the right ballpark.
   - If your sum is much higher, you're including a navigation/utility lineage — reconsider.

**Return:** The indices (0, 1, 2, ...) from the SAMPLE list of links you classify as products. Your decision on each sample will be applied to all other links sharing its lineage.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return URLClassification
