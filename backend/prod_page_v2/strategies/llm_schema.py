"""
LLM Schema Discovery Strategy.

Captures API responses, asks LLM to create a mapping schema,
then reuses that schema for all future extractions on the same site.
"""

import json
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from pathlib import Path

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


SCHEMA_PROMPT = """You are analyzing API responses captured from an e-commerce product page.

CAPTURED API RESPONSES:
{api_data}

Based on these API responses, create a JSON mapping schema that extracts product data.

Output ONLY valid JSON in this exact format:
{{
  "name": "<path to product name>",
  "price": "<path to price value>",
  "currency": "<path to currency code>",
  "images": "<path to images array>",
  "description": "<path to description>",
  "variants": {{
    "source": "<path to variants/sizes array>",
    "size": "<field name for size>",
    "available": "<field name for availability>",
    "stock_count": "<field name for stock count>"
  }}
}}

Path format: [response_index].path.to.field
Example: [1].selectedColor.name means response #1, then selectedColor.name

If a field is not available, use null.
If data needs to be merged from multiple responses, note it in the path.
"""


EXTRACT_PROMPT = """Extract product data from these API responses using this schema:

SCHEMA:
{schema}

API RESPONSES:
{api_data}

Output ONLY valid JSON with the extracted product data:
{{
  "name": "<extracted name>",
  "price": <extracted price as number>,
  "currency": "<extracted currency>",
  "images": [<extracted image urls>],
  "description": "<extracted description>",
  "variants": [
    {{"size": "<size>", "available": <true/false>, "stock_count": <number or null>}},
    ...
  ]
}}
"""


class LlmSchemaStrategy(BaseStrategy):
    """
    Two-phase extraction:
    1. Discovery: LLM analyzes API responses and creates a mapping schema
    2. Extraction: Use schema to extract data (can use LLM or direct mapping)
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

        if not self.llm:
            return ExtractionResult.failure(self.strategy_type, "LLM not available")

        domain = self._get_domain(url)
        schema = self._load_schema(domain)

        # Format API responses
        api_data = self._format_api_responses(page_data.json_responses)

        if not schema:
            # Discovery phase - create schema
            print(f"  [LLM Schema] No schema for {domain}, discovering...")
            schema = self._discover_schema(api_data)
            if schema:
                self._save_schema(domain, schema)
                print(f"  [LLM Schema] Schema saved for {domain}")

        if not schema:
            return ExtractionResult.failure(self.strategy_type, "Failed to create schema")

        # Extract using schema
        product_data = self._extract_with_schema(api_data, schema)
        if not product_data:
            return ExtractionResult.failure(self.strategy_type, "Extraction failed")

        product = self._build_product(product_data, url)
        return ExtractionResult.from_product(product, self.strategy_type)

    def can_handle(self, url: str, page_data: Optional[PageData] = None) -> bool:
        """Can handle if we have API responses."""
        if not self.llm:
            return False
        if not page_data or not page_data.json_responses:
            return False
        # Filter out tracking/session APIs
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
        useful = self._filter_useful_responses(responses)

        lines = []
        for i, (url, data) in enumerate(useful.items(), 1):
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
        """Ask LLM to create a mapping schema."""
        prompt = SCHEMA_PROMPT.format(api_data=api_data)

        result = self.llm.call(
            prompt=prompt,
            expected_format="json",
            max_tokens=1000
        )

        if result.get("success"):
            # Handle both parsed data and raw response
            if result.get("data"):
                return result["data"]
            # Try parsing from response (may have markdown fences)
            if result.get("response"):
                return self._parse_json_response(result["response"])
        return None

    def _parse_json_response(self, response: str) -> Optional[Dict]:
        """Parse JSON from LLM response, handling markdown fences."""
        # Strip markdown code fences
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            response = "\n".join(lines)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return None

    def _extract_with_schema(self, api_data: str, schema: Dict) -> Optional[Dict]:
        """Extract product data using schema."""
        prompt = EXTRACT_PROMPT.format(
            schema=json.dumps(schema, indent=2),
            api_data=api_data
        )

        result = self.llm.call(
            prompt=prompt,
            expected_format="json",
            max_tokens=2000
        )

        if result.get("success"):
            if result.get("data"):
                return result["data"]
            if result.get("response"):
                return self._parse_json_response(result["response"])
        return None

    def _build_product(self, data: Dict, url: str) -> Product:
        """Build Product from extracted data."""
        variants = []
        variant_data = data.get('variants') or []
        for v in variant_data:
            if isinstance(v, dict):
                variants.append(Variant(
                    size=v.get('size'),
                    available=v.get('available'),
                    stock_count=v.get('stock_count'),
                ))

        return self._create_product(
            name=data.get('name'),
            price=data.get('price'),
            currency=data.get('currency', 'USD'),
            images=data.get('images', []),
            description=data.get('description', ''),
            url=url,
            variants=variants,
            brand=self._infer_brand_from_url(url),
        )

    def _load_schema(self, domain: str) -> Optional[Dict]:
        """Load saved schema for domain."""
        path = self.schema_dir / f"{domain.replace('.', '_')}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    def _save_schema(self, domain: str, schema: Dict):
        """Save schema for domain."""
        path = self.schema_dir / f"{domain.replace('.', '_')}.json"
        with open(path, 'w') as f:
            json.dump(schema, f, indent=2)
