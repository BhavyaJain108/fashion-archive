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

            product = self._parse_ld_json(ld_json_data, url, page_data)
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

    def _parse_ld_json(self, data: dict, url: str, page_data: PageData = None) -> Product:
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

        # Extract images - prefer network-captured images, then LD+JSON, then DOM fallback
        images = data.get('image', [])
        if isinstance(images, str):
            images = [images]

        # If we have network-captured images, use filtered version
        if page_data and page_data.image_urls:
            network_images = self._filter_product_images(page_data.image_urls, url)
            if len(network_images) > len(images):
                images = network_images
        # Fallback to DOM extraction if still only 1 image
        elif len(images) <= 1 and page_data and page_data.html:
            dom_images = self._extract_images_from_dom(page_data.html, url)
            if len(dom_images) > len(images):
                images = dom_images

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

        # Fallback: infer brand from domain if not in LD+JSON
        if not brand:
            brand = self._infer_brand_from_url(url)

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

    def _extract_images_from_dom(self, html: str, url: str) -> List[str]:
        """Extract product images from DOM when LD+JSON doesn't have enough."""
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse

        soup = BeautifulSoup(html, 'html.parser')
        domain = urlparse(url).netloc.replace('www.', '')

        images = set()

        # Look for high-quality product images in img tags
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''

            # Skip tiny images, icons, logos
            if any(x in src.lower() for x in ['icon', 'logo', 'sprite', 'pixel', '1x1']):
                continue

            # Keep images that look like product images
            if domain.split('.')[0] in src or 'product' in src.lower() or 'asset' in src:
                # Prefer larger versions
                srcset = img.get('srcset', '')
                if srcset:
                    # Get largest from srcset
                    parts = srcset.split(',')
                    for part in parts:
                        part_url = part.strip().split(' ')[0]
                        if part_url.startswith('http'):
                            images.add(part_url)
                elif src.startswith('http'):
                    images.add(src)

        # Also check for images in data attributes (common in galleries)
        for el in soup.find_all(attrs={'data-zoom': True}):
            images.add(el.get('data-zoom'))
        for el in soup.find_all(attrs={'data-large': True}):
            images.add(el.get('data-large'))

        # Filter and deduplicate
        filtered = []
        seen_basenames = set()
        for img in images:
            if not img or not img.startswith('http'):
                continue
            # Dedupe by basename (avoid same image in different sizes)
            basename = img.split('?')[0].split('/')[-1].split('_')[0]
            if basename not in seen_basenames:
                seen_basenames.add(basename)
                filtered.append(img)

        return filtered[:15]  # Limit to 15 images
