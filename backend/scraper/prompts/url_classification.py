"""
URL Classification Prompt
=========================

Classifies links from a category page as product links vs navigation/recommendations/utility.
Uses URL patterns, DOM lineage, and link text for classification.
"""

from typing import Dict, List
from pydantic import BaseModel, Field


class URLClassification(BaseModel):
    """Structured output for URL classification"""
    analysis: str = Field(description="Reasoning for identifying which links are genuine product links vs navigation/recommendations")
    product_link_indices: List[int] = Field(description="List of indices (0-indexed) of links that are genuine product links")
    confidence: str = Field(description="High/Medium/Low confidence in this classification")


def get_prompt(page_url: str, category_name: str, links: List[Dict]) -> str:
    """
    Generate URL classification prompt.

    Args:
        page_url: The category page URL
        category_name: Human-readable category name
        links: List of link dicts with {url, lineage, link_text, position_index}

    Returns:
        Formatted prompt string
    """
    # Format links for display
    links_list = ""
    for i, link in enumerate(links):
        url = link.get('url', '')
        lineage = link.get('lineage', 'unknown')
        text = link.get('link_text', '').strip()[:50]  # Truncate long text
        links_list += f"{i}. URL: {url}\n   Lineage: {lineage}\n   Text: \"{text}\"\n\n"

    return f"""
You are analyzing links extracted from an e-commerce category page to identify which links lead to actual product pages.

**Context:**
- Page URL: {page_url}
- Category: {category_name}
- Total links to analyze: {len(links)}

**Goal:** Identify which links are genuine product detail pages for "{category_name}" products.

**Links to Classify (index, URL, DOM lineage, link text):**
{links_list.strip()}

**Classification Instructions:**
1. Identify links that lead to PRODUCT DETAIL PAGES - individual product pages where you can view/buy a specific product.

2. INCLUDE as product links:
   - Links with URL patterns like /products/, /p/, /item/, /shop/, /product-detail/
   - Links in product grid/listing containers (look for "product", "item", "card" in lineage)
   - Links where text looks like a product name

3. EXCLUDE (not product links):
   - Category/collection navigation links (e.g., /collections/, /category/, /c/)
   - Utility links (cart, wishlist, login, account, search)
   - Footer/header navigation links
   - "View All", "See More", "Load More" type links
   - Recommendation section links if clearly separated from main grid
   - Social media, policy pages, contact links
   - Pagination links (page numbers, next/prev)

4. Use lineage patterns to identify:
   - Main product grid: usually consistent lineage with "grid", "product", "item", "catalog"
   - Recommendations: often in separate containers like "recommend", "also-like", "related"
   - Navigation: typically in "nav", "header", "footer", "menu" containers

**Return:** The indices (0, 1, 2, etc.) of links that are genuine product pages. If links #0, #3, and #5 are products, return [0, 3, 5].
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return URLClassification
