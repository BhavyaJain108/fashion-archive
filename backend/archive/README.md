# Archive v2 — module map

The scraping body. Spec: `docs/superpowers/specs/2026-08-27-archive-v2-design.md`.
Front door: `python -m backend.archive.runner.cli plan | scrape | status | capability`

## The six stages

Use these names when discussing the pipeline — every file belongs to exactly one.

| # | Stage | What it answers | Files |
|---|-------|-----------------|-------|
| **S1** | **SCOPE** | *What kind of site is this?* | `fingerprint.py` |
| **S2** | **PLAN** | *Which lane do we use on it?* | `planner.py` |
| **S3** | **DISCOVER** | *What products exist?* (`connector.discover`) | `connectors/shopify.py`, `connectors/woocommerce.py`, `connectors/sitemap.py` |
| **S4** | **FETCH** | *What are this product's fields?* (`connector.fetch`) | `connectors/shopify.py`, `connectors/woocommerce.py`, `connectors/structured.py` |
| **S4b** | **FIND** | *The channel left a field empty — where is it on the page?* | `finder.py` (apply + validate), `finder_llm.py` (learn), `domain/recipe.py` |
| **S5** | **STORE** | *What do we keep, and what changed?* | `store/catalog.py`, `store/schema.sql`, `images.py` |
| **S6** | **VERIFY** | *Did we get it all, and is it any good?* | `verify.py`, `capability.py`, `report.py` (field fill per brand) |

S3 and S4 share files because bulk-feed connectors answer both questions from one response
(Shopify's `/products.json` is discovery *and* fetch); the sitemap+structured pair splits them.

## Support layers (not stages)

| Layer | Role | Files |
|-------|------|-------|
| **TRANSPORT** | How a request is made — injected into connectors, never owned by them | `transport.py` (HTTP), `browser/transport.py` + `browser/stealth.py` (Chromium) |
| **DOMAIN** | The data shapes everything passes around; imports nothing | `domain/brand.py`, `domain/product.py`, `domain/run.py` |
| **RUN** | Orchestration and entry points | `runner/run.py` (lifecycle), `runner/cli.py` (CLI), `brands.yml` (target list) |

## Rules of the body

- Connectors never own transports and never touch the DB.
- `domain/` imports nothing from the package; nothing here imports legacy `scraper/`, `stages/`, `prod_page_v2/`.
- Runs and observations are append-only; no code deletes prior data.
- Products are stored in the **E0005 schema** — the same field names the frontend and the old
  pipeline use. One vocabulary, no mapping layer.
- All tests are hermetic (httpx.MockTransport, tmp_path). Live-site runs are announced first.

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
