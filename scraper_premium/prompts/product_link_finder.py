"""
Product Link Finder Prompt
==========================

Identifies valid product links from a list of website links.
"""

from typing import List
from pydantic import BaseModel, Field


class ProductLinkResponse(BaseModel):
    """Response containing up to 3 selected product URLs"""
    product_urls: List[str] = Field(description="Up to 3 selected product URLs for pattern analysis")


def get_prompt(page_url: str, all_links: List[str]) -> str:
    """Generate product link finder prompt"""
    links_text = "\n".join(f"- {link}" for link in all_links)
    
    return f"""
Find UP TO 3 different product links from this fashion website for pattern analysis.

Current page being analyzed: {page_url}
All links found on this page:
{links_text}

PRIORITY: Choose product links that are CONTEXTUALLY RELEVANT to the current page.
- If on a collection page like /collections/best-sellers/, prioritize links that include that collection path
- If on a category page, prioritize links from that category
- Choose links that appear early/first in the provided list (higher up on the page)

Return the FIRST 3 product links that lead to individual clothing/fashion items.
Choose SIMILAR products from the SAME SECTION to help identify common container patterns.

REQUIREMENTS for each selected URL:
- Must lead to individual product detail pages  
- Should maintain the page context (e.g., /collections/best-sellers/products/ not just /products/)
- Must NOT be the homepage or main domain URL

EXCLUDE: 
- Homepage and domain root URLs
- Collections/categories without specific products: /collections/, /category/, /shop/
- About/info pages: /about, /contact, /faq, /terms
- Account pages: /account, /login, /register
- Blog/content: /blog, /news, /story
- Search/filter pages: /search, /filter

Return 1-3 URLs (fewer if limited selection available).
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return ProductLinkResponse