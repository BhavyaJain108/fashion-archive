"""
Base class for extraction strategies.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from models import Product, Variant, ExtractionResult, ExtractionStrategy, MissingFields


@dataclass
class PageData:
    """Data captured from page load."""
    url: str
    html: str
    json_responses: Dict[str, Any]  # url -> response body
    aria: Optional[dict] = None


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
