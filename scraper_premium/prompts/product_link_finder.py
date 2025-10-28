"""
Product Link Finder Prompt
==========================

Identifies valid product links from a list of website links.
"""

from typing import List
from pydantic import BaseModel, Field


class ProductLinkResponse(BaseModel):
    """Simple response containing the selected product URL"""
    product_url: str = Field(description="The selected product URL")


def get_prompt(base_url: str, all_links: List[str]) -> str:
    """Generate product link finder prompt"""
    links_text = "\n".join(f"- {link}" for link in all_links)
    
    return f"""
Find ONE link that leads to a product page from this fashion website.

Website: {base_url}
All links found:
{links_text}

Return the ONE best product link that leads to an individual clothing/fashion item.
Exclude: collections, categories, about pages, contact, search, account, blog.

Return only the URL, nothing else.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return ProductLinkResponse