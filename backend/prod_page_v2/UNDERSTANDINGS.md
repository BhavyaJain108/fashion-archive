# Product Page Extraction - Research Findings

## Overview

Tested 12 fashion brands to understand how product data can be extracted. Found 4 main patterns for data availability.

---

## Platform Categories

### 1. Shopify Stores (5 brands)
**Brands:** Khaite, Stussy, Kuurth, Jukuhara, Entire Studios, Eckhaus Latta

**Pattern:** Append `.json` to product URL or intercept GraphQL

```
https://khaite.com/products/sandor-jacket.json
→ Returns complete product JSON
```

**Data Available:**
- ✅ Title, description, vendor
- ✅ Price (base + compare_at)
- ✅ All variants with SKUs
- ✅ Full image gallery with dimensions
- ✅ Inventory policy
- ❌ Stock quantities (hidden by default)
- ⚠️ Materials (in description HTML, needs parsing)

**Variants:**
- Some block `.json` endpoint (Eckhaus Latta) but expose GraphQL
- Entire Studios uses Next.js frontend → Shopify GraphQL backend

**Extraction Strategy:**
```python
# Try .json first
response = requests.get(f"{product_url}.json")
if response.status_code == 200:
    return response.json()['product']
# Fall back to page load + GraphQL interception
```

---

### 2. LD+JSON Embedded (4 brands)
**Brands:** Acne Studios, Balenciaga, Aritzia, COS

**Pattern:** Product data in `<script type="application/ld+json">` tags

**Data Available:**
- ✅ Name, description, brand
- ✅ Price + currency
- ✅ SKU
- ✅ Images (often multiple)
- ✅ Availability per size (as separate Offer objects)
- ⚠️ Sizes (encoded in SKU suffix or separate offers)
- ⚠️ Materials (in description text, needs parsing)

**Example (Acne Studios):**
```json
{
  "@type": "Product",
  "name": "Loose fit jeans - 1981",
  "sku": "CK0138-AUZ",
  "offers": [
    {"sku": "CK0138-AUZ140", "price": "950.00", "availability": "OutOfStock"},
    {"sku": "CK0138-AUZ142", "price": "950.00", "availability": "InStock"},
    ...
  ]
}
```

**Extraction Strategy:**
```python
# Parse HTML for ld+json scripts
soup = BeautifulSoup(html, 'html.parser')
for script in soup.find_all('script', type='application/ld+json'):
    data = json.loads(script.string)
    if data.get('@type') == 'Product':
        return data
```

---

### 3. REST APIs (2 brands)
**Brands:** Uniqlo, Alexander McQueen

**Pattern:** Dedicated API endpoints with product ID

**Uniqlo:**
```
/api/commerce/v5/en/products/{ID}/price-groups/00/l2s?withPrices=true&withStocks=true
```
- Prices, stock counts, size/color matrix
- Requires product ID extraction from URL

**Alexander McQueen (Kering):**
```
/api/v1/amq/product/variants?pid={ID}
/api/v1/amq/availability/{ID}
/api/v1/amq/price/?pids={ID}
```
- Separate endpoints for variants, availability, pricing
- Rich data including season, images with srcset

**Data Available:**
- ✅ Everything: name, price, sizes, colors, stock counts
- ✅ Real-time inventory
- ✅ Multiple image sizes/formats
- ✅ Detailed variant data

**Extraction Strategy:**
```python
# Intercept API calls during page load
# Or construct API URLs from product ID pattern
product_id = extract_id_from_url(url)
api_url = f"/api/v1/product/variants?pid={product_id}"
```

---

### 4. Hybrid / GraphQL Only (1 brand)
**Brands:** Eckhaus Latta (blocks .json, uses GraphQL)

**Pattern:** Shopify Storefront API via GraphQL

**Data Available:**
- ✅ Title, price range
- ⚠️ Limited variant data in intercepted calls
- Need to construct own GraphQL queries for full data

---

## Data Completeness Matrix

| Field | Shopify | LD+JSON | REST API |
|-------|---------|---------|----------|
| Name | ✅ | ✅ | ✅ |
| Price | ✅ | ✅ | ✅ |
| Currency | ✅ | ✅ | ✅ |
| Description | ✅ HTML | ✅ text | ✅ |
| Images | ✅ full gallery | ✅ 1-9 | ✅ srcset |
| Sizes | ✅ variants | ⚠️ in SKU/offers | ✅ |
| Colors | ✅ options | ⚠️ single | ✅ |
| Stock | ❌ hidden | ⚠️ InStock/Out | ✅ counts |
| Materials | ⚠️ in desc | ⚠️ in desc | ⚠️ varies |
| SKU | ✅ | ✅ | ✅ |

---

## Recommended Extraction Approach

### Phase 1: Detection
```
1. Check if Shopify (.json endpoint or myshopify.com in requests)
2. Check for LD+JSON in page HTML
3. Check for product API patterns in network requests
4. Fall back to DOM parsing
```

### Phase 2: Extraction Priority
```
1. Shopify .json → Most complete, single request
2. REST APIs → Most complete, may need multiple requests
3. LD+JSON → Good coverage, embedded in HTML
4. DOM/ARIA → Last resort, fragile
```

### Phase 3: Normalization
All sources should output unified schema:
```python
@dataclass
class Product:
    name: str
    brand: str
    price: float
    currency: str
    description: str
    images: List[str]
    variants: List[Variant]  # size/color/sku/stock
    materials: Optional[str]
    category: Optional[str]
    url: str
```

---

## Platform Detection Heuristics

| Signal | Platform |
|--------|----------|
| `myshopify.com` in network | Shopify |
| `/products/*.json` works | Shopify |
| `demandware.store` in URLs | Salesforce Commerce (Demandware) |
| `dam.kering.com` in images | Kering group (Gucci, Balenciaga, McQueen) |
| `/api/v1/` product endpoints | Custom REST |
| `graphql.json` in network | Shopify Storefront API |

---

## Edge Cases & Gotchas

1. **Lazy-loaded content:** Materials/care often in accordion (Uniqlo)
2. **Blocked endpoints:** Some Shopify stores block `.json` (Eckhaus Latta)
3. **Price variations:** Sale prices, member prices, regional pricing
4. **Size encoding:** May be in SKU suffix (Acne: AUZ140 = size 40)
5. **Image URLs:** May need size parameter substitution for full-res
6. **Stock accuracy:** LD+JSON stock is boolean, APIs have counts

---

## Next Steps

1. **Build unified extractor** with platform detection
2. **Create extractors** for each platform type:
   - `ShopifyExtractor`
   - `LdJsonExtractor`
   - `KeringApiExtractor`
   - `UniqloApiExtractor`
3. **Add material parsing** from description text
4. **Handle variant normalization** across formats
5. **Test on full product catalog** from navigation tree

---

## Test Products Reference

See `test_products.json` for validated URLs across all 12 brands.
