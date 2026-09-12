# Deleting the old generation

**Date:** 2026-09-12
**Status:** approved

## Why

The archive scraper (`backend/archive/`) and the My Brands page now work end to end
and are on master. The generation they replaced is still in the tree: four packages
and an API module that nothing reaches. Left alone it costs a reader — human or
model — the time to work out which of two scrapers is the real one, every time.

The measurement that settles it:

```
backend/pipeline.py      229 lines   imported by NOBODY
  └ backend/stages/     4,090 lines   only by pipeline.py
     └ prod_page_v2/    8,532 lines   only by stages/streaming.py
        └ scraper/     21,684 lines   only by those two + api/routes.py
backend/api/routes.py     998 lines   22 endpoints, reads backend/extractions/
backend/extractions/        0 files   ← empty
```

No live frontend component calls `/api/brands*` or `/api/products*`. Every panel's
API use was checked one by one: My Brands uses `ArchiveAPI` only; Favourites and the
image viewer use favourites/recents/images; High Fashion uses seasons/collections/
video; the product detail, seasons and collections panels make no calls at all.

## What is deleted

| path | lines | reached only by |
|---|---|---|
| `backend/scraper/` | 21,684 | prod_page_v2, stages, routes.py |
| `backend/prod_page_v2/` | 8,532 | stages/streaming.py |
| `backend/stages/` | 4,090 | pipeline.py |
| `backend/api/routes.py` | 998 | nothing |
| `backend/services/` | 395 | scraper/brand.py |
| `backend/pipeline.py` | 229 | nothing |
| `backend/utils/` | 203 | scraper/navigation/dynamic_explorer.py |
| `backend/storage/{storage_layer,extraction_manager}.py`, `schema.sql`, `test_catalog_index.py` | ~1,200 | routes.py |
| `backend/extractions/` | 0 files | — |
| `backend/{test_category,test_triplet}.py`, `backend/api/test_{integration,full_api_demo}.py` | ~700 | — |

Consequential edits: `backend/api/__init__.py` stops exporting `register_routes`,
`backend/app.py` stops registering it, `backend/storage/__init__.py` keeps only
`images`.

## What is kept

`backend/archive/`, and the one module outside it the scraper needs:
`backend/storage/images.py` — `R2ImageStore` / `LocalImageStore`, which
`archive/images.py` uses as its sink.

The live app is untouched: `app.py`, `api/{archive,auth,favorites,high_fashion,
brand_following}_routes.py`, `auth/`, `userdata/`, `high_fashion/`.

## What is knowingly lost

**`scraper/navigation/`** — roughly twenty files that drove a browser to explore a
shop's category tree. The archive discovers products through sitemaps, bulk JSON and
category pages, and has no equivalent. This does not bite today, but the brands
producing nothing are where it would have been tried. The decision was to delete
rather than quarantine: the code is written against a browser session, popup engine
and LLM handler that are all going, so it would arrive in the archive already broken
and sit there unrunnable. If a shop ever needs it, that is real work against the
archive's own transport, and `git log` has the old approach to read.

**`prod_page_v2/e0005/field_specs.py`** — the E0005 field definitions.
`archive/domain/product.py` cited it in a comment as the authority for its 42-field
tuple. Nothing imported it, so nothing breaks; the comment is rewritten so that
tuple is the authority, rather than pointing at a file that no longer exists.

## Tests

- `tests/unit/test_llm_recorder.py` — tests `scraper.llm_recorder`. Deleted with it.
- `tests/unit/test_url_dedup.py` — tests `stages.urls`. Deleted with it.
- `tests/conftest.py` — put `backend/` on `sys.path` only so `from stages.…`
  resolved. Simplified to the repo root.
- `tests/api/test_route_protection.py` imports the real app and iterates whatever
  routes exist, so it keeps passing with fewer of them.

## Order

One commit per layer, outermost first, so each step reverts on its own and the app
imports throughout:

1. `routes.py` and its filesystem store
2. the island, leaf-first: `pipeline.py` → `stages` → `prod_page_v2` → `scraper` →
   `services` → `utils`
3. tests and `conftest.py`
4. `web_ui/src/services/api.js` — the ~20 brand methods that would now call 404s

After each: `ruff`, `mypy`, `pytest -m unit`, `python -c "import backend.app"`, and
the My Brands page actually rendering in a browser — not only green tests.

## Reviving any of it

`git log --diff-filter=D --name-only` finds the deleting commit; the content is at
its parent. This document names what was in each package so nobody has to bisect to
find out.
