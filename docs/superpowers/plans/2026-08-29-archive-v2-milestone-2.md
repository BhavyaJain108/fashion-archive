# Archive v2 — Milestone 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Same conventions as milestone 1 (`2026-08-27-archive-v2-milestone-1.md`): TDD, hermetic tests via httpx.MockTransport, ruff/format per task, one commit per task. Global Constraints from the M1 plan apply verbatim.

**Goal:** Activate the 8 `needs_attention` brands: extend the free HTTP lane (WooCommerce Store API; sitemap discovery paired with JSON-LD structured fetch), then add the browser transport with stealth for the enterprise tail.

**Re-scope vs spec §7:** The live fleet run of 2026-08-29 showed all previously bot-challenged Shopify stores are now open at T0, so browser×bulk_json is a planner rung we keep for drift, not the milestone's center. The e0005 recipes port is DEFERRED to milestone 3 pending field-fill measurements from the structured lane — JSON-LD may suffice for most non-Shopify brands.

**Architecture recap:** new connectors slot in behind the existing `Connector` protocol; new capability facts extend `Capability`; new rungs extend `compose_plan`'s ladder; nothing else changes.

## M2a — the free lane extension (no browser)

### Task 1: Capability facts + deeper fingerprint
- `Capability` gains `woo_api: bool = False` and `ldjson_product: bool = False`.
- `fingerprint.probe` gains two conditional steps (only when `bulk_json` is closed and the site is not gated/challenged — open Shopify pays nothing extra):
  - if platform is woocommerce/wordpress (or unknown): GET `/wp-json/wc/store/v1/products?per_page=1` (fall back `/wp-json/wc/store/products?per_page=1`) → `woo_api=True` on HTTP 200 + JSON list.
  - if a sitemap exists: walk it via `SitemapConnector`, GET the FIRST product URL, `ldjson_product=True` iff the HTML contains an `application/ld+json` block whose `@type` includes `Product`.
- Tests: woo detected; ldjson detected via mocked sitemap+product page; open-Shopify probe makes NO extra requests (assert ledger length).

### Task 2: `connectors/woocommerce.py`
- `WooConnector.kind = "woo"`; `discover` pages `/wp-json/wc/store/v1/products?per_page=100&page=N` until short page; refs carry payloads (discover==fetch, like Shopify). No per-item timestamp in Store API → `change_hint = str(hash of (prices, is_in_stock, name))` derived client-side.
- `map_woo_product(p) -> ProductRecord`: `name`→title, `permalink`→canonical_url, `prices.price`/`regular_price` with `currency_minor_unit` scaling (e.g. "1999" + 2 → 19.99; `full_price` only when regular>price), `is_in_stock`, `images[].src`, `categories[].name`, size attribute (`attributes[]` whose name is Size, terms→sizes) else [].
- Tests: fixture page with 2 products incl. minor-unit prices and a sale; pagination stop; 401/403 → `ChannelBlocked`.

### Task 3: `connectors/structured.py`
- `StructuredConnector.kind = "structured"`; `discover` delegates to a `SitemapConnector` (constructor takes `sitemap_url`); `fetch` GETs the product URL and parses JSON-LD: all `<script type="application/ld+json">` blocks, tolerate `@graph` arrays, pick the `Product` node.
- Mapping: `name`, `description`, `sku`→product_code, `brand.name`, `image` (str|list|ImageObject), `offers` (single or list): min price, `priceCurrency`, availability contains "InStock"; offer `name`/`sku` used as size labels only when ≥2 named offers. OG meta fallback for title/image when JSON-LD absent → else `SkipProduct`.
- `raw` keeps the Product node. Tests: full JSON-LD page; @graph variant; offer-array sizes; OG-only fallback; no-data → SkipProduct.

### Task 4: planner rungs + registry
- Ladder (each rung skipped if its composition is in `tried`): gated → shopify bulk (T0) → **woo (T0)** → **sitemap×structured (T0, C1 lastmod)** → needs_attention.
- `get_connector` resolves `DiscoveryChannel.SITEMAP`+`FetchChannel.STRUCTURED_DATA` → `StructuredConnector(sitemap_url)`; new `DiscoveryChannel` member not needed (reuse SITEMAP); add `FetchChannel.STRUCTURED_DATA` wiring; woo uses new `DiscoveryChannel.WOO_API`... simpler: reuse BULK_JSON discovery with a `platform` field on the plan? NO — add `DiscoveryChannel.WOO_API` for explicitness.
- `run_brand` passes `sitemap_url` from the plan; `ScrapePlan` gains `sitemap_url: str | None = None` (persisted; set by composer from capability).
- Tests: woo capability → woo plan; sitemap+ldjson capability → structured plan; ladder respects `tried`; registry resolves all three.

### Task 5: mocked end-to-end for both new lanes
- CLI-level test: one mocked WordPress brand (robots→sitemap→product pages with JSON-LD) and one mocked Woo brand scrape to `ok` with observations; delta re-run writes nothing (structured lane: unchanged `lastmod` → no fetches; woo lane: identical payload-hash → no observations).

## M2b — the browser transport

### Task 6: `browser/transport.py` — `PlaywrightTransport`
- Implements the same `Transport` protocol (`level=T2`, `.get(url) -> httpx.Response`-compatible object with `status_code/text/content/headers/url/json()`), backed by one persistent Chromium context: `page.goto` for HTML; `context.request.get` for JSON/xml endpoints (rides the challenge cookies). Stealth: port `prod_page_v2/stealth/patches.py` init script + launch args into `backend/archive/browser/stealth.py` (copy, not import — the no-legacy-imports rule stands).
- Ledger identical to HttpxTransport. Tests: protocol-shape unit test with a fake page object; stealth JS present in init scripts (no real browser in CI).

### Task 7: planner browser rungs + CLI flag
- Rungs after the T0 ladder, before needs_attention (requires browser transport available): challenged+shopify → T2×bulk_json; enterprise/others with sitemap → T2×sitemap×structured.
- `run_brand`/CLI: `--browser` opt-in for now (scheduled runs stay HTTP-only until M2b is validated); transport picked per plan.transport.

### Task 8: live validation (ANNOUNCE FIRST — house rule)
- M2a: probe + scrape wiacollections, laluneofficial, xsai.vision, psylos1.com, www.outlw.xyz (≈6 probe GETs each; catalogs via Woo pages or sitemap+one GET per product — outlw/xsai/psylos1 catalogs unknown but small brands; cap structured fetch at 300 products/run initially).
- M2b: browser probe of gentlemonster/theoutnet/viviennewestwood/vancleefarpels, then structured scrape of whichever yields JSON-LD. Field-fill report decides whether milestone 3 (e0005 recipes port) is needed per brand.
