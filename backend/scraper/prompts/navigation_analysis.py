"""
Navigation Analysis Prompt
==========================

Analyzes website navigation to find product category URLs.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


def _build_link_tree(links: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a tree structure from links based on their DOM ancestor paths.

    Groups links by their common ancestors to reveal the navigation hierarchy.
    Returns a nested dict structure that can be formatted as a tree.
    """
    if not links or not isinstance(links[0], dict):
        return {}

    # Filter to only links that have ancestor_path (navigation links)
    nav_links = [l for l in links if l.get('ancestor_path')]
    if not nav_links:
        # Fallback: use all links with nav_depth
        nav_links = links

    # Build tree using ancestor paths
    root = {'children': {}, 'links': []}

    for link in nav_links:
        ancestor_path = link.get('ancestor_path', [])
        nav_depth = link.get('nav_depth', 0)

        # Navigate/create path in tree
        current = root
        for tag_name, identifier, idx in ancestor_path:
            key = f"{identifier}[{idx}]"
            if key not in current['children']:
                current['children'][key] = {'children': {}, 'links': [], 'tag': tag_name}
            current = current['children'][key]

        # Add link at this position
        current['links'].append(link)

    return root


def _format_tree_text(tree: Dict[str, Any], prefix: str = "", is_last: bool = True, depth: int = 0) -> str:
    """
    Format the tree structure as text with tree-drawing characters.

    Returns string like:
    ├── <a href="/mens">Men</a>
    │   ├── <a href="/mens/clothing">Clothing</a>
    │   │   ├── <a href="/mens/tshirts">T-Shirts</a>
    │   │   └── <a href="/mens/hoodies">Hoodies</a>
    │   └── <a href="/mens/shoes">Shoes</a>
    └── <a href="/womens">Women</a>
    """
    lines = []

    # Get all items at this level (links + child containers)
    items = []

    # Add links at this level
    for link in tree.get('links', []):
        items.append(('link', link))

    # Add child containers (but only if they have links somewhere below)
    for key, child in tree.get('children', {}).items():
        if _has_links(child):
            items.append(('container', key, child))

    # Format each item
    for i, item in enumerate(items):
        is_last_item = (i == len(items) - 1)

        if item[0] == 'link':
            link = item[1]
            connector = "└── " if is_last_item else "├── "
            lines.append(f"{prefix}{connector}{link['full_element']}")
        else:
            # Container with children - recurse
            _, key, child = item
            child_prefix = prefix + ("    " if is_last_item else "│   ")
            child_text = _format_tree_text(child, child_prefix, is_last_item, depth + 1)
            if child_text:
                lines.append(child_text)

    return "\n".join(lines)


def _has_links(tree: Dict[str, Any]) -> bool:
    """Check if tree or any descendants have links."""
    if tree.get('links'):
        return True
    for child in tree.get('children', {}).values():
        if _has_links(child):
            return True
    return False


def _format_links_as_tree(links: List[Dict[str, Any]]) -> str:
    """
    Format links as a tree structure based on their nav_depth.

    Uses simple indentation based on nav_depth for a cleaner approach
    that doesn't require complex ancestor path tracking.
    """
    if not links:
        return ""

    # Check if links have nav_depth info
    has_depth_info = any(l.get('nav_depth', 0) > 0 for l in links if isinstance(l, dict))

    if not has_depth_info or not isinstance(links[0], dict):
        # Fallback to flat list
        if isinstance(links[0], dict):
            return "\n".join(f"{i}. {l['full_element']}" for i, l in enumerate(links))
        else:
            return "\n".join(f"{i}. {l}" for i, l in enumerate(links))

    # Group consecutive links by depth to build tree structure
    lines = []
    prev_depth = -1
    depth_stack = []  # Track which depths are "last" at each level

    for i, link in enumerate(links):
        depth = link.get('nav_depth', 0)
        element = link['full_element']

        # Look ahead to see if this is the last item at this depth
        is_last_at_depth = True
        for j in range(i + 1, len(links)):
            future_depth = links[j].get('nav_depth', 0)
            if future_depth == depth:
                is_last_at_depth = False
                break
            elif future_depth < depth:
                break

        # Build prefix based on depth
        if depth == 0:
            connector = "└── " if is_last_at_depth else "├── "
            prefix = ""
        else:
            # Build the prefix showing the tree structure
            prefix_parts = []
            for d in range(depth):
                # Check if there are more items at this ancestor depth
                has_more_at_d = False
                for j in range(i + 1, len(links)):
                    if links[j].get('nav_depth', 0) == d:
                        has_more_at_d = True
                        break
                    elif links[j].get('nav_depth', 0) < d:
                        break
                prefix_parts.append("│   " if has_more_at_d else "    ")

            prefix = "".join(prefix_parts)
            connector = "└── " if is_last_at_depth else "├── "

        lines.append(f"{prefix}{connector}{element}")
        prev_depth = depth

    return "\n".join(lines)


class CategoryNode(BaseModel):
    """Hierarchical category node"""
    name: str = Field(description="Display name of the category")
    url: Optional[str] = Field(default=None, description="The category URL (required for leaf nodes)")
    reasoning: str = Field(description="Why this category was included and why this position was selected based on emperical data")
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


class NavigationAnalysis(BaseModel):
    """Structured output for navigation/category analysis"""
    category_tree: List[CategoryNode] = Field(description="Hierarchical product category structure")
    excluded_count: int = Field(description="Number of URLs that were excluded (for informational purposes only)")
    
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
        # New format with HTML context - use tree representation
        links_text = _format_links_as_tree(links)
    else:
        # Old format - just URLs
        links_text = "\n".join(f"{i}. {link}" for i, link in enumerate(links))

    return f"""
Analyze this fashion brand website's navigation links and create a hierarchical product category tree:

Website: {website_url}

Link elements found on the page (shown as a tree based on their DOM position - indentation indicates menu nesting):
{links_text}

IMPORTANT: The tree structure above shows how links are nested in the website's HTML navigation menus.
- Links at the same indentation level are siblings in the menu
- Deeper indentation (├── or └──) indicates submenu items
- Use this structure as a strong hint for your category hierarchy

You are a clothing expert and understand all types of clothing styles and categories.
This is a clothing/fashion website. Build a hierarchical tree structure that shows how this brand organizes its products.

CREATE A CATEGORY TREE:
- Use the DOM tree structure above as guidance for organizing categories
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
1. STRONGLY prefer the hierarchy shown in the DOM tree structure above. If links appear nested in the input, they should likely be nested in your output.
2. If no clear hierarchy exists in the DOM, try your best to organize based on common sense. If there is a type of tshirt category - then that can probably go under tshirts.
   A parent node will always have more than one child node, as if we are categorizing something by some type - then there must have been a separation from the rest of the products.
   Be vigilant to catch all the children nodes.
3. NEVER INCLUDE "Shop All" or "All products" or just simply "Collections" pages that have no indication of the type of product
4. Include specific product categories regardless of URL pattern: /collections/tees, /pages/sneakers, /shop/mens-shoes, /category/dresses, /products/accessories.
   IMPORTANT: Focus on the CONTENT/PURPOSE of the link, not the URL structure. If it leads to browsable products, include it.
5. If mens/shoes and womens/shoes exist separately, include both under their respective parents
6. Each URL should lead to actual products customers can purchase
7. When in doubt, INCLUDE the category rather than exclude it
8. CRITICAL: Always return the COMPLETE URL exactly as provided in the input - do not truncate to relative paths
9. EXCLUDE "shop all" or "all products" pages that do not indicate specific product types.

OUTPUT:
- Return the category_tree with the hierarchical structure
- For excluded_count, just return the NUMBER of URLs you excluded (e.g., 15) - no need to list them or explain why

Build the most logical tree structure that represents how this brand organizes its products for customers.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return NavigationAnalysis