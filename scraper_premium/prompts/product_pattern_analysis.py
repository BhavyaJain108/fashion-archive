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
    container_selector: str = Field(description="Most precise CSS selector for product containers")
    image_selector: str = Field(description="Most precise CSS selector for images within container")
    name_selector: Optional[str] = Field(description="Most precise CSS selector for names within container")
    link_selector: str = Field(description="Most precise CSS selector for product links within container")
    image_name_extraction: str = Field(description="yes or no - whether image URLs contain extractable names")
    alternative_selectors: List[str] = Field(default=[], description="Other selectors considered but rejected")


def get_prompt(product_contexts: List[tuple]) -> str:
    """Generate product pattern analysis prompt"""
    
    # Format multiple product contexts
    contexts_text = ""
    for i, (product_link, context_html) in enumerate(product_contexts, 1):
        contexts_text += f"""
PRODUCT {i}:
Link: {product_link}
HTML Context:
{context_html}
"""
    
    return f"""
You are analyzing an e-commerce product listing page to identify the CORE ATTRIBUTES (url, image, name) that represents each individual product.
Your goal is to find the MOST PRECISE AND DISCRIMINATING selector that identifies the products in the provided examples.

CRITICAL REQUIREMENT: MAXIMUM SPECIFICITY IS DESIRED
- You are ONLY analyzing the provided product examples - ignore any other potential content on the page
- Use the MOST SPECIFIC classes/attributes available on ALL provided products
- Combining multiple identifiers is ALWAYS better than using single generic ones
- High specificity protects against false matches and is the PRIMARY goal

{contexts_text}

MANDATORY PRECISION RULES:
1. **USE ALL COMMON IDENTIFIERS**: If all products share multiple classes/attributes, combine them
2. **INCLUDE DATA ATTRIBUTES**: Product-specific attributes add crucial specificity  
3. **AVOID LAYOUT-ONLY SELECTORS**: Single layout classes are too generic
4. **SEMANTIC + LAYOUT**: Combine semantic meaning with layout for best precision

SELECTOR CONSTRUCTION STRATEGY:
1. **Multiple specific classes**: Combine all classes that appear on ALL products
2. **Semantic + attributes**: Product-meaningful classes with data attributes
3. **Custom elements**: Non-standard HTML elements are often product-specific
4. **Child selectors**: Use descendant selectors (space) or direct child (>) when needed
5. **AVOID**: Single generic classes that could match non-products

IMPORTANT CSS COMPATIBILITY:
- Use STANDARD CSS selectors only (class, id, attribute, descendant, child)
- DO NOT use modern selectors like :has(), :is(), :where(), :not() 
- DO NOT use complex pseudo-selectors that may not be supported
- Stick to basic selectors: .class, #id, [attribute], div > .class, .parent .child

ANALYSIS PROCESS:
1. Find the MAIN CONTAINER element that wraps each complete product (image, link, name)
2. List ALL classes and attributes on that SPECIFIC CONTAINER element for each example
3. Identify which classes/attributes appear on the SAME CONTAINER element across ALL three products
4. Combine ONLY the classes/attributes from that single container element
5. DO NOT mix classes from different nested elements (container vs inner elements)

CRITICAL: Your selector must target ONE SPECIFIC ELEMENT TYPE
- If the container is a div with classes A and B, use: div.A.B
- Do NOT combine classes from parent + child elements like: div.parent.child-class
- Each class in your selector must exist on the SAME HTML element

SPECIFICITY CHECK:
Ask yourself: "Is this the MOST SPECIFIC selector possible using all available classes/attributes from the examples?"
If NO, combine more identifiers to maximize precision. Overly specific is better than under-specific.

NAME EXTRACTION STRATEGY:
Product names should primarily come from product URLs if possible. CSS text selectors are first fallback, and final fallback is image filenames/URLs when they contain meaningful names.

""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return ProductPatternAnalysis