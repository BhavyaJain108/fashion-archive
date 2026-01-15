"""
LD+JSON extraction strategy.

Extracts product data from <script type="application/ld+json"> tags in HTML.
"""

import json
import re
from typing import Optional, List

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from models import Product, Variant, ExtractionResult, ExtractionStrategy
from strategies.base import BaseStrategy, PageData


class LdJsonStrategy(BaseStrategy):
    """Extract product data from embedded LD+JSON."""

    strategy_type = ExtractionStrategy.LD_JSON

    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """Extract product from LD+JSON in HTML."""
        try:
            if not page_data or not page_data.html:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No HTML provided"
                )

            ld_json_data = self._find_product_ld_json(page_data.html)

            if not ld_json_data:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No Product LD+JSON found in page"
                )

            product = self._parse_ld_json(ld_json_data, url)
            return ExtractionResult.from_product(product, self.strategy_type)

        except Exception as e:
            return ExtractionResult.failure(self.strategy_type, f"Error: {e}")

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """LD+JSON can potentially be on any page."""
        # We can try this on any page - it's non-destructive
        return True

    def _find_product_ld_json(self, html: str) -> Optional[dict]:
        """Find Product LD+JSON in HTML."""
        # Find all ld+json scripts
        pattern = r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>'
        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

        for match in matches:
            try:
                data = json.loads(match.strip())

                # Handle @graph arrays
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Product':
                            return item

                # Direct Product type
                if data.get('@type') == 'Product':
                    return data

            except json.JSONDecodeError:
                continue

        return None

    def _parse_ld_json(self, data: dict, url: str) -> Product:
        """Parse LD+JSON Product into Product model."""
        # Extract offers/variants
        variants = []
        offers = data.get('offers', [])

        # Normalize to list
        if isinstance(offers, dict):
            offers = [offers]

        for offer in offers:
            variant = Variant(
                sku=offer.get('sku'),
                price=self._parse_price(offer.get('price')),
                available=self._parse_availability(offer.get('availability')),
            )
            # Try to extract size from SKU (common pattern: SKU140 = size 40)
            if variant.sku and not variant.size:
                size_match = re.search(r'(\d{2,3})$', variant.sku)
                if size_match:
                    variant.size = size_match.group(1)
            variants.append(variant)

        # Extract images
        images = data.get('image', [])
        if isinstance(images, str):
            images = [images]

        # Get price from offers if not at top level
        price = self._parse_price(data.get('price'))
        if price is None and variants:
            price = variants[0].price

        # Get currency
        currency = None
        if offers:
            first_offer = offers[0] if isinstance(offers, list) else offers
            currency = first_offer.get('priceCurrency')

        # Get description
        description = data.get('description', '')
        raw_description = description

        # Get brand
        brand = None
        if isinstance(data.get('brand'), dict):
            brand = data['brand'].get('name')
        elif isinstance(data.get('brand'), str):
            brand = data.get('brand')

        # Get category
        category = None
        if isinstance(data.get('category'), dict):
            category = data['category'].get('name')
        elif isinstance(data.get('category'), str):
            category = data.get('category')

        # Get color if available
        color = data.get('color')
        if color and variants:
            for v in variants:
                v.color = color

        return self._create_product(
            name=data.get('name'),
            price=price,
            currency=currency,
            images=images,
            description=description,
            url=url,
            variants=variants,
            brand=brand,
            sku=data.get('sku') or data.get('mpn'),
            category=category,
            raw_description=raw_description,
            raw_data=data,
        )

    def _parse_availability(self, availability: Optional[str]) -> Optional[bool]:
        """Parse schema.org availability to boolean."""
        if not availability:
            return None
        availability = availability.lower()
        if 'instock' in availability:
            return True
        if 'outofstock' in availability:
            return False
        return None
