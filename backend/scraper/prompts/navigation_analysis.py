"""
Navigation Analysis Prompt
==========================

Analyzes website navigation to find product category URLs.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class CategoryNode(BaseModel):
    """Hierarchical category node"""
    name: str = Field(description="Display name of the category")
    url: Optional[str] = Field(default=None, description="The category URL (required for leaf nodes)")
    reasoning: str = Field(description="Why this category was included")
    children: Optional[List['CategoryNode']] = Field(default=None, description="Subcategories")
    
    def flatten_urls(self) -> List[str]:
        """Flatten tree to list of URLs (leaf nodes only)"""
        urls = []
        if self.children:
            # Has children - this is a branch node, recurse into children
            for child in self.children:
                urls.extend(child.flatten_urls())
        else:
            # No children - this is a leaf node, include URL if it exists
            if self.url:
                urls.append(self.url)
        return urls


class CategoryLink(BaseModel):
    """Individual category URL with reasoning (for excluded URLs)"""
    url: str = Field(description="The category URL")
    reasoning: str = Field(description="Why this URL was excluded")


class NavigationAnalysis(BaseModel):
    """Structured output for navigation/category analysis"""
    category_tree: List[CategoryNode] = Field(description="Hierarchical product category structure")
    excluded_urls: List[CategoryLink] = Field(description="URLs that were excluded and why")
    
    def get_flat_urls(self) -> List[str]:
        """Flatten entire tree to list of URLs for backward compatibility"""
        urls = []
        for root in self.category_tree:
            urls.extend(root.flatten_urls())
        return urls


# Enable forward references for recursive model
CategoryNode.model_rebuild()


def get_prompt(website_url: str, links) -> str:
    """Generate navigation analysis prompt"""
    # Handle both old format (list of strings) and new format (list of dicts)
    if links and isinstance(links[0], dict):
        # New format with HTML context
        links_text = "\n".join(f"- {link_info['full_element']}" for link_info in links)
    else:
        # Old format - just URLs
        links_text = "\n".join(f"- {link}" for link in links)
    
    return f"""
Analyze this fashion brand website's navigation links and create a hierarchical product category tree:

Website: {website_url}

All link elements found on the page:
{links_text}

You are a clothing expert and understand all types of clothing styles and categories.
This is a clothing/fashion website. Build a hierarchical tree structure that shows how this brand organizes its products.

CREATE A CATEGORY TREE:
- Organize categories in a logical hierarchy (e.g., Men's → Clothing → T-Shirts)
- Branch nodes (like "Men's", "Clothing") can be organizational only - no URL required
- Leaf nodes MUST have URLs where customers can actually shop for products
- Include ALL product category URLs that customers can browse and buy from
- CRITICAL: Look for product categories in ANY URL path pattern (/collections/, /pages/, /shop/, /category/, /products/, etc.) - brands use different URL structures
- Exclude: About pages, contact pages, info pages, search pages, account pages, blog pages

HIERARCHY EXAMPLES:
```
Men's (no URL - just organization)
├── Clothing (no URL - just organization)
│   ├── T-Shirts (https://brand_name.com/collections/mens-tees) ← HAS URL
│   ├── Hoodies (https://brand_name.com//collections/mens-hoodies) ← HAS URL
│   └── Jackets (https://brand_name.com/collections/mens-jackets) ← HAS URL
└── Shoes (https://brand_name.com/collections/mens-shoes) ← HAS URL (or organize further)

Women's ((https://brand_name.com/pages/womens) ← HAS URL if it's a real page
├── Tops (https://brand_name.com/pages/womens-tops) ← HAS URL
└── Dresses (https://brand_name.com/pages/womens-dresses) ← HAS URL

OR if no hierarchy exists:
├── Shoes (https://brand_name.com/bin/shoes) ← HAS URL
└── Accessories (https://brand_name.com/bin/accessories) ← HAS URL
```

IMPORTANT RULES:
1. If no clear hierarchy exists, try your best to organize. If there is a type of tshirt category - then that can probably go under tshits. 
    Only the case that you if you can't, create top-level categories.
    Further, a parent node will always have more than one child node. as if we are categorizing something by some type - then there must have been a separation from the rest of the products. 
    Be vigilant to catch all the children nodes.
2. NEVER INCLUDE "Shop All" or "All products" or just simply "Collections" pages that have no indication of the type of product 
3. Include specific product categories regardless of URL pattern: /collections/tees, /pages/sneakers, /shop/mens-shoes, /category/dresses, /products/accessories. 
   IMPORTANT: Focus on the CONTENT/PURPOSE of the link, not the URL structure. If it leads to browsable products, include it. 
4. If mens/shoes and womens/shoes exist separately, include both under their respective parents
5. Each URL should lead to actual products customers can purchase
6. When in doubt, INCLUDE the category rather than exclude it
7. CRITICAL: Always return the COMPLETE URL exactly as provided in the input - do not truncate to relative paths
8. EXCLUDE "shop all" or "all products" pages that do not indicate specific product types. 

Build the most logical tree structure that represents how this brand organizes its products for customers.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return NavigationAnalysis