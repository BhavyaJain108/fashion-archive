"""
Product Pattern Analysis Prompt
===============================

Analyzes HTML around product links to identify container patterns for extraction.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class ProductPatternAnalysis(BaseModel):
    """Structured output for product pattern analysis"""
    analysis: str = Field(description="Explanation of reasoning and selectors considered")
    container_selector: str = Field(description="Exact CSS selector for product containers")
    image_selector: str = Field(description="Exact CSS selector for images within container")
    name_selector: Optional[str] = Field(description="Exact CSS selector for names within container")
    link_selector: str = Field(description="Exact CSS selector for product links within container")
    image_name_extraction: str = Field(description="yes or no - whether image URLs contain extractable names")
    alternative_selectors: List[str] = Field(default=[], description="Other selectors considered but rejected")


def get_prompt(product_link: str, context_html: str) -> str:
    """Generate product pattern analysis prompt"""
    return f"""
You are analyzing an e-commerce product listing page to identify the CORE CONTAINER that represents each individual product.
Your goal is to find the most reliable, minimal selector that identifies product containers across different page layouts.

Product Link: {product_link}
HTML Context:
{context_html}

LOGICAL ANALYSIS PROCESS:
1. Locate the provided product link in the HTML
2. Find the ACTUAL PRESENT container that holds product information (image, name, link, price)
3. Use the EXACT container visible in the HTML context - don't assume parent wrappers exist
4. Look for the most SEMANTIC identifier (tag name, meaningful class, data attribute)
5. Choose the SIMPLEST selector that works with the HTML structure provided
6. Verify the selector excludes non-product elements (nav, ads, related items)

CRITICAL: Work with the HTML structure AS PROVIDED - don't assume missing parent containers exist.

SELECTOR PRIORITY (choose the first that works):
1. **Custom element tags**: product-card, x-cell, product-item
2. **Semantic classes**: .product, .product-card, .item
3. **Inner semantic classes**: .product__inner, .product-block__inner, .c-product__item
4. **Data attributes**: [data-product], [prod-instock]
5. **Component classes**: .card (if specifically for products)
6. **Layout classes**: Only as last resort (.grid__item, .column)

HANDLE PARTIAL HTML:
- If you see `.product-block__inner` but no `.product-block`, use `.product-block__inner`
- If you see `.c-product__item` but no `.c-product`, use `.c-product__item`
- Select based on what's ACTUALLY PRESENT in the HTML context

CONTAINER SELECTOR LOGIC:
The container selector must be:
- COMPREHENSIVE: Matches every product container on the page
- PRECISE: Specific enough to exclude navigation, ads, or other non-product elements
- FLEXIBLE: Works for both full page layouts AND isolated product elements
- MINIMAL: Use the simplest selector that reliably identifies product containers

CRITICAL SELECTOR GUIDELINES:
1. **Avoid over-specific selectors**: Don't chain multiple classes unless absolutely necessary
2. **Prioritize semantic containers**: Look for elements that naturally contain complete product info
3. **Test mental model**: The selector should work on a page with 1 product or 100 products
4. **Consider tag types**: Custom elements (like <product-card>, <x-cell>) often indicate containers
5. **Avoid layout-specific classes**: Classes like 'grid__item', 'column' may not always be present

COMMON RELIABLE PATTERNS:
- Custom elements: product-card, x-cell, product-item
- Semantic classes: .product, .product-card, .item
- Data attributes: [data-product], [prod-instock]
- Avoid: Layout classes (.grid__item, .column, .flex), position classes (.first, .last)

IMAGE EXTRACTION STRATEGY:
Product names should primarily come from product URLs, then image filenames/URLs when they contain meaningful names. CSS text selectors are fallback only.

EXTENSIBILITY FOCUS:
The pattern should work across different:
- Page layouts (grid, list, slider)
- Container structures (with/without wrapper elements)  
- HTML frameworks (Shopify, custom, etc.)
- Product quantities (single product vs full catalog pages)
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return ProductPatternAnalysis