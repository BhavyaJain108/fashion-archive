"""
Brand Validation Prompt
=======================

LLM prompt for validating if a URL belongs to a legitimate clothing/apparel brand.
This is a pre-check before initiating brand scraping.
"""

from pydantic import BaseModel, Field
from typing import Literal


class BrandValidationResponse(BaseModel):
    """Response model for brand validation"""
    valid: bool = Field(description="Whether this is a legitimate clothing/apparel brand")
    brand_name: str = Field(description="The extracted brand name from the website")
    reasoning: str = Field(description="Explanation for the validation decision")
    confidence: Literal["high", "medium", "low"] = Field(description="Confidence level in the validation")


def get_brand_validation_prompt(url: str, page_title: str = "", page_content_sample: str = "") -> dict:
    """
    Get the brand validation prompt and response model.

    Args:
        url: The brand's homepage URL
        page_title: Optional page title from the website
        page_content_sample: Optional sample of page content for better validation

    Returns:
        dict with 'prompt' and 'model' keys
    """

    prompt = f"""You are a fashion industry expert validating whether a URL belongs to a suitable clothing/apparel brand for our curated collection.

URL to validate: {url}
Page Title: {page_title or "Not available"}
Page Content Sample: {page_content_sample[:500] if page_content_sample else "Not available"}

Your task:
1. Determine if this is a clothing/apparel brand that fits our criteria
2. Extract the brand name
3. Provide clear, specific reasoning for your decision
4. If the page content is insufficient, make the best guess based on URL and title and any researchable knowledge you have

✅ ACCEPT (valid: true):
- High-end luxury fashion brands (e.g., Rick Owens, Comme des Garçons, Maison Margiela)
- Independent/emerging designers and labels
- Small-scale boutique brands
- Niche streetwear brands
- Artisanal clothing makers
- Designer-owned fashion houses
- Avant-garde fashion brands

❌ REJECT (valid: false):
- Multi-brand marketplaces (Amazon, Etsy, ASOS, Farfetch, Grailed, etc.)
- Mass-market large scale commercial brands (Nike, Zara, H&M, Gap, Uniqlo, etc.)
- Fast fashion retailers
- Department stores selling multiple brands
- Non-clothing websites
- Personal blogs or portfolios without actual clothing sales
- Dropshipping sites
- Generic online retailers

Key considerations:
- Is this a single, independent brand with its own identity?
- Does the brand have creative direction/unique aesthetic?
- Is it NOT a major commercial/mass-market brand?
- Does it actually sell clothing (not just showcase work)?
- High end factor should trump scale factor. so if a brand is high end we should allow it regardless of its scale

Be strict with validation. When in doubt about whether a brand is too commercial, reject it.

Respond with:
- valid: true/false
- brand_name: The extracted brand name (or best guess from URL if unclear)
- reasoning: Explain specifically why you accepted or rejected (mention which category it falls into)
- confidence: high/medium/low
"""

    return {
        "prompt": prompt,
        "model": BrandValidationResponse
    }
