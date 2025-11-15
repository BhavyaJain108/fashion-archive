# Premium Scraper Integration - Complete Specification

**Last Updated:** 2025-11-15
**Status:** Design Phase
**Version:** 1.0

---

## Table of Contents
1. [Overview](#overview)
2. [Data Storage Architecture](#data-storage-architecture)
3. [Database Schema](#database-schema)
4. [API Capabilities](#api-capabilities)
5. [API Endpoints](#api-endpoints)
6. [Implementation Status](#implementation-status)
7. [Migration Guide](#migration-guide)

---

## Overview

This document tracks the complete integration of the premium scraper with a flexible, scalable API layer. The system is designed to:

- **Store scraping intelligence** (patterns, navigation trees) for reuse and optimization
- **Normalize product data** with flexible attributes and multi-dimensional classifications
- **Provide powerful APIs** for querying, filtering, and aggregating product data
- **Scale from local files → database → cloud** with minimal refactoring

### Key Design Principles

1. **Separation of Concerns**: Scraping intelligence vs. Product catalog vs. Brand registry
2. **Flexibility**: Schema-less attributes and classifications (JSONB)
3. **Extensibility**: New attributes/classifications don't require schema changes
4. **Queryability**: Optimized for common access patterns (by brand, category, attributes)
5. **Progressive Enhancement**: Start simple (files), scale as needed (DB → cloud)

---

## Data Storage Architecture

### Phase 1: Local File Storage

**Directory Structure:**
```
/data/
  /brands/
    /{brand_slug}/              # e.g., "jukuhara", "eckhauslatta"

      # Core brand data
      - brand.json              # Brand metadata
      - navigation.json         # Current navigation tree
      - scraping_intel.json     # Pattern library (The Brain)
      - products.json           # All products for this brand

      # Media
      /images/
        /{category_slug}/       # Organized by category
          /{product_slug}_1.jpg
          /{product_slug}_2.jpg

      # Historical scrape runs
      /scrape_runs/
        /{run_id}.json          # Full scrape run details

  # Global indexes (for quick lookups)
  /indexes/
    - brands.json               # List of all brands
```

---

### File Schemas

#### 1. `brand.json` - Brand Metadata
```json
{
  "brand_id": "jukuhara",
  "name": "Jukuhara",
  "homepage_url": "https://jukuhara.jp",
  "domain": "jukuhara.jp",

  "status": {
    "last_scrape_run_id": "run_20251115_123000",
    "last_scrape_at": "2025-11-15T12:30:00Z",
    "last_scrape_status": "completed",
    "total_products": 26,
    "total_categories": 7
  },

  "metadata": {
    "added_at": "2025-11-13T10:00:00Z",
    "total_scrape_runs": 3,
    "scraper_version": "1.0"
  }
}
```

**Purpose:** Quick brand lookups, status tracking
**Access Pattern:** Read frequently, write on scrape completion

---

#### 2. `navigation.json` - Latest Navigation Tree
```json
{
  "brand_id": "jukuhara",
  "captured_at": "2025-11-15T12:30:00Z",
  "run_id": "run_20251115_123000",

  "category_tree": [
    {
      "name": "T-Shirts & Compressions",
      "url": null,
      "reasoning": "Main category for t-shirts...",
      "children": [
        {
          "name": "T-Shirts",
          "url": "https://jukuhara.jp/collections/t-shirts-compressions",
          "reasoning": "Dedicated category...",
          "children": null
        }
      ]
    }
  ],

  "excluded_urls": [
    {
      "url": "https://jukuhara.jp/",
      "reasoning": "Homepage, not a specific product category"
    }
  ],

  "all_category_urls": [
    "https://jukuhara.jp/collections/t-shirts-compressions",
    "https://jukuhara.jp/collections/hoodies-jackets"
  ]
}
```

**Purpose:** Category discovery, hierarchy browsing
**Access Pattern:** Read on brand detail view, write on each scrape

---

#### 3. `scraping_intel.json` - Pattern Library (The Brain)
```json
{
  "brand_id": "jukuhara",
  "last_updated": "2025-11-15T12:30:00Z",

  "patterns": {
    "product_listing": {
      "primary": {
        "container_selector": "x-cell[prod-instock='true']",
        "name_selector": "h2.card-title a",
        "link_selector": "a[href^='/products/']",
        "image_selector": "img",

        "success_metrics": {
          "total_uses": 7,
          "successful_extractions": 7,
          "success_rate": 1.0,
          "total_products_found": 26
        },

        "worked_on_categories": [
          {
            "category_url": "https://jukuhara.jp/collections/t-shirts-compressions",
            "category_name": "T Shirts Compressions",
            "products_found": 10,
            "run_id": "run_20251115_123000"
          },
          {
            "category_url": "https://jukuhara.jp/collections/pants",
            "category_name": "Pants",
            "products_found": 3,
            "run_id": "run_20251115_123000"
          }
        ],

        "alternative_selectors": [
          "x-cell",
          "x-cell[class='']",
          ".card-title"
        ],

        "llm_analysis": "Looking at the three product examples..."
      },

      "alternatives": []
    },

    "navigation": {
      "menu_expansion_required": true,
      "menu_selectors": [
        "nav button[aria-expanded]",
        ".menu-toggle"
      ]
    },

    "load_more": {
      "has_load_more": false,
      "button_selector": null,
      "pagination_type": "none"
    },

    "modals": {
      "bypassed": [],
      "strategies": {}
    }
  },

  "lineages": {
    "common_lineages": [
      "section.product > x-grid.cards#ajaxSection > x-cell",
      "section.products.product > x-grid.cards > x-cell"
    ],
    "unique_lineages_count": 2
  }
}
```

**Purpose:** Reuse patterns on future scrapes, reduce LLM costs, improve speed
**Access Pattern:** Read on scrape start, write on scrape completion
**Note:** Stays as file (rarely queried, very flexible schema)

---

#### 4. `products.json` - Normalized Product Catalog
```json
{
  "brand_id": "jukuhara",
  "total_products": 26,
  "last_updated": "2025-11-15T12:30:00Z",
  "run_id": "run_20251115_123000",

  "products": [
    {
      "product_url": "https://jukuhara.jp/products/filipino-t-shirt-coming-soon",
      "product_id": "filipino-t-shirt-coming-soon",
      "product_name": "Filipino T Shirt Coming Soon",

      "images": [
        {
          "src": "https://jukuhara.jp/cdn/shop/files/filipinotee.png?v=1761799218&width=1280",
          "alt": "FILIPINO T SHIRT",
          "width": 319,
          "height": 414,
          "local_path": "data/brands/jukuhara/images/t_shirts/Filipino_T_Shirt_Coming_Soon_1.png"
        }
      ],

      "attributes": {
        "price": "",
        "availability": "Unknown"
      },

      "classifications": [
        {
          "type": "category",
          "url": "https://jukuhara.jp/collections/t-shirts-compressions",
          "name": "T Shirts Compressions",
          "hierarchy": ["T-Shirts & Compressions", "T-Shirts"]
        }
      ],

      "metadata": {
        "discovered_at": "2025-11-13T11:38:43.144066",
        "extraction_time": 1763051923.144095,
        "dom_lineage": "section.product > x-grid.cards#ajaxSection > x-cell",
        "run_id": "run_20251115_123000"
      }
    }
  ]
}
```

**Purpose:** Main queryable product data
**Access Pattern:** Read very frequently (all product browsing), write on each scrape
**Note:** Will move to database in Phase 2

---

#### 5. `scrape_runs/{run_id}.json` - Historical Run Record
```json
{
  "run_id": "run_20251115_123000",
  "brand_id": "jukuhara",
  "start_time": "2025-11-15T12:30:00Z",
  "end_time": "2025-11-15T12:32:18Z",
  "duration_seconds": 138.79,
  "status": "completed",

  "summary": {
    "total_categories": 7,
    "categories_processed": 7,
    "total_products": 26,
    "total_images_queued": 47,
    "images_downloaded": 37,
    "images_failed": 0
  },

  "categories_processed": [
    {
      "url": "https://jukuhara.jp/collections/t-shirts-compressions",
      "name": "T Shirts Compressions",
      "products_found": 10,
      "images_queued": 19,
      "pages_processed": 1,
      "extraction_time": 17.18,
      "pattern_used": "product_listing.primary"
    }
  ],

  "errors": [],

  "scraper_config": {
    "version": "1.0",
    "test_mode": false,
    "parallel_workers": 8
  }
}
```

**Purpose:** Scrape history, debugging, analytics
**Access Pattern:** Write once on completion, read for history views

---

#### 6. `/indexes/brands.json` - Global Brand Index
```json
{
  "brands": [
    {
      "brand_id": "jukuhara",
      "name": "Jukuhara",
      "domain": "jukuhara.jp",
      "total_products": 26,
      "last_scrape_at": "2025-11-15T12:30:00Z"
    },
    {
      "brand_id": "eckhauslatta",
      "name": "Eckhaus Latta",
      "domain": "eckhauslatta.com",
      "total_products": 150,
      "last_scrape_at": "2025-11-13T00:14:00Z"
    }
  ],
  "total_brands": 2,
  "last_updated": "2025-11-15T12:30:00Z"
}
```

**Purpose:** Fast brand list without scanning all directories
**Access Pattern:** Read frequently (brand listing), write on brand add/update

---

## Database Schema

### Phase 2: PostgreSQL/SQLite Migration

**What Moves to Database:**
- ✅ Brands (efficient lookup)
- ✅ Products (primary queryable data)
- ✅ Scrape runs (optional - can track in DB)

**What Stays as Files:**
- 📁 Scraping intelligence (`scraping_intel.json`) - rarely queried, flexible schema
- 📁 Navigation trees (`navigation.json`) - reference data
- 📁 Images - file system storage

---

### Table Schemas

#### 1. `brands` Table
```sql
CREATE TABLE brands (
    brand_id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    homepage_url TEXT NOT NULL,
    domain VARCHAR(255) NOT NULL,

    -- Status
    last_scrape_run_id VARCHAR(255),
    last_scrape_at TIMESTAMP,
    last_scrape_status VARCHAR(50),
    total_products INTEGER DEFAULT 0,
    total_categories INTEGER DEFAULT 0,

    -- Metadata
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_scrape_runs INTEGER DEFAULT 0,
    scraper_version VARCHAR(50),

    -- Paths to file-based data
    data_path TEXT,  -- e.g., "data/brands/jukuhara"

    -- Indexes
    CREATE INDEX idx_domain ON brands(domain);
    CREATE INDEX idx_last_scrape ON brands(last_scrape_at);
);
```

**Indexes:**
- Primary key: `brand_id`
- `domain` - for URL-based lookups
- `last_scrape_at` - for sorting by recency

---

#### 2. `products` Table
```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    product_url TEXT UNIQUE NOT NULL,  -- Natural key
    product_id VARCHAR(255) NOT NULL,
    product_name TEXT NOT NULL,
    brand_id VARCHAR(255) NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,

    -- Flexible attributes as JSONB
    attributes JSONB DEFAULT '{}',
    -- Examples: {"price": "$120", "availability": "in_stock", "color": "black"}

    -- Classifications as JSONB array
    classifications JSONB DEFAULT '[]',
    -- Example: [
    --   {"type": "category", "url": "...", "name": "T-Shirts", "hierarchy": [...]},
    --   {"type": "collection", "url": "...", "name": "JP Sounds"}
    -- ]

    -- Images as JSONB array
    images JSONB DEFAULT '[]',
    -- Example: [{"src": "...", "alt": "...", "local_path": "..."}]

    -- Metadata
    discovered_at TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    extraction_source TEXT,
    dom_lineage TEXT,
    run_id VARCHAR(255),

    -- Indexes
    CREATE INDEX idx_brand ON products(brand_id);
    CREATE INDEX idx_product_id ON products(product_id);
    CREATE INDEX idx_discovered ON products(discovered_at);

    -- JSONB indexes for fast queries
    CREATE INDEX idx_attributes_gin ON products USING GIN (attributes);
    CREATE INDEX idx_classifications_gin ON products USING GIN (classifications);
);
```

**Indexes:**
- Primary key: `id` (auto-increment)
- Unique: `product_url` (deduplication)
- `brand_id` - most common query filter
- `product_id` - for URL slug lookups
- GIN indexes on JSONB columns - enables fast attribute/classification queries

**Key Design:** JSONB columns provide schema flexibility while maintaining queryability

---

#### 3. `scrape_runs` Table
```sql
CREATE TABLE scrape_runs (
    run_id VARCHAR(255) PRIMARY KEY,
    brand_id VARCHAR(255) NOT NULL REFERENCES brands(brand_id) ON DELETE CASCADE,

    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds REAL,
    status VARCHAR(50) NOT NULL,  -- 'running', 'completed', 'failed'

    -- Summary stats as JSONB
    summary JSONB DEFAULT '{}',
    -- Example: {"total_categories": 7, "total_products": 26, "images_downloaded": 37}

    -- Detailed run data (optional - could stay as file)
    categories_processed JSONB DEFAULT '[]',
    errors JSONB DEFAULT '[]',
    scraper_config JSONB DEFAULT '{}',

    -- Path to full run details file
    file_path TEXT,

    -- Indexes
    CREATE INDEX idx_brand_run ON scrape_runs(brand_id, start_time DESC);
    CREATE INDEX idx_status ON scrape_runs(status);
);
```

**Purpose:** Track scraping history in database for quick queries
**Note:** Detailed run data can still live in files, referenced by `file_path`

---

### Database Query Examples

#### Query by brand
```sql
SELECT * FROM products WHERE brand_id = 'jukuhara';
```

#### Query by classification type
```sql
SELECT * FROM products
WHERE classifications @> '[{"type": "category"}]'::jsonb;
```

#### Query by specific classification URL
```sql
SELECT * FROM products
WHERE classifications @> '[{"url": "https://jukuhara.jp/collections/t-shirts"}]'::jsonb;
```

#### Query by attribute
```sql
-- Products with color = "black"
SELECT * FROM products
WHERE attributes @> '{"color": "black"}'::jsonb;

-- Products that have a color attribute (any value)
SELECT * FROM products
WHERE attributes ? 'color';
```

#### Combined filters
```sql
SELECT * FROM products
WHERE brand_id = 'jukuhara'
  AND classifications @> '[{"type": "category"}]'::jsonb
  AND attributes @> '{"availability": "in_stock"}'::jsonb;
```

#### Aggregation - count by classification
```sql
SELECT
    jsonb_array_elements(classifications)->>'name' as category_name,
    COUNT(*) as product_count
FROM products
WHERE brand_id = 'jukuhara'
  AND classifications @> '[{"type": "category"}]'::jsonb
GROUP BY category_name
ORDER BY product_count DESC;
```

---

## API Capabilities

### 1. Brand Management
- ✅ List all available brands
- ✅ Get single brand details (name, URL, status, product count)
- ✅ Get brand statistics (total products, categories, last scrape date)
- ✅ Add new brand for scraping
- ✅ Update brand information
- ✅ Delete brand (and all associated data)

### 2. Product Discovery & Browsing
- ✅ Browse all products (with pagination)
- ✅ Browse products by brand
- ✅ Browse products by category (using classification URL or name)
- ✅ Browse products by collection
- ✅ Browse products by hierarchy level (all "Tops" including subcategories)
- ✅ Get single product details
- ✅ Get product images

### 3. Category/Classification Navigation
- ✅ Get all classifications for a brand
- ✅ Get category hierarchy tree (nested structure with product counts)
- ✅ Get categories by type (just categories, or just collections)
- ✅ Get products in category (with option to include/exclude subcategories)
- ✅ Get category metadata (product count, name, URL)

### 4. Attribute Exploration
- ✅ Discover available attributes (what attributes exist for a brand)
- ✅ Get attribute values (all unique values for color, size, etc.)
- ✅ Get attribute statistics (how many products have each attribute)
- ✅ Get products with specific attribute
- ✅ Get attribute schema (data types, sample values)

### 5. Search & Filtering
- ✅ Full-text search (product names)
- ✅ Filter by single attribute
- ✅ Filter by multiple attributes (AND logic)
- ✅ Filter by classification
- ✅ Combined filters (brand + category + attributes + search)
- 🔲 Filter by price range (future - when prices are parsed)

### 6. Aggregations & Analytics
- ✅ Count products by category
- ✅ Count products by attribute value
- ✅ Group products by classification
- ✅ Get product distribution
- ✅ Get attribute value distribution
- 🔲 Time-based analytics (future)

### 7. Image Serving
- ✅ Serve local images
- ✅ Get image URL
- ✅ Get all images for product
- 🔲 Get thumbnail (future - different sizes)
- 🔲 Proxy external images (future)

### 8. Scraping Operations
- ✅ Trigger brand scrape
- ✅ Get scrape status
- ✅ Get scrape progress (real-time)
- ✅ Get scrape history
- ✅ Get scraping intelligence (patterns, navigation)
- 🔲 Cancel running scrape (future)
- ✅ Analyze brand (check if scrapable)

### 9. Data Export
- 🔲 Export products as CSV (future)
- 🔲 Export products as JSON (future)
- 🔲 Export category structure (future)
- 🔲 Export images as ZIP (future)

**Legend:**
- ✅ Required for MVP
- 🔲 Future enhancement

---

## API Endpoints

### Base URL
```
http://localhost:8081/api
```

---

### 1. Brands API

#### `GET /brands`
**Description:** List all brands with optional filtering and pagination

**Query Parameters:**
- `limit` (int, default: 50) - Results per page
- `offset` (int, default: 0) - Pagination offset
- `sort_by` (string) - Sort field: `name`, `last_scrape_at`, `total_products`
- `order` (string) - `asc` or `desc`

**Response:**
```json
{
  "brands": [
    {
      "brand_id": "jukuhara",
      "name": "Jukuhara",
      "homepage_url": "https://jukuhara.jp",
      "domain": "jukuhara.jp",
      "total_products": 26,
      "total_categories": 7,
      "last_scrape_at": "2025-11-15T12:30:00Z",
      "last_scrape_status": "completed"
    }
  ],
  "pagination": {
    "total": 10,
    "limit": 50,
    "offset": 0,
    "has_more": false
  }
}
```

---

#### `GET /brands/{brand_id}`
**Description:** Get detailed information about a specific brand

**Response:**
```json
{
  "brand_id": "jukuhara",
  "name": "Jukuhara",
  "homepage_url": "https://jukuhara.jp",
  "domain": "jukuhara.jp",
  "status": {
    "last_scrape_run_id": "run_20251115_123000",
    "last_scrape_at": "2025-11-15T12:30:00Z",
    "last_scrape_status": "completed",
    "total_products": 26,
    "total_categories": 7
  },
  "metadata": {
    "added_at": "2025-11-13T10:00:00Z",
    "total_scrape_runs": 3,
    "scraper_version": "1.0"
  }
}
```

---

#### `POST /brands`
**Description:** Add a new brand to the system

**Request Body:**
```json
{
  "name": "Brand Name",
  "homepage_url": "https://brand.com"
}
```

**Response:**
```json
{
  "success": true,
  "brand_id": "brand_name",
  "message": "Brand added successfully"
}
```

---

#### `PUT /brands/{brand_id}`
**Description:** Update brand information

**Request Body:**
```json
{
  "name": "Updated Name",
  "homepage_url": "https://newurl.com"
}
```

---

#### `DELETE /brands/{brand_id}`
**Description:** Delete brand and all associated data

**Response:**
```json
{
  "success": true,
  "message": "Brand and all associated data deleted"
}
```

---

### 2. Products API

#### `GET /products`
**Description:** Query products with flexible filters

**Query Parameters:**

**Basic Filters:**
- `brand_id` (string) - Filter by brand
- `limit` (int, default: 50) - Results per page
- `offset` (int, default: 0) - Pagination offset
- `sort_by` (string) - Sort field: `name`, `discovered_at`
- `order` (string) - `asc` or `desc`

**Classification Filters:**
- `classification_type` (string) - Filter by classification type: `category`, `collection`, etc.
- `classification_name` (string) - Filter by classification name
- `classification_url` (string) - Filter by exact classification URL
- `classification_hierarchy` (string) - Comma-separated path, e.g., `Clothing,Tops` (matches all under that path)

**Attribute Filters:**
- `attribute.<key>=<value>` - Filter by attribute value, e.g., `attribute.color=black`
- `has_attribute=<key>` - Filter products that have a specific attribute defined

**Search:**
- `search` (string) - Full-text search in product name

**Response Options:**
- `include_images` (bool, default: true) - Include image data
- `fields` (string) - Comma-separated list of fields to include (for reduced payload)

**Response:**
```json
{
  "products": [
    {
      "product_url": "https://jukuhara.jp/products/filipino-t-shirt",
      "product_id": "filipino-t-shirt",
      "product_name": "Filipino T Shirt Coming Soon",
      "brand_id": "jukuhara",
      "images": [
        {
          "src": "https://jukuhara.jp/cdn/.../image.jpg",
          "alt": "FILIPINO T SHIRT",
          "width": 319,
          "height": 414,
          "local_path": "data/brands/jukuhara/images/..."
        }
      ],
      "attributes": {
        "price": "",
        "availability": "Unknown"
      },
      "classifications": [
        {
          "type": "category",
          "url": "https://jukuhara.jp/collections/t-shirts",
          "name": "T-Shirts",
          "hierarchy": ["T-Shirts & Compressions", "T-Shirts"]
        }
      ],
      "metadata": {
        "discovered_at": "2025-11-13T11:38:43Z"
      }
    }
  ],
  "pagination": {
    "total": 156,
    "limit": 50,
    "offset": 0,
    "has_more": true
  },
  "applied_filters": {
    "brand_id": "jukuhara",
    "classification_type": "category"
  }
}
```

**Example Queries:**
```
# Get all products for a brand
GET /products?brand_id=jukuhara

# Get products in a specific category
GET /products?brand_id=jukuhara&classification_url=https://jukuhara.jp/collections/t-shirts

# Get black T-shirts
GET /products?brand_id=jukuhara&classification_name=T-Shirts&attribute.color=black

# Search for "hoodie"
GET /products?brand_id=jukuhara&search=hoodie

# Get all products under "Clothing > Tops" (including subcategories)
GET /products?brand_id=jukuhara&classification_hierarchy=Clothing,Tops
```

---

#### `GET /products/{product_url_encoded}`
**Description:** Get single product details

**Note:** `product_url` should be URL-encoded since it contains special characters

**Response:**
```json
{
  "product_url": "https://jukuhara.jp/products/filipino-t-shirt",
  "product_id": "filipino-t-shirt",
  "product_name": "Filipino T Shirt Coming Soon",
  "brand_id": "jukuhara",
  "images": [...],
  "attributes": {...},
  "classifications": [...],
  "metadata": {...}
}
```

---

#### `GET /products/aggregate`
**Description:** Aggregate products by classification or attribute

**Query Parameters:**
- `brand_id` (string, required) - Brand to aggregate
- `group_by` (string, required) - Field to group by:
  - `classification.category.name` - Group by category name
  - `classification.collection.name` - Group by collection name
  - `attribute.<key>` - Group by attribute value
- All filters from `/products` apply

**Response:**
```json
{
  "groups": [
    {
      "key": "T-Shirts",
      "count": 45,
      "sample_products": [...]  // First 3 products
    },
    {
      "key": "Pants",
      "count": 30,
      "sample_products": [...]
    }
  ],
  "total_groups": 12,
  "total_products": 156
}
```

**Example Queries:**
```
# Count products by category
GET /products/aggregate?brand_id=jukuhara&group_by=classification.category.name

# Count products by color
GET /products/aggregate?brand_id=jukuhara&group_by=attribute.color
```

---

### 3. Classifications API

#### `GET /brands/{brand_id}/classifications`
**Description:** Get all classifications for a brand

**Query Parameters:**
- `type` (string, optional) - Filter by classification type: `category`, `collection`, etc.

**Response:**
```json
{
  "brand_id": "jukuhara",
  "classifications": {
    "category": [
      {
        "name": "T-Shirts",
        "url": "https://jukuhara.jp/collections/t-shirts",
        "hierarchy": ["T-Shirts & Compressions", "T-Shirts"],
        "product_count": 10
      },
      {
        "name": "Pants",
        "url": "https://jukuhara.jp/collections/pants",
        "hierarchy": ["Bottoms", "Pants"],
        "product_count": 3
      }
    ],
    "collection": [
      {
        "name": "JP Sounds Capsule",
        "url": "https://jukuhara.jp/collections/jp-sounds",
        "product_count": 6
      }
    ]
  },
  "total_classifications": 13
}
```

---

#### `GET /brands/{brand_id}/categories/hierarchy`
**Description:** Get full category hierarchy tree with product counts

**Response:**
```json
{
  "brand_id": "jukuhara",
  "hierarchy": [
    {
      "name": "T-Shirts & Compressions",
      "url": null,
      "product_count": 11,
      "children": [
        {
          "name": "T-Shirts",
          "url": "https://jukuhara.jp/collections/t-shirts",
          "product_count": 10,
          "children": null
        },
        {
          "name": "Compressions",
          "url": "https://jukuhara.jp/collections/compressions",
          "product_count": 1,
          "children": null
        }
      ]
    },
    {
      "name": "Bottoms",
      "url": null,
      "product_count": 3,
      "children": [
        {
          "name": "Pants",
          "url": "https://jukuhara.jp/collections/pants",
          "product_count": 3,
          "children": null
        }
      ]
    }
  ]
}
```

---

### 4. Attributes API

#### `GET /brands/{brand_id}/attributes`
**Description:** Discover all attributes available for a brand

**Response:**
```json
{
  "brand_id": "jukuhara",
  "attributes": {
    "price": {
      "type": "string",
      "sample_values": ["", "$50", "$120"],
      "products_with_attribute": 26,
      "unique_values_count": 3
    },
    "availability": {
      "type": "string",
      "unique_values": ["Unknown", "In Stock", "Sold Out"],
      "products_with_attribute": 26,
      "unique_values_count": 3
    },
    "color": {
      "type": "string",
      "unique_values": ["black", "white", "red", "blue"],
      "products_with_attribute": 15,
      "unique_values_count": 4
    }
  },
  "total_attributes": 3
}
```

---

#### `GET /brands/{brand_id}/attributes/{attribute_key}/values`
**Description:** Get all unique values for a specific attribute with product counts

**Response:**
```json
{
  "attribute_key": "color",
  "values": [
    {
      "value": "black",
      "product_count": 8
    },
    {
      "value": "white",
      "product_count": 5
    },
    {
      "value": "red",
      "product_count": 2
    }
  ],
  "total_values": 3,
  "total_products_with_attribute": 15
}
```

---

### 5. Search API

#### `GET /products/search`
**Description:** Full-text search across products

**Query Parameters:**
- `q` (string, required) - Search query
- `brand_id` (string, optional) - Limit to specific brand
- All pagination and filter parameters from `/products` apply

**Response:**
```json
{
  "query": "hoodie",
  "products": [...],
  "pagination": {...},
  "total_results": 12
}
```

---

### 6. Scraping API

#### `POST /brands/{brand_id}/scrape`
**Description:** Start a scraping job for a brand

**Request Body (optional):**
```json
{
  "force_rescrape": false,  // Force even if recently scraped
  "parallel_workers": 8     // Number of parallel workers
}
```

**Response:**
```json
{
  "success": true,
  "run_id": "run_20251115_123000",
  "message": "Scraping job started",
  "estimated_time_seconds": 120
}
```

---

#### `GET /brands/{brand_id}/scrape/status`
**Description:** Get current scraping job status

**Response:**
```json
{
  "run_id": "run_20251115_123000",
  "brand_id": "jukuhara",
  "status": "running",  // 'running', 'completed', 'failed'
  "progress": {
    "categories_processed": 3,
    "total_categories": 7,
    "products_found": 15,
    "images_downloaded": 25,
    "current_action": "Processing category: Pants"
  },
  "start_time": "2025-11-15T12:30:00Z",
  "elapsed_seconds": 45
}
```

---

#### `GET /brands/{brand_id}/scrape/stream`
**Description:** Server-sent events stream for real-time scraping progress

**Response:** SSE stream
```
data: {"status": "running", "progress": {"categories_processed": 1, ...}}

data: {"status": "running", "progress": {"categories_processed": 2, ...}}

data: {"status": "completed", "summary": {...}}
```

---

#### `GET /brands/{brand_id}/scrape/history`
**Description:** Get all past scraping runs for a brand

**Query Parameters:**
- `limit` (int, default: 10)
- `offset` (int, default: 0)

**Response:**
```json
{
  "runs": [
    {
      "run_id": "run_20251115_123000",
      "start_time": "2025-11-15T12:30:00Z",
      "end_time": "2025-11-15T12:32:18Z",
      "duration_seconds": 138.79,
      "status": "completed",
      "summary": {
        "total_categories": 7,
        "total_products": 26,
        "images_downloaded": 37
      }
    }
  ],
  "pagination": {...}
}
```

---

#### `GET /brands/{brand_id}/scraping-intelligence`
**Description:** Get scraping patterns and intelligence for a brand

**Response:**
```json
{
  "brand_id": "jukuhara",
  "patterns": {
    "product_listing": {
      "primary": {
        "container_selector": "x-cell[prod-instock='true']",
        "success_rate": 1.0,
        "worked_on_categories": [...]
      }
    },
    "navigation": {...},
    "load_more": {...},
    "modals": {...}
  },
  "lineages": {...}
}
```

---

#### `POST /brands/analyze`
**Description:** Analyze a brand URL to check if it's scrapable

**Request Body:**
```json
{
  "url": "https://brand.com"
}
```

**Response:**
```json
{
  "success": true,
  "is_scrapable": true,
  "analysis": {
    "category_pages_found": 12,
    "categories": ["T-Shirts", "Pants", "Jackets", ...],
    "confidence": "high",
    "estimated_time_seconds": 60
  },
  "message": "Found 12 product category pages"
}
```

---

### 7. Images API

#### `GET /images/{brand_id}/{category_slug}/{filename}`
**Description:** Serve a product image from local storage

**Response:** Image file (JPEG, PNG, GIF, etc.)

**Example:**
```
GET /images/jukuhara/t_shirts/Filipino_T_Shirt_1.png
```

---

#### `GET /products/{product_url_encoded}/images`
**Description:** Get all images for a specific product

**Response:**
```json
{
  "product_url": "https://jukuhara.jp/products/filipino-t-shirt",
  "images": [
    {
      "src": "https://jukuhara.jp/cdn/.../image.jpg",
      "alt": "FILIPINO T SHIRT",
      "width": 319,
      "height": 414,
      "local_path": "data/brands/jukuhara/images/...",
      "local_url": "/images/jukuhara/t_shirts/Filipino_T_Shirt_1.png"
    }
  ]
}
```

---

## Implementation Status

### Phase 1: File Storage (Current)

| Component | Status | Notes |
|-----------|--------|-------|
| File structure setup | 🔲 TODO | Create `/data/brands/` directory structure |
| Brand file I/O | 🔲 TODO | Read/write `brand.json` |
| Products file I/O | 🔲 TODO | Read/write `products.json` |
| Navigation file I/O | 🔲 TODO | Read/write `navigation.json` |
| Scraping intel file I/O | 🔲 TODO | Read/write `scraping_intel.json` |
| Scrape runs file I/O | 🔲 TODO | Read/write run history |
| Brand index management | 🔲 TODO | Maintain `/indexes/brands.json` |
| Image storage organization | 🔲 TODO | Category-based folder structure |

### Phase 2: Database Migration

| Component | Status | Notes |
|-----------|--------|-------|
| Database schema creation | 🔲 TODO | PostgreSQL/SQLite tables |
| Migration scripts | 🔲 TODO | JSON → DB import |
| ORM setup (optional) | 🔲 TODO | SQLAlchemy or raw SQL |
| JSONB query optimization | 🔲 TODO | Test GIN indexes |

### API Endpoints - Brands

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/brands` | GET | 🔲 TODO | List brands |
| `/brands/{id}` | GET | 🔲 TODO | Get brand details |
| `/brands` | POST | 🔲 TODO | Add brand |
| `/brands/{id}` | PUT | 🔲 TODO | Update brand |
| `/brands/{id}` | DELETE | 🔲 TODO | Delete brand |

### API Endpoints - Products

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/products` | GET | 🔲 TODO | Query products with filters |
| `/products/{url}` | GET | 🔲 TODO | Get single product |
| `/products/aggregate` | GET | 🔲 TODO | Aggregations |
| `/products/search` | GET | 🔲 TODO | Full-text search |

### API Endpoints - Classifications

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/brands/{id}/classifications` | GET | 🔲 TODO | Get all classifications |
| `/brands/{id}/categories/hierarchy` | GET | 🔲 TODO | Category tree |

### API Endpoints - Attributes

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/brands/{id}/attributes` | GET | 🔲 TODO | Discover attributes |
| `/brands/{id}/attributes/{key}/values` | GET | 🔲 TODO | Get attribute values |

### API Endpoints - Scraping

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/brands/{id}/scrape` | POST | 🔲 TODO | Start scrape job |
| `/brands/{id}/scrape/status` | GET | 🔲 TODO | Get status |
| `/brands/{id}/scrape/stream` | GET | 🔲 TODO | SSE stream |
| `/brands/{id}/scrape/history` | GET | 🔲 TODO | Get history |
| `/brands/{id}/scraping-intelligence` | GET | 🔲 TODO | Get patterns |
| `/brands/analyze` | POST | 🔲 TODO | Analyze brand |

### API Endpoints - Images

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/images/{brand}/{category}/{file}` | GET | 🔲 TODO | Serve image |
| `/products/{url}/images` | GET | 🔲 TODO | Get product images |

---

## Migration Guide

### Phase 1 → Phase 2 Migration

#### Step 1: Set up database
```sql
-- Run schema creation scripts
psql -f create_tables.sql
```

#### Step 2: Import existing data
```python
# Migration script
python migrate_files_to_db.py --brand jukuhara
python migrate_files_to_db.py --all
```

#### Step 3: Update API layer
- Switch data source from files to database
- Keep scraping intelligence as files
- Maintain backward compatibility

#### Step 4: Verify
```bash
# Test all API endpoints
python test_api_endpoints.py
```

---

## Future Enhancements

### Phase 3: Cloud Migration
- Move database to RDS/Supabase
- Move images to S3/CDN
- Add caching layer (Redis)
- Add API rate limiting
- Add authentication/authorization

### Advanced Features
- Price tracking over time
- Product recommendations
- Similar product search
- Automated re-scraping schedules
- Webhook notifications
- GraphQL API (alternative to REST)

---

## Development Notes

### Adding Implementation Details

As you implement each component, add notes here:

```markdown
### Component: Brand File I/O
**Implemented:** 2025-11-XX
**File:** `data_manager.py`
**Key Functions:**
- `read_brand(brand_id)` - Read brand.json
- `write_brand(brand_id, data)` - Write brand.json
- `update_brand_status(brand_id, status)` - Update status

**Challenges:**
- Handling concurrent writes during scraping
- Atomic file updates

**Solutions:**
- Use file locking for concurrent access
- Write to temp file, then atomic rename
```

---

## Testing Checklist

### File Storage Tests
- [ ] Create brand directory structure
- [ ] Write/read brand.json
- [ ] Write/read products.json
- [ ] Write/read navigation.json
- [ ] Write/read scraping_intel.json
- [ ] Handle concurrent file access
- [ ] Test with multiple brands

### Database Tests
- [ ] Create tables successfully
- [ ] Insert brand records
- [ ] Insert product records with JSONB
- [ ] Query by brand_id
- [ ] Query by classification (JSONB)
- [ ] Query by attribute (JSONB)
- [ ] Test GIN index performance
- [ ] Test aggregation queries

### API Tests
- [ ] GET /brands - list brands
- [ ] GET /brands/{id} - get brand
- [ ] POST /brands - add brand
- [ ] GET /products - filter by brand
- [ ] GET /products - filter by classification
- [ ] GET /products - filter by attribute
- [ ] GET /products - combined filters
- [ ] GET /products/aggregate
- [ ] POST /brands/{id}/scrape
- [ ] GET /brands/{id}/scrape/status

---

**End of Document**

This is a living document. Update as implementation progresses.

---

## Implementation Progress Log

### 2025-11-15 - Storage Infrastructure Complete

**Completed:**
- ✅ Created /data/ directory structure
- ✅ Built DataManager class (data_manager.py)
  - File-based operations with atomic writes
  - Thread-safe file locking
  - Brand, products, navigation, scraping intelligence, scrape runs
  - Brand index management
- ✅ Created database schema SQL (create_database.sql)
  - SQLite compatible (PostgreSQL ready)
  - Brands, products, scrape_runs tables
  - JSONB columns for flexibility
- ✅ Built DatabaseManager class (db_manager.py)
  - SQLite implementation complete
  - Product querying with JSONB filters
  - Aggregation support
- ✅ Created unified Storage layer (storage.py)
  - Single interface for files/database/both
  - Seamless mode switching
  - Helper methods for classifications/attributes
- ✅ Built ScrapeResultsWriter class (scrape_results_writer.py)
  - Transforms raw scraper output to normalized format
  - Deduplicates products by URL
  - Extracts scraping intelligence
  - Saves all 5 JSON files

**Next Steps:**
- Integrate with Brand pipeline (production mode)
- Implement all API endpoints
- Test end-to-end flow

