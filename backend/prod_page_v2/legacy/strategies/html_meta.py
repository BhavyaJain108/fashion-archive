"""
HTML Meta Tag extraction strategy.

Fallback strategy that extracts basic product info from HTML meta tags.
Most sites have og:title, og:image, description for SEO purposes.
"""

import re
from typing import Optional, List
from urllib.parse import urljoin

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from models import Product, Variant, ExtractionResult, ExtractionStrategy
from strategies.base import BaseStrategy, PageData


class HtmlMetaStrategy(BaseStrategy):
    """Extract product data from HTML meta tags."""

    strategy_type = ExtractionStrategy.HTML_META

    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """Extract product info from meta tags."""
        try:
            if not page_data or not page_data.html:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "No HTML content"
                )

            html = page_data.html

            # Extract from meta tags — prefer itemprop="name" (most specific)
            name = self._extract_itemprop_name(html) or self._extract_meta(html, [
                'og:title',
                'twitter:title',
                'title',
            ]) or self._extract_title_tag(html)

            description = self._extract_meta(html, [
                'og:description',
                'twitter:description',
                'description',
            ])

            # Extract images
            images = []
            og_image = self._extract_meta(html, ['og:image', 'twitter:image'])
            if og_image:
                images.append(og_image)

            # Also look for additional og:image tags
            additional_images = re.findall(
                r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
                html,
                re.IGNORECASE
            )
            for img in additional_images:
                if img not in images:
                    images.append(img)

            # Try to extract price from meta or structured patterns
            price = self._extract_price_from_html(html)
            currency = self._extract_meta(html, ['og:price:currency', 'product:price:currency']) or 'USD'

            # Clean up name (remove site suffix like "| UNIQLO US")
            if name:
                name = re.sub(r'\s*[|\-–]\s*[^|\-–]+$', '', name).strip()

            if not name:
                return ExtractionResult.failure(
                    self.strategy_type,
                    "Could not extract product name from meta tags"
                )

            product = self._create_product(
                name=name,
                price=price,
                currency=currency,
                images=images,
                description=description or '',
                url=url,
                variants=[],
                brand=self._extract_meta(html, ['og:site_name', 'twitter:site']),
            )

            return ExtractionResult.from_product(product, self.strategy_type)

        except Exception as e:
            return ExtractionResult.failure(self.strategy_type, f"Error: {e}")

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """Can handle if we have HTML with meta tags."""
        if not page_data or not page_data.html:
            return False
        # Check if there's at least og:title or a title tag
        return 'og:title' in page_data.html or '<title>' in page_data.html

    def _extract_itemprop_name(self, html: str) -> Optional[str]:
        """Extract product name from itemprop='name' element (most reliable)."""
        # Match <... itemprop="name">TEXT</...>
        match = re.search(
            r'itemprop=["\']name["\'][^>]*>([^<]+)<',
            html,
            re.IGNORECASE
        )
        if match:
            val = match.group(1).strip()
            if val and len(val) > 1:
                return val
        # Match <meta itemprop="name" content="...">
        match = re.search(
            r'<meta[^>]*itemprop=["\']name["\'][^>]*content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return None

    def _extract_meta(self, html: str, properties: List[str]) -> Optional[str]:
        """Extract content from meta tag by property or name."""
        for prop in properties:
            # Try property="..."
            match = re.search(
                rf'<meta[^>]*(?:property|name)=["\']?{re.escape(prop)}["\']?[^>]*content=["\']([^"\']+)["\']',
                html,
                re.IGNORECASE
            )
            if match:
                return match.group(1).strip()

            # Try content before property (different tag ordering)
            match = re.search(
                rf'<meta[^>]*content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']?{re.escape(prop)}["\']?',
                html,
                re.IGNORECASE
            )
            if match:
                return match.group(1).strip()

        return None

    def _extract_title_tag(self, html: str) -> Optional[str]:
        """Extract from <title> tag."""
        match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_price_from_html(self, html: str) -> Optional[float]:
        """Try to extract price from various HTML patterns."""
        # Try og:price:amount
        price_meta = self._extract_meta(html, ['og:price:amount', 'product:price:amount'])
        if price_meta:
            return self._parse_price(price_meta)

        # Try common price patterns in HTML
        patterns = [
            r'class=["\'][^"\']*price[^"\']*["\'][^>]*>\s*\$?([\d,]+\.?\d*)',
            r'data-price=["\']?([\d,]+\.?\d*)',
            r'itemprop=["\']price["\'][^>]*content=["\']?([\d,]+\.?\d*)',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return self._parse_price(match.group(1))

        return None
