# The archive in R2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the archive catalogue out of a 68 MB SQLite file on one laptop and into
R2 objects, so the scraper stores nothing locally and the hosted site can read what it
writes.

**Architecture:** An `ObjectStore` protocol with two implementations — R2 for real and
a local directory for tests — and `Catalog` rewritten over it, keeping the same 40
public methods so nothing outside `backend/archive/store/` changes. Per-brand objects,
because two workers never scrape the same brand; the only contended object is the
schedule row, claimed with a conditional write.

**Tech Stack:** Python 3.12, boto3 (already present for images), pydantic, pytest.

## Global Constraints

- Nothing outside `backend/archive/store/` may know which store is in use.
- `run_id` is a string `<iso-8601>-<6 hex>`, lexically sortable. Not an int.
- `product_id` is removed; image methods take `itemurl`.
- The 347 existing tests must pass with a fixture change only — no assertion rewrites.
- Conditional writes are required of both implementations, and tested on both.
- `catalogue/<domain>.json` is read and written whole; the sidebar must never read it.
  Counts come from `catalogue/<domain>.meta.json`.
- Writes buffer and flush every 200 products and on `close()`.
- `backend/archive/data/catalog.db` is not deleted by this plan.
- Line length 100, ruff and mypy clean, `pytest -m unit` green after every task.

---

### Task 1: The ObjectStore protocol and the directory implementation

**Files:**
- Create: `backend/archive/store/objects.py`
- Test: `tests/unit/archive/test_object_store.py`

**Interfaces:**
- Produces: `ObjectStore` protocol with `get(key) -> tuple[bytes, str] | None`,
  `put(key, body, *, if_match=None, if_none_match=False) -> str`,
  `list(prefix) -> list[str]`, `delete(key) -> None`; `DirectoryObjectStore(root: Path)`;
  `Conflict(RuntimeError)` raised when a condition fails.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from backend.archive.store.objects import Conflict, DirectoryObjectStore


@pytest.fixture()
def store(tmp_path):
    return DirectoryObjectStore(tmp_path)


@pytest.mark.unit
def test_put_then_get_round_trips(store):
    etag = store.put("a/b.json", b'{"x":1}')
    assert store.get("a/b.json") == (b'{"x":1}', etag)


@pytest.mark.unit
def test_get_missing_is_none_not_an_error(store):
    assert store.get("nope.json") is None


@pytest.mark.unit
def test_create_if_absent_refuses_the_second_writer(store):
    store.put("claim.json", b"first", if_none_match=True)
    with pytest.raises(Conflict):
        store.put("claim.json", b"second", if_none_match=True)
    assert store.get("claim.json")[0] == b"first"


@pytest.mark.unit
def test_replace_needs_the_current_etag(store):
    etag = store.put("row.json", b"one")
    store.put("row.json", b"two", if_match=etag)
    with pytest.raises(Conflict):
        store.put("row.json", b"three", if_match=etag)   # stale
    assert store.get("row.json")[0] == b"two"


@pytest.mark.unit
def test_list_returns_keys_under_a_prefix_only(store):
    store.put("runs/a/1.json", b"{}")
    store.put("runs/a/2.json", b"{}")
    store.put("runs/b/1.json", b"{}")
    assert store.list("runs/a/") == ["runs/a/1.json", "runs/a/2.json"]


@pytest.mark.unit
def test_a_key_cannot_escape_the_root(store):
    with pytest.raises(ValueError):
        store.put("../outside.json", b"{}")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `venv/bin/pytest tests/unit/archive/test_object_store.py -q`
Expected: collection error, `ModuleNotFoundError: backend.archive.store.objects`

- [ ] **Step 3: Implement**

```python
"""Where the archive keeps its objects.

Two implementations behind one protocol: a directory during development and in the
tests, R2 in production. Both support conditional writes, because that is what lets
parallel workers claim a brand without a database — and a test that mocked it would
be testing nothing.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol


class Conflict(RuntimeError):
    """A conditional write was refused: someone else got there first."""


class ObjectStore(Protocol):
    def get(self, key: str) -> tuple[bytes, str] | None: ...
    def put(self, key: str, body: bytes, *, if_match: str | None = None,
            if_none_match: bool = False) -> str: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, key: str) -> None: ...


def _etag(body: bytes) -> str:
    return hashlib.md5(body).hexdigest()  # noqa: S324 - matches S3 etag semantics


class DirectoryObjectStore:
    def __init__(self, root: Path):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"object key escapes the store root: {key!r}")
        return candidate

    def get(self, key: str) -> tuple[bytes, str] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        body = path.read_bytes()
        return body, _etag(body)

    def put(self, key: str, body: bytes, *, if_match: str | None = None,
            if_none_match: bool = False) -> str:
        path = self._path(key)
        current = self.get(key)
        if if_none_match and current is not None:
            raise Conflict(f"{key} already exists")
        if if_match is not None and (current is None or current[1] != if_match):
            raise Conflict(f"{key} changed under us")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return _etag(body)

    def list(self, prefix: str) -> list[str]:
        base = self._root
        return sorted(
            str(p.relative_to(base))
            for p in base.rglob("*")
            if p.is_file() and str(p.relative_to(base)).startswith(prefix)
        )

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def dumps(value) -> bytes:
    """One JSON encoding for every object, so an etag is stable across writes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def loads(body: bytes):
    return json.loads(body)
```

- [ ] **Step 4: Run them and watch them pass**

Run: `venv/bin/pytest tests/unit/archive/test_object_store.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/archive/store/objects.py tests/unit/archive/test_object_store.py
git commit -m "feat(archive): an object store with conditional writes"
```

---

### Task 2: The R2 implementation, and the same tests run against it

**Files:**
- Modify: `backend/archive/store/objects.py`
- Test: `tests/unit/archive/test_object_store.py`

**Interfaces:**
- Consumes: `ObjectStore`, `Conflict` from Task 1.
- Produces: `R2ObjectStore(bucket, client=None, prefix="")`; `object_store()` which
  returns R2 when `R2_*` is configured and a directory otherwise.

- [ ] **Step 1: Write the failing test — a fake S3 client that enforces the conditions**

```python
@pytest.mark.unit
def test_r2_store_maps_preconditions_onto_conflict():
    from backend.archive.store.objects import R2ObjectStore
    store = R2ObjectStore("bucket", client=FakeS3())
    etag = store.put("k.json", b"one")
    with pytest.raises(Conflict):
        store.put("k.json", b"two", if_none_match=True)
    store.put("k.json", b"two", if_match=etag)
    with pytest.raises(Conflict):
        store.put("k.json", b"three", if_match=etag)
    assert store.get("k.json")[0] == b"two"
```

`FakeS3` lives in the same test module and raises
`ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")` when a condition
does not hold, which is exactly what the live probe against R2 returned.

- [ ] **Step 2: Run and watch it fail** — `ImportError: cannot import name 'R2ObjectStore'`

- [ ] **Step 3: Implement**

```python
class R2ObjectStore:
    """Cloudflare R2 over its S3 API. The same bucket the images already use."""

    def __init__(self, bucket: str, client=None, prefix: str = ""):
        self._bucket = bucket
        self._prefix = prefix
        self._client = client if client is not None else _r2_client()

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> tuple[bytes, str] | None:
        from botocore.exceptions import ClientError
        try:
            r = self._client.get_object(Bucket=self._bucket, Key=self._key(key))
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        return r["Body"].read(), r["ETag"].strip('"')

    def put(self, key: str, body: bytes, *, if_match: str | None = None,
            if_none_match: bool = False) -> str:
        from botocore.exceptions import ClientError
        kwargs = {"Bucket": self._bucket, "Key": self._key(key), "Body": body,
                  "ContentType": "application/json"}
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        if if_match is not None:
            kwargs["IfMatch"] = if_match
        try:
            r = self._client.put_object(**kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("PreconditionFailed", "412"):
                raise Conflict(f"{key} changed under us") from e
            raise
        return r["ETag"].strip('"')

    def list(self, prefix: str) -> list[str]:
        keys = []
        pages = self._client.get_paginator("list_objects_v2")
        for page in pages.paginate(Bucket=self._bucket, Prefix=self._key(prefix)):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"][len(self._prefix):])
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._key(key))
```

Plus `_r2_client()` reading `config.config`, and:

```python
def object_store(local_root: Path | None = None) -> ObjectStore:
    """R2 when it is configured, a directory when it is not. One answer to
    "where does the archive keep things", chosen in one place."""
    from config.config import config
    if config.R2_ACCOUNT_ID and config.R2_ACCESS_KEY_ID and config.R2_BUCKET:
        return R2ObjectStore(config.R2_BUCKET, prefix="archive-store/")
    return DirectoryObjectStore(local_root or Path("backend/archive/data/objects"))
```

- [ ] **Step 4: Run and watch it pass** — `venv/bin/pytest tests/unit/archive/test_object_store.py -q`

- [ ] **Step 5: Probe the real bucket once**, to confirm the mapping matches live R2:

```bash
venv/bin/python -c "
from backend.archive.store.objects import R2ObjectStore, Conflict
from config.config import config
s = R2ObjectStore(config.R2_BUCKET, prefix='_probe/')
e = s.put('x.json', b'one')
try:
    s.put('x.json', b'two', if_none_match=True); print('FAIL: not refused')
except Conflict: print('refused correctly')
s.delete('x.json')
"
```

- [ ] **Step 6: Commit**

---

### Task 3: Catalog over the object store — brands, plans, rules, evidence

**Files:**
- Create: `backend/archive/store/catalog_objects.py`
- Test: `tests/unit/archive/test_catalog_objects.py`

The small per-brand documents first, because they are read-modify-write of one key and
exercise the layout without the buffering.

**Interfaces:**
- Consumes: `ObjectStore`, `dumps`, `loads`.
- Produces: `Catalog(store: ObjectStore)` with `upsert_brand`, `get_brand`,
  `list_brands`, `set_brand_state`, `get_brand_state`, `save_plan`, `load_plan`,
  `save_recipe_book`, `load_recipe_book`, `record_evidence`, `load_evidence`, `close`.

- [ ] **Step 1: Write the failing tests** — the existing assertions from
  `tests/unit/archive/test_catalog_core.py`, against the new constructor:

```python
@pytest.mark.unit
def test_brand_and_state_round_trip(store):
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    assert cat.get_brand("kuurth.com").homepage_url == "https://kuurth.com"
    assert cat.get_brand_state("kuurth.com") == "new"
    cat.set_brand_state("kuurth.com", "active")
    assert cat.get_brand_state("kuurth.com") == "active"
```

- [ ] **Step 2: Run, watch it fail**
- [ ] **Step 3: Implement those eleven methods over `brands/<domain>.json`,
  `plans/<domain>.json`, `rules/<domain>.json`, `evidence/<domain>.json`**
- [ ] **Step 4: Run, watch it pass**
- [ ] **Step 5: Commit**

---

### Task 4: Runs, and the string run id

**Files:** modify `catalog_objects.py`; test in `test_catalog_objects.py`

**Interfaces:**
- Produces: `open_run(domain, mode) -> str`, `finalize_run(run_id, exit_status,
  coverage)`, `latest_run(domain) -> dict | None`, `run_ids(domain) -> list[str]`.
  Run ids are `<iso-8601>-<6 hex>` and sort by time.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.unit
def test_run_ids_sort_by_time(store):
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="k.com", homepage_url="https://k.com"))
    first = cat.open_run("k.com", "full")
    second = cat.open_run("k.com", "delta")
    assert first < second
    assert cat.run_ids("k.com") == [first, second]


@pytest.mark.unit
def test_latest_run_is_the_last_finalised_one(store):
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="k.com", homepage_url="https://k.com"))
    run = cat.open_run("k.com", "full")
    cat.finalize_run(run, 0, COV)
    assert cat.latest_run("k.com")["id"] == run
    assert cat.latest_run("k.com")["exit_status"] == 0
```

- [ ] **Steps 2-5:** fail, implement over `runs/<domain>/<run>.json` +
  `runs/<domain>/index.json`, pass, commit.

---

### Task 5: The catalogue, buffered

**Files:** modify `catalog_objects.py`; test in `test_catalog_objects.py`

**Interfaces:**
- Produces: `record_product(domain, run_id, record, change_hint) -> bool`,
  `mark_seen`, `get_change_hints`, `current_products(domain, live_only=True)`,
  `observation_count`, `rewrite_field`, `live_product_counts`, `status_rows`,
  `search_products(domains, needle, limit) -> list[tuple[str, dict]]`, `flush()`.
  `FLUSH_EVERY = 200`.

- [ ] **Step 1: Write the failing tests** — carried over from
  `test_catalog_products.py`, plus two new ones for the buffering:

```python
@pytest.mark.unit
def test_products_survive_a_flush_mid_run(store):
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="k.com", homepage_url="https://k.com"))
    run = cat.open_run("k.com", "full")
    for i in range(250):                       # crosses FLUSH_EVERY
        cat.record_product("k.com", run, rec(f"p{i}"), None)
    cat.finalize_run(run, 0, COV)
    cat.close()
    assert len(Catalog(store).current_products("k.com")) == 250


@pytest.mark.unit
def test_the_sidebar_count_does_not_read_the_catalogue(store, monkeypatch):
    """live_product_counts must read the small meta object, not 55 MB of records."""
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="k.com", homepage_url="https://k.com"))
    run = cat.open_run("k.com", "full")
    cat.record_product("k.com", run, rec("p1"), None)
    cat.finalize_run(run, 0, COV)
    cat.close()

    read = []
    inner = store.get
    monkeypatch.setattr(store, "get", lambda k: (read.append(k), inner(k))[1])
    assert Catalog(store).live_product_counts() == {"k.com": 1}
    assert not any(k.startswith("catalogue/") and not k.endswith(".meta.json")
                   for k in read)
```

- [ ] **Steps 2-5:** fail, implement over `catalogue/<domain>.json`,
  `catalogue/<domain>.meta.json` and `history/<domain>/<run>.json`, pass, commit.

---

### Task 6: Images, keyed by itemurl

**Files:** modify `catalog_objects.py`, `backend/archive/images.py`,
`backend/archive/runner/archive_images.py`; tests in `test_images.py`,
`test_archive_images.py`

**Interfaces:**
- Produces: `record_image(domain, itemurl, url, content_hash, stored_url)`,
  `stored_image_urls(domain, itemurl) -> set[str]`, `archived_images(domain)`,
  `images_awaiting_archive(domain) -> list[tuple[str, list[str]]]`,
  `stored_image_count(domain) -> int`. `product_id_for` and `local_image_files` are
  removed — the local files they served are deleted and every row now has a
  `stored_url`.

- [ ] **Step 1: Write the failing tests** — the existing image assertions with
  `itemurl` in place of `product_id`.
- [ ] **Steps 2-5:** fail, implement over `images/<domain>.json`, pass, commit.

---

### Task 7: The rest — scorecards, requests, hosts, extraction versions, schedule

**Files:** modify `catalog_objects.py`; test in `test_catalog_objects.py`,
`test_scheduler.py`

**Interfaces:**
- Produces: `save_scorecard`, `scorecards`, `record_requests`, `host_stats`,
  `extraction_version_for`, `set_extraction_version`, and the `Scheduler` methods
  backed by `control/schedule/<domain>.json` with `claim_next` using a conditional
  write.

- [ ] **Step 1: Write the failing test that matters most — the claim**

```python
@pytest.mark.unit
def test_two_workers_cannot_claim_the_same_brand(store):
    sched = Scheduler(store)
    sched.add("k.com", cadence_seconds=0)
    assert sched.claim_next("worker-a") is not None
    assert sched.claim_next("worker-b") is None
```

- [ ] **Steps 2-5:** fail, implement, pass, commit.

---

### Task 8: Switch every caller, delete the SQLite store

**Files:** modify `backend/archive/store/__init__.py`,
`backend/archive/runner/cli.py`, `backend/archive/runner/daemon.py`,
`backend/api/archive_routes.py`; delete `backend/archive/store/catalog.py`,
`backend/archive/store/schema.sql`; rename `catalog_objects.py` to `catalog.py`

- [ ] **Step 1:** `venv/bin/pytest -m unit -q` — all 347 plus the new ones green
- [ ] **Step 2:** `venv/bin/python -c "import backend.app"` succeeds
- [ ] **Step 3:** `--db PATH` becomes `--objects PATH` on every CLI subcommand, and
  `ARCHIVE_DB` becomes `ARCHIVE_OBJECTS` in `archive_routes.py`
- [ ] **Step 4:** ruff, ruff format, mypy clean
- [ ] **Step 5:** Commit

---

### Task 9: Migrate the existing catalogue

**Files:** Create `backend/archive/store/migrate_sqlite.py`;
Test: `tests/unit/archive/test_migrate_sqlite.py`

**Interfaces:**
- Produces: `migrate(db_path: Path, store: ObjectStore) -> dict[str, int]` returning
  counts written per kind, and `python -m backend.archive.store.migrate_sqlite`.

- [ ] **Step 1: Write the failing test** — build a small SQLite catalogue with the
  old schema, migrate it, and assert the objects read back identically:

```python
@pytest.mark.unit
def test_migration_preserves_products_and_history(tmp_path):
    legacy = _legacy_db(tmp_path)          # 2 brands, 3 products, 2 observations
    store = DirectoryObjectStore(tmp_path / "objects")
    counts = migrate(legacy, store)
    assert counts["products"] == 3
    cat = Catalog(store)
    assert len(cat.current_products("k.com")) == 2
    assert cat.observation_count("k.com") == 2
```

- [ ] **Step 2: Run, watch it fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, watch it pass**
- [ ] **Step 5: Run it against a COPY of the real catalogue into a local directory,
  and compare counts against the SQL:**

```bash
cp backend/archive/data/catalog.db /tmp/probe.db
venv/bin/python -m backend.archive.store.migrate_sqlite /tmp/probe.db --objects /tmp/objects
```

Expected: `brands 37, plans 36, runs 238, products 7281, observations 11085,
rules 17, images 1246, evidence 755, scorecards 10`

- [ ] **Step 6: Commit**

---

### Task 10: The API reads objects, and the site serves products

**Files:** modify `backend/api/archive_routes.py`;
test `tests/unit/api/test_archive_routes.py`

- [ ] **Step 1:** the fixture builds a `DirectoryObjectStore`, not a `catalog.db`
- [ ] **Step 2:** `NoCatalogue` is raised when `brands/` lists nothing, so a bucket
      with no archive in it still reports honestly rather than showing 32 empty brands
- [ ] **Step 3:** all 13 route tests pass
- [ ] **Step 4:** run the migration against the real catalogue into R2, then confirm
      `/api/archive/health` reports 4,572 products with `ARCHIVE_OBJECTS` unset
- [ ] **Step 5:** Commit

---

### Task 11: The scraper's own image

**Files:** Create `Dockerfile.scraper`, `.dockerignore`

- [ ] **Step 1:** `python:3.12-slim`, `requirements.txt` minus playwright, the
      `backend/archive` and `config` packages, entrypoint
      `python -m backend.archive.runner.cli`
- [ ] **Step 2:** `docker build -f Dockerfile.scraper -t archive-scraper .`
- [ ] **Step 3:** `docker run --env-file config/.env archive-scraper status` prints the
      fleet, proving it reads R2 with no local state
- [ ] **Step 4:** `.dockerignore` excluding `venv`, `node_modules`, `backend/archive/data`
- [ ] **Step 5:** Commit

---

## Self-review

**Spec coverage.** Object layout → Tasks 3-7. Identity changes → Tasks 4 and 6.
Buffering → Task 5. Concurrency/CAS → Tasks 1, 2 and 7. `site/` objects → **gap**, see
below. What is lost → Task 5's `search_products` signature change. Where it runs →
Task 11. Testing → the `DirectoryObjectStore` fixture throughout. Migration → Task 9.

**Gap found:** the spec's `site/manifest.json`, `site/index.json` and
`site/<domain>.json` have no task. They are what makes the hosted page fast, but the
API can serve from `catalogue/` and `.meta.json` without them, so they are a
follow-up rather than part of this move. Recorded here deliberately instead of
being smuggled into Task 10.

**Type consistency.** `run_id: str` used consistently in Tasks 4, 5, 7 and 9.
`itemurl: str` replaces `product_id: int` in Task 6 and nowhere is the old name used
after it. `search_products` returns `list[tuple[str, dict]]` in Task 5 and
`archive_routes.py` already unpacks that shape.
