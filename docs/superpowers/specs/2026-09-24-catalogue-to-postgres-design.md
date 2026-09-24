# Catalogue storage: from one JSON object per brand to Postgres

Status: built 2026-09-24 (phases 0–3 in one change; phase 4 pending a scrape pass).
Owner: Bhavya. The section "As built" at the end records where the build
departed from this design.

## The problem, measured

The product catalogue is stored in R2 as **one JSON object per brand**:
`catalogue/<domain>.json`, holding every product the brand has ever shown,
each with its full record (including the connector's `raw` payload) and its
run stamps. Reading one product means downloading the brand; writing one
product means re-uploading the brand.

| | |
|---|---|
| Brand catalogue objects | 38 |
| Total bytes | 164.9 MB |
| Product rows | 25,305 (23,846 live) |
| Largest object | psylos1.com, 35.2 MB, 8,134 rows, 1.3 s per GET |
| Next three | thesupermade 24.9 MB, bode 16.8 MB, staud 16.4 MB |
| Bytes per row | 1.6–10.9 KB, of which `raw` is 20–75% |
| Image index objects (`images/<domain>.json`) | 36, up to 19 MB (psylos1) |
| Observation objects (`history/<domain>/<run>.json`) | 308 |
| Run objects (`runs/…`) | 894 |

What that costs today:

- **The shop front** needs everything at once, so the API builds an in-memory
  index at boot by reading all 38 objects (50–90 s) and refreshes it every 30
  minutes. Before that finishes, the page says "Building the shop front".
- **Opening a product** used to download the brand's object to pick one row
  out. It now reads the in-memory index instead, which is a workaround, not a
  fix: a second API instance, a restart, or a deploy pays the 90 s again.
- **The scraper** buffers a whole brand in memory and rewrites the 35 MB object
  at the end of a pass. A run killed mid-pass loses the pass. The image index
  is rewritten whole per flush (`FLUSH_EVERY = 200` photographs).
- **Search** downloads `search/<domain>.json` for every brand and does a
  substring scan in Python.
- **Two writers can't share a brand.** A stale buffer once put an unstamped
  copy back over a finished run (the "missing coverage stamps" incident noted
  in `catalog.py`). The object store has no row-level writes, so this class of
  bug can only be avoided by discipline.

None of this is a bandwidth or storage problem: 165 MB is small. It is a
**shape** problem. Rows are being stored as one blob.

## Options considered

| Option | Point read | List / filter / facets | Concurrent writes | Verdict |
|---|---|---|---|---|
| **A. Keep R2, one object per product** | fixed | still needs a full index somewhere; 25k GETs to build it; facets impossible without it | fixed | Half a fix. Moves the problem from reads to listing. |
| **B. Parquet/DuckDB on R2** | slow (column scan) | good for analytics, awkward for a live shop front | none (rewrite files) | Wrong tool for a read-write catalogue. |
| **C. SQLite file in R2** | needs the whole file | ok once downloaded | none | Same shape problem, smaller. |
| **D. Postgres (already provisioned)** | index lookup, ms | SQL: WHERE / ORDER / LIMIT / GROUP BY, full-text search built in | row-level, transactional | **Recommended.** |

Postgres is already there: `fashion-archive-db` on Render (basic-256mb, Oregon,
same region as the API and the scraper), a pool in `backend/auth/db.py`,
and `schema.sql` files applied at boot. Auth, favourites, albums, shares and
rate limits already live in it. The catalogue is the one thing that doesn't.

## Target

R2 keeps what is genuinely a blob: **photographs**, **run logs**, the
scraper's **plans and recipe books**, `fleet.json`. Everything that is a row
moves to Postgres.

### Schema (new file `backend/archive/schema.sql`, applied at boot like the others)

```sql
CREATE TABLE IF NOT EXISTS products (
    brand           text NOT NULL,            -- roster domain, e.g. bode.com
    itemurl         text NOT NULL,
    handle          text NOT NULL,            -- last path segment; the page's URL
    product_code    text,
    title           text NOT NULL,
    description     text,
    price           numeric,
    full_price      numeric,
    currency        text,
    in_stock        boolean,
    size_info       text,
    size_availability text,
    size_stock_counts text,
    color_info      text,
    material_info   text,
    variant_info    text,
    categories      text[] NOT NULL DEFAULT '{}',   -- category1..10, in order
    main_image_url  text,
    all_images      jsonb NOT NULL DEFAULT '[]',    -- parsed, not a string
    additional_tags text,
    specifications  text,
    -- derived at write time so the shop front is one query (see storefront.py)
    shop_group      text NOT NULL,            -- Clothing / Shoes / Bags / Accessories / Everything else
    shop_bucket     text NOT NULL,            -- Tees, Jackets & coats, …
    shop_colour     text,                     -- one of twelve, or NULL
    -- run stamps, exactly as today
    change_hint     text,
    first_seen_run  text NOT NULL,
    last_seen_run   text NOT NULL,
    last_covered_run text,                    -- NULL until the run earns coverage
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (brand, itemurl)
);
CREATE UNIQUE INDEX IF NOT EXISTS products_handle ON products (brand, handle);
CREATE INDEX IF NOT EXISTS products_live ON products (brand, last_covered_run);
CREATE INDEX IF NOT EXISTS products_shop ON products (shop_group, shop_bucket, shop_colour);
CREATE INDEX IF NOT EXISTS products_price ON products (price);
CREATE INDEX IF NOT EXISTS products_first_seen ON products (first_seen_run DESC);
-- search: title, description, material, colour, categories, tags
ALTER TABLE products ADD COLUMN IF NOT EXISTS search tsvector
    GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(description,'') || ' ' ||
                    coalesce(material_info,'') || ' ' || coalesce(color_info,'') || ' ' ||
                    array_to_string(categories,' ') || ' ' || coalesce(additional_tags,''))
    ) STORED;
CREATE INDEX IF NOT EXISTS products_search ON products USING gin (search);

-- The connector's untouched payload. Its own table so no listing ever carries
-- it: it is 20–75% of every row's bytes and nothing but a re-mapping reads it.
CREATE TABLE IF NOT EXISTS product_raw (
    brand   text NOT NULL,
    itemurl text NOT NULL,
    raw     jsonb NOT NULL,
    PRIMARY KEY (brand, itemurl),
    FOREIGN KEY (brand, itemurl) REFERENCES products (brand, itemurl) ON DELETE CASCADE
);

-- What changed, per run. Replaces history/<domain>/<run>.json.
CREATE TABLE IF NOT EXISTS product_observations (
    id          bigserial PRIMARY KEY,
    brand       text NOT NULL,
    itemurl     text NOT NULL,
    run_id      text NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    price       numeric,
    full_price  numeric,
    in_stock    boolean,
    size_availability text
);
CREATE INDEX IF NOT EXISTS observations_product ON product_observations (brand, itemurl, observed_at DESC);
CREATE INDEX IF NOT EXISTS observations_run ON product_observations (brand, run_id);

-- Photographs the archive holds. Replaces images/<domain>.json.
CREATE TABLE IF NOT EXISTS product_images (
    brand     text NOT NULL,
    itemurl   text NOT NULL,
    source_url text NOT NULL,                 -- the shop's URL
    stored_key text,                          -- R2 key once archived, NULL if missed
    bytes     integer,
    status    text NOT NULL DEFAULT 'stored', -- stored | missed
    stored_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (brand, itemurl, source_url)
);
```

Runs, plans, scorecards, evidence, recommendations, attention, progress and
host stats **stay in R2 for this migration.** They are the scraper's control
plane, are small, and are read by the dev page only. Moving them is a second
migration, if ever.

### The adapter

`backend/archive/store/catalog.py` keeps its public interface. The product,
observation and image methods (listed in the plan below) get a Postgres
implementation; the run/plan/etc. methods keep calling the object store. A
`CATALOG_BACKEND` environment variable selects `r2`, `pg` or `both`
(dual-write, read from `pg`). Default stays `r2` until Phase 3 flips it.

The 20 test files that build a `Catalog(DirectoryObjectStore(...))` keep
working unchanged in `r2` mode. New tests for the `pg` path use the throwaway
Postgres fixtures in `tests/db/conftest.py`.

### What each reader becomes

| Today | After |
|---|---|
| `current_products(domain)` — GET 35 MB, filter in Python | `SELECT … WHERE brand=%s AND last_covered_run = (latest covered run)` |
| Shop front: in-memory index, 90 s warm, 30 min TTL | One query: `WHERE` on group/bucket/brand/colour/sale, `ORDER BY` on first_seen/price/discount, `LIMIT/OFFSET`; facets via three `GROUP BY` queries. No warm-up, no index, no `WARMING` state. |
| Product page: index scan | `SELECT … WHERE brand=%s AND handle=%s` |
| `search_products` — GET every `search/<domain>.json`, substring scan | `WHERE search @@ plainto_tsquery('simple', %s)` |
| `product_history(domain)` — derived from run stamps in the blob | the three run-stamp columns, plus `product_observations` for the price line |
| `archived_images(domain)` — GET 19 MB image index | `SELECT source_url, stored_key FROM product_images WHERE brand=%s AND status='stored'` |
| Dev page `products_at_run`, `catalogue_changes` | `WHERE last_seen_run = %s` / `ORDER BY updated_at DESC` |

### What each writer becomes

| Today | After |
|---|---|
| `record_product` — mutate the in-memory blob, flush every 200 | `INSERT … ON CONFLICT (brand,itemurl) DO UPDATE`, batched with `executemany` every `FLUSH_EVERY`; `raw` into `product_raw` in the same transaction; a changed watched field appends to `product_observations` |
| `finalize_run` — walk the blob, stamp `last_covered_run`, rewrite 35 MB | `UPDATE products SET last_covered_run=%s WHERE brand=%s AND last_seen_run=%s` — one statement |
| `record_image` — rewrite the whole image index | `INSERT … ON CONFLICT DO UPDATE` per photograph, no buffer, no lock |
| `_write_search_index` | gone; the `search` column is generated |
| `_refresh_meta` (`catalogue/<domain>.meta.json`) | `SELECT count(*) …`; `fleet.json` keeps being written for the dev page until it reads the DB |

The stale-buffer hazard disappears with the buffer.

## Plan, in phases

Each phase is its own commit (or two), ships to master, and is verified
before the next starts. Nothing is deleted from R2 in any phase.

**Phase 0 — schema and adapter skeleton.** `backend/archive/schema.sql`,
applied at boot beside the others. `CATALOG_BACKEND` read in one place. The
Postgres implementations of the product / observation / image methods, with
tests against the throwaway DB. `r2` remains the default; nothing observable
changes. Exit: unit suite green, `pytest tests/db` green, boot on Render
applies the schema (check the log).

**Phase 1 — backfill.** `scripts/backfill_catalogue.py`: for each brand, read
`catalogue/<domain>.json`, `images/<domain>.json`, every
`history/<domain>/*.json`, and upsert. Idempotent; re-runnable; prints a
per-brand reconciliation. Exit criteria, printed by the script and checked by
hand: **25,305 product rows, 23,846 with `last_covered_run` set, per-brand
counts equal to the R2 objects, `product_raw` count equal to `products`.**
Run it once against production from a laptop (`DATABASE_URL` from Render).

**Phase 2 — prove the writes without a scrape.** Run the existing catalogue
tests (`test_catalog`, `test_end_to_end`, `test_flush_safety`,
`test_stale_buffer`, `test_images`, `test_image_concurrency`,
`test_truncated_images`, `test_upload_budget`) against the `pg` backend using
the throwaway Postgres fixtures. They already drive `record_product`,
`finalize_run`, `record_image` and the readers end to end. Exit: green on
both backends. `both` mode exists as a rollback aid, not a gate.

**Phase 3 — cut reads over.** Flip the API to `CATALOG_BACKEND=pg`. Replace
`storefront.get/build/warm` with SQL (keep `classify`, `colour`, `tile`,
`slim`, `SORTS` and their tests; they now run at write time and in the
backfill). Delete the in-memory index and the `WARMING` state on both ends.
Exit: `/brands` answers cold in under 300 ms; product page under 100 ms; the
storefront unit tests are rewritten against the DB fixtures and green; a
manual click-through of shop, product, search, dev page.

**Phase 4 — stop writing the blobs.** Scraper to `CATALOG_BACKEND=pg`. Remove
the `catalogue/`, `search/`, `history/`, `images/` writers and the `.meta.json`
refresh; keep `fleet.json` until the dev page reads counts from the DB (a
one-line change in `status_rows`). R2 objects stay as an archive; a note in
`docs/` says they are frozen as of the cut-over date. Exit: one scheduled
pass completes with no R2 catalogue writes in the logs.

## Sizing and risks

- **Database size.** 165 MB of JSON becomes roughly 60 MB in `products` plus
  ~60 MB in `product_raw` plus indexes; call it 150–200 MB. The basic-256mb
  plan's *storage* is 1 GB; fine. Its *memory* is 256 MB, which is enough for
  index lookups but not for a `GROUP BY` over 25k rows a hundred times a
  second — and it doesn't need to be. Facet queries are three small
  aggregates per page load. If the shop gets traffic, upgrade the plan; do
  not add a cache first.
- **Connections.** The scraper's image pass runs threads; give it its own
  small pool (`min 1, max 4`) rather than sharing the API's.
- **The `raw` column.** Keep it, in its own table. It is what lets a field
  mapping be re-derived without a re-scrape, which is the whole reason it was
  stored.
- **Currency and visibility rules** added on 2026-09-24 (`_shop_products`,
  `has_photograph`, visitor currency) must be re-expressed as `WHERE` clauses,
  not lost in the port. Grep for them before Phase 3.
- **Two agents.** Another session has been committing to `storefront.py` and
  `archive_routes.py` the same day. Whoever takes this should announce it in
  the commit history first (a Phase 0 commit) so the other stops touching the
  index code.
- **Rollback.** Every phase is a flag flip back to `r2`. Nothing in R2 is
  changed until Phase 4, and even then only writes stop.

## Effort

Phase 0: half a day. Phase 1: half a day plus one run. Phase 2: one scheduled
pass (a day of calendar time, an hour of work). Phase 3: a day. Phase 4: an
hour. About three working days of agent time, spread over a week of
calendar time because of the passes in between.

## What not to do

- Don't move runs, plans, scorecards, evidence into Postgres in this
  migration. They're small, they work, and the dev page is the only reader.
- Don't introduce an ORM. `psycopg` with SQL strings is what the rest of the
  backend uses.
- Don't keep the in-memory index "as a cache" after Phase 3. It is the thing
  being removed.
- Don't split R2 into one object per product. It fixes the point read and
  breaks listing; see Option A.

## As built (2026-09-24)

- **`products.record jsonb`** holds the connector's record minus `raw`, returned
  verbatim to every reader that used to get it from the JSON object, so no
  reader had to change. The typed columns beside it are what queries filter
  and sort on. This doubles some bytes; it is what made the port safe.
- **`search`** is a plain `tsvector` column set by the upsert, not a generated
  column: `array_to_string` is not immutable and Postgres refuses it in a
  generation expression.
- **`product_images`** keeps the object's row shape (`url`, `content_hash`,
  `stored_url`, `misses`) rather than the `status` column sketched above, so
  the inherited image-queue logic works unchanged.
- **`catalogue_brands`** (`live_run`, counts) replaces listing runs to find the
  live run and replaces `.meta.json` for the counts; `fleet.json` and the
  `.meta.json` objects are still written so the dev page needs no change yet.
- **No `both` mode.** Rollback is `CATALOG_BACKEND=r2`, which reads the R2
  objects as they were at cut-over.
- **Backfill runs inside the API** at boot when the table is empty
  (`backfill_if_empty`), and as `python -m backend.archive.store.backfill`.
  The shop answers 503 WARMING until it finishes.
- **The scrape-pass gate was dropped** on Bhavya's call: the write path is
  proven by `tests/db/test_pg_catalog.py`, which drives record → finalize →
  read, the image queue, the backfill reconciliation and the SQL shop front
  against a real Postgres.
- **Local development:** the Homebrew cluster's databases were SQL_ASCII and
  refused `\u00a0` inside jsonb; `fa_dev` and `fashion_archive_test` were
  recreated as UTF-8 (the old one is kept as `fa_dev_ascii`).
