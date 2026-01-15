"""
Shopify .json extraction strategy.

Works for sites that allow appending .json to product URLs.
"""

import aiohttp
from typing import Optional, List
from urllib.parse import urlparse

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from models import Product, Variant, ExtractionResult, ExtractionStrategy
from strategies.base import BaseStrategy, PageData


class ShopifyStrategy(BaseStrategy):
    """Extract product data via Shopify .json endpoint."""

    strategy_type = ExtractionStrategy.SHOPIFY_JSON

    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """Try to fetch product data from .json endpoint."""
        try:
            json_url = self._get_json_url(url)
            data = await self._fetch_json(json_url)

            if not data or 'product' not in data:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No product data in response"
                )

            product = self._parse_shopify_product(data['product'], url)
            return ExtractionResult.from_product(product, self.strategy_type)

        except aiohttp.ClientError as e:
            return ExtractionResult.failure(self.strategy_type, f"HTTP error: {e}")
        except Exception as e:
            return ExtractionResult.failure(self.strategy_type, f"Error: {e}")

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """Check if URL looks like a Shopify product URL."""
        # Shopify URLs typically have /products/ in the path
        return '/products/' in url.lower()

    def _get_json_url(self, url: str) -> str:
        """Convert product URL to .json endpoint."""
        # Remove query params and trailing slash
        base_url = url.split('?')[0].rstrip('/')
        # Add .json if not already present
        if not base_url.endswith('.json'):
            base_url += '.json'
        return base_url

    async def _fetch_json(self, url: str) -> Optional[dict]:
        """Fetch JSON from URL."""
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    text = await response.text()
                    # Check if it's actually JSON (not "Not allowed" or HTML)
                    if text.startswith('{'):
                        import json
                        return json.loads(text)
                return None

    def _parse_shopify_product(self, data: dict, url: str) -> Product:
        """Parse Shopify product JSON into Product model."""
        # Build option name -> position mapping from options array
        option_map = {}  # e.g. {'size': 1, 'color': 2}
        for opt in data.get('options', []):
            name_lower = opt.get('name', '').lower()
            position = opt.get('position')
            if position:
                if 'size' in name_lower:
                    option_map['size'] = position
                elif 'color' in name_lower or 'colour' in name_lower:
                    option_map['color'] = position
                elif 'material' in name_lower:
                    option_map['material'] = position

        # Extract variants using the option mapping
        variants = []
        for v in data.get('variants', []):
            # Get size/color based on the option mapping
            size = None
            color = None

            if 'size' in option_map:
                size = v.get(f'option{option_map["size"]}')
            if 'color' in option_map:
                color = v.get(f'option{option_map["color"]}')

            # Fallback: if no mapping found, try to guess from option values
            if not size and not color:
                opt1, opt2 = v.get('option1'), v.get('option2')
                # If only one option, use it as size
                if opt1 and not opt2:
                    size = opt1
                # If two options, check if first looks like a color name
                elif opt1 and opt2:
                    color_keywords = ['black', 'white', 'red', 'blue', 'green', 'grey', 'gray', 'brown', 'navy', 'beige', 'cream', 'pink']
                    if any(kw in opt1.lower() for kw in color_keywords):
                        color, size = opt1, opt2
                    else:
                        size, color = opt1, opt2

            variant = Variant(
                size=size,
                color=color,
                sku=v.get('sku'),
                price=self._parse_price(v.get('price')),
                available=v.get('available'),
                stock_count=v.get('inventory_quantity'),
            )
            # Try to parse size/color from title if still missing
            if not variant.size and v.get('title'):
                variant.size = v.get('title').split('/')[0].strip() if '/' in v.get('title', '') else v.get('title')
            variants.append(variant)

        # Extract images
        images = [img.get('src') for img in data.get('images', []) if img.get('src')]

        # Get price from first variant if not at top level
        price = self._parse_price(data.get('price'))
        if price is None and variants:
            price = variants[0].price

        # Get description
        description = data.get('body_html', '')
        raw_description = description
        description = self._clean_html(description)

        return self._create_product(
            name=data.get('title'),
            price=price,
            currency='USD',  # Shopify typically returns price in shop's currency
            images=images,
            description=description,
            url=url,
            variants=variants,
            brand=data.get('vendor'),
            sku=data.get('variants', [{}])[0].get('sku') if data.get('variants') else None,
            category=data.get('product_type'),
            raw_description=raw_description,
            raw_data=data,
        )
