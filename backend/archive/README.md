# Archive v2 — module map

The scraping body. Spec: `docs/superpowers/specs/2026-08-27-archive-v2-design.md`.
Front door: `python -m backend.archive.runner.cli plan | scrape | status | capability | coverage | access`

## The seven stages

Use these names when discussing the pipeline — every file belongs to exactly one.

| # | Stage | What it answers | Files |
|---|-------|-----------------|-------|
| **S1** | **SCOPE** | *What kind of site is this, and what will it talk to?* | `fingerprint.py`, `escalate.py` |
| **S2** | **PLAN** | *Which lane do we use on it?* | `planner.py` |
| **S3** | **DISCOVER** | *What products exist?* (`connector.discover`) | `connectors/shopify.py`, `connectors/woocommerce.py`, `connectors/sitemap.py` |
| **S4** | **FETCH** | *What are this product's fields?* (`connector.fetch`) | `connectors/shopify.py`, `connectors/woocommerce.py`, `connectors/structured.py` |
| **S4b** | **FIND** | *The channel left a field empty — where is it on the page?* | `finder.py` (apply + validate), `finder_llm.py` (learn), `domain/recipe.py` |
| **S4c** | **PLACE** | *What is this thing, in words every brand shares?* | `taxonomy.py` (the vocabulary and the phrase book), `taxonomy_llm.py` (ask) |
| **S5** | **STORE** | *What do we keep, and what changed?* | `store/catalog.py`, `store/pg_catalog.py`, `store/periods.py`, `store/objects.py`, `images.py` |
| **S6** | **VERIFY** | *Did we get it all, and is it any good?* | `verify.py`, `capability.py`, `score.py` (the scorecard per run) |
| **S7** | **LEARN** | *Which of E0005's 42 fields are we still not getting, and why?* | `coverage.py`, `access/` (the bench), `access/LEARNINGS.md` (the record) |

S4c is the one layer that is *not* the brand's own words. `category1..10` stays exactly
as the shop published it — bode's `MENS SHIRTS`, marrknull's `上衣` — and the shared
vocabulary sits beside it, joined on at read time from one fleet-wide phrase book
(`taxonomy/phrases.json`). The scrape only *learns*: it sends the phrases the book has
never seen (a category level, or a title's trailing words when a brand publishes no
categories at all) to a small model, once each, ever. Nothing is written into E0005, so
correcting the book re-answers every brand at once instead of costing 41 rescrapes.

S3 and S4 share files because bulk-feed connectors answer both questions from one response
(Shopify's `/products.json` is discovery *and* fetch); the sitemap+structured pair splits them.

## The transport ladder

S1 does not assume a brand will talk to us. It climbs until one level can read the site,
and records the level it stopped at on the `Capability`, so S2 plans for the same
transport and `transport.for_level` builds it at scrape time.

Nor does it assume the shop is on the brand's own host. When the bare domain has no
feed, no Woo API and no product JSON-LD, S1 reads the homepage for a link whose words
or path say shop or store and lead somewhere else, and probes that host once: La Lune's
site is a portfolio, its nav sends buyers to shop.laluneofficial.com, and that is a
WooCommerce store with 63 products. The capability stays keyed on the brand's domain
and carries the shop host as `shop_domain`; only discovery addresses it.

| Level | What it is | Cost | Why it exists |
|---|---|---|---|
| **T0** | Python's own HTTP | one request | most brands need nothing more |
| **T1** | the same request with a real browser's TLS handshake (`curl_cffi`) | one request | our headers said Chrome while our handshake said Python, and a WAF hashes the handshake before it reads a header. Vivienne Westwood 403 → 200, Van Cleef timeout → 200 |
| **T2** | a real browser, which runs the page's own challenge script | ~3s and a browser | a JavaScript challenge, or a page whose products only exist after it renders |

A timeout counts as a refusal: a WAF that drops the connection without answering looks
exactly like a host being down until something asks in another voice.

**T2 is in the deployed scraper image** since 2026-09-22: `Dockerfile.scraper` builds on
the Playwright base and the worker runs on a plan that fits Chromium, so the daemon climbs
T0 → T1 → T2 on its own. `--browser` is only needed for a hand-run scrape.

## Support layers (not stages)

| Layer | Role | Files |
|-------|------|-------|
| **TRANSPORT** | How a request is made — injected into connectors, never owned by them | `transport.py` (T0 plain HTTP, T1 curl_cffi), `browser/transport.py` + `browser/stealth.py` + `browser/challenge.py` (T2 Chromium) |
| **ACCESS** | The bench for trying new ways in, and the record of what each taught | `access/` (`archive access`), `access/LEARNINGS.md` |
| **DOMAIN** | The data shapes everything passes around; imports nothing | `domain/brand.py`, `domain/product.py`, `domain/run.py` |
| **RUN** | Orchestration and entry points | `runner/run.py` (lifecycle), `runner/cli.py` (CLI), `brands.yml` (target list) |

## Run modes

`runner/run.py` runs the first three; `runner/sweep.py` the last. The scheduler
offers delta on the brand's cadence, learn when the owner asks, and sweep on its own
per-brand cadence (`sweep_seconds`, 0 = off) whenever the brand is unclaimed and its
real turn is more than ten minutes away.

| Mode | Reads | Writes | Covered run? | Cost per brand |
|---|---|---|---|---|
| **delta** | the feed, then the pages and photographs of products whose change hint moved | products, images, stamps, evidence, scorecard | yes | feed pages + one page per changed product + its images |
| **full** | everything delta reads, for every product | the same | yes | feed pages + one page per product + images |
| **learn** | a spread of product pages, through the finder | the recipe book and the evidence; no products | no | `learn_budget` finder calls (~$0.17 each) |
| **sweep** | the bulk feed only: Shopify `/products.json?country=…` pages or Woo Store API pages | `in_stock`, `size_availability`, `size_stock_counts`, `price`, `full_price`, `promotion_type`, `currency`, `offers[].available/price` of products already held; an observation per watched change | no | ⌈products/250⌉+1 requests on Shopify, ⌈products/100⌉+1 on Woo; a few seconds |

A sweep never adds or removes a product, never touches images, stamps or the
reference run, and never probes: a brand whose plan reads the structured-data lane
is skipped with the reason "no cheap stock source" and nothing is fetched. Its run
row says `checked`, `changed` and `seconds`. `cli scrape X --sweep` runs one by
hand; `cli brands sweep X --every 900` sets the cadence.

## Which prices the catalogue holds

The catalogue is priced for one market, `ARCHIVE_MARKET` (US). A Shopify store with
Markets prices each country itself — kuurth.com asks 34.95 EUR at home and 52.00 USD in
the US, a decision the shop made, not a conversion — and `/products.json?country=US`
returns that market's figures, with a `cart_currency` cookie naming the currency they
are in. The connector reads the cookie, so a store without a US market (marrknull.com)
keeps its own currency and the site converts it for display. The market rides on the
change hint, so switching it re-records every product once. WooCommerce's Store API
only relabels the symbol when asked for a currency, and JSON-LD sites state one price;
neither gets a market. `market` on the record says which country a price is for.

## The per-field timeline (periods)

The owner's rule, verbatim: "we keep storing only if it has changed from the last
record. otherwise we just update the period." `store/periods.py` is that rule. For every
product and each of eleven fields — `price`, `full_price`, `in_stock`, `size_availability`,
`size_info`, `color_info`, `material_info`, `main_image_url`, `product_title`, `currency`
and the description's sha1 — the catalogue holds a list of periods `{value, from, to}`,
oldest first. A run that reads the same value moves `to` forward; a different value
closes the open period at the run's time and opens a new one there. Nothing is stored
per run except a boundary. Values are normalised first (stripped text, prices to 2 dp,
`in_stock` to a bool) so `126.004` after `126.0` opens nothing. At most 50 periods per
field per product; the oldest are dropped.

One worked example. A hoodie is read by four runs, at 10:00 on four days, and its
price goes 180 → 126 → 126 → 180. Three periods:

| value | from | to |
|---|---|---|
| 180 | day 1 10:00 | day 2 10:00 |
| 126 | day 2 10:00 | day 4 10:00 |
| 180 | day 4 10:00 | day 4 10:00 |

The third run wrote nothing for the price — it moved the second period's `to`. The
title, currency and sizes never moved, so each has one period from day 1 to day 4.

Where it lives: on Postgres, the `product_periods` table, written in the same
transaction as the product row (`PgCatalog._flush_locked`, one statement per batch,
one more to cap at 50), and reached forward by `mark_seen` for products a delta run
left untouched. On the object store, `periods: {field: [[value, from], …]}` on each
product entry, with `from` in epoch seconds and no `to` — a closed period ends where
the next begins, and the open one ends at `last_seen_run`, which the entry already
carries. Measured on a synthetic 8,000-product catalogue (6.3 KB a record, four runs,
a tenth of prices moving each run): 610 bytes a product, 9.7% growth.

Readers: `product_history(domain, itemurl=None)` returns the run stamps as before plus
`periods` per product, on both backends. `catalogue_changes(domain, limit)` keeps its
`added`/`removed` rows and adds `changed` and `changed_names` — each a period boundary,
as `Nemo Hoodie: price 180 → 126` — newest first.

Migration: `archive periods migrate <domain>|--all` replays `product_observations`
(the object store's `history/<domain>/<run>.json`) oldest first into periods, and is
safe to run twice. `archive periods show <domain> <itemurl>` prints one product's
timeline. Observations are still written: the backfill reconciles on their count and
the migration reads them.

## Rules of the body

- Connectors never own transports and never touch the DB.
- `domain/` imports nothing from the package; nothing here imports legacy `scraper/`, `stages/`, `prod_page_v2/`.
- Runs and observations are append-only; no code deletes prior data.
- Products are stored in the **E0005 schema** — the same field names the frontend and the old
  pipeline use. One vocabulary, no mapping layer.
- All tests are hermetic (httpx.MockTransport, tmp_path). Live-site runs are announced first.
- A rule learned on one brand lives in `access/` until it has been shown to hold on the
  brands that did *not* teach it; only then does it move into the connectors, where every
  brand pays for it.
- S7 is a loop, not a step: `coverage` shows what is still missing, `access/LEARNINGS.md`
  holds the procedure for closing one gap and the record of every rule already closed —
  brand, date, evidence. Read it before adding a rule, and add to it after.

## S4b — how a learned rule earns its place

A rule the model proposes has to survive four checks before anything is stored. Each
one exists because a rule got past the ones before it on a real brand.

| Check | Question | Caught in the wild |
|---|---|---|
| **replay** (`verify_recipe`) | Does the rule reproduce the value the model predicted? | invented selectors |
| **shape** (`is_plausible`) | Could this text be a value for this field at all? | theoutnet storing `"Sold out"` as every size |
| **label** (`_is_label`) | Is this the heading above the value rather than the value? | psylos1's material reading `"Fabrics & Materials"` |
| **echo** (`_echoes`) | Is it just the product's own title or description? | wiacollections' colour reading the product title |

Plus two record-level invariants in `runner/run.py`: `size_availability` must have as
many entries as `size_info` (E0005 stores them as parallel lists), and no two fields may
be filled from the same span of the description.

Rules accumulate: a brand keeps several strategies per field, because one storefront
lays the same field out differently across its catalogue. A field keeps the first value
that survives all four checks. Any product whose gaps the existing rules cannot fill is
a chance to learn another rule, bounded by `--learn-budget` and three failed attempts
per field.
