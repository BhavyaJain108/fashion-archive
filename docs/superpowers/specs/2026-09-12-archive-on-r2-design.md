# The archive, stored in R2

**Date:** 2026-09-12
**Status:** approved

## Why

Two requirements, both from Bhavya, both unmet today:

1. **No database on the laptop.** The catalogue is a 68 MB SQLite file in
   `backend/archive/data/`. It grows with every scrape, and it is the last thing the
   scraper writes locally now that image bytes go to R2.
2. **The hosted site shows products.** It cannot, because that file is the catalogue
   and Render has no disk. `/api/archive/*` returns 503 in production.

These are the same problem. The photographs already reached the internet; the index
that says what they are did not.

The plan this replaces had the scraper keep SQLite and add a `publish` command to
export snapshots to R2. Writing the catalogue to R2 directly removes the export: the
scraper writes what the site reads.

```
before:  scraper → SQLite (laptop) → publish → R2 → site
after:   scraper → R2 → site
```

## What makes this possible

R2 supports conditional writes through its S3 API. Probed against the live bucket:

| operation | result |
|---|---|
| `put(IfNoneMatch="*")` on an absent key | accepted |
| the same call again | refused, `PreconditionFailed` |
| `put(IfMatch=etag)` with the current etag | accepted |
| `put(IfMatch=etag)` with a stale etag | refused, `PreconditionFailed` |

That is compare-and-swap, which is what parallel workers need to claim a brand
without a database. Without it this design would not work, so it was checked first.

## Object layout

Per-brand objects, because two workers never scrape the same brand at once — the
claim prevents it — so nothing but the control plane is contended.

```
brands/<domain>.json            brand row + state
plans/<domain>.json             the scrape plan
rules/<domain>.json             learned extraction rules
evidence/<domain>.json          which fields have been searched, per source
catalogue/<domain>.json         every product, full records, with the raw payload
catalogue/<domain>.meta.json    counts and freshness only — small, read often
history/<domain>/<run>.json     price and stock observations from that run
runs/<domain>/<run>.json        mode, times, exit status, coverage
runs/<domain>/index.json        run ids, newest last
scores/<domain>/<run>.json      the scorecard
images/<domain>.json            per product: source url, stored url, content hash
requests/<domain>/<run>.json    what the hosts answered during that run
control/schedule/<domain>.json  cadence, next due, claim  (CAS)
control/daemon.json             stop flag, code version   (CAS)
site/manifest.json              the roster with counts, for the page
site/index.json                 every product, minimal fields, for search
site/<domain>.json              one brand's products, slim, for the grid
```

### Why `.meta.json` exists

The biggest catalogue object is STAUD's at **9.8 MB**; the whole archive's records
are 55.5 MB. Reading one brand's catalogue once per run is fine. Drawing the sidebar
must not read all 32 — so counts, state and freshness live in a separate object of a
few hundred bytes. `status_rows` and `live_product_counts` read those.

### Why `site/` exists separately

A stored record averages 7.8 KB because it carries the connector's untouched payload,
kept so a mapping can be re-derived later. The page needs none of it: the slim form
of a 500-product brand is 118 KB gzipped, measured. The run writes both — the archive's
copy and the page's copy — so there is still no export step.

## Identity

Two surrogate keys in the current interface have no equivalent in an object store.

**`run_id: int`** becomes a string, `<iso-8601>-<6 hex>`, which sorts lexically by
time. Everything that took a run id keeps working; the type changes.

**`product_id: int`** goes away. It exists only to join images to products, and
`product_id_for(domain, itemurl)` already exists to look it up — so the image methods
take `itemurl` directly. This touches `images.py`, `runner/archive_images.py` and
their tests.

## Writes are buffered

`record_product` currently commits per product. Against objects that would be one
9.8 MB write per product, so the store loads a brand's catalogue once, mutates it in
memory, and flushes.

Flush happens every 200 products and at run end. A killed run therefore loses at most
the last 200 products, where today it loses none. That is acceptable: "no resume after
kill" was already the decision, and a killed run is re-run from the start.

The interface does not change — `record_product` still returns whether an observation
was appended — but `close()` becomes load-bearing rather than tidy, so every caller
must flush. The runner already uses `try/finally`.

## Concurrency

- **Per-brand objects**: a worker scraping `staud.clothing` touches no object any
  other worker touches.
- **The claim** is the exception, and the only place CAS is needed:
  `control/schedule/<domain>.json` is read with its etag, and written back with
  `IfMatch`. A refusal means another worker claimed it; the worker moves on.
- **`runs/<domain>/index.json`** is per-brand and so only contended if two workers
  run one brand, which the claim prevents.

## The store interface

Unchanged for all 40 public methods except the image ones, so nothing outside
`store/` needs rewriting. Underneath, `Catalog` is replaced by an implementation over:

```python
class ObjectStore(Protocol):
    def get(self, key: str) -> tuple[bytes, str] | None:  # (body, etag)
    def put(self, key: str, body: bytes, *, if_match: str | None = None,
            if_none_match: bool = False) -> str            # returns the new etag
    def list(self, prefix: str) -> list[str]
    def delete(self, key: str) -> None
```

Two implementations:

- `R2ObjectStore` — the bucket, via the same credentials the image store uses.
- `DirectoryObjectStore` — a local directory, with the same semantics including
  conditional writes. This is what the tests run against, so the 347 existing tests
  stay meaningful without a live bucket. `backend/storage/images.py` already models
  this two-implementation shape.

## What is lost

**SQL.** Questions currently answered with a query — how many brand-field pairs have
been searched, products per category, cost per brand — become Python over downloaded
objects. At 4,572 products that is under a second. At half a million it is minutes,
and some questions stop being worth asking. This is the trade being accepted
deliberately, not an oversight.

**Cross-brand product search** server-side. `search_products` currently does a LIKE
over every brand. It becomes a read of `site/index.json` (232 KB) and a filter, which
is what the page already does client-side.

## Where the scraper runs

Its own small image, not the API's. 27 of the 32 shown brands need only plain HTTP
and a bulk-JSON endpoint; the 4 that want a real browser are exactly the 4 that
currently produce nothing. So the image is `python:slim` plus the archive package —
no Chromium, a few hundred MB.

It runs wherever the R2 credentials are: `docker run` on a laptop, or on a VM, or as
a Render worker when the scheduler is turned on. The code does not know the difference.

## Testing

Every archive test builds `Catalog(tmp_path / "catalog.db")`. Those become
`Catalog(DirectoryObjectStore(tmp_path))`. The fixture changes; the assertions do not.
`DirectoryObjectStore` implements conditional writes, so the claim logic is tested for
real rather than mocked.

Two new test areas:

- The object store itself: conditional-write semantics on both implementations,
  including that a stale `if_match` is refused.
- Buffering: that a flush at 200 products keeps what came before, and that a store
  closed without flushing loses only the unflushed tail.

## Migration

One command reads the existing `catalog.db` and writes every object: 37 brands,
36 plans, 238 runs, 7,281 products, 11,085 observations, 17 rule books, 1,246 image
rows, 755 evidence rows, 10 scorecards. It is idempotent and does not delete the
SQLite file — that stays until the objects have been read back and checked.

## Stages

Each lands on its own, with the suite green:

1. `ObjectStore` and both implementations, with their own tests.
2. `Catalog` rewritten over it; every existing test passing against
   `DirectoryObjectStore`.
3. Migration, run against a copy, verified by comparing counts and spot-checking
   records.
4. The API reads the object store, so the hosted site serves products.
5. The scraper's Dockerfile, and `docker run` verified end to end.

Deleting `catalog.db` happens after stage 4 is confirmed working in production, not
before.
