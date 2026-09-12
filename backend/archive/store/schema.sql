CREATE TABLE IF NOT EXISTS brands (
  domain        TEXT PRIMARY KEY,
  homepage_url  TEXT NOT NULL,
  display_name  TEXT,
  notes         TEXT,
  state         TEXT NOT NULL DEFAULT 'new'   -- new|scoped|calibrating|active|degraded|gated|unreachable|needs_attention
);

CREATE TABLE IF NOT EXISTS scrape_plans (
  domain           TEXT PRIMARY KEY REFERENCES brands(domain),
  plan_json        TEXT NOT NULL,
  fingerprinted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  domain       TEXT NOT NULL REFERENCES brands(domain),
  mode         TEXT NOT NULL,                 -- full|delta|calibrate
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  exit_status  INTEGER,                       -- NULL while running/crashed
  coverage_json TEXT
);

CREATE TABLE IF NOT EXISTS products (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  domain        TEXT NOT NULL REFERENCES brands(domain),
  itemurl TEXT NOT NULL,
  product_code  TEXT,
  change_hint   TEXT,
  first_seen_run INTEGER NOT NULL REFERENCES runs(id),
  last_seen_run  INTEGER NOT NULL REFERENCES runs(id),
  current_json  TEXT NOT NULL,
  UNIQUE (domain, itemurl)
);

CREATE TABLE IF NOT EXISTS observations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id),
  run_id     INTEGER NOT NULL REFERENCES runs(id),
  price      REAL,
  full_price REAL,
  in_stock   INTEGER,
  size_availability TEXT
);

CREATE TABLE IF NOT EXISTS recipe_books (
  domain     TEXT PRIMARY KEY REFERENCES brands(domain),
  book_json  TEXT NOT NULL,
  learned_at TEXT NOT NULL
);

-- One archived photograph. `url` is where the shop served it, `stored_url` where we
-- serve it from now. The second is the one that means anything anywhere else: the
-- first can stop resolving, and local_path names a directory on one laptop.
CREATE TABLE IF NOT EXISTS images (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id   INTEGER NOT NULL REFERENCES products(id),
  url          TEXT NOT NULL,
  local_path   TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  stored_url   TEXT,
  UNIQUE (product_id, url)
);

CREATE TABLE IF NOT EXISTS field_evidence (
  domain      TEXT NOT NULL REFERENCES brands(domain),
  field       TEXT NOT NULL,
  source      TEXT NOT NULL,                 -- channel|page_rules|page_rendered|page_llm
  examined    INTEGER NOT NULL,              -- products this source was consulted on
  found       INTEGER NOT NULL,              -- of those, how many yielded a value
  run_id      INTEGER NOT NULL REFERENCES runs(id),
  searched_at TEXT NOT NULL,
  PRIMARY KEY (domain, field, source)
);

-- The control plane: what to scrape and when. Editable while the daemon runs, and
-- untouched by a code deploy — the point of separating the two.
CREATE TABLE IF NOT EXISTS schedule (
  domain          TEXT PRIMARY KEY REFERENCES brands(domain),
  enabled         INTEGER NOT NULL DEFAULT 1,
  cadence_seconds INTEGER NOT NULL DEFAULT 86400,
  next_due        TEXT NOT NULL,
  claimed_by      TEXT,                       -- worker id, NULL when free
  claimed_at      TEXT
);

CREATE TABLE IF NOT EXISTS daemon_control (
  id           INTEGER PRIMARY KEY CHECK (id = 1),
  stop         INTEGER NOT NULL DEFAULT 0,
  code_version TEXT
);

CREATE TABLE IF NOT EXISTS scorecards (
  run_id    INTEGER PRIMARY KEY REFERENCES runs(id),
  domain    TEXT NOT NULL,
  card_json TEXT NOT NULL,
  scored_at TEXT NOT NULL
);

-- Every request, so constant scraping produces observations and not just products:
-- which hosts degrade as our rate rises, which answer 403 rather than 429 (a WAF
-- deciding we are a bot, a different thing entirely), and whether a block is volume,
-- time of day, or permanent.
CREATE TABLE IF NOT EXISTS requests (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  host        TEXT NOT NULL,
  status      INTEGER,
  latency_ms  INTEGER,
  retry_after INTEGER,
  at          TEXT NOT NULL
);

-- Which extraction code last wrote this brand's records, so a mapper change can force
-- a full run instead of leaving old rows behind a delta.
CREATE TABLE IF NOT EXISTS extraction_versions (
  domain   TEXT PRIMARY KEY REFERENCES brands(domain),
  version  TEXT NOT NULL,
  seen_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_host ON requests(host, id);
CREATE INDEX IF NOT EXISTS idx_schedule_due ON schedule(enabled, next_due);

CREATE INDEX IF NOT EXISTS idx_products_domain ON products(domain);
CREATE INDEX IF NOT EXISTS idx_observations_product ON observations(product_id);
CREATE INDEX IF NOT EXISTS idx_runs_domain ON runs(domain, id);
