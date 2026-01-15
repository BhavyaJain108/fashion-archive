"""
Base class for extraction strategies.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from models import Product, Variant, ExtractionResult, ExtractionStrategy, MissingFields, PageData


class BaseStrategy(ABC):
    """Base class for extraction strategies."""

    strategy_type: ExtractionStrategy

    @abstractmethod
    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """
        Extract product data from a URL.

        Args:
            url: Product page URL
            page_data: Optional pre-captured page data (HTML, JSON responses)

        Returns:
            ExtractionResult with success/failure and product data
        """
        pass

    @abstractmethod
    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """
        Check if this strategy can handle the given URL.

        Quick check without making requests.
        """
        pass

    def _create_product(
        self,
        name: Optional[str],
        price: Optional[float],
        currency: Optional[str],
        images: Optional[List[str]],
        description: Optional[str],
        url: str,
        variants: Optional[List[Variant]] = None,
        brand: Optional[str] = None,
        sku: Optional[str] = None,
        category: Optional[str] = None,
        raw_description: Optional[str] = None,
        raw_data: Optional[dict] = None,
    ) -> Product:
        """
        Create a Product with missing field tracking.
        """
        missing = MissingFields()

        # Track missing required fields
        if not name:
            missing.name = True
            name = ""
        if price is None:
            missing.price = True
            price = 0.0
        if not currency:
            missing.currency = True
            currency = "USD"  # default
        if not images:
            missing.images = True
            images = []
        if not description:
            missing.description = True
            description = ""
        if not variants:
            missing.variants = True
            variants = []

        return Product(
            name=name,
            price=price,
            currency=currency,
            images=images,
            description=description,
            url=url,
            variants=variants,
            brand=brand,
            sku=sku,
            category=category,
            raw_description=raw_description,
            raw_data=raw_data,
            missing_fields=missing,
        )

    def _clean_html(self, html: str) -> str:
        """Strip HTML tags from text."""
        import re
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', ' ', html)
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()

    def _parse_price(self, price_str: str) -> Optional[float]:
        """Parse price from string like '$29.90' or '29.90'."""
        import re
        if not price_str:
            return None
        # Remove currency symbols and commas
        clean = re.sub(r'[^\d.]', '', str(price_str))
        try:
            return float(clean)
        except ValueError:
            return None

    def _infer_brand_from_url(self, url: str) -> Optional[str]:
        """Infer brand name from domain when not available in data."""
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.lower()
        # Remove www. and TLD
        domain = domain.replace('www.', '')
        parts = domain.split('.')
        if len(parts) >= 2:
            brand_part = parts[0]  # e.g., "alexandermcqueen" from "alexandermcqueen.com"
        else:
            brand_part = domain

        # Known brand name mappings (domain -> proper name)
        brand_map = {
            'alexandermcqueen': 'Alexander McQueen',
            'balenciaga': 'Balenciaga',
            'acnestudios': 'Acne Studios',
            'eckhauslatta': 'Eckhaus Latta',
            'entirestudios': 'Entire Studios',
            'khaite': 'Khaite',
            'stussy': 'Stussy',
            'uniqlo': 'Uniqlo',
            'cos': 'COS',
            'aritzia': 'Aritzia',
            'kuurth': 'Kuurth',
            'jukuhara': 'Jukuhara',
        }

        return brand_map.get(brand_part)

    def _filter_product_images(self, image_urls: List[str], product_url: str, exclude_urls: List[str] = None) -> List[str]:
        """
        Filter network-captured images to find likely product images.

        Uses heuristics to exclude icons, logos, tracking pixels, and UI elements.
        Deduplicates size variants of the same image.

        Args:
            image_urls: All captured image URLs
            product_url: The product page URL (for context)
            exclude_urls: Site-wide images to exclude (from cross-product comparison)
        """
        from urllib.parse import urlparse, parse_qs
        import re

        if not image_urls:
            return []

        # Domains/patterns to always exclude
        EXCLUDE_DOMAINS = [
            'cookielaw', 'onetrust', 'riskified', 'analytics',
            'google', 'facebook', 'doubleclick', 'criteo',
            'pixel', 'tracking', 'beacon', 'clarity.ms',
            'akstat.io', 'akamai', 'cloudflare',
        ]

        # URL patterns to exclude (icons, logos, etc.)
        EXCLUDE_PATTERNS = [
            '/icon', '/logo', '/favicon', '/sprite',
            '/footer/', '/header/', '/nav/',
            'payment', 'cc-', '-brands.svg',
            'placeholder', 'clear.svg', 'arrow',
        ]

        # File extensions to exclude (usually not product photos)
        EXCLUDE_EXTENSIONS = ['.svg', '.gif']

        # Build set of excluded image identifiers (for cross-product filtering)
        excluded_ids = set()
        if exclude_urls:
            for url in exclude_urls:
                excluded_ids.add(self._get_image_identity(url))

        product_images = []
        seen_identities = set()

        for url in image_urls:
            url_lower = url.lower()

            # Skip excluded domains
            if any(d in url_lower for d in EXCLUDE_DOMAINS):
                continue

            # Skip excluded patterns
            if any(p in url_lower for p in EXCLUDE_PATTERNS):
                continue

            # Skip excluded extensions
            if any(url_lower.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
                continue

            # Get normalized identity for deduplication
            identity = self._get_image_identity(url)

            # Skip if this is a site-wide image
            if identity in excluded_ids:
                continue

            # Skip if we've seen this image (size variant)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)

            product_images.append(url)

        return product_images

    def _get_image_identity(self, url: str) -> str:
        """
        Get a normalized identity for an image URL, ignoring size variations.

        Handles patterns like:
        - image.jpg?width=600 vs image.jpg?width=1200
        - image_500x500.jpg vs image_1000x1000.jpg
        - Small/image.jpg vs Large/image.jpg
        - /asset/uuid/Small_thumbnail/file.jpg vs /asset/uuid/Large/file.jpg
        """
        from urllib.parse import urlparse, parse_qs
        import re

        parsed = urlparse(url)
        path = parsed.path.lower()

        # Remove size-related query params
        query = parse_qs(parsed.query)
        size_params = ['width', 'height', 'w', 'h', 'size', 'sw', 'sh', 'resize', 'v']
        filtered_query = {k: v for k, v in query.items() if k.lower() not in size_params}

        # Get filename without extension
        filename = path.split('/')[-1]
        name_part = filename.rsplit('.', 1)[0] if '.' in filename else filename

        # Remove size patterns from filename
        # Patterns: _500x500, -1000x1000, _small, _large, _thumbnail, etc.
        name_part = re.sub(r'[-_]?\d+x\d+', '', name_part)
        name_part = re.sub(r'[-_](small|medium|large|thumb|thumbnail|xl|xs|sm|md|lg)$', '', name_part, flags=re.IGNORECASE)

        # Remove size indicators from path segments
        # Handles: /Small/, /Large/, /Small_thumbnail/, /2000x/, etc.
        size_segment_pattern = r'/(small|medium|large|thumb|thumbnail|small_thumbnail|large_thumbnail|\d+x\d*|\d+x)(/|$)'
        path_normalized = re.sub(size_segment_pattern, '/', path, flags=re.IGNORECASE)

        # For URLs with asset IDs (like Kering DAM), use the asset ID as primary identity
        # Pattern: /asset/uuid/Size/filename or /m/hash/Size-filename
        asset_match = re.search(r'/asset/([a-f0-9-]{36})/', path)
        if asset_match:
            # Use asset UUID as the primary identifier
            return f"{parsed.netloc.lower()}|asset|{asset_match.group(1)}"

        # For hash-based paths like /m/hash/filename
        hash_match = re.search(r'/m/([a-f0-9]{16,})/', path)
        if hash_match:
            return f"{parsed.netloc.lower()}|hash|{hash_match.group(1)}"

        # Combine host + normalized path + filtered query for identity
        identity_parts = [parsed.netloc.lower(), path_normalized, name_part]
        if filtered_query:
            identity_parts.append(str(sorted(filtered_query.items())))

        return '|'.join(identity_parts)
