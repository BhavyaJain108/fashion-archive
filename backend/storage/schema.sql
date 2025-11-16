-- Premium Scraper Database Schema
-- Supports both PostgreSQL and SQLite
--
-- For PostgreSQL: psql -d database_name -f create_database.sql
-- For SQLite: sqlite3 database.db < create_database.sql

-- =============================================================================
-- BRANDS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS brands (
    brand_id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    homepage_url TEXT NOT NULL,
    domain VARCHAR(255) NOT NULL,

    -- Status fields
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

    -- Path to file-based data
    data_path TEXT
);

-- Indexes for brands
CREATE INDEX IF NOT EXISTS idx_brands_domain ON brands(domain);
CREATE INDEX IF NOT EXISTS idx_brands_last_scrape ON brands(last_scrape_at);

-- =============================================================================
-- PRODUCTS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- SQLite: AUTOINCREMENT, PostgreSQL: SERIAL
    product_url TEXT UNIQUE NOT NULL,
    product_id VARCHAR(255) NOT NULL,
    product_name TEXT NOT NULL,
    brand_id VARCHAR(255) NOT NULL,

    -- Flexible attributes (JSON/JSONB)
    attributes TEXT DEFAULT '{}',  -- JSON string for SQLite, JSONB for PostgreSQL

    -- Classifications (JSON/JSONB array)
    classifications TEXT DEFAULT '[]',  -- JSON string for SQLite, JSONB for PostgreSQL

    -- Images (JSON/JSONB array)
    images TEXT DEFAULT '[]',  -- JSON string for SQLite, JSONB for PostgreSQL

    -- Metadata
    discovered_at TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    extraction_source TEXT,
    dom_lineage TEXT,
    run_id VARCHAR(255),

    -- Foreign key
    FOREIGN KEY (brand_id) REFERENCES brands(brand_id) ON DELETE CASCADE
);

-- Indexes for products
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand_id);
CREATE INDEX IF NOT EXISTS idx_products_product_id ON products(product_id);
CREATE INDEX IF NOT EXISTS idx_products_discovered ON products(discovered_at);

-- Note: For PostgreSQL, you would also create GIN indexes:
-- CREATE INDEX idx_products_attributes_gin ON products USING GIN (attributes jsonb_path_ops);
-- CREATE INDEX idx_products_classifications_gin ON products USING GIN (classifications jsonb_path_ops);

-- =============================================================================
-- SCRAPE RUNS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS scrape_runs (
    run_id VARCHAR(255) PRIMARY KEY,
    brand_id VARCHAR(255) NOT NULL,

    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds REAL,
    status VARCHAR(50) NOT NULL,  -- 'running', 'completed', 'failed'

    -- Summary stats (JSON/JSONB)
    summary TEXT DEFAULT '{}',  -- JSON string for SQLite, JSONB for PostgreSQL

    -- Detailed run data (JSON/JSONB)
    categories_processed TEXT DEFAULT '[]',  -- JSON string for SQLite, JSONB for PostgreSQL
    errors TEXT DEFAULT '[]',  -- JSON string for SQLite, JSONB for PostgreSQL
    scraper_config TEXT DEFAULT '{}',  -- JSON string for SQLite, JSONB for PostgreSQL

    -- Path to full run details file
    file_path TEXT,

    -- Foreign key
    FOREIGN KEY (brand_id) REFERENCES brands(brand_id) ON DELETE CASCADE
);

-- Indexes for scrape_runs
CREATE INDEX IF NOT EXISTS idx_scrape_runs_brand ON scrape_runs(brand_id);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_start_time ON scrape_runs(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_status ON scrape_runs(status);

-- =============================================================================
-- PostgreSQL-specific optimizations (comment out for SQLite)
-- =============================================================================

-- Uncomment these for PostgreSQL only:
--
-- -- Convert TEXT columns to JSONB for better performance
-- ALTER TABLE products ALTER COLUMN attributes TYPE JSONB USING attributes::jsonb;
-- ALTER TABLE products ALTER COLUMN classifications TYPE JSONB USING classifications::jsonb;
-- ALTER TABLE products ALTER COLUMN images TYPE JSONB USING images::jsonb;
--
-- ALTER TABLE scrape_runs ALTER COLUMN summary TYPE JSONB USING summary::jsonb;
-- ALTER TABLE scrape_runs ALTER COLUMN categories_processed TYPE JSONB USING categories_processed::jsonb;
-- ALTER TABLE scrape_runs ALTER COLUMN errors TYPE JSONB USING errors::jsonb;
-- ALTER TABLE scrape_runs ALTER COLUMN scraper_config TYPE JSONB USING scraper_config::jsonb;
--
-- -- GIN indexes for JSONB columns
-- CREATE INDEX idx_products_attributes_gin ON products USING GIN (attributes jsonb_path_ops);
-- CREATE INDEX idx_products_classifications_gin ON products USING GIN (classifications jsonb_path_ops);
--
-- -- Change AUTOINCREMENT to SERIAL
-- ALTER TABLE products ALTER COLUMN id SET DATA TYPE SERIAL;
