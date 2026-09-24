-- The product catalogue, one row per product. Replaces catalogue/<domain>.json,
-- images/<domain>.json, search/<domain>.json and history/<domain>/<run>.json in
-- R2, which held every product of a brand in one object and so had to be read
-- and rewritten whole for every product (psylos1: 35 MB, 1.3 s a read). Runs,
-- plans and logs stay in R2; they are the scraper's control plane, not rows.
--
-- Idempotent, applied at every boot like the other schema files.

CREATE TABLE IF NOT EXISTS products (
    brand             text NOT NULL,                 -- roster domain, e.g. bode.com
    itemurl           text NOT NULL,
    handle            text NOT NULL,                 -- last path segment; the page's URL
    product_code      text,
    title             text NOT NULL DEFAULT '',
    description       text,
    price             double precision,
    full_price        double precision,
    currency          text,
    in_stock          boolean,
    size_info         text,
    size_availability text,
    size_stock_counts text,
    color_info        text,
    material_info     text,
    variant_info      text,
    categories        text[] NOT NULL DEFAULT '{}',  -- category1..10, in order
    main_image_url    text,
    all_images        jsonb NOT NULL DEFAULT '[]',   -- parsed; the record keeps the shop's string
    additional_tags   text,
    specifications    text,
    -- derived at write time so the shop front is one query (backend/archive/storefront.py)
    shop_group        text NOT NULL DEFAULT 'Everything else',
    shop_bucket       text NOT NULL DEFAULT 'Everything else',
    shop_colour       text,
    -- the record as the connector produced it, minus `raw`, returned verbatim to
    -- every reader that used to get it from the JSON object
    record            jsonb NOT NULL,
    -- run stamps, exactly as before
    change_hint       text,
    first_seen_run    text NOT NULL,
    last_seen_run     text NOT NULL,
    last_covered_run  text,                          -- NULL until a run earns coverage
    updated_at        timestamptz NOT NULL DEFAULT now(),
    -- title, description, material, colour, code, categories, tags; set by the upsert
    -- (array_to_string is not immutable, so it cannot be a generated column)
    search            tsvector,
    PRIMARY KEY (brand, itemurl)
);
CREATE INDEX IF NOT EXISTS products_handle ON products (brand, handle);
CREATE INDEX IF NOT EXISTS products_live ON products (brand, last_covered_run);
CREATE INDEX IF NOT EXISTS products_seen ON products (brand, last_seen_run);
CREATE INDEX IF NOT EXISTS products_shop ON products (shop_group, shop_bucket, shop_colour);
CREATE INDEX IF NOT EXISTS products_price ON products (price);
CREATE INDEX IF NOT EXISTS products_first_seen ON products (first_seen_run DESC);
CREATE INDEX IF NOT EXISTS products_search ON products USING gin (search);

-- The connector's untouched payload. Its own table so no listing carries it:
-- it is 20–75% of every row's bytes and only a re-mapping audit reads it.
CREATE TABLE IF NOT EXISTS product_raw (
    brand   text NOT NULL,
    itemurl text NOT NULL,
    raw     jsonb NOT NULL,
    PRIMARY KEY (brand, itemurl),
    FOREIGN KEY (brand, itemurl) REFERENCES products (brand, itemurl) ON DELETE CASCADE
);

-- What changed, per run: the watched fields each time one of them moved.
CREATE TABLE IF NOT EXISTS product_observations (
    id                bigserial PRIMARY KEY,
    brand             text NOT NULL,
    itemurl           text NOT NULL,
    run_id            text NOT NULL,
    observed_at       timestamptz NOT NULL DEFAULT now(),
    price             double precision,
    full_price        double precision,
    in_stock          boolean,
    size_availability text
);
CREATE INDEX IF NOT EXISTS observations_product ON product_observations (brand, itemurl, observed_at DESC);
CREATE INDEX IF NOT EXISTS observations_run ON product_observations (brand, run_id);

-- Photographs: what the shop published for each product, and where we keep a copy.
CREATE TABLE IF NOT EXISTS product_images (
    brand        text NOT NULL,
    itemurl      text NOT NULL,
    url          text NOT NULL,                     -- the shop's URL
    content_hash text,
    stored_url   text,                              -- ours, once archived
    misses       integer NOT NULL DEFAULT 0,        -- fetch failures; given up after 3
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (brand, itemurl, url)
);
CREATE INDEX IF NOT EXISTS product_images_stored ON product_images (brand) WHERE stored_url IS NOT NULL;

-- One row per brand: which run its live products belong to, and the counts the
-- sidebar shows. Written when a run finishes; read instead of listing runs.
CREATE TABLE IF NOT EXISTS catalogue_brands (
    brand         text PRIMARY KEY,
    live_run      text,
    products      integer NOT NULL DEFAULT 0,
    live_products integer NOT NULL DEFAULT 0,
    images        integer NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now()
);
