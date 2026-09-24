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
| **S5** | **STORE** | *What do we keep, and what changed?* | `store/catalog.py`, `store/objects.py`, `images.py` |
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

### What the model is shown

One call is one page, and the page is most of the bill: 220,000 characters (~55k
tokens) cost 17–20 cents on a heavy page against 1.5 on a light one. Since 2026-09-24
`finder_llm.prepare_page` sends at most 110,000 characters, and what it removes is
what no rule can point at:

| Removed | Why it is safe |
|---|---|
| `<script>` (except `application/ld+json`), `<style>`, `<svg>`, `<noscript>`, comments | not markup a selector lands on; JSON-LD stays where it was |
| stylesheet / preload / icon `<link>`s | plumbing; `canonical` and `alternate` stay |
| `style=`, `on*=`, `sizes=` attributes | presentation and behaviour |
| `data-*` values over 120 characters that are not about the product | Elementor `data-settings`, a mega-menu's config; kept when the name says product/variant/size/price/image… or the value carries an image URL (`data-product_variations` stays) |
| `srcset` beyond its first two candidates | the rule reads the attribute; its `expected` may be the first entry, and replay accepts a value that begins with it |
| whitespace runs | collapsed to one space |

When the page marks where the product is — `<main>`, an `itemtype=…Product`
container, or a `product-single` / `pdp` / `single-product`-style class — only that
region is sent, with the head's `<meta>` tags and the JSON-LD in front of it; the
header, mega-menu and footer are not. An empty `<main>` (an app shell) does not count.

Measured on the three synthetic storefront pages in `tests/unit/archive/fixtures/`
(built to the proportions of the platforms, not fetched — see
`test_finder_trim.py`), against what the old code sent:

| Fixture | Raw | Old payload | Now | Now / old |
|---|---|---|---|---|
| `nextjs_product_page.html` | 370,890 | 129,769 | 55,434 | 0.43 |
| `shopify_product_page.html` | 278,979 | 148,739 | 78,587 | 0.53 |
| `woo_elementor_product_page.html` | 282,415 | 132,875 | 63,301 | 0.48 |

`_holds_up` replays every proposal on the page **as fetched**, never on the trimmed
copy: the rule is applied to untrimmed pages for the rest of the brand's life, so a
selector that only works on the trimmed copy is exactly what replay throws out — and
a rule that points at something the model was not shown (a `<noscript>` image, say)
is kept if it holds. The prompt tells the model the page is trimmed and that replay is
on the whole page, so it anchors selectors on the product's own containers.

## Backups

Nothing was backed up before 2026-09-24. `backup.py` copies, once a day, what cannot
be re-scraped, under `backups/<YYYY-MM-DD>/` in the same bucket:

| | What | How |
|---|---|---|
| `pg/<table>.ndjson.gz` | the five catalogue tables (`schema.sql`), `raw` included | streamed out of Postgres through a server-side cursor, one JSON line per row into gzip; a 25k-row table is never in memory as rows and as bytes at once |
| `r2/<key>` | `fleet.json`, `rules/`, `plans/`, `control/schedule/` | the bucket's own same-bucket `CopyObject` (`ObjectStore.copy`) — no bytes leave R2, no worker egress |
| `manifest.json` | row counts, bytes, seconds, what was pruned | what `backup()` returns and the log line says |

Not copied: photographs (re-fetchable from `product_images.url`, and gigabytes), run
logs (history, not state), runs/scores/evidence (re-derived by the next pass), and
the frozen `history/` observation objects (the table is dumped instead). Fourteen days
are kept; older days are deleted. Bandwidth: ~25–35 MB uploaded a day, ~1 GB a month.

**Who runs it:** the daemon. Each worker looks at `control/backup.json` once per
calendar day; the first to see a new date claims it with a compare-and-swap and runs
the backup, the others see the claim and carry on scraping. A day that failed is
retried by the next worker to look; a claim whose worker died is retaken after three
hours. The r2 backend has no rows to dump, so on `CATALOG_BACKEND=r2` nothing happens.

```
python -m backend.archive.runner.cli backup             # run one now
python -m backend.archive.runner.cli backup --status    # last day, state, days held
python -m backend.archive.runner.cli restore 2026-09-24 bode.com
```

`restore` puts one brand back as it was on one day: delete its rows in all five
tables, insert the day's rows, one transaction. Other brands are untouched. Tests:
`tests/unit/archive/test_backup.py` (line format, copies, prune, claim) and
`tests/db/test_backup.py` (dump and restore against a real Postgres).
