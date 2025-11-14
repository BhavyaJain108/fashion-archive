"""
Product Link Finder Prompt
==========================

Identifies valid product links from a list of website links.
"""

from typing import List
from pydantic import BaseModel, Field


class SelectedProductLink(BaseModel):
    """A selected product link with its parent container"""
    url: str = Field(description="The product URL")
    parent_container: str = Field(description="Parent container CSS path (e.g., 'ul.product-grid > li')")


class ProductLinkResponse(BaseModel):
    """Response containing up to 3 selected product links with parent containers"""
    selected_links: List[SelectedProductLink] = Field(description="Up to 3 selected product links with parent container info")


def get_prompt(page_url: str, links_with_context: List[dict]) -> str:
    """
    Generate product link finder prompt with parent container information

    Args:
        page_url: The current page being analyzed
        links_with_context: List of dicts with 'url' and 'parent_container' keys
    """
    # Format links with parent container info
    links_text = "\n".join(
        f"- {link['url']}\n  Parent: {link['parent_container']}"
        for link in links_with_context
    )

    return f"""
Find UP TO 3 different product links from this fashion website for pattern analysis.

Current page being analyzed: {page_url}
All links found on this page (with parent container info):
{links_text}

PRIORITY: Choose product links that are CONTEXTUALLY RELEVANT to the current page.
- If on a collection page like /collections/best-sellers/, prioritize links that include that collection path
- If on a category page, prioritize links from that category
- Choose links that appear early/first in the provided list (higher up on the page)

CONTAINER FILTERING (CRITICAL):
AVOID links from these container types (likely navigation/menus, NOT product catalogs):
- Containers with: "menu", "nav", "drawer", "header", "sidebar", "featured"
- Example bad: ul.menu-drawer__featured-content-list

PREFER links from these container types (likely main product grids/catalogs):
- Containers with: "product-grid", "product-list", "catalog", "collection-grid", "main", "content"
- Example good: ul.product-grid.product-grid--template

Return the FIRST 3 product links that lead to individual clothing/fashion items.
Choose SIMILAR products from the SAME SECTION to help identify common container patterns.

REQUIREMENTS for each selected URL:
- Must lead to individual product detail pages
- Should maintain the page context (e.g., /collections/best-sellers/products/ not just /products/)
- Must NOT be the homepage or main domain URL
- Must come from product catalog containers (NOT navigation menus)

EXCLUDE:
- Homepage and domain root URLs
- Collections/categories without specific products: /collections/, /category/, /shop/
- About/info pages: /about, /contact, /faq, /terms
- Account pages: /account, /login, /register
- Blog/content: /blog, /news, /story
- Search/filter pages: /search, /filter

For each selected link, return BOTH the URL and its parent_container path.
Return 1-3 links (fewer if limited selection available).
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return ProductLinkResponse