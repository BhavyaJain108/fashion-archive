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
    name_selector: Optional[str] = Field(description="Most precise CSS selector for names within container")
    link_selector: str = Field(description="Most precise CSS selector for product links within container")
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
You are analyzing an e-commerce product listing page to identify the CORE ATTRIBUTES (url, name) that represents each individual product.
Your goal is to find the MOST PRECISE AND DISCRIMINATING selector that identifies the products in the provided examples.

CRITICAL REQUIREMENT: ALL PRESENT INTERSECTION AND NOT UNION
- You are ONLY analyzing the provided product examples - ignore any other potential content on the page
- Use the SPECIFIC classes/attributes available on ALL provided products
- Combining multiple identifiers is POSSIBLE, that is ALWAYS better than using single generic ones
- High specificity of this sort protects against false matches and is the PRIMARY goal

**ALL PRESENT INTERSECTION AND NOT UNION**: Use only classes that exist on ALL products, not classes from just one product

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
1. Find the MAIN CONTAINER element that wraps each complete product (link, name, images)
2. List ALL classes and attributes on that SPECIFIC CONTAINER element for each example
3. Identify which classes/attributes appear on the SAME CONTAINER element across ALL products
4. Combine ONLY the classes/attributes from that single container element
5. Get rid of the classses/attributes that dont appear on both elements
6. DO NOT mix classes from different nested elements (container vs inner elements)

CRITICAL: Your selector must target ONE SPECIFIC ELEMENT TYPE
- If the container is a div with classes A and B, use: div.A.B
- Do NOT combine classes from parent + child elements like: div.parent.child-class
- Each class in your selector must exist on the SAME HTML element

NAME EXTRACTION STRATEGY:
Product names should primarily come from product URLs if possible. CSS text selectors are fallback when URL extraction isn't sufficient.

THE CONTENT:
{contexts_text}

NO ADDITIONAL CONTENT OTHER THAN EXPECTED JSON.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return ProductPatternAnalysis