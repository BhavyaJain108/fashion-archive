# Product Extraction Architecture

## File Structure

```
prod_page_v2/
├── models.py          # Data classes (Product, Variant, PageData, ExtractionResult)
├── page_loader.py     # Loads page with Playwright, captures HTML + API responses
├── extractor.py       # Main orchestrator - runs strategies, merges results
├── strategies/
│   ├── base.py        # BaseStrategy abstract class
│   ├── shopify.py     # Fetches /product.json endpoint
│   ├── shopify_graphql.py  # Queries Shopify GraphQL API
│   ├── ld_json.py     # Parses <script type="application/ld+json">
│   ├── api_intercept.py    # Parses captured JSON API responses
│   ├── llm_schema.py  # LLM discovers API schema (NEW)
│   ├── embedded_json.py    # LLM parses embedded scripts
│   └── html_meta.py   # Reads meta tags (fallback)
└── stealth/           # Bot detection evasion
    └── patches.py     # Chrome patches to avoid detection
```

## Data Flow

```
1. INPUT: Product URL
        ↓
2. page_loader.py
   - Opens Playwright browser (with stealth patches)
   - Navigates to URL
   - Captures:
     • HTML content
     • JSON API responses (intercepted from network)
     • Image URLs
   - Returns: PageData object
        ↓
3. extractor.py
   - Receives PageData
   - Runs each strategy in order:

     Strategy 1: ShopifyStrategy
       → Tries to fetch {url}.json
       → Returns: ExtractionResult (success/fail + Product)

     Strategy 2: ShopifyGraphQLStrategy
       → Looks for Shopify GraphQL endpoint
       → Returns: ExtractionResult

     Strategy 3: LdJsonStrategy
       → Searches HTML for <script type="application/ld+json">
       → Parses JSON, looks for @type: "Product"
       → Returns: ExtractionResult

     Strategy 4: ApiInterceptStrategy
       → Looks through captured JSON responses
       → Scores each by product-related keywords
       → Parses best match
       → Returns: ExtractionResult

     Strategy 5: LlmSchemaStrategy
       → If no schema exists for domain:
         - Sends API responses to LLM
         - LLM returns mapping schema
         - Schema saved to disk
       → Uses schema to extract product
       → Returns: ExtractionResult

     Strategy 6: EmbeddedJsonStrategy
       → Searches for <script> tags with product data
       → Sends to LLM to parse
       → Returns: ExtractionResult

     Strategy 7: HtmlMetaStrategy
       → Reads og:title, og:image, meta tags
       → Returns: ExtractionResult (usually low quality)
        ↓
4. _merge_products()
   - Takes all successful ExtractionResults
   - Merges fields (highest score wins conflicts)
   - Returns: Final merged Product
        ↓
5. OUTPUT: Product with name, price, images, variants, etc.
```

## Key Classes

### PageData (models.py)
```python
@dataclass
class PageData:
    url: str
    html: str = ""
    json_responses: Dict[str, Any] = {}  # URL -> response data
    image_urls: List[str] = []
```

### Product (models.py)
```python
@dataclass
class Product:
    name: str
    price: float
    currency: str
    images: List[str]
    description: str
    url: str
    variants: List[Variant]
    brand: Optional[str]
    sku: Optional[str]
```

### ExtractionResult (models.py)
```python
@dataclass
class ExtractionResult:
    success: bool
    product: Optional[Product]
    strategy: ExtractionStrategy
    score: int  # 0-100, higher = more complete
    error: Optional[str]
```

## Strategy Interface

Each strategy implements:
```python
class BaseStrategy:
    strategy_type: ExtractionStrategy  # Enum identifier

    def can_handle(url, page_data) -> bool:
        """Quick check if this strategy might work"""

    async def extract(url, page_data) -> ExtractionResult:
        """Attempt extraction, return result"""
```

## Current Issues

1. **No DOM scraping strategy** - If structured data (LD+JSON, APIs) doesn't exist,
   we have no way to extract from actual HTML elements

2. **Strategy overlap** - ApiInterceptStrategy and LlmSchemaStrategy both look at
   the same API responses but in different ways

3. **Fallback quality** - HtmlMetaStrategy often returns garbage (site name instead
   of product name) because many sites have broken meta tags
