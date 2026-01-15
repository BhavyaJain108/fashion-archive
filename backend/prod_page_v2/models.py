"""
Data models for product extraction.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


@dataclass
class PageData:
    """Data captured from page load."""
    url: str
    html: str = ""
    json_responses: Dict[str, Any] = field(default_factory=dict)
    request_headers: Dict[str, Dict[str, str]] = field(default_factory=dict)
    aria: Optional[dict] = None
    image_urls: List[str] = field(default_factory=list)


class ExtractionStrategy(Enum):
    """Available extraction strategies."""
    SHOPIFY_JSON = "shopify_json"
    SHOPIFY_GRAPHQL = "shopify_graphql"
    LD_JSON = "ld_json"
    API_INTERCEPT = "api_intercept"
    HTML_META = "html_meta"
    DOM_FALLBACK = "dom_fallback"


@dataclass
class Variant:
    """A product variant (size/color combination)."""
    size: Optional[str] = None
    color: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[float] = None
    available: Optional[bool] = None
    stock_count: Optional[int] = None  # if known


@dataclass
class MissingFields:
    """Track which fields could not be extracted."""
    name: bool = False
    price: bool = False
    currency: bool = False
    images: bool = False
    description: bool = False
    variants: bool = False

    def any_missing(self) -> bool:
        return any([self.name, self.price, self.currency,
                    self.images, self.description, self.variants])

    def to_list(self) -> List[str]:
        missing = []
        if self.name: missing.append("name")
        if self.price: missing.append("price")
        if self.currency: missing.append("currency")
        if self.images: missing.append("images")
        if self.description: missing.append("description")
        if self.variants: missing.append("variants")
        return missing


@dataclass
class Product:
    """Normalized product data."""
    # Required fields
    name: str
    price: float
    currency: str
    images: List[str]
    description: str
    url: str

    # Variant info
    variants: List[Variant] = field(default_factory=list)

    # Optional but useful
    brand: Optional[str] = None
    sku: Optional[str] = None
    category: Optional[str] = None

    # Raw dump for unstructured data
    raw_description: Optional[str] = None  # original HTML/text before cleaning
    raw_data: Optional[dict] = None  # full raw response for debugging

    # Extraction metadata
    extraction_strategy: Optional[ExtractionStrategy] = None
    missing_fields: MissingFields = field(default_factory=MissingFields)

    def is_complete(self) -> bool:
        """Check if all required fields are present."""
        return (
            bool(self.name) and
            self.price is not None and
            bool(self.currency) and
            bool(self.images) and
            bool(self.description)
        )

    def completeness_score(self) -> int:
        """Score how complete the extraction is (0-100)."""
        score = 0
        # Required fields (60 points)
        if self.name: score += 15
        if self.price is not None: score += 15
        if self.currency: score += 5
        if self.images: score += 15
        if self.description: score += 10
        # Variants (25 points)
        if self.variants:
            score += 15
            if any(v.available is not None for v in self.variants):
                score += 10
        # Optional (15 points)
        if self.brand: score += 5
        if self.sku: score += 5
        if self.category: score += 5
        return score


@dataclass
class ExtractionResult:
    """Result of an extraction attempt."""
    success: bool
    product: Optional[Product] = None
    strategy: Optional[ExtractionStrategy] = None
    error: Optional[str] = None
    score: int = 0  # completeness score

    @classmethod
    def failure(cls, strategy: ExtractionStrategy, error: str) -> 'ExtractionResult':
        return cls(success=False, strategy=strategy, error=error, score=0)

    @classmethod
    def from_product(cls, product: Product, strategy: ExtractionStrategy) -> 'ExtractionResult':
        product.extraction_strategy = strategy
        return cls(
            success=True,
            product=product,
            strategy=strategy,
            score=product.completeness_score()
        )


@dataclass
class BrandConfig:
    """Configuration for extracting from a specific brand."""
    domain: str
    strategy: ExtractionStrategy

    # Strategy-specific config
    api_pattern: Optional[str] = None  # URL pattern for API calls
    product_id_regex: Optional[str] = None  # how to extract product ID from URL

    # Verification
    verified: bool = False
    discovery_url: Optional[str] = None
    verification_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "strategy": self.strategy.value,
            "api_pattern": self.api_pattern,
            "product_id_regex": self.product_id_regex,
            "verified": self.verified,
            "discovery_url": self.discovery_url,
            "verification_url": self.verification_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'BrandConfig':
        return cls(
            domain=data["domain"],
            strategy=ExtractionStrategy(data["strategy"]),
            api_pattern=data.get("api_pattern"),
            product_id_regex=data.get("product_id_regex"),
            verified=data.get("verified", False),
            discovery_url=data.get("discovery_url"),
            verification_url=data.get("verification_url"),
        )
