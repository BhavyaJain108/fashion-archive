"""
API Intercept extraction strategy.

Extracts product data from captured JSON API responses during page load.
"""

import re
from typing import Optional, List, Dict, Any

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from models import Product, Variant, ExtractionResult, ExtractionStrategy
from strategies.base import BaseStrategy, PageData


# Fields that indicate product data
PRODUCT_INDICATORS = [
    'title', 'name', 'productName',
    'price', 'listPrice', 'salePrice',
    'variants', 'sizes', 'colors',
    'sku', 'productId',
    'description', 'descriptionHtml',
    'images', 'image', 'gallery',
]

# Domains to ignore (tracking, analytics, etc.)
IGNORE_DOMAINS = [
    'google', 'facebook', 'analytics', 'tracking', 'pixel',
    'doubleclick', 'criteo', 'klaviyo', 'attentive', 'onetrust',
    'cookielaw', 'abtasty', 'gorgias', 'preproduct',
]


class ApiInterceptStrategy(BaseStrategy):
    """Extract product data from intercepted API responses."""

    strategy_type = ExtractionStrategy.API_INTERCEPT

    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """Extract product from captured API responses."""
        try:
            if not page_data or not page_data.json_responses:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No JSON responses captured"
                )

            # Find the best product API response
            best_response = self._find_best_product_response(page_data.json_responses)

            if not best_response:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No product data found in API responses"
                )

            product = self._parse_api_response(best_response, url)
            return ExtractionResult.from_product(product, self.strategy_type)

        except Exception as e:
            return ExtractionResult.failure(self.strategy_type, f"Error: {e}")

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """Check if we have captured API responses."""
        if not page_data or not page_data.json_responses:
            return False
        # Check if any response looks like product data
        return self._find_best_product_response(page_data.json_responses) is not None

    def _find_best_product_response(self, responses: Dict[str, Any]) -> Optional[dict]:
        """Find the API response most likely to contain product data."""
        candidates = []

        for api_url, data in responses.items():
            # Skip tracking/analytics
            if self._is_tracking_domain(api_url):
                continue

            # Score this response
            score = self._score_product_response(data)
            if score > 0:
                candidates.append((score, data, api_url))

        if not candidates:
            return None

        # Return highest scoring response
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _is_tracking_domain(self, url: str) -> bool:
        """Check if URL is from a tracking/analytics domain."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in IGNORE_DOMAINS)

    def _score_product_response(self, data: Any, prefix: str = "") -> int:
        """Score how likely this response contains product data."""
        score = 0

        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()

                # Check for product indicators
                for indicator in PRODUCT_INDICATORS:
                    if indicator.lower() in key_lower:
                        score += 10
                        break

                # Recurse into nested objects (limit depth)
                if prefix.count('.') < 3:
                    score += self._score_product_response(value, f"{prefix}.{key}")

        elif isinstance(data, list) and data:
            # Check first item of arrays
            score += self._score_product_response(data[0], f"{prefix}[0]")

        return score

    def _parse_api_response(self, data: dict, url: str) -> Product:
        """Parse API response into Product model."""
        # Try to find product data at various paths
        product_data = self._find_product_object(data)

        if not product_data:
            product_data = data

        # Extract fields with various possible key names
        name = self._find_field(product_data, ['title', 'name', 'productName', 'product_name'])
        price = self._find_price(product_data)
        currency = self._find_field(product_data, ['currency', 'currencyCode', 'priceCurrency']) or 'USD'
        images = self._find_images(product_data)
        description = self._find_field(product_data, ['description', 'descriptionHtml', 'body_html', 'productDescription'])
        variants = self._find_variants(product_data)

        raw_description = description
        if description:
            description = self._clean_html(description)

        return self._create_product(
            name=name,
            price=price,
            currency=currency,
            images=images,
            description=description,
            url=url,
            variants=variants,
            brand=self._find_field(product_data, ['brand', 'vendor', 'brandName']),
            sku=self._find_field(product_data, ['sku', 'productId', 'id', 'mpn']),
            category=self._find_field(product_data, ['category', 'productType', 'product_type']),
            raw_description=raw_description,
            raw_data=data,
        )

    def _find_product_object(self, data: dict) -> Optional[dict]:
        """Find the product object within nested data."""
        # Common paths where product data might be
        paths = [
            ['product'],
            ['data', 'product'],
            ['result'],
            ['data'],
            ['items', 0],
            ['products', 0],
        ]

        for path in paths:
            obj = data
            try:
                for key in path:
                    if isinstance(key, int):
                        obj = obj[key]
                    else:
                        obj = obj.get(key)
                    if obj is None:
                        break
                if obj and isinstance(obj, dict):
                    return obj
            except (KeyError, IndexError, TypeError):
                continue

        return None

    def _find_field(self, data: dict, keys: List[str]) -> Optional[str]:
        """Find first matching field from list of possible keys."""
        for key in keys:
            # Try direct key
            if key in data:
                val = data[key]
                if isinstance(val, dict):
                    # Might be nested like {"brand": {"name": "..."}}
                    return val.get('name') or val.get('value')
                return str(val) if val else None

            # Try case-insensitive
            for k, v in data.items():
                if k.lower() == key.lower():
                    if isinstance(v, dict):
                        return v.get('name') or v.get('value')
                    return str(v) if v else None

        return None

    def _find_price(self, data: dict) -> Optional[float]:
        """Find price in data."""
        price_keys = ['price', 'listPrice', 'salePrice', 'amount', 'priceValue', 'listPriceValue', 'salePriceValue']

        for key in price_keys:
            if key in data:
                val = data[key]
                if isinstance(val, dict):
                    # Handle nested like {"price": {"amount": 29.90}}
                    return self._parse_price(val.get('amount') or val.get('value'))
                return self._parse_price(val)

        # Check nested priceRange
        if 'priceRange' in data:
            pr = data['priceRange']
            if isinstance(pr, dict):
                min_price = pr.get('minVariantPrice', {})
                if isinstance(min_price, dict):
                    return self._parse_price(min_price.get('amount'))

        return None

    def _find_images(self, data: dict) -> List[str]:
        """Find images in data."""
        images = []
        image_keys = ['images', 'image', 'gallery', 'media']

        for key in image_keys:
            if key in data:
                val = data[key]
                if isinstance(val, str):
                    images.append(val)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str):
                            images.append(item)
                        elif isinstance(item, dict):
                            img_url = item.get('src') or item.get('url') or item.get('image')
                            if img_url:
                                images.append(img_url)
                elif isinstance(val, dict):
                    # Handle {"main": {...}, "sub": [...]}
                    for v in val.values():
                        if isinstance(v, dict) and 'image' in v:
                            images.append(v['image'])
                        elif isinstance(v, list):
                            for item in v:
                                if isinstance(item, dict) and 'image' in item:
                                    images.append(item['image'])

        return images

    def _find_variants(self, data: dict) -> List[Variant]:
        """Find variants in data."""
        variants = []
        variant_keys = ['variants', 'sizes', 'skuAvailabilities', 'l2s']

        for key in variant_keys:
            if key not in data:
                continue

            val = data[key]

            # Handle list of variants
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        variants.append(Variant(
                            size=item.get('size') or item.get('title'),
                            color=item.get('color'),
                            sku=item.get('sku') or item.get('id'),
                            price=self._parse_price(item.get('price')),
                            available=item.get('available') or item.get('availableForSale') or item.get('inStock'),
                            stock_count=item.get('inventory_quantity') or item.get('quantity'),
                        ))

            # Handle dict of variants (keyed by SKU)
            elif isinstance(val, dict):
                for sku, item in val.items():
                    if isinstance(item, dict):
                        variants.append(Variant(
                            sku=sku,
                            available=item.get('inStock'),
                            stock_count=item.get('quantity'),
                        ))

            # Handle nested variants like {"edges": [{"node": {...}}]}
            if 'edges' in val if isinstance(val, dict) else False:
                for edge in val.get('edges', []):
                    node = edge.get('node', {})
                    variants.append(Variant(
                        size=node.get('title'),
                        sku=node.get('sku') or node.get('id'),
                        price=self._parse_price(node.get('price', {}).get('amount')),
                        available=node.get('availableForSale'),
                    ))

        return variants
