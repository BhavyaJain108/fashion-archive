# Archive v2 — Design Spec

**Date:** 2026-08-27
**Status:** Approved direction; spec pending Bhavya's review
**Scope:** Brand-scraping pipeline only. The runway archive (`backend/high_fashion/`), user system, and web UI are untouched by this design and will be cleaned up separately.

## 1. Why (context)

The current scraper was built when running a page through an LLM was expensive, and it evolved through at least three generations. A full audit (2026-08) found:

- Exactly **one live thread** (`stages/` → `scraper/url_extractor` → `prod_page_v2/e0005`), surrounded by ~15–20k lines of dead prior-generation code. No document describes the live thread.
- All three stages are **browser-first**: Stage 1 launches two *headful* Chromiums (hardcoded `headless=False` — the pipeline cannot run under cron at all), Stage 2 drives scroll/pagination/LLM-lineage-classification per category, Stage 3 (e0005) compiles LLM discovery into verified deterministic recipes — the one part whose economics are already right.
- **Catalog-level machine-readable channels are ignored.** Probe of the current 36-brand target list (2026-08-26): ~30 are Shopify, **18 expose the full catalog at `/products.json`**, 22 publish sitemaps with `lastmod`. The repo never fetches a sitemap or bulk catalog endpoint anywhere.
- **Not schedulable:** destructive pre-clean before unproven runs, false-success exit codes, a 600s consumer timeout that silently truncates, no locking, no timestamps, no change detection, no cache invalidation, and a per-product browser leak in e0005.
- Cost regressions: the Haiku routing behind the May-2026 "73% cost cut" was silently broken by the provider refactor (`llm_handler.py` discards its `model` arg); the streaming path never persists the cross-run brand cache.

**Goal:** a clean, modular body that can be scheduled to scrape brands continuously and on demand, built on the invariant that brands *want* their products displayed and bought — so machine-readable channels come first, browsers second, LLMs only where they earn it.

## 2. Decisions already made

| Decision | Choice |
|---|---|
| Scope | Brand scraper only |
| Primary store | SQLite (`catalog.db`) with append-only run/observation history; JSON export available |
| History | Keep it — runs append observations (price/stock/availability, on change and on first sight); current catalog is a view |
| Rebuild strategy | New package `backend/archive/` grows alongside the old pipeline; old body is deleted once the new one scrapes the full brand list |
| Architecture shape | Connector + compiler (rejected: per-platform monolithic adapters — duplicates orchestration; agent-first — cost scales with catalog size and has no change-detection story) |

## 3. Design principles

1. **One seam.** All catalog access goes through a single `Connector` protocol. Adding or deleting a channel never touches the planner, runner, or store.
2. **Dependencies point inward.** `domain/` (pure models) imports nothing from the package; connectors and store depend on `domain/`; nothing depends on a connector.
3. **Compile → verify → replay.** LLMs run as one-time compilers per brand (plans, recipes). Their output must survive deterministic verification before it is stored, and must keep passing `verify` to stay trusted. Runtime is deterministic replay.
4. **Append-only memory.** Runs and observations are never overwritten or pre-deleted. A failed run cannot damage good data.
5. **Deletability.** Each module must be re-writable without reading its neighbors' internals. This gut-and-reconfigure will happen again; the body is designed for it.
6. **Politeness.** Modest request rates, honest User-Agent on plain-HTTP tiers, per-brand rate limits, and no live-site traffic from tests without explicit announcement (house rule).

## 4. Architecture

```
backend/archive/
├── domain/            # pure models (pydantic), zero I/O
│   ├── brand.py       # Brand, Capability, ScrapePlan
│   ├── product.py     # ProductRef, ProductRecord (E0005 fields), Observation
│   └── run.py         # RunReport, Coverage, Health
├── fingerprint.py     # one polite HTTP round per brand → Capability
├── connectors/
│   ├── base.py        # Connector protocol
│   ├── shopify.py     # bulk /products.json + /collections/{handle}/products.json
│   ├── sitemap.py     # sitemap-index walk → ProductRefs with lastmod
│   ├── recipes.py     # browser render + e0005 verified-recipe catalog (ported)
│   └── agent.py       # LLM-with-browser fallback; findings compiled, never re-browsed per run
├── planner.py         # Capability → ordered connector chain (ScrapePlan), persisted; re-plans on drift
├── extraction/        # ported e0005: schema, field specs, methods, oneshot, verify-by-replay
├── browser/           # ported BrowserPool + stealth patches, wired and leak-free
├── store/
│   ├── schema.sql     # brands, scrape_plans, runs, products, observations, images
│   └── catalog.py     # the only module that touches the DB; exposes typed reads/writes + current-catalog view
├── verify.py          # coverage vs channel counts; per-field blank-rate health; drift → re-discovery
└── runner/
    ├── run.py         # run_brand(brand, mode): lock, timeouts, exit codes, JSONL run log
    └── cli.py         # archive plan <url> | archive scrape <brand|--all> [--delta|--full] | archive status
```

### 4.0 The capability model: four orthogonal axes

Every brand's situation is a coordinate on four independent axes, and a ScrapePlan is a *composition* along them — not a tier label:

- **T — Transport** (what it takes to make a request): `T0` plain HTTP · `T1` browser-grade headers · `T2` real browser + stealth (JS challenge) · `T3` browser-only (TLS fingerprinting) · `T4` gated (password/members → skip + watch)
- **D — Discovery** (enumerating the catalog): `D1` bulk platform feed (`/products.json`, Woo Store API) · `D2` sitemap product URLs · `D3` structured category pages · `D4` interactive browse (agent)
- **F — Fetch** (reading a product's fields): `F1` platform JSON · `F2` embedded structured data (JSON-LD/OG) · `F3` internal API via network capture · `F4` rendered DOM → verified recipes · `F5` per-product LLM (last resort)
- **C — Change signal**: `C1` per-item timestamps (`updated_at`/`lastmod`) · `C2` counts/etags · `C3` none → content-hash diff

Blockers live on T; data shape lives on D/F. A bot-challenged Shopify store is still Shopify — the countermeasure is to fetch the *same* JSON endpoints through a browser session that passed the challenge, not to fall back to HTML scraping. Consequently **transport is an injected dependency of connectors** (httpx session or BrowserPool page exposing a common `get()` surface), never something a connector owns. Against the 2026-08-26 probe of the 36-brand target list, the nine observed situations (open Shopify ×18; JSON-challenged Shopify ×2; fully client-filtered Shopify ×4; password-gated ×4; open Woo/WordPress ×2; custom-with-sitemap ×2; Webflow ×1; enterprise JS-challenge ×2; TLS-blocked ×1) all reduce to compositions of these axes, and 24 of 36 share one logical plan (`D1·F1·C1`) differing only in T. Blocker→countermeasure pairs: T1→header profile; T2→BrowserPool+stealth transport; T3→browser, then agent, then `unreachable` + alert (no evasion beyond ordinary stealth, by policy); T4→skip with cheap re-probe every run; rate sensitivity→per-brand AdaptiveRateLimiter.

### 4.1 Connector protocol (`connectors/base.py`)

```python
class Connector(Protocol):
    kind: str                                   # "shopify" | "sitemap" | "recipes" | "agent"
    def probe(self, brand: Brand) -> Capability:        ...   # cheap; may make 1–3 HTTP requests
    def discover(self, brand: Brand) -> list[ProductRef]: ... # refs carry change hints (lastmod/updated_at/etag)
    def fetch(self, ref: ProductRef) -> ProductRecord:   ...  # full E0005 record; may raise Skip/Retry
```

- `discover` and `fetch` are separable on purpose: a plan may pair `sitemap.discover` with `recipes.fetch`.
- Connectors are stateless between calls except via explicitly injected resources (HTTP session, BrowserPool, catalog handle).
- `ProductRef.change_hint` is an opaque string (lastmod timestamp, `updated_at`, etag). The runner compares it to the stored hint to decide delta membership; connectors never touch the DB.

### 4.2 Connector behaviors

- **shopify** — pages `/products.json?limit=250&page=N` (and per-collection endpoints when category structure is wanted). One response yields refs *and* near-complete records (title, price, variants→sizes, images, `updated_at`, availability), so for pure-Shopify brands `discover` and `fetch` collapse into bulk reads. Handles 429 with backoff; detects the password page and bot-challenge responses, reporting them as Capability states rather than errors.
- **sitemap** — reads `robots.txt` → sitemap index → product sitemaps; classifies product URLs by platform URL-shape (`/products/`, locale prefixes); returns refs with `lastmod`. Platform-agnostic; used for discovery on non-Shopify sites and as a cross-check on Shopify ones.
- **recipes** — the ported e0005: per-brand one-shot vision discovery compiled to a verified recipe catalog; `fetch` renders via the shared BrowserPool (bug fixed: the orchestrator uses the injected page and closes memos) and replays recipes cheapest-first. Stealth patches applied to every launch.
- **agent** — for sites where fingerprinting finds no usable channel and recipes discovery fails (enterprise/bot-walled/fully custom). An LLM drives a browser session to map categories and locate product pages; everything it learns is written down as a ScrapePlan + recipes and verified. Scheduled runs replay the compiled result; the agent re-runs only when `verify` flags drift. Cost ceiling per brand per invocation is configured, and failures degrade to "needs attention" rather than retry loops.

### 4.3 Planner (`planner.py`)

`plan(brand)`: run `fingerprint` + connector `probe`s → resolve the brand's (T, D, F, C) coordinate per §4.0 and compose the chain: transport choice + discovery connector + fetch connector + delta strategy. Representative compositions:

- open Shopify → `[shopify]` (sitemap as count cross-check)
- challenge-protected Shopify → `[sitemap → recipes]` or `[recipes]` (browser passes the challenge)
- WooCommerce/WordPress/custom-with-sitemap → `[sitemap → recipes]`
- nothing usable → `[agent]` (compiles toward one of the above)
- password-gated → plan = `skip`, with the reason recorded; re-probed each run so a store opening is noticed automatically

Plans are persisted in `scrape_plans` with the fingerprint evidence. `verify` failures mark a plan stale, which triggers re-planning on the next run — never mid-run.

### 4.3b Brand lifecycle (onboarding = self-healing)

Every brand moves through one state machine: `new → scoped → calibrating → active`, with `degraded`, `gated` (password), `unreachable`, and `needs-attention` as recoverable side states. **Calibrate before committing:** a newly planned (or re-planned) brand first runs its plan on a small sample (~5 products) and must pass verify before promotion to a full run — failure is cheap and informative, never damaging. **Re-entry carries memory:** failed compositions are recorded on the plan (`tried: [...]`) so each re-planning iteration moves down the escalation ladder (upgrade transport → switch discovery → recipes → agent) instead of repeating itself; a brand that exhausts the ladder lands in `needs-attention` with the full trail. MONITOR-phase verify failures re-enter the same loop — onboarding and drift-recovery are one mechanism, and a brand is never "set up," only currently converged.

### 4.4 Store (`store/`)

SQLite, WAL mode, one `catalog.db`. Core tables:

- `brands(id, domain, homepage_url, display_name, status, notes)` — seeded from `brands.yml` (the human-editable source of truth for *which* brands and per-brand overrides).
- `scrape_plans(brand_id, chain, capability_json, fingerprinted_at, stale)`
- `runs(id, brand_id, mode, started_at, finished_at, exit_status, coverage_json, log_path)`
- `products(id, brand_id, canonical_url, product_code, first_seen_run, last_seen_run, current_json)` — `current_json` is the latest full E0005 record for cheap reads.
- `observations(product_id, run_id, price, full_price, in_stock, sizes_json, raw_delta_json)` — appended when a watched field changed (and always on first sight), giving price/stock history without storing unchanged snapshots every run.
- `images(product_id, url, local_path, content_hash)` — **image files are first-class archive material, not metadata**: every product's images are downloaded through the same transport into a content-addressed local store (`data/images/{domain}/{hash[:2]}/{hash}.{ext}`) on first sight and when the product's image set changes. Remote CDNs delete images when products are delisted; the archive must not. Already-known URLs are never re-downloaded, so delta runs stay cheap.

`catalog.py` is the only DB gateway; it also provides the JSON export (per-brand dump matching today's shape closely enough for the UI reader) and the current-catalog view (`last_seen_run` on the latest successful run = live product; older = delisted, kept forever — it's an archive).

### 4.5 Verify (`verify.py`)

After each run, per brand: compare extracted count vs channel-reported counts (bulk JSON `count`/page math, sitemap URL count, JSON-LD `numberOfItems` when present — the good idea from `count_detection`, now free); compute per-field blank rates against that brand's historical baseline. Outcomes: `ok`, `degraded` (coverage below threshold or blank-rate spike → plan marked stale, run exit 1), `failed`. Verdicts land in `runs.coverage_json` and drive `archive status`.

### 4.5b Coverage as a first-class output

Because every brand carries a persisted plan and every run carries verify's arithmetic, coverage is a queryable fact, not an estimate. `archive status` renders the fleet coverage matrix — one row per brand: tier/chain, product count, coverage % (extracted vs channel-reported), field fill-rate (n/38 E0005 fields), freshness (time since last successful run), and last-run LLM cost. This view is simultaneously the health dashboard, the work queue (worst row = next improvement, and connector fixes lift whole tiers), and — via append-only runs — a coverage *trend* per brand, where slow decay means drift and a cliff means redesign. `archive plan <url>` gives the same classification for a brand before it is ever scraped, so new additions arrive as known quantities.

### 4.6 Runner (`runner/`)

`run_brand(brand, mode)`:
1. Acquire per-brand lockfile (skip with a note if held).
2. Open a `runs` row immediately (crash-visible), JSONL log to `logs/runs/<brand>/<run_id>.jsonl`.
3. Load or create plan → `discover` → delta selection by change hints (`--full` ignores hints).
4. `fetch` with per-brand rate limit and the ported AdaptiveRateLimiter for burst safety; per-product failures retry ×3 then record, never abort the brand.
5. Write records/observations transactionally per batch; run `verify`; finalize the run row.
6. Global per-brand wall-clock timeout; SIGTERM handler closes browsers and finalizes the row as `interrupted`.

Exit codes: `0` verified ok, `1` degraded (ran, but coverage/health flagged), `2` failed. `archive scrape --all` exits with the worst brand status and prints a one-line-per-brand summary — exactly what a scheduler needs to alert on.

Scheduling itself is external and thin: launchd/cron (or a Claude scheduled task) invokes `archive scrape --all --delta`. No daemon, no queue — the CLI + lockfiles are the concurrency model at this scale (~tens of brands).

### 4.7 LLM usage policy

- Models/providers configured in one place (`config/.env`), passed explicitly — the handler must honor the requested model (fixes the discarded-model regression; a unit test asserts it).
- Every call routed through one tracked client; per-run token/cost totals land in the run report. No raw SDK clients anywhere.
- LLM call sites: agent connector (per weird brand, on compile/drift only), e0005 one-shot discovery (once per brand until stale), e0005 `llm_batch` fallback rows (rare, catalog-verified). Nothing per-product-per-run on healthy brands.

## 5. What is kept, what is gutted

**Ported into the new body:** e0005 extraction (schema, methods, oneshot, verify-by-replay) with the memo/pool wiring fixed; BrowserPool; stealth patches; AdaptiveRateLimiter; the JSON-LD/platform-selector count heuristics (into `verify`); `llm_recorder` fixture recording (generalized to HTTP fixtures); the `tests/` conventions and CI ratchet.

**Deleted once `archive` scrapes the full brand list:** `backend/stages/`, `backend/scraper/` (nav DFS explorer, static vision extractor, url_extractor scroll/lineage machinery, legacy `Brand` pipeline, `page_extractor`, `premium_api`), `backend/services/results_writer.py`, `backend/storage/` (old schema.sql, extraction_manager — replaced by `catalog.py` behind the same API routes), `prod_page_v2/legacy/` + orphaned `schemas/`/`extraction_patterns/`, and the stale docs describing them. The Flask API keeps its routes but reads from `catalog.py`; scrape triggering shells out to the runner (one code path for UI and cron).

## 6. Testing

- **Unit** (CI, hermetic): domain models, planner decisions from canned Capabilities, delta selection, store round-trips (tmp DB), verify math, exit-code mapping, LLM-handler model-honoring.
- **Contract per connector** (CI, hermetic): recorded HTTP/HTML fixtures per real brand shape (open Shopify, challenged Shopify, Woo, sitemap-index variants, password page) replayed against `probe/discover/fetch`.
- **Live smoke** (manual, `-m live`): one brand per tier; each test prints exactly what requests it will make and requires explicit opt-in — per the house rule, never run without announcing first.
- CI trigger fixed (`master`), ruff/mypy scoped to `backend/archive/` + `tests/` from day one — the new body starts clean and stays clean.

## 7. Milestones (each independently shippable)

1. **Skeleton + Tier 1:** domain, store, fingerprint, shopify + sitemap connectors, planner, runner/CLI, verify. Scrapes the ~18 open-Shopify brands on a schedule with history. *(No browser, no LLM.)*
2. **Tier 2:** browser/ + extraction/ port with the leak fix and stealth; `recipes` connector; challenged-Shopify and Woo/custom-with-sitemap brands come online.
3. **Tier 3:** agent connector for the enterprise/weird tail; drift-triggered recompilation loop proven on one redesign.
4. **The gut:** API reads move to `catalog.py`; old packages deleted; docs rewritten to describe the one real system; scheduled `--all --delta` becomes the steady state.

## 8. Out of scope

Runway-archive/high_fashion cleanup; auth hardening (tracked separately from the earlier security audit); UI redesign; any non-fashion verticals; proxy rotation/CAPTCHA solving (bot-walled sites get the browser/agent lane or are marked `needs-attention` — we do not build evasion beyond ordinary stealth headers already in the repo).
