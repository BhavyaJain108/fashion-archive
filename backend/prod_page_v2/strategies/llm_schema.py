"""
LLM Schema Discovery Strategy.

Uses LLM to DISCOVER extraction paths from API responses on first URL,
then extracts WITHOUT LLM on subsequent URLs using the learned paths.

Path format: [response_index].path.to.field
Example: [1].product.name means response #1, then product.name
"""

import json
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from pathlib import Path
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])
sys.path.insert(0, str(__file__).rsplit('/', 4)[0])

from models import Product, Variant, ExtractionResult, ExtractionStrategy
from strategies.base import BaseStrategy, PageData

try:
    from backend.scraper.llm_handler import LLMHandler
except ImportError:
    try:
        from scraper.llm_handler import LLMHandler
    except ImportError:
        LLMHandler = None


# Pydantic model for extraction schema (what LLM returns during discovery)
class ApiExtractionSchema(BaseModel):
    """Schema describing paths to extract product data from API responses."""
    name: Optional[str] = Field(default=None, description="Path to product name, e.g., '[1].product.title'")
    price: Optional[str] = Field(default=None, description="Path to price value, e.g., '[1].product.price'")
    currency: Optional[str] = Field(default=None, description="Path to currency OR literal like 'USD'")
    description: Optional[str] = Field(default=None, description="Path to description")
    brand: Optional[str] = Field(default=None, description="Path to brand OR literal value")
    category: Optional[str] = Field(default=None, description="Path to category")
    sku: Optional[str] = Field(default=None, description="Path to SKU")
    images: Optional[str] = Field(default=None, description="Path to images array, e.g., '[1].product.images'")
    image_url_field: Optional[str] = Field(default=None, description="Field name within image object for URL")
    variants: Optional[str] = Field(default=None, description="Path to variants/sizes array")
    variant_size_field: Optional[str] = Field(default=None, description="Field name for size in variant")
    variant_color_field: Optional[str] = Field(default=None, description="Field name for color in variant")
    variant_price_field: Optional[str] = Field(default=None, description="Field name for variant price")
    variant_available_field: Optional[str] = Field(default=None, description="Field name for availability")
    variant_stock_field: Optional[str] = Field(default=None, description="Field name for stock count")
    variant_sku_field: Optional[str] = Field(default=None, description="Field name for variant SKU")


DISCOVER_SCHEMA_PROMPT = """Analyze these API responses from an e-commerce product page and identify the PATHS to product data.

I need you to tell me WHERE each piece of data is located, not extract the data itself.

CAPTURED API RESPONSES:
{api_data}

Path format: [response_number].path.to.field
- [1] means the first response, [2] means second, etc.
- Use dot notation for nested paths (e.g., "[1].product.variants")
- If a value is a literal (like currency is always "USD"), put the literal value
- If a field is not found, use null

For variants, also identify the field names WITHIN each variant object (e.g., "size", "name", "available").

IMPORTANT: Look for the response that contains the most product data. Common patterns:
- product.title, product.name, product.price
- variants array with size/color/stock info
"""


class LlmSchemaStrategy(BaseStrategy):
    """
    Two-phase extraction from API responses:
    1. Discovery (first URL): LLM finds extraction paths, saves schema
    2. Extraction (subsequent URLs): Use saved schema with pure Python - NO LLM
    """

    strategy_type = ExtractionStrategy.LLM_SCHEMA

    def __init__(self, schema_dir: Optional[Path] = None):
        self.llm = LLMHandler() if LLMHandler else None
        self.schema_dir = schema_dir or Path(__file__).parent.parent / "schemas"
        self.schema_dir.mkdir(exist_ok=True)

    async def extract(self, url: str, page_data: Optional[PageData] = None) -> ExtractionResult:
        """Extract product using saved schema or discover new one."""
        if not page_data or not page_data.json_responses:
            return ExtractionResult.failure(self.strategy_type, "No API responses captured")

        domain = self._get_domain(url)

        # Filter to useful responses
        useful_responses = self._filter_useful_responses(page_data.json_responses)
        if not useful_responses:
            return ExtractionResult.failure(self.strategy_type, "No useful API responses")

        # Convert to indexed list for path extraction
        responses_list = list(useful_responses.values())

        schema = self._load_schema(domain)

        if schema:
            # Use saved schema - NO LLM!
            print(f"    [llm_schema] Using saved schema for {domain} (no LLM)")
            product_data = self._extract_with_schema(responses_list, schema)
            if product_data:
                product = self._build_product(product_data, url)
                return ExtractionResult.from_product(product, self.strategy_type)
            else:
                print(f"    [llm_schema] Schema extraction failed, falling back to discovery")

        # No saved schema or extraction failed - need LLM
        if not self.llm:
            return ExtractionResult.failure(self.strategy_type, "LLM not available")

        # Discovery phase - create schema
        print(f"    [llm_schema] Discovering extraction schema for {domain}")
        api_data = self._format_api_responses(useful_responses)
        schema = self._discover_schema(api_data)

        if schema:
            self._save_schema(domain, schema)
            print(f"    [llm_schema] Saved schema for {domain}")

            # Try extracting with the new schema
            product_data = self._extract_with_schema(responses_list, schema)
            if product_data:
                product = self._build_product(product_data, url)
                return ExtractionResult.from_product(product, self.strategy_type)

        return ExtractionResult.failure(self.strategy_type, "Failed to create or use schema")

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """Can handle if we have useful API responses."""
        if not page_data or not page_data.json_responses:
            return False

        # Check if we have saved schema (can work without LLM)
        domain = self._get_domain(url)
        if self._load_schema(domain):
            return True

        # Otherwise need LLM
        if not self.llm:
            return False

        # Check for useful responses
        useful_responses = self._filter_useful_responses(page_data.json_responses)
        return len(useful_responses) > 0

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')

    def _filter_useful_responses(self, responses: Dict[str, Any]) -> Dict[str, Any]:
        """Filter out tracking/session/analytics responses."""
        skip_patterns = ['/session', '/customer/', 'tracking', 'analytics', 'pixel', 'cookie', 'juDryKs']
        useful = {}
        for url, data in responses.items():
            # Check path only (before query params)
            path = url.split('?')[0].lower()
            if any(p in path for p in skip_patterns):
                continue
            # Skip tiny responses (likely pings)
            data_str = json.dumps(data)
            if len(data_str) < 100:
                continue
            useful[url] = data
        return useful

    def _format_api_responses(self, responses: Dict[str, Any]) -> str:
        """Format API responses for LLM consumption."""
        lines = []
        for i, (url, data) in enumerate(responses.items(), 1):
            # Truncate URL for readability
            short_url = url.split('?')[0][-60:]

            # Truncate large responses
            data_str = json.dumps(data, indent=2)
            if len(data_str) > 3000:
                data_str = data_str[:3000] + "\n... [truncated]"

            lines.append(f"[{i}] {short_url}")
            lines.append(data_str)
            lines.append("")

        return "\n".join(lines)

    def _discover_schema(self, api_data: str) -> Optional[Dict]:
        """Ask LLM to create extraction schema (paths, not data)."""
        prompt = DISCOVER_SCHEMA_PROMPT.format(api_data=api_data)

        result = self.llm.call(
            prompt=prompt,
            expected_format="json",
            response_model=ApiExtractionSchema,
            max_tokens=1000,
            operation="api_schema_discovery",
        )

        if result.get("success") and result.get("data"):
            return result["data"]
        return None

    def _extract_with_schema(self, responses: List[Dict], schema: Dict) -> Optional[Dict]:
        """Extract product data using schema paths - NO LLM."""
        try:
            product_data = {}

            # Simple fields
            for field in ['name', 'price', 'currency', 'description', 'brand', 'category', 'sku']:
                path = schema.get(field)
                if path:
                    value = self._get_by_path(responses, path)
                    if value is not None:
                        product_data[field] = value

            # Images
            images_path = schema.get('images')
            if images_path:
                images_data = self._get_by_path(responses, images_path)
                if images_data and isinstance(images_data, list):
                    url_field = schema.get('image_url_field', 'url')
                    images = []
                    for img in images_data:
                        if isinstance(img, str):
                            images.append(img)
                        elif isinstance(img, dict):
                            # Try multiple common field names
                            for f in [url_field, 'url', 'src', 'source', 'image', 'imageUrl']:
                                if f in img:
                                    images.append(img[f])
                                    break
                    product_data['images'] = images

            # Variants
            variants_path = schema.get('variants')
            if variants_path:
                variants_data = self._get_by_path(responses, variants_path)
                if variants_data and isinstance(variants_data, list):
                    variants = []
                    size_field = schema.get('variant_size_field', 'size')
                    color_field = schema.get('variant_color_field', 'color')
                    price_field = schema.get('variant_price_field', 'price')
                    avail_field = schema.get('variant_available_field', 'available')
                    stock_field = schema.get('variant_stock_field', 'stock')
                    sku_field = schema.get('variant_sku_field', 'sku')

                    for v in variants_data:
                        if isinstance(v, dict):
                            variant = {}
                            # Size - try multiple field names
                            for f in [size_field, 'size', 'name', 'title', 'option', 'sizeLabel']:
                                if f in v:
                                    variant['size'] = v[f]
                                    break
                            # Color
                            for f in [color_field, 'color', 'colorName', 'colour']:
                                if f in v:
                                    variant['color'] = v[f]
                                    break
                            # Price
                            for f in [price_field, 'price', 'amount', 'value']:
                                if f in v:
                                    variant['price'] = v[f]
                                    break
                            # Availability
                            for f in [avail_field, 'available', 'inStock', 'in_stock', 'isAvailable', 'availability']:
                                if f in v:
                                    val = v[f]
                                    if isinstance(val, bool):
                                        variant['available'] = val
                                    elif isinstance(val, str):
                                        variant['available'] = val.lower() in ['true', 'yes', '1', 'in stock', 'available']
                                    elif isinstance(val, int):
                                        variant['available'] = val > 0
                                    break
                            # Stock count
                            for f in [stock_field, 'stock', 'stockCount', 'stock_count', 'inventory', 'quantity']:
                                if f in v:
                                    variant['stock_count'] = v[f]
                                    break
                            # SKU
                            for f in [sku_field, 'sku', 'id', 'variantId', 'variant_id']:
                                if f in v:
                                    variant['sku'] = v[f]
                                    break

                            if variant:
                                variants.append(variant)

                    product_data['variants'] = variants

            # Need at least name or price
            return product_data if product_data.get('name') or product_data.get('price') else None

        except Exception as e:
            print(f"    [llm_schema] Schema extraction error: {e}")
            return None

    def _get_by_path(self, responses: List[Dict], path: str) -> Any:
        """Get value from responses using path like [1].product.name"""
        if not path or path == 'null':
            return None

        # Check if it's a literal value (no brackets or dots)
        if not any(c in path for c in '.[]'):
            return path  # Return as literal (e.g., "USD")

        # Parse response index from [N] prefix
        match = re.match(r'\[(\d+)\]\.?(.*)', path)
        if match:
            idx = int(match.group(1)) - 1  # 1-indexed to 0-indexed
            remaining_path = match.group(2)

            if idx < 0 or idx >= len(responses):
                return None

            data = responses[idx]

            if not remaining_path:
                return data

            return self._navigate_path(data, remaining_path)
        else:
            # No index prefix - try all responses
            for data in responses:
                result = self._navigate_path(data, path)
                if result is not None:
                    return result
            return None

    def _navigate_path(self, data: Any, path: str) -> Any:
        """Navigate a dot-notation path within a data structure."""
        if not path:
            return data

        parts = path.replace('[', '.').replace(']', '').split('.')
        current = data

        for part in parts:
            if not part:
                continue
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx]
                except (ValueError, IndexError):
                    return None
            else:
                return None

            if current is None:
                return None

        return current

    def _build_product(self, data: Dict, url: str) -> Product:
        """Build Product from extracted data."""
        variants = []
        variant_data = data.get('variants') or []
        for v in variant_data:
            if isinstance(v, dict):
                variants.append(Variant(
                    size=v.get('size'),
                    color=v.get('color'),
                    available=v.get('available'),
                    stock_count=v.get('stock_count'),
                    sku=v.get('sku'),
                    price=v.get('price'),
                ))

        return self._create_product(
            name=data.get('name'),
            price=data.get('price'),
            currency=data.get('currency', 'USD'),
            images=data.get('images', []),
            description=data.get('description', ''),
            url=url,
            variants=variants,
            brand=data.get('brand') or self._infer_brand_from_url(url),
            category=data.get('category'),
            sku=data.get('sku'),
        )

    def _load_schema(self, domain: str) -> Optional[Dict]:
        """Load saved schema for domain."""
        path = self.schema_dir / f"{domain.replace('.', '_')}.json"
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except:
                pass
        return None

    def _save_schema(self, domain: str, schema: Dict):
        """Save schema for domain."""
        path = self.schema_dir / f"{domain.replace('.', '_')}.json"
        with open(path, 'w') as f:
            json.dump(schema, f, indent=2)
