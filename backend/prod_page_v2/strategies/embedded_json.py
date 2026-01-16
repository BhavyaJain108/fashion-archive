"""
Embedded JSON extraction strategy.

Uses LLM to extract product data from messy JSON embedded in script tags.
Handles escaped JSON, Next.js data, React state, etc.
"""

import json
import os
from typing import Optional
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])
sys.path.insert(0, str(__file__).rsplit('/', 4)[0])  # For llm_handler

from models import Product, Variant, ExtractionResult, ExtractionStrategy
from strategies.base import BaseStrategy, PageData

try:
    from backend.scraper.llm_handler import LLMHandler
except ImportError:
    try:
        from scraper.llm_handler import LLMHandler
    except ImportError:
        LLMHandler = None


# Pydantic model for structured LLM output
class ExtractedProduct(BaseModel):
    """Structured product data from LLM extraction."""
    title: str = Field(description="Product name/title")
    price: Optional[float] = Field(description="Product price as number")
    currency: str = Field(default="USD", description="Currency code")
    description: Optional[str] = Field(default="", description="Product description")
    brand: Optional[str] = Field(default=None, description="Brand name")
    category: Optional[str] = Field(default=None, description="Product category")
    sku: Optional[str] = Field(default=None, description="Product SKU")
    images: list[str] = Field(default=[], description="Image URLs")
    variants: list[dict] = Field(default=[], description="Product variants with size/color/price/available/stock_count")


EXTRACT_PROMPT = """Extract the product information from this script content.

Look for product data including: title, price, variants (with size, color, availability, stock count), images, description.

IMPORTANT: If a field is not found, use null (not strings like "unknown" or "N/A").
Price must be a number or null.

Script content:
"""


class EmbeddedJsonStrategy(BaseStrategy):
    """Extract product data from embedded JSON using LLM."""

    strategy_type = ExtractionStrategy.DOM_FALLBACK

    def __init__(self):
        self.llm = LLMHandler() if LLMHandler else None

    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """Extract product from embedded JSON in scripts."""
        try:
            if not page_data or not page_data.html:
                return ExtractionResult.failure(self.strategy_type, "No HTML provided")

            if not self.llm:
                return ExtractionResult.failure(self.strategy_type, "LLMHandler not available")

            # Find script with product data
            script_content = self._find_product_script(page_data.html)
            if not script_content:
                return ExtractionResult.failure(self.strategy_type, "No product script found")

            # Use LLM to extract clean JSON
            product_data = self._llm_extract(script_content)
            if not product_data:
                return ExtractionResult.failure(self.strategy_type, "LLM extraction failed")

            product = self._parse_product(product_data, url, page_data)
            return ExtractionResult.from_product(product, self.strategy_type)

        except Exception as e:
            return ExtractionResult.failure(self.strategy_type, f"Error: {e}")

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """Check if page has embedded product-like scripts."""
        if not self.llm:
            return False
        if not page_data or not page_data.html:
            return False
        # Look for scripts with product indicators (various terminology)
        html = page_data.html.lower()
        has_product_data = 'price' in html and (
            'variants' in html or
            'variant' in html or
            'size' in html or
            'sizes' in html or
            'productdetail' in html or
            '__next_data__' in html
        )
        return has_product_data

    def _find_product_script(self, html: str) -> Optional[str]:
        """Find the script most likely to contain product data."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        best_script = None
        best_score = 0

        # First check for __NEXT_DATA__ which is a strong indicator
        next_data = soup.find('script', id='__NEXT_DATA__')
        if next_data and next_data.string:
            text = next_data.string.lower()
            if 'price' in text and ('product' in text or 'size' in text):
                return next_data.string

        for script in soup.find_all('script'):
            if not script.string:
                continue
            text = script.string.lower()

            # Score based on product-related keywords
            score = 0
            if 'variants' in text: score += 3
            if 'variant' in text: score += 2
            if 'price' in text: score += 2
            if 'title' in text: score += 1
            if 'inventory' in text: score += 2
            if 'shopify' in text: score += 2
            if 'product' in text: score += 2
            if 'size' in text: score += 2
            if 'sku' in text: score += 1

            # Penalize very short scripts
            length = len(script.string)
            if length < 500: score -= 2

            if score > best_score:
                best_score = score
                best_script = script.string

        return best_script if best_score >= 4 else None

    def _llm_extract(self, script_content: str) -> Optional[dict]:
        """Use LLM to extract product JSON from script content."""
        # Truncate if too long
        if len(script_content) > 30000:
            script_content = script_content[:30000] + "\n...[truncated]"

        prompt = EXTRACT_PROMPT + script_content

        # Use LLMHandler with structured output
        result = self.llm.call(
            prompt=prompt,
            expected_format="json",
            response_model=ExtractedProduct,
            max_tokens=2000
        )

        if result.get("success") and result.get("data"):
            return result["data"]
        return None

    def _parse_product(self, data: dict, url: str, page_data: Optional[PageData] = None) -> Product:
        """Parse LLM response into Product model."""
        variants = []
        for v in data.get('variants', []):
            variant = Variant(
                size=v.get('size'),
                color=v.get('color'),
                sku=v.get('sku'),
                price=v.get('price'),
                available=v.get('available'),
                stock_count=v.get('stock_count'),
            )
            variants.append(variant)

        price = data.get('price')
        if price is None and variants:
            price = variants[0].price

        # Get images - prefer network-captured over LLM-extracted
        images = data.get('images', [])
        if page_data and page_data.image_urls:
            network_images = self._filter_product_images(page_data.image_urls, url)
            if len(network_images) > len(images):
                images = network_images

        return self._create_product(
            name=data.get('title') or data.get('name'),
            price=price,
            currency=data.get('currency', 'USD'),
            images=images,
            description=data.get('description', ''),
            url=url,
            variants=variants,
            brand=data.get('brand') or self._infer_brand_from_url(url),
            sku=data.get('sku'),
            category=data.get('category'),
            raw_data=data,
        )
