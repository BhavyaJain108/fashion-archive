"""
Shopify GraphQL Storefront API extraction strategy.

Works for Shopify sites that block .json but expose Storefront API.
Captures access token from page requests and queries GraphQL directly.
"""

import re
import aiohttp
from typing import Optional, List, Tuple
from urllib.parse import urlparse

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from models import Product, Variant, ExtractionResult, ExtractionStrategy
from strategies.base import BaseStrategy, PageData


# GraphQL query for product data
PRODUCT_QUERY = """
query getProduct($handle: String!) {
  product(handle: $handle) {
    id
    title
    description
    descriptionHtml
    vendor
    productType
    priceRange {
      minVariantPrice {
        amount
        currencyCode
      }
      maxVariantPrice {
        amount
        currencyCode
      }
    }
    images(first: 20) {
      edges {
        node {
          url
          altText
        }
      }
    }
    variants(first: 100) {
      edges {
        node {
          id
          title
          sku
          availableForSale
          price {
            amount
            currencyCode
          }
          selectedOptions {
            name
            value
          }
        }
      }
    }
    options {
      name
      values
    }
  }
}
"""


class ShopifyGraphQLStrategy(BaseStrategy):
    """Extract product data via Shopify Storefront GraphQL API."""

    strategy_type = ExtractionStrategy.SHOPIFY_GRAPHQL

    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """Extract product using Storefront GraphQL API."""
        try:
            if not page_data:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No page data provided"
                )

            # Find GraphQL endpoint and access token
            graphql_url, access_token = self._find_graphql_config(page_data)

            if not graphql_url or not access_token:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No Shopify GraphQL endpoint or access token found"
                )

            # Extract product handle from URL
            handle = self._extract_handle(url)
            if not handle:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "Could not extract product handle from URL"
                )

            # Query GraphQL API
            data = await self._query_graphql(graphql_url, access_token, handle)

            if not data or 'product' not in data.get('data', {}):
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No product data in GraphQL response"
                )

            product = self._parse_graphql_product(data['data']['product'], url)
            return ExtractionResult.from_product(product, self.strategy_type)

        except Exception as e:
            return ExtractionResult.failure(self.strategy_type, f"Error: {e}")

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """Check if we have Shopify GraphQL credentials."""
        if not page_data:
            return False
        graphql_url, access_token = self._find_graphql_config(page_data)
        return graphql_url is not None and access_token is not None

    def _find_graphql_config(self, page_data: PageData) -> Tuple[Optional[str], Optional[str]]:
        """Find GraphQL endpoint URL and access token from captured requests."""
        graphql_url = None
        access_token = None

        for url, headers in page_data.request_headers.items():
            if 'myshopify.com' in url and 'graphql' in url:
                graphql_url = url
                # Look for access token in headers
                for key, value in headers.items():
                    if 'storefront-access-token' in key.lower():
                        access_token = value
                        break
                if access_token:
                    break

        # Also check HTML for embedded config if not found in headers
        if not access_token and page_data.html:
            # Try to find token in HTML/JS
            token_match = re.search(
                r'storefrontAccessToken["\'\s:]+([a-f0-9]{32})',
                page_data.html,
                re.IGNORECASE
            )
            if token_match:
                access_token = token_match.group(1)

            # Find shop domain if we don't have graphql_url
            if not graphql_url:
                domain_match = re.search(
                    r'([a-z0-9-]+\.myshopify\.com)',
                    page_data.html,
                    re.IGNORECASE
                )
                if domain_match:
                    graphql_url = f"https://{domain_match.group(1)}/api/2024-01/graphql.json"

        return graphql_url, access_token

    def _extract_handle(self, url: str) -> Optional[str]:
        """Extract product handle from URL."""
        parsed = urlparse(url)
        path = parsed.path

        # Common patterns:
        # /products/product-handle
        # /product/product-handle
        # /collections/xxx/products/product-handle
        patterns = [
            r'/products?/([^/?]+)',
            r'/p/([^/?]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, path)
            if match:
                return match.group(1)

        return None

    async def _query_graphql(self, url: str, token: str, handle: str) -> Optional[dict]:
        """Query Shopify Storefront GraphQL API."""
        headers = {
            'Content-Type': 'application/json',
            'X-Shopify-Storefront-Access-Token': token,
        }

        payload = {
            'query': PRODUCT_QUERY,
            'variables': {'handle': handle}
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None

    def _parse_graphql_product(self, data: dict, url: str) -> Product:
        """Parse GraphQL product response into Product model."""
        # Extract images
        images = []
        for edge in data.get('images', {}).get('edges', []):
            node = edge.get('node', {})
            if node.get('url'):
                images.append(node['url'])

        # Extract variants with proper option mapping
        variants = []
        options_def = data.get('options', [])  # [{name: "Size", values: [...]}, ...]

        for edge in data.get('variants', {}).get('edges', []):
            node = edge.get('node', {})

            # Parse selected options to get size/color
            size = None
            color = None
            for opt in node.get('selectedOptions', []):
                name_lower = opt.get('name', '').lower()
                value = opt.get('value')
                if 'size' in name_lower:
                    size = value
                elif 'color' in name_lower or 'colour' in name_lower:
                    color = value

            # Fallback: parse from title if options not found
            if not size and not color and node.get('title'):
                parts = node['title'].split(' / ')
                if len(parts) >= 1:
                    size = parts[0]
                if len(parts) >= 2:
                    color = parts[1]

            price_data = node.get('price', {})
            variants.append(Variant(
                size=size,
                color=color,
                sku=node.get('sku'),
                price=self._parse_price(price_data.get('amount')),
                available=node.get('availableForSale'),
            ))

        # Get price from priceRange
        price_range = data.get('priceRange', {})
        min_price = price_range.get('minVariantPrice', {})
        price = self._parse_price(min_price.get('amount'))
        currency = min_price.get('currencyCode', 'USD')

        # Get description
        description = data.get('description', '')
        raw_description = data.get('descriptionHtml', '')
        if not description and raw_description:
            description = self._clean_html(raw_description)

        return self._create_product(
            name=data.get('title'),
            price=price,
            currency=currency,
            images=images,
            description=description,
            url=url,
            variants=variants,
            brand=data.get('vendor'),
            category=data.get('productType'),
            raw_description=raw_description,
            raw_data=data,
        )
