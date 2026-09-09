# Archive v2 — Milestone 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the new `backend/archive/` body far enough that the open-Shopify brands (~18 of 36) can be planned, calibrated, scraped with history, delta-scraped, and reported in a fleet coverage matrix — pure HTTP, zero browser, zero LLM.

**Architecture:** Connector + compiler per `docs/superpowers/specs/2026-08-27-archive-v2-design.md`. Pure domain models at the center; transports injected into connectors; planner composes a (T,D,F,C) coordinate into a ScrapePlan; runner executes the lifecycle (scope → plan → calibrate → promote → monitor) against an append-only SQLite store; verify turns channel counts into coverage verdicts.

**Tech Stack:** Python 3.11+, pydantic v2, httpx (new dep), PyYAML (new dep), sqlite3 (stdlib), pytest (existing suite conventions in `tests/unit/`).

## Global Constraints

- All new code lives under `backend/archive/`; it MUST NOT import from `backend/scraper/`, `backend/stages/`, or `backend/prod_page_v2/` (the new body is standalone).
- Absolute imports rooted at `backend.archive.*` (repo root is on `sys.path` via `tests/conftest.py`; CLI runs as `python -m backend.archive.runner.cli` from repo root).
- Every test is hermetic: no network, no live sites. All HTTP goes through `httpx.MockTransport`; DBs use `tmp_path`. Mark every test `@pytest.mark.unit`.
- No live-site traffic from any test, ever, without explicit prior announcement to Bhavya (house rule). This plan contains zero live tests.
- Timestamps are UTC ISO-8601 strings (`datetime.now(timezone.utc).isoformat()`).
- SQLite opened with WAL mode; `store/catalog.py` is the only module that touches the DB.
- Runs/observations are append-only: no task may delete or overwrite prior run data.
- Follow existing test style in `tests/unit/` (plain functions, `tmp_path`, rationale comments on regression guards).

## File Structure

```
backend/archive/__init__.py
backend/archive/domain/__init__.py
backend/archive/domain/brand.py        # axes enums, Capability, Brand, PlanAttempt, ScrapePlan
backend/archive/domain/product.py      # ProductRef, ProductRecord, WATCHED_FIELDS
backend/archive/domain/run.py          # Coverage
backend/archive/transport.py           # Response, Transport protocol, HttpxTransport (T0 + browser-grade headers)
backend/archive/fingerprint.py         # probe(domain, transport) -> Capability
backend/archive/connectors/__init__.py # get_connector(plan) registry
backend/archive/connectors/base.py     # Connector protocol, ChannelBlocked/SkipProduct
backend/archive/connectors/shopify.py  # bulk /products.json discover+fetch
backend/archive/connectors/sitemap.py  # robots→sitemap→product ProductRefs with lastmod
backend/archive/planner.py             # compose_plan(capability, tried) -> ScrapePlan
backend/archive/store/__init__.py
backend/archive/store/schema.sql
backend/archive/store/catalog.py       # Catalog: the only DB gateway
backend/archive/verify.py              # field_fill_rates, assess -> Coverage
backend/archive/runner/__init__.py
backend/archive/runner/run.py          # select_delta, run_brand (lifecycle)
backend/archive/runner/cli.py          # plan | scrape | status; brands.yml loader
backend/archive/brands.yml             # the 36-brand target list with notes
backend/archive/README.md              # the body's own map (written last)
tests/unit/archive/…                   # one test module per source module
tests/unit/archive/fixtures/…          # crafted JSON/XML fixtures
```

---

### Task 1: Package skeleton, dependencies, tooling ratchet, CI trigger fix

**Files:**
- Create: `backend/archive/__init__.py`, `backend/archive/domain/__init__.py`, `backend/archive/connectors/__init__.py`, `backend/archive/store/__init__.py`, `backend/archive/runner/__init__.py`, `tests/unit/archive/__init__.py`
- Modify: `requirements.txt`, `pyproject.toml`, `.github/workflows/pr.yml`
- Test: `tests/unit/archive/test_package.py`

**Interfaces:**
- Consumes: nothing.
- Produces: importable `backend.archive` package; `httpx`, `pyyaml`, `pydantic` installable from `requirements.txt`; mypy/ruff cover `backend/archive`; CI actually fires on `master`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_package.py
import pytest


@pytest.mark.unit
def test_archive_package_imports():
    import backend.archive  # noqa: F401


@pytest.mark.unit
def test_archive_does_not_import_legacy_packages():
    """The new body must stand alone (spec §3.2 / Global Constraints)."""
    import sys

    import backend.archive  # noqa: F401

    forbidden = [m for m in sys.modules if m.startswith(("scraper", "stages", "prod_page_v2"))]
    assert forbidden == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_package.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'backend.archive'`

- [ ] **Step 3: Create the package skeleton and dependency/tooling edits**

Create each `__init__.py` above containing only a module docstring, e.g. `backend/archive/__init__.py`:

```python
"""Archive v2 — the scheduled brand-scraping body (spec: docs/superpowers/specs/2026-08-27-archive-v2-design.md)."""
```

Append to `requirements.txt`:

```
# archive v2 (backend/archive)
httpx>=0.27
pydantic>=2.5
PyYAML>=6.0
```

In `pyproject.toml`, change the mypy files line:

```toml
[tool.mypy]
files = ["tests", "backend/archive"]
```

In `.github/workflows/pr.yml`, change both triggers from `branches: [main]` to `branches: [master]`, and extend the ruff steps to also cover the new package:

```yaml
      - run: ruff check tests/ backend/archive/
      - run: ruff format --check tests/ backend/archive/
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_package.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive tests/unit/archive requirements.txt pyproject.toml .github/workflows/pr.yml
git commit -m "feat(archive): package skeleton, deps, tooling ratchet, fix CI trigger to master"
```

---

### Task 2: Domain models

**Files:**
- Create: `backend/archive/domain/brand.py`, `backend/archive/domain/product.py`, `backend/archive/domain/run.py`
- Test: `tests/unit/archive/test_domain.py`

**Interfaces:**
- Consumes: pydantic.
- Produces (exact, used by every later task):
  - `TransportLevel(str, Enum)`: `T0 T1 T2 T3 T4`; `DiscoveryChannel(str, Enum)`: `BULK_JSON SITEMAP CATEGORY_PAGES AGENT`; `FetchChannel(str, Enum)`: `PLATFORM_JSON STRUCTURED_DATA NETWORK_API RECIPES LLM`; `ChangeSignal(str, Enum)`: `PER_ITEM COUNTS NONE`
  - `Capability(domain, platform, transport, bulk_json, sitemap_url, password_gated, challenged, evidence)`
  - `Brand(domain, homepage_url, display_name=None, notes=None)`
  - `PlanAttempt(composition, failed_at, reason)`
  - `ScrapePlan(domain, transport, discovery, fetch, change_signal, status, tried, fingerprinted_at, stale=False)` with `status in {"ready","skip_gated","needs_attention"}` and `composition` property `"{t}×{d}×{f}×{c}"`
  - `ProductRef(url, change_hint=None, payload=None)`; `ProductRecord(canonical_url, product_title, product_code=None, brand=None, description=None, price=None, full_price=None, currency=None, in_stock=None, sizes=[], images=[], categories=[], raw={})`; `WATCHED_FIELDS = ("price","full_price","in_stock","sizes")`
  - `Coverage(extracted, channel_counts, coverage_pct, field_fill, verdict, reasons=[])`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_domain.py
import pytest

from backend.archive.domain.brand import (
    Capability,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    PlanAttempt,
    ScrapePlan,
    TransportLevel,
)
from backend.archive.domain.product import WATCHED_FIELDS, ProductRecord, ProductRef


@pytest.mark.unit
def test_scrape_plan_composition_string():
    plan = ScrapePlan(
        domain="kuurth.com",
        transport=TransportLevel.T0,
        discovery=DiscoveryChannel.BULK_JSON,
        fetch=FetchChannel.PLATFORM_JSON,
        change_signal=ChangeSignal.PER_ITEM,
        status="ready",
        fingerprinted_at="2026-08-27T00:00:00+00:00",
    )
    assert plan.composition == "t0×bulk_json×platform_json×per_item"
    assert plan.tried == [] and plan.stale is False


@pytest.mark.unit
def test_plan_round_trips_through_json():
    """Plans are persisted as JSON in SQLite — serialization must be lossless."""
    plan = ScrapePlan(
        domain="x.com",
        transport=TransportLevel.T4,
        discovery=DiscoveryChannel.BULK_JSON,
        fetch=FetchChannel.PLATFORM_JSON,
        change_signal=ChangeSignal.NONE,
        status="skip_gated",
        tried=[PlanAttempt(composition="t0×bulk_json×platform_json×per_item", failed_at="2026-08-27T00:00:00+00:00", reason="challenged")],
        fingerprinted_at="2026-08-27T00:00:00+00:00",
    )
    assert ScrapePlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.unit
def test_product_record_defaults_and_watched_fields():
    rec = ProductRecord(canonical_url="https://kuurth.com/products/x", product_title="X")
    assert rec.sizes == [] and rec.images == [] and rec.raw == {}
    assert WATCHED_FIELDS == ("price", "full_price", "in_stock", "sizes")


@pytest.mark.unit
def test_capability_and_ref():
    cap = Capability(domain="kuurth.com", platform="shopify", transport=TransportLevel.T0,
                     bulk_json=True, sitemap_url="https://kuurth.com/sitemap.xml",
                     password_gated=False, challenged=False)
    assert cap.evidence == {}
    assert ProductRef(url="https://kuurth.com/products/x").change_hint is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_domain.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/domain/brand.py
"""Capability axes and planning models (spec §4.0, §4.3)."""
from enum import Enum

from pydantic import BaseModel, Field


class TransportLevel(str, Enum):
    T0 = "t0"  # plain HTTP
    T1 = "t1"  # browser-grade headers
    T2 = "t2"  # real browser + stealth
    T3 = "t3"  # browser-only (TLS fingerprinting)
    T4 = "t4"  # gated (password/members)


class DiscoveryChannel(str, Enum):
    BULK_JSON = "bulk_json"
    SITEMAP = "sitemap"
    CATEGORY_PAGES = "category_pages"
    AGENT = "agent"


class FetchChannel(str, Enum):
    PLATFORM_JSON = "platform_json"
    STRUCTURED_DATA = "structured_data"
    NETWORK_API = "network_api"
    RECIPES = "recipes"
    LLM = "llm"


class ChangeSignal(str, Enum):
    PER_ITEM = "per_item"
    COUNTS = "counts"
    NONE = "none"


class Capability(BaseModel):
    domain: str
    platform: str | None = None
    transport: TransportLevel
    bulk_json: bool = False
    sitemap_url: str | None = None
    password_gated: bool = False
    challenged: bool = False
    evidence: dict[str, str] = Field(default_factory=dict)


class Brand(BaseModel):
    domain: str
    homepage_url: str
    display_name: str | None = None
    notes: str | None = None


class PlanAttempt(BaseModel):
    composition: str
    failed_at: str
    reason: str


class ScrapePlan(BaseModel):
    domain: str
    transport: TransportLevel
    discovery: DiscoveryChannel
    fetch: FetchChannel
    change_signal: ChangeSignal
    status: str  # "ready" | "skip_gated" | "needs_attention"
    tried: list[PlanAttempt] = Field(default_factory=list)
    fingerprinted_at: str
    stale: bool = False

    @property
    def composition(self) -> str:
        return f"{self.transport.value}×{self.discovery.value}×{self.fetch.value}×{self.change_signal.value}"
```

```python
# backend/archive/domain/product.py
"""Product models (E0005-aligned core fields; spec §4.4)."""
from pydantic import BaseModel, Field

WATCHED_FIELDS = ("price", "full_price", "in_stock", "sizes")


class ProductRef(BaseModel):
    url: str
    change_hint: str | None = None
    payload: dict | None = None  # bulk feeds carry the full record along


class ProductRecord(BaseModel):
    canonical_url: str
    product_title: str
    product_code: str | None = None
    brand: str | None = None
    description: str | None = None
    price: float | None = None
    full_price: float | None = None
    currency: str | None = None
    in_stock: bool | None = None
    sizes: list[dict] = Field(default_factory=list)  # [{"size": "M", "available": True}]
    images: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)
```

```python
# backend/archive/domain/run.py
"""Run/coverage models (spec §4.5)."""
from pydantic import BaseModel, Field


class Coverage(BaseModel):
    extracted: int
    channel_counts: dict[str, int] = Field(default_factory=dict)
    coverage_pct: float
    field_fill: dict[str, float] = Field(default_factory=dict)
    verdict: str  # "ok" | "degraded" | "failed"
    reasons: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_domain.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/domain tests/unit/archive/test_domain.py
git commit -m "feat(archive): domain models — capability axes, plans, products, coverage"
```

---

### Task 3: Transport

**Files:**
- Create: `backend/archive/transport.py`
- Test: `tests/unit/archive/test_transport.py`

**Interfaces:**
- Consumes: `TransportLevel` from Task 2; httpx.
- Produces: `Transport` protocol with `level: TransportLevel` and `get(url: str) -> httpx.Response` (httpx's own Response is the response type everywhere); `HttpxTransport(level=TransportLevel.T0, client: httpx.Client | None = None)` sending `BROWSER_HEADERS`, `follow_redirects=True`, `timeout=15.0`; module constant `BROWSER_HEADERS: dict[str, str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_transport.py
import httpx
import pytest

from backend.archive.domain.brand import TransportLevel
from backend.archive.transport import BROWSER_HEADERS, HttpxTransport


@pytest.mark.unit
def test_get_sends_browser_headers_and_follows_redirects():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("user-agent")
        if request.url.path == "/":
            return httpx.Response(301, headers={"location": "https://www.x.com/home"})
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler), headers=BROWSER_HEADERS, follow_redirects=True)
    t = HttpxTransport(client=client)
    resp = t.get("https://x.com/")
    assert resp.status_code == 200 and str(resp.url) == "https://www.x.com/home"
    assert "Mozilla/5.0" in seen["ua"]
    assert t.level == TransportLevel.T0


@pytest.mark.unit
def test_get_does_not_raise_on_4xx():
    """Fingerprinting interprets 429/403/404 as evidence, not errors."""
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    assert HttpxTransport(client=client).get("https://x.com/products.json").status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_transport.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/transport.py
"""Transports: how requests are made. Injected into connectors, never owned by them (spec §4.0)."""
from typing import Protocol

import httpx

from backend.archive.domain.brand import TransportLevel

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class Transport(Protocol):
    level: TransportLevel

    def get(self, url: str) -> httpx.Response: ...


class HttpxTransport:
    """T0/T1 plain-HTTP transport with a browser-grade header profile."""

    def __init__(self, level: TransportLevel = TransportLevel.T0, client: httpx.Client | None = None):
        self.level = level
        self._client = client or httpx.Client(headers=BROWSER_HEADERS, follow_redirects=True, timeout=15.0)

    def get(self, url: str) -> httpx.Response:
        return self._client.get(url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_transport.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/transport.py tests/unit/archive/test_transport.py
git commit -m "feat(archive): injectable HTTP transport with browser-grade headers"
```

---

### Task 4: Fingerprint

**Files:**
- Create: `backend/archive/fingerprint.py`
- Test: `tests/unit/archive/test_fingerprint.py`

**Interfaces:**
- Consumes: `Transport` (Task 3), `Capability`, `TransportLevel` (Task 2).
- Produces: `probe(domain: str, transport: Transport) -> Capability`. Behavior: GET `https://{domain}/robots.txt` (read `Sitemap:` line; fall back to checking `https://{domain}/sitemap.xml` returns 200), GET `https://{domain}/products.json?limit=1` (open ⇔ 200 + `"products"` key), GET `https://{domain}/` (password ⇔ final URL path `/password` or title contains "password"/"opening soon"; shopify ⇔ body contains `cdn.shopify` or `myshopify.com`; woocommerce ⇔ body contains `woocommerce`). `challenged=True` when products.json or homepage return 429/403 or a challenge page (body contains "Verifying your connection"). `transport` is `T4` when gated, `T2` when challenged, else `T0`. Evidence dict records raw observations (`{"products_json": "200-open", "homepage": "200", "robots": "sitemap"}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_fingerprint.py
import httpx
import pytest

from backend.archive.domain.brand import TransportLevel
from backend.archive.fingerprint import probe
from backend.archive.transport import HttpxTransport

SHOP_HOME = '<html><head><title>KUURTH</title></head><body><script src="https://cdn.shopify.com/x.js"></script></body></html>'
PW_HOME = "<html><head><title>Password – colt</title></head><body>opening soon</body></html>"


def make_transport(routes: dict[str, httpx.Response]) -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(request.url.path, httpx.Response(404))

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


@pytest.mark.unit
def test_open_shopify_capability():
    t = make_transport({
        "/robots.txt": httpx.Response(200, text="User-agent: *\nSitemap: https://kuurth.com/sitemap.xml\n"),
        "/products.json": httpx.Response(200, json={"products": [{"id": 1}]}),
        "/": httpx.Response(200, text=SHOP_HOME),
    })
    cap = probe("kuurth.com", t)
    assert cap.platform == "shopify" and cap.bulk_json is True
    assert cap.sitemap_url == "https://kuurth.com/sitemap.xml"
    assert cap.transport == TransportLevel.T0
    assert not cap.password_gated and not cap.challenged


@pytest.mark.unit
def test_password_gated_store():
    t = make_transport({
        "/robots.txt": httpx.Response(404),
        "/products.json": httpx.Response(302, headers={"location": "https://coltmcr.com/password"}),
        "/password": httpx.Response(200, text=PW_HOME),
        "/": httpx.Response(302, headers={"location": "https://coltmcr.com/password"}),
        "/sitemap.xml": httpx.Response(404),
    })
    cap = probe("coltmcr.com", t)
    assert cap.password_gated is True and cap.transport == TransportLevel.T4


@pytest.mark.unit
def test_challenged_store_needs_browser():
    """staud.clothing-style: every plain-HTTP request 429s (probe of 2026-08-26)."""
    t = make_transport({
        "/robots.txt": httpx.Response(429),
        "/products.json": httpx.Response(429),
        "/": httpx.Response(429),
        "/sitemap.xml": httpx.Response(429),
    })
    cap = probe("staud.clothing", t)
    assert cap.challenged is True and cap.bulk_json is False
    assert cap.transport == TransportLevel.T2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_fingerprint.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/fingerprint.py
"""One polite HTTP round per brand → Capability (spec §4.0; ~4 GETs, seconds, $0)."""
import re

from backend.archive.domain.brand import Capability, TransportLevel
from backend.archive.transport import Transport

_CHALLENGE_MARKERS = ("verifying your connection", "checking your browser")
_PASSWORD_MARKERS = ("password", "opening soon", "coming soon")


def probe(domain: str, transport: Transport) -> Capability:
    base = f"https://{domain}"
    evidence: dict[str, str] = {}

    sitemap_url = None
    robots = transport.get(f"{base}/robots.txt")
    if robots.status_code == 200:
        m = re.search(r"(?im)^sitemap:\s*(\S+)", robots.text)
        if m:
            sitemap_url = m.group(1)
            evidence["robots"] = "sitemap"
    if sitemap_url is None:
        sm = transport.get(f"{base}/sitemap.xml")
        if sm.status_code == 200 and "<" in sm.text[:200]:
            sitemap_url = f"{base}/sitemap.xml"
            evidence["robots"] = "direct-sitemap"

    pj = transport.get(f"{base}/products.json?limit=1")
    bulk_json = pj.status_code == 200 and '"products"' in pj.text[:200]
    evidence["products_json"] = f"{pj.status_code}-{'open' if bulk_json else 'closed'}"

    home = transport.get(f"{base}/")
    body = home.text.lower() if home.status_code == 200 else ""
    evidence["homepage"] = str(home.status_code)

    password_gated = "/password" in str(home.url) or any(
        m in _title(body) for m in _PASSWORD_MARKERS
    )
    challenged = (
        home.status_code in (403, 429)
        or pj.status_code in (403, 429)
        or any(m in body for m in _CHALLENGE_MARKERS)
    )

    platform = None
    if "cdn.shopify" in body or "myshopify.com" in body:
        platform = "shopify"
    elif "woocommerce" in body:
        platform = "woocommerce"

    if password_gated:
        transport_level = TransportLevel.T4
    elif challenged:
        transport_level = TransportLevel.T2
    else:
        transport_level = TransportLevel.T0

    return Capability(
        domain=domain,
        platform=platform,
        transport=transport_level,
        bulk_json=bulk_json,
        sitemap_url=sitemap_url,
        password_gated=password_gated,
        challenged=challenged,
        evidence=evidence,
    )


def _title(body: str) -> str:
    m = re.search(r"<title>([^<]*)</title>", body)
    return m.group(1) if m else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_fingerprint.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/fingerprint.py tests/unit/archive/test_fingerprint.py
git commit -m "feat(archive): capability fingerprinting from 4 polite GETs"
```

---

### Task 5: Connector protocol + sitemap connector

**Files:**
- Create: `backend/archive/connectors/base.py`, `backend/archive/connectors/sitemap.py`
- Create: `tests/unit/archive/fixtures/sitemap_index.xml`, `tests/unit/archive/fixtures/sitemap_products.xml`
- Test: `tests/unit/archive/test_sitemap_connector.py`

**Interfaces:**
- Consumes: `Brand`, `ProductRef`, `ProductRecord`, `Transport`.
- Produces:
  - `base.py`: `class ChannelBlocked(Exception)`, `class SkipProduct(Exception)`, and `class Connector(Protocol)` with `kind: str`, `discover(self, brand: Brand, transport: Transport) -> list[ProductRef]`, `fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord`.
  - `sitemap.py`: `class SitemapConnector` with `kind = "sitemap"`; `discover` walks `Capability`-style sitemap URL passed via `brand.notes`? No — it takes the sitemap URL as constructor arg: `SitemapConnector(sitemap_url: str)`. Handles both a `<sitemapindex>` (fetch each child `<sitemap><loc>`) and a flat `<urlset>`. Returns refs for URLs matching `/products/` (with optional locale prefix), `change_hint` = `<lastmod>` when present. `fetch` raises `NotImplementedError` in M1 (structured-data fetch is M2); `count(brand, transport) -> int` returns product-URL count for verify cross-checks.

- [ ] **Step 1: Write fixtures and the failing test**

```xml
<!-- tests/unit/archive/fixtures/sitemap_index.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://kuurth.com/sitemap_products_1.xml</loc></sitemap>
  <sitemap><loc>https://kuurth.com/sitemap_pages_1.xml</loc></sitemap>
</sitemapindex>
```

```xml
<!-- tests/unit/archive/fixtures/sitemap_products.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://kuurth.com/products/ring-one</loc><lastmod>2026-08-01T10:00:00Z</lastmod></url>
  <url><loc>https://kuurth.com/products/cuff-two</loc><lastmod>2026-08-20T09:30:00Z</lastmod></url>
  <url><loc>https://kuurth.com/pages/about</loc></url>
</urlset>
```

```python
# tests/unit/archive/test_sitemap_connector.py
from pathlib import Path

import httpx
import pytest

from backend.archive.connectors.sitemap import SitemapConnector
from backend.archive.domain.brand import Brand
from backend.archive.transport import HttpxTransport

FIX = Path(__file__).parent / "fixtures"


def make_transport() -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, text=(FIX / "sitemap_index.xml").read_text())
        if request.url.path == "/sitemap_products_1.xml":
            return httpx.Response(200, text=(FIX / "sitemap_products.xml").read_text())
        if request.url.path == "/sitemap_pages_1.xml":
            return httpx.Response(
                200,
                text='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://kuurth.com/pages/faq</loc></url></urlset>",
            )
        return httpx.Response(404)

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


BRAND = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")


@pytest.mark.unit
def test_discover_walks_index_and_keeps_only_product_urls():
    refs = SitemapConnector("https://kuurth.com/sitemap.xml").discover(BRAND, make_transport())
    assert [r.url for r in refs] == [
        "https://kuurth.com/products/ring-one",
        "https://kuurth.com/products/cuff-two",
    ]
    assert refs[1].change_hint == "2026-08-20T09:30:00Z"


@pytest.mark.unit
def test_count_matches_discover():
    c = SitemapConnector("https://kuurth.com/sitemap.xml")
    assert c.count(BRAND, make_transport()) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_sitemap_connector.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/connectors/base.py
"""The one seam: every catalog channel implements this protocol (spec §4.1)."""
from typing import Protocol

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.transport import Transport


class ChannelBlocked(Exception):
    """The channel exists but this transport may not use it (challenge/429/password)."""


class SkipProduct(Exception):
    """This ref should be skipped without failing the run."""


class Connector(Protocol):
    kind: str

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]: ...

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord: ...
```

```python
# backend/archive/connectors/sitemap.py
"""Sitemap discovery: product URLs + lastmod change hints, any platform (spec §4.2)."""
import re
import xml.etree.ElementTree as ET

from backend.archive.connectors.base import ChannelBlocked
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.transport import Transport

_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_PRODUCT_URL = re.compile(r"^https?://[^/]+(/[a-z]{2}(-[a-z]{2})?)?/products/[^?#]+$", re.I)


class SitemapConnector:
    kind = "sitemap"

    def __init__(self, sitemap_url: str):
        self.sitemap_url = sitemap_url

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        refs: list[ProductRef] = []
        for url, lastmod in self._walk(self.sitemap_url, transport, depth=0):
            if _PRODUCT_URL.match(url):
                refs.append(ProductRef(url=url, change_hint=lastmod))
        return refs

    def count(self, brand: Brand, transport: Transport) -> int:
        return len(self.discover(brand, transport))

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord:
        raise NotImplementedError("structured-data fetch arrives in milestone 2")

    def _walk(self, url: str, transport: Transport, depth: int) -> list[tuple[str, str | None]]:
        if depth > 2:  # sitemap indexes nest at most once in practice; guard against loops
            return []
        resp = transport.get(url)
        if resp.status_code != 200:
            raise ChannelBlocked(f"sitemap {url} → HTTP {resp.status_code}")
        root = ET.fromstring(resp.text)
        out: list[tuple[str, str | None]] = []
        if root.tag.endswith("sitemapindex"):
            for sm in root.findall("sm:sitemap/sm:loc", _NS):
                out.extend(self._walk((sm.text or "").strip(), transport, depth + 1))
        else:
            for u in root.findall("sm:url", _NS):
                loc = u.find("sm:loc", _NS)
                lastmod = u.find("sm:lastmod", _NS)
                if loc is not None and loc.text:
                    out.append((loc.text.strip(), lastmod.text.strip() if lastmod is not None and lastmod.text else None))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_sitemap_connector.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/connectors tests/unit/archive/fixtures tests/unit/archive/test_sitemap_connector.py
git commit -m "feat(archive): connector protocol + sitemap discovery with lastmod hints"
```

---

### Task 6: Shopify connector

**Files:**
- Create: `backend/archive/connectors/shopify.py`
- Create: `tests/unit/archive/fixtures/shopify_products_page1.json` (2 products, crafted below), `tests/unit/archive/fixtures/shopify_products_page2.json` (`{"products": []}`)
- Test: `tests/unit/archive/test_shopify_connector.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 5 (`ChannelBlocked`).
- Produces: `class ShopifyConnector` with `kind = "shopify"`; `discover(brand, transport)` pages `https://{domain}/products.json?limit=250&page=N` until an empty page, returning refs where `url = https://{domain}/products/{handle}`, `change_hint = updated_at`, `payload = <raw product dict>`; `fetch(ref, transport)` maps `ref.payload` → `ProductRecord` with **no HTTP** (raises `SkipProduct` if payload missing); module function `map_product(p: dict, domain: str) -> ProductRecord` implementing the field mapping (title, body_html→description stripped of tags, handle→canonical_url+product_code, variants→sizes/price/in_stock, min compare_at_price→full_price when > price, images[].src, product_type+tags→categories, vendor→brand, raw=p). Raises `ChannelBlocked` on 401/403/429 or a `/password` redirect.

- [ ] **Step 1: Write fixtures and the failing test**

```json
// tests/unit/archive/fixtures/shopify_products_page1.json
{"products": [
  {"id": 1, "title": "Nemo Hoodie", "handle": "nemo-hoodie", "vendor": "KUURTH",
   "product_type": "Hoodies", "tags": ["unisex", "fleece"], "updated_at": "2026-08-20T09:30:00-04:00",
   "body_html": "<p>Heavy fleece.</p>",
   "variants": [
     {"title": "M", "option1": "M", "price": "126.00", "compare_at_price": "180.00", "available": true},
     {"title": "L", "option1": "L", "price": "126.00", "compare_at_price": "180.00", "available": false}
   ],
   "images": [{"src": "https://cdn.shopify.com/s/files/nemo-1.jpg"}]},
  {"id": 2, "title": "Ring One", "handle": "ring-one", "vendor": "KUURTH",
   "product_type": "Jewelry", "tags": [], "updated_at": "2026-08-01T10:00:00-04:00",
   "body_html": "", "variants": [{"title": "Default", "option1": "Default", "price": "95.00", "compare_at_price": null, "available": true}],
   "images": []}
]}
```

```json
// tests/unit/archive/fixtures/shopify_products_page2.json
{"products": []}
```

```python
# tests/unit/archive/test_shopify_connector.py
import json
from pathlib import Path

import httpx
import pytest

from backend.archive.connectors.base import ChannelBlocked
from backend.archive.connectors.shopify import ShopifyConnector, map_product
from backend.archive.domain.brand import Brand
from backend.archive.transport import HttpxTransport

FIX = Path(__file__).parent / "fixtures"
BRAND = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")


def make_transport() -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        name = "shopify_products_page1.json" if page == "1" else "shopify_products_page2.json"
        return httpx.Response(200, json=json.loads((FIX / name).read_text()))

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.unit
def test_discover_pages_until_empty_and_carries_payloads():
    refs = ShopifyConnector().discover(BRAND, make_transport())
    assert [r.url for r in refs] == [
        "https://kuurth.com/products/nemo-hoodie",
        "https://kuurth.com/products/ring-one",
    ]
    assert refs[0].change_hint == "2026-08-20T09:30:00-04:00"
    assert refs[0].payload["title"] == "Nemo Hoodie"


@pytest.mark.unit
def test_fetch_maps_payload_without_http():
    refs = ShopifyConnector().discover(BRAND, make_transport())
    rec = ShopifyConnector().fetch(refs[0], transport=None)  # no HTTP needed → None is safe
    assert rec.product_title == "Nemo Hoodie" and rec.product_code == "nemo-hoodie"
    assert rec.price == 126.0 and rec.full_price == 180.0  # compare_at_price → sale detection
    assert rec.in_stock is True
    assert rec.sizes == [{"size": "M", "available": True}, {"size": "L", "available": False}]
    assert rec.categories == ["Hoodies", "unisex", "fleece"]
    assert rec.description == "Heavy fleece."


@pytest.mark.unit
def test_no_compare_at_price_means_no_full_price():
    rec = map_product(json.loads((FIX / "shopify_products_page1.json").read_text())["products"][1], "kuurth.com")
    assert rec.full_price is None and rec.price == 95.0


@pytest.mark.unit
def test_challenge_raises_channel_blocked():
    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))))
    with pytest.raises(ChannelBlocked):
        ShopifyConnector().discover(BRAND, t)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_shopify_connector.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/connectors/shopify.py
"""Bulk Shopify catalog: /products.json is discovery AND fetch in one channel (spec §4.2)."""
import re

from backend.archive.connectors.base import ChannelBlocked, SkipProduct
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.transport import Transport

_TAG_RE = re.compile(r"<[^>]+>")
_MAX_PAGES = 200  # 200 × 250 = 50k products; loop guard, not a coverage cap


class ShopifyConnector:
    kind = "shopify"

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]:
        refs: list[ProductRef] = []
        for page in range(1, _MAX_PAGES + 1):
            url = f"https://{brand.domain}/products.json?limit=250&page={page}"
            resp = transport.get(url)
            if resp.status_code in (401, 403, 429) or "/password" in str(resp.url):
                raise ChannelBlocked(f"{url} → HTTP {resp.status_code}")
            if resp.status_code != 200:
                raise ChannelBlocked(f"{url} → HTTP {resp.status_code}")
            products = resp.json().get("products", [])
            if not products:
                break
            for p in products:
                refs.append(
                    ProductRef(
                        url=f"https://{brand.domain}/products/{p['handle']}",
                        change_hint=p.get("updated_at"),
                        payload=p,
                    )
                )
        return refs

    def fetch(self, ref: ProductRef, transport: Transport | None) -> ProductRecord:
        if not ref.payload:
            raise SkipProduct(f"no payload on {ref.url}")
        domain = ref.url.split("/")[2]
        return map_product(ref.payload, domain)


def map_product(p: dict, domain: str) -> ProductRecord:
    variants = p.get("variants", [])
    prices = [float(v["price"]) for v in variants if v.get("price") is not None]
    compare = [float(v["compare_at_price"]) for v in variants if v.get("compare_at_price")]
    price = min(prices) if prices else None
    full_price = min(compare) if compare else None
    if full_price is not None and price is not None and full_price <= price:
        full_price = None  # compare_at_price equal/below price is not a sale
    categories = [c for c in [p.get("product_type") or None, *p.get("tags", [])] if c]
    return ProductRecord(
        canonical_url=f"https://{domain}/products/{p['handle']}",
        product_title=p["title"],
        product_code=p["handle"],
        brand=p.get("vendor"),
        description=_TAG_RE.sub("", p.get("body_html") or "").strip() or None,
        price=price,
        full_price=full_price,
        in_stock=any(v.get("available") for v in variants) if variants else None,
        sizes=[{"size": v.get("option1") or v.get("title"), "available": bool(v.get("available"))} for v in variants],
        images=[img["src"] for img in p.get("images", []) if img.get("src")],
        categories=categories,
        raw=p,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_shopify_connector.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/connectors/shopify.py tests/unit/archive/fixtures/shopify_products_page*.json tests/unit/archive/test_shopify_connector.py
git commit -m "feat(archive): shopify bulk connector — discover+fetch from products.json"
```

---

### Task 7: Planner

**Files:**
- Create: `backend/archive/planner.py`
- Modify: `backend/archive/connectors/__init__.py`
- Test: `tests/unit/archive/test_planner.py`

**Interfaces:**
- Consumes: Task 2 models; connectors from Tasks 5–6.
- Produces:
  - `compose_plan(cap: Capability, tried: list[PlanAttempt] | None = None, now: str | None = None) -> ScrapePlan`. M1 rules, in order: gated → `status="skip_gated"`; `bulk_json and transport==T0` and no prior failed `t0×bulk_json…` attempt → ready `t0×bulk_json×platform_json×per_item`; anything else (challenged, non-shopify, exhausted) → `status="needs_attention"` with `tried` carried through. (Browser transports and further ladder rungs arrive in M2/M3 — the ladder structure exists now, its rungs grow later.)
  - `connectors/__init__.py`: `get_connector(plan: ScrapePlan, cap_or_sitemap_url: str | None = None)` returning `ShopifyConnector()` for `discovery==BULK_JSON`, `SitemapConnector(sitemap_url)` for `SITEMAP`; raises `ValueError` otherwise.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_planner.py
import pytest

from backend.archive.connectors import get_connector
from backend.archive.connectors.shopify import ShopifyConnector
from backend.archive.domain.brand import Capability, PlanAttempt, TransportLevel
from backend.archive.planner import compose_plan

NOW = "2026-08-27T00:00:00+00:00"


def cap(**kw) -> Capability:
    base = dict(domain="x.com", transport=TransportLevel.T0, bulk_json=False,
                password_gated=False, challenged=False)
    base.update(kw)
    return Capability(**base)


@pytest.mark.unit
def test_open_shopify_composes_bulk_plan():
    plan = compose_plan(cap(platform="shopify", bulk_json=True), now=NOW)
    assert plan.status == "ready"
    assert plan.composition == "t0×bulk_json×platform_json×per_item"
    assert isinstance(get_connector(plan), ShopifyConnector)


@pytest.mark.unit
def test_password_gate_skips():
    plan = compose_plan(cap(password_gated=True, transport=TransportLevel.T4), now=NOW)
    assert plan.status == "skip_gated"


@pytest.mark.unit
def test_challenged_lands_in_needs_attention_in_m1():
    plan = compose_plan(cap(platform="shopify", challenged=True, transport=TransportLevel.T2), now=NOW)
    assert plan.status == "needs_attention"


@pytest.mark.unit
def test_replan_does_not_repeat_a_failed_composition():
    """Re-entry carries memory (spec §4.3b): a failed t0×bulk_json attempt is not retried."""
    failed = PlanAttempt(composition="t0×bulk_json×platform_json×per_item", failed_at=NOW, reason="calibration failed")
    plan = compose_plan(cap(platform="shopify", bulk_json=True), tried=[failed], now=NOW)
    assert plan.status == "needs_attention"
    assert plan.tried == [failed]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_planner.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/planner.py
"""Compose a (T,D,F,C) coordinate into a ScrapePlan; escalation with memory (spec §4.0, §4.3, §4.3b)."""
from datetime import datetime, timezone

from backend.archive.domain.brand import (
    Capability,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    PlanAttempt,
    ScrapePlan,
    TransportLevel,
)


def compose_plan(cap: Capability, tried: list[PlanAttempt] | None = None, now: str | None = None) -> ScrapePlan:
    tried = tried or []
    now = now or datetime.now(timezone.utc).isoformat()
    tried_compositions = {a.composition for a in tried}

    def plan(transport, discovery, fetch, change, status) -> ScrapePlan:
        return ScrapePlan(domain=cap.domain, transport=transport, discovery=discovery, fetch=fetch,
                          change_signal=change, status=status, tried=tried, fingerprinted_at=now)

    if cap.password_gated:
        return plan(TransportLevel.T4, DiscoveryChannel.BULK_JSON, FetchChannel.PLATFORM_JSON,
                    ChangeSignal.NONE, "skip_gated")

    candidate = plan(TransportLevel.T0, DiscoveryChannel.BULK_JSON, FetchChannel.PLATFORM_JSON,
                     ChangeSignal.PER_ITEM, "ready")
    if cap.bulk_json and cap.transport == TransportLevel.T0 and candidate.composition not in tried_compositions:
        return candidate

    # M2 adds browser-transport rungs (T2×bulk_json, sitemap×recipes); M3 adds the agent rung.
    return plan(cap.transport, DiscoveryChannel.BULK_JSON, FetchChannel.PLATFORM_JSON,
                ChangeSignal.NONE, "needs_attention")
```

```python
# backend/archive/connectors/__init__.py
"""Connector registry: plans name channels, this resolves them (spec §4.1)."""
from backend.archive.connectors.shopify import ShopifyConnector
from backend.archive.connectors.sitemap import SitemapConnector
from backend.archive.domain.brand import DiscoveryChannel, ScrapePlan


def get_connector(plan: ScrapePlan, sitemap_url: str | None = None):
    if plan.discovery == DiscoveryChannel.BULK_JSON:
        return ShopifyConnector()
    if plan.discovery == DiscoveryChannel.SITEMAP:
        if not sitemap_url:
            raise ValueError("sitemap discovery requires a sitemap_url")
        return SitemapConnector(sitemap_url)
    raise ValueError(f"no connector for {plan.discovery} in milestone 1")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_planner.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/planner.py backend/archive/connectors/__init__.py tests/unit/archive/test_planner.py
git commit -m "feat(archive): planner composes coordinates with escalation memory"
```

---

### Task 8: Store — schema, brands, plans, runs

**Files:**
- Create: `backend/archive/store/schema.sql`, `backend/archive/store/catalog.py`
- Test: `tests/unit/archive/test_catalog_core.py`

**Interfaces:**
- Consumes: Task 2 models.
- Produces: `class Catalog(db_path: Path)` (opens SQLite, WAL, executes `schema.sql` idempotently) with:
  - `upsert_brand(brand: Brand) -> None`, `get_brand(domain) -> Brand | None`, `list_brands() -> list[Brand]`, `set_brand_state(domain, state)`, `get_brand_state(domain) -> str` (default `"new"`)
  - `save_plan(plan: ScrapePlan) -> None` (upsert by domain), `load_plan(domain) -> ScrapePlan | None`
  - `open_run(domain, mode) -> int`, `finalize_run(run_id, exit_status: int, coverage: Coverage | None) -> None`, `latest_run(domain) -> dict | None`
  - `close()`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_catalog_core.py
import pytest

from backend.archive.domain.brand import (
    Brand, ChangeSignal, DiscoveryChannel, FetchChannel, ScrapePlan, TransportLevel,
)
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import Catalog


def make_plan(domain="kuurth.com") -> ScrapePlan:
    return ScrapePlan(domain=domain, transport=TransportLevel.T0, discovery=DiscoveryChannel.BULK_JSON,
                      fetch=FetchChannel.PLATFORM_JSON, change_signal=ChangeSignal.PER_ITEM,
                      status="ready", fingerprinted_at="2026-08-27T00:00:00+00:00")


@pytest.mark.unit
def test_brand_and_state_round_trip(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    assert cat.get_brand("kuurth.com").homepage_url == "https://kuurth.com"
    assert cat.get_brand_state("kuurth.com") == "new"
    cat.set_brand_state("kuurth.com", "active")
    assert cat.get_brand_state("kuurth.com") == "active"


@pytest.mark.unit
def test_plan_round_trip_and_upsert(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    cat.save_plan(make_plan())
    assert cat.load_plan("kuurth.com").status == "ready"
    stale = make_plan(); stale.stale = True
    cat.save_plan(stale)  # upsert, not insert
    assert cat.load_plan("kuurth.com").stale is True


@pytest.mark.unit
def test_runs_are_append_only_and_crash_visible(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    run1 = cat.open_run("kuurth.com", "full")
    assert cat.latest_run("kuurth.com")["exit_status"] is None  # open run is visible immediately
    cov = Coverage(extracted=2, channel_counts={"bulk_json": 2}, coverage_pct=1.0,
                   field_fill={"product_title": 1.0}, verdict="ok")
    cat.finalize_run(run1, 0, cov)
    run2 = cat.open_run("kuurth.com", "delta")
    assert run2 != run1
    latest = cat.latest_run("kuurth.com")
    assert latest["id"] == run2 and latest["mode"] == "delta"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_catalog_core.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```sql
-- backend/archive/store/schema.sql
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
  canonical_url TEXT NOT NULL,
  product_code  TEXT,
  change_hint   TEXT,
  first_seen_run INTEGER NOT NULL REFERENCES runs(id),
  last_seen_run  INTEGER NOT NULL REFERENCES runs(id),
  current_json  TEXT NOT NULL,
  UNIQUE (domain, canonical_url)
);

CREATE TABLE IF NOT EXISTS observations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id),
  run_id     INTEGER NOT NULL REFERENCES runs(id),
  price      REAL,
  full_price REAL,
  in_stock   INTEGER,
  sizes_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_products_domain ON products(domain);
CREATE INDEX IF NOT EXISTS idx_observations_product ON observations(product_id);
CREATE INDEX IF NOT EXISTS idx_runs_domain ON runs(domain, id);
```

```python
# backend/archive/store/catalog.py
"""The only module that touches the DB (spec §4.4). Append-only runs/observations."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.archive.domain.brand import Brand, ScrapePlan
from backend.archive.domain.run import Coverage

_SCHEMA = Path(__file__).parent / "schema.sql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Catalog:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA.read_text())

    def close(self) -> None:
        self._db.close()

    # --- brands ---
    def upsert_brand(self, brand: Brand) -> None:
        self._db.execute(
            "INSERT INTO brands (domain, homepage_url, display_name, notes) VALUES (?,?,?,?) "
            "ON CONFLICT(domain) DO UPDATE SET homepage_url=excluded.homepage_url, "
            "display_name=excluded.display_name, notes=excluded.notes",
            (brand.domain, brand.homepage_url, brand.display_name, brand.notes),
        )
        self._db.commit()

    def get_brand(self, domain: str) -> Brand | None:
        row = self._db.execute("SELECT * FROM brands WHERE domain=?", (domain,)).fetchone()
        return Brand(domain=row["domain"], homepage_url=row["homepage_url"],
                     display_name=row["display_name"], notes=row["notes"]) if row else None

    def list_brands(self) -> list[Brand]:
        rows = self._db.execute("SELECT * FROM brands ORDER BY domain").fetchall()
        return [Brand(domain=r["domain"], homepage_url=r["homepage_url"],
                      display_name=r["display_name"], notes=r["notes"]) for r in rows]

    def set_brand_state(self, domain: str, state: str) -> None:
        self._db.execute("UPDATE brands SET state=? WHERE domain=?", (state, domain))
        self._db.commit()

    def get_brand_state(self, domain: str) -> str:
        row = self._db.execute("SELECT state FROM brands WHERE domain=?", (domain,)).fetchone()
        return row["state"] if row else "new"

    # --- plans ---
    def save_plan(self, plan: ScrapePlan) -> None:
        self._db.execute(
            "INSERT INTO scrape_plans (domain, plan_json, fingerprinted_at) VALUES (?,?,?) "
            "ON CONFLICT(domain) DO UPDATE SET plan_json=excluded.plan_json, "
            "fingerprinted_at=excluded.fingerprinted_at",
            (plan.domain, plan.model_dump_json(), plan.fingerprinted_at),
        )
        self._db.commit()

    def load_plan(self, domain: str) -> ScrapePlan | None:
        row = self._db.execute("SELECT plan_json FROM scrape_plans WHERE domain=?", (domain,)).fetchone()
        return ScrapePlan.model_validate_json(row["plan_json"]) if row else None

    # --- runs ---
    def open_run(self, domain: str, mode: str) -> int:
        cur = self._db.execute("INSERT INTO runs (domain, mode, started_at) VALUES (?,?,?)",
                               (domain, mode, _now()))
        self._db.commit()
        return cur.lastrowid

    def finalize_run(self, run_id: int, exit_status: int, coverage: Coverage | None) -> None:
        self._db.execute(
            "UPDATE runs SET finished_at=?, exit_status=?, coverage_json=? WHERE id=?",
            (_now(), exit_status, coverage.model_dump_json() if coverage else None, run_id),
        )
        self._db.commit()

    def latest_run(self, domain: str) -> dict | None:
        row = self._db.execute("SELECT * FROM runs WHERE domain=? ORDER BY id DESC LIMIT 1",
                               (domain,)).fetchone()
        return dict(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_catalog_core.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/store tests/unit/archive/test_catalog_core.py
git commit -m "feat(archive): sqlite store — brands, plans, append-only runs"
```

---

### Task 9: Store — products, observations, delta hints, status rows

**Files:**
- Modify: `backend/archive/store/catalog.py` (add methods to `Catalog`)
- Test: `tests/unit/archive/test_catalog_products.py`

**Interfaces:**
- Consumes: Task 8 `Catalog`; `ProductRecord`, `WATCHED_FIELDS`.
- Produces (added to `Catalog`):
  - `record_product(domain, run_id, record: ProductRecord, change_hint: str | None) -> bool` — upserts the product (advancing `last_seen_run`, `change_hint`, `current_json`); appends an observation on first sight or when any of `WATCHED_FIELDS` changed vs the stored `current_json`; returns True iff an observation was appended.
  - `get_change_hints(domain) -> dict[str, str]` — `canonical_url → change_hint` for delta selection.
  - `observation_count(domain) -> int`; `current_products(domain, live_only: bool = True) -> list[dict]` (live ⇔ `last_seen_run` == latest **finished ok/degraded** run's id or the run currently open); `status_rows() -> list[dict]` — one per brand: `domain, state, products, coverage_pct, verdict, freshness (finished_at), mode` from the latest finalized run.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_catalog_products.py
import pytest

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import Catalog

COV = Coverage(extracted=1, channel_counts={}, coverage_pct=1.0, field_fill={}, verdict="ok")


def rec(price=126.0, in_stock=True) -> ProductRecord:
    return ProductRecord(canonical_url="https://kuurth.com/products/nemo", product_title="Nemo",
                         price=price, in_stock=in_stock)


@pytest.fixture()
def cat(tmp_path):
    c = Catalog(tmp_path / "catalog.db")
    c.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    return c


@pytest.mark.unit
def test_first_sight_always_appends_observation(cat):
    run = cat.open_run("kuurth.com", "full")
    assert cat.record_product("kuurth.com", run, rec(), "hint-1") is True
    assert cat.observation_count("kuurth.com") == 1


@pytest.mark.unit
def test_unchanged_product_appends_nothing(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), "hint-1")
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "delta")
    assert cat.record_product("kuurth.com", r2, rec(), "hint-1") is False
    assert cat.observation_count("kuurth.com") == 1  # history stores change, not repetition


@pytest.mark.unit
def test_price_change_appends_observation_and_updates_hint(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(price=180.0), "hint-1")
    r2 = cat.open_run("kuurth.com", "delta")
    assert cat.record_product("kuurth.com", r2, rec(price=126.0), "hint-2") is True
    assert cat.observation_count("kuurth.com") == 2
    assert cat.get_change_hints("kuurth.com") == {"https://kuurth.com/products/nemo": "hint-2"}


@pytest.mark.unit
def test_delisted_product_leaves_current_view_but_stays_stored(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), None)
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "full")  # product NOT seen this run
    cat.finalize_run(r2, 0, COV)
    assert cat.current_products("kuurth.com", live_only=True) == []
    assert len(cat.current_products("kuurth.com", live_only=False)) == 1  # the archive keeps it
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_catalog_products.py -v`
Expected: FAIL with `AttributeError: 'Catalog' object has no attribute 'record_product'`

- [ ] **Step 3: Add the methods to `Catalog`**

```python
# append inside class Catalog (backend/archive/store/catalog.py)
    # --- products & observations ---
    def record_product(self, domain: str, run_id: int, record, change_hint: str | None) -> bool:
        from backend.archive.domain.product import WATCHED_FIELDS

        row = self._db.execute(
            "SELECT id, current_json FROM products WHERE domain=? AND canonical_url=?",
            (domain, record.canonical_url),
        ).fetchone()
        record_json = record.model_dump_json()
        changed = True
        if row:
            prev = json.loads(row["current_json"])
            cur = record.model_dump()
            changed = any(prev.get(f) != cur.get(f) for f in WATCHED_FIELDS)
            self._db.execute(
                "UPDATE products SET last_seen_run=?, change_hint=?, current_json=? WHERE id=?",
                (run_id, change_hint, record_json, row["id"]),
            )
            product_id = row["id"]
        else:
            cur_ = self._db.execute(
                "INSERT INTO products (domain, canonical_url, product_code, change_hint, "
                "first_seen_run, last_seen_run, current_json) VALUES (?,?,?,?,?,?,?)",
                (domain, record.canonical_url, record.product_code, change_hint, run_id, run_id, record_json),
            )
            product_id = cur_.lastrowid
        if changed:
            self._db.execute(
                "INSERT INTO observations (product_id, run_id, price, full_price, in_stock, sizes_json) "
                "VALUES (?,?,?,?,?,?)",
                (product_id, run_id, record.price, record.full_price,
                 None if record.in_stock is None else int(record.in_stock), json.dumps(record.sizes)),
            )
        self._db.commit()
        return changed

    def get_change_hints(self, domain: str) -> dict[str, str]:
        rows = self._db.execute(
            "SELECT canonical_url, change_hint FROM products WHERE domain=? AND change_hint IS NOT NULL",
            (domain,),
        ).fetchall()
        return {r["canonical_url"]: r["change_hint"] for r in rows}

    def observation_count(self, domain: str) -> int:
        return self._db.execute(
            "SELECT COUNT(*) c FROM observations o JOIN products p ON p.id=o.product_id WHERE p.domain=?",
            (domain,),
        ).fetchone()["c"]

    def current_products(self, domain: str, live_only: bool = True) -> list[dict]:
        if live_only:
            latest = self._db.execute(
                "SELECT id FROM runs WHERE domain=? AND (exit_status IN (0,1) OR exit_status IS NULL) "
                "ORDER BY id DESC LIMIT 1",
                (domain,),
            ).fetchone()
            if not latest:
                return []
            rows = self._db.execute(
                "SELECT current_json FROM products WHERE domain=? AND last_seen_run=?",
                (domain, latest["id"]),
            ).fetchall()
        else:
            rows = self._db.execute("SELECT current_json FROM products WHERE domain=?", (domain,)).fetchall()
        return [json.loads(r["current_json"]) for r in rows]

    def status_rows(self) -> list[dict]:
        rows = self._db.execute(
            """SELECT b.domain, b.state,
                      (SELECT COUNT(*) FROM products p WHERE p.domain=b.domain) AS products,
                      r.coverage_json, r.finished_at, r.mode
               FROM brands b
               LEFT JOIN runs r ON r.id = (SELECT id FROM runs WHERE domain=b.domain
                                           AND exit_status IS NOT NULL ORDER BY id DESC LIMIT 1)
               ORDER BY b.domain"""
        ).fetchall()
        out = []
        for r in rows:
            cov = json.loads(r["coverage_json"]) if r["coverage_json"] else None
            out.append({
                "domain": r["domain"], "state": r["state"], "products": r["products"],
                "coverage_pct": cov["coverage_pct"] if cov else None,
                "verdict": cov["verdict"] if cov else None,
                "freshness": r["finished_at"], "mode": r["mode"],
            })
        return out
```

- [ ] **Step 4: Run all catalog tests**

Run: `python3 -m pytest tests/unit/archive/test_catalog_core.py tests/unit/archive/test_catalog_products.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/store/catalog.py tests/unit/archive/test_catalog_products.py
git commit -m "feat(archive): product upserts, change-only observations, delta hints, status rows"
```

---

### Task 10: Verify

**Files:**
- Create: `backend/archive/verify.py`
- Test: `tests/unit/archive/test_verify.py`

**Interfaces:**
- Consumes: `ProductRecord`, `Coverage`.
- Produces: `field_fill_rates(records: list[ProductRecord]) -> dict[str, float]` over fields `("product_title","price","in_stock","images","sizes","description","categories")` (a field counts as filled when truthy / non-None; `in_stock` counts False as filled); `assess(extracted: int, channel_counts: dict[str, int], field_fill: dict[str, float]) -> Coverage` with rules: `expected = max(channel_counts.values())` when non-empty else `extracted`; `coverage_pct = extracted/expected` (1.0 when expected 0); verdict `failed` when `extracted == 0 < expected` or `coverage_pct < 0.6`; `degraded` when `coverage_pct < 0.95` or `field_fill.get("product_title", 1.0) < 1.0`; else `ok`; `reasons` lists each triggered rule.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_verify.py
import pytest

from backend.archive.domain.product import ProductRecord
from backend.archive.verify import assess, field_fill_rates


@pytest.mark.unit
def test_full_coverage_is_ok():
    cov = assess(291, {"bulk_json": 291, "sitemap": 291}, {"product_title": 1.0})
    assert cov.verdict == "ok" and cov.coverage_pct == 1.0 and cov.reasons == []


@pytest.mark.unit
def test_shortfall_degrades_with_reason():
    cov = assess(250, {"bulk_json": 291}, {"product_title": 1.0})
    assert cov.verdict == "degraded" and any("coverage" in r for r in cov.reasons)


@pytest.mark.unit
def test_zero_extracted_when_channel_reports_products_is_failed():
    """Regression guard: the old pipeline reported 0-URL runs as success (streaming.py:179)."""
    cov = assess(0, {"bulk_json": 291}, {})
    assert cov.verdict == "failed"


@pytest.mark.unit
def test_field_fill_counts_in_stock_false_as_filled():
    recs = [
        ProductRecord(canonical_url="u1", product_title="A", price=10.0, in_stock=False),
        ProductRecord(canonical_url="u2", product_title="B"),
    ]
    fill = field_fill_rates(recs)
    assert fill["product_title"] == 1.0
    assert fill["price"] == 0.5
    assert fill["in_stock"] == 0.5  # False is knowledge; None is absence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_verify.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/verify.py
"""Immune system: channel counts and field fill → verdicts (spec §4.5)."""
from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage

_FILL_FIELDS = ("product_title", "price", "in_stock", "images", "sizes", "description", "categories")


def field_fill_rates(records: list[ProductRecord]) -> dict[str, float]:
    if not records:
        return {}
    fill: dict[str, float] = {}
    for f in _FILL_FIELDS:
        filled = sum(1 for r in records if getattr(r, f) is not None and getattr(r, f) != [] and getattr(r, f) != "")
        fill[f] = filled / len(records)
    return fill


def assess(extracted: int, channel_counts: dict[str, int], field_fill: dict[str, float]) -> Coverage:
    expected = max(channel_counts.values()) if channel_counts else extracted
    coverage_pct = 1.0 if expected == 0 else extracted / expected
    reasons: list[str] = []
    if extracted == 0 and expected > 0:
        reasons.append(f"extracted 0 of {expected} channel-reported products")
        verdict = "failed"
    elif coverage_pct < 0.6:
        reasons.append(f"coverage {coverage_pct:.0%} below 60%")
        verdict = "failed"
    else:
        if coverage_pct < 0.95:
            reasons.append(f"coverage {coverage_pct:.0%} below 95%")
        if field_fill.get("product_title", 1.0) < 1.0:
            reasons.append("product_title fill below 100%")
        verdict = "degraded" if reasons else "ok"
    return Coverage(extracted=extracted, channel_counts=channel_counts,
                    coverage_pct=round(coverage_pct, 4), field_fill=field_fill,
                    verdict=verdict, reasons=reasons)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_verify.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/verify.py tests/unit/archive/test_verify.py
git commit -m "feat(archive): coverage verification with honest failure verdicts"
```

---

### Task 11: Runner — delta selection and the lifecycle

**Files:**
- Create: `backend/archive/runner/run.py`
- Test: `tests/unit/archive/test_runner.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `select_delta(refs: list[ProductRef], hints: dict[str, str]) -> list[ProductRef]` — keep refs that are new (url not in hints), hintless, or whose `change_hint != hints[url]`.
  - `run_brand(brand: Brand, catalog: Catalog, transport: Transport, mode: str = "delta", sample_size: int = 5, locks_dir: Path, log_dir: Path, prober=probe, composer=compose_plan, connector_factory=get_connector) -> int` implementing the lifecycle (spec §4.3b): lockfile → open run → load plan (re-probe + compose when absent or `stale`) → `skip_gated` finalizes exit 0 with state `gated`; `needs_attention` finalizes exit 1 → discover (`ChannelBlocked` ⇒ record `PlanAttempt`, mark plan stale, state `needs_attention`, exit 1) → if brand state not `active`: calibrate on `refs[:sample_size]` (all fetches must yield `product_title`; failure ⇒ PlanAttempt + stale + exit 1; success ⇒ state `active`) → select refs (`delta` uses `select_delta` unless first run) → fetch each (`SkipProduct`/exceptions recorded, never abort) → `record_product` each → `assess` with `channel_counts={"<connector.kind>": len(all_refs)}` → finalize (`ok→0, degraded→1, failed→2`), set state (`active`/`degraded`) → write one JSON line per event to `log_dir/<domain>/<run_id>.jsonl` → release lock in `finally`. Lock held ⇒ return 0 immediately with a `skipped-locked` log line and **no run row**.
  - The injectable `prober/composer/connector_factory` parameters exist so tests (and later milestones) can substitute fakes — they default to the real functions.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_runner.py
import pytest

from backend.archive.connectors.base import ChannelBlocked
from backend.archive.domain.brand import Brand, Capability, TransportLevel
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.planner import compose_plan
from backend.archive.runner.run import run_brand, select_delta
from backend.archive.store.catalog import Catalog

BRAND = Brand(domain="kuurth.com", homepage_url="https://kuurth.com")
OPEN_CAP = Capability(domain="kuurth.com", platform="shopify", transport=TransportLevel.T0, bulk_json=True)


def ref(n: str, hint: str) -> ProductRef:
    return ProductRef(url=f"https://kuurth.com/products/{n}", change_hint=hint,
                      payload={"handle": n, "title": n.title(), "variants": [], "images": [], "tags": []})


class FakeConnector:
    kind = "shopify"

    def __init__(self, refs):
        self.refs = refs
        self.fetched: list[str] = []

    def discover(self, brand, transport):
        return self.refs

    def fetch(self, r, transport):
        self.fetched.append(r.url)
        return ProductRecord(canonical_url=r.url, product_title=r.payload["title"])


@pytest.mark.unit
def test_select_delta_keeps_new_and_changed_only():
    refs = [ref("a", "h1"), ref("b", "h2"), ref("c", "h3")]
    hints = {refs[0].url: "h1", refs[1].url: "OLD"}
    assert [r.url for r in select_delta(refs, hints)] == [refs[1].url, refs[2].url]


@pytest.fixture()
def env(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(BRAND)
    return cat, tmp_path / "locks", tmp_path / "logs"


@pytest.mark.unit
def test_first_run_calibrates_promotes_and_verifies(env):
    cat, locks, logs = env
    conn = FakeConnector([ref("a", "h1"), ref("b", "h2")])
    code = run_brand(BRAND, cat, transport=None, mode="full", locks_dir=locks, log_dir=logs,
                     prober=lambda d, t: OPEN_CAP, composer=compose_plan,
                     connector_factory=lambda plan, sitemap_url=None: conn)
    assert code == 0
    assert cat.get_brand_state("kuurth.com") == "active"
    assert cat.latest_run("kuurth.com")["exit_status"] == 0
    assert len(cat.current_products("kuurth.com")) == 2


@pytest.mark.unit
def test_delta_run_fetches_only_changed(env):
    cat, locks, logs = env
    conn = FakeConnector([ref("a", "h1"), ref("b", "h2")])
    kwargs = dict(locks_dir=locks, log_dir=logs, prober=lambda d, t: OPEN_CAP, composer=compose_plan,
                  connector_factory=lambda plan, sitemap_url=None: conn)
    run_brand(BRAND, cat, None, mode="full", **kwargs)
    conn.fetched.clear()
    conn.refs = [ref("a", "h1"), ref("b", "h2-NEW")]
    code = run_brand(BRAND, cat, None, mode="delta", **kwargs)
    assert code == 0
    assert conn.fetched == ["https://kuurth.com/products/b"]  # unchanged 'a' untouched


@pytest.mark.unit
def test_blocked_channel_records_attempt_and_marks_stale(env):
    cat, locks, logs = env

    class Blocked(FakeConnector):
        def discover(self, brand, transport):
            raise ChannelBlocked("429")

    code = run_brand(BRAND, cat, None, mode="full", locks_dir=locks, log_dir=logs,
                     prober=lambda d, t: OPEN_CAP, composer=compose_plan,
                     connector_factory=lambda plan, sitemap_url=None: Blocked([]))
    assert code == 1
    plan = cat.load_plan("kuurth.com")
    assert plan.stale is True and len(plan.tried) == 1
    assert cat.get_brand_state("kuurth.com") == "needs_attention"


@pytest.mark.unit
def test_held_lock_skips_without_a_run_row(env):
    cat, locks, logs = env
    locks.mkdir(parents=True)
    (locks / "kuurth.com.lock").write_text("held")
    code = run_brand(BRAND, cat, None, mode="full", locks_dir=locks, log_dir=logs,
                     prober=lambda d, t: OPEN_CAP, composer=compose_plan,
                     connector_factory=lambda plan, sitemap_url=None: FakeConnector([]))
    assert code == 0 and cat.latest_run("kuurth.com") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_runner.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/runner/run.py
"""The lifecycle: scope → plan → calibrate → promote → monitor (spec §4.3b, §4.6)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.archive.connectors import get_connector
from backend.archive.connectors.base import ChannelBlocked, SkipProduct
from backend.archive.domain.brand import Brand, PlanAttempt
from backend.archive.domain.product import ProductRef
from backend.archive.fingerprint import probe
from backend.archive.planner import compose_plan
from backend.archive.store.catalog import Catalog
from backend.archive.verify import assess, field_fill_rates

_EXIT = {"ok": 0, "degraded": 1, "failed": 2}


def select_delta(refs: list[ProductRef], hints: dict[str, str]) -> list[ProductRef]:
    return [r for r in refs if r.url not in hints or r.change_hint is None or r.change_hint != hints[r.url]]


def run_brand(brand: Brand, catalog: Catalog, transport, mode: str = "delta", sample_size: int = 5,
              locks_dir: Path = Path("locks"), log_dir: Path = Path("logs/runs"),
              prober=probe, composer=compose_plan, connector_factory=get_connector) -> int:
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock = locks_dir / f"{brand.domain}.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return 0  # overlap is a skip, not an alarm (spec §4.6)

    run_id = catalog.open_run(brand.domain, mode)
    log_path = log_dir / brand.domain / f"{run_id}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(event: str, **kw) -> None:
        with log_path.open("a") as f:
            f.write(json.dumps({"t": datetime.now(timezone.utc).isoformat(), "event": event, **kw}) + "\n")

    def fail_plan(plan, reason: str) -> int:
        plan.tried.append(PlanAttempt(composition=plan.composition,
                                      failed_at=datetime.now(timezone.utc).isoformat(), reason=reason))
        plan.stale = True
        catalog.save_plan(plan)
        catalog.set_brand_state(brand.domain, "needs_attention")
        catalog.finalize_run(run_id, 1, None)
        log("plan-failed", reason=reason, composition=plan.composition)
        return 1

    try:
        plan = catalog.load_plan(brand.domain)
        if plan is None or plan.stale:
            cap = prober(brand.domain, transport)
            plan = composer(cap, tried=plan.tried if plan else [])
            catalog.save_plan(plan)
            catalog.set_brand_state(brand.domain, "scoped")
            log("planned", composition=plan.composition, status=plan.status)

        if plan.status == "skip_gated":
            catalog.set_brand_state(brand.domain, "gated")
            catalog.finalize_run(run_id, 0, None)
            log("skipped-gated")
            return 0
        if plan.status == "needs_attention":
            catalog.set_brand_state(brand.domain, "needs_attention")
            catalog.finalize_run(run_id, 1, None)
            log("needs-attention", tried=[a.composition for a in plan.tried])
            return 1

        connector = connector_factory(plan)
        try:
            refs = connector.discover(brand, transport)
        except ChannelBlocked as e:
            return fail_plan(plan, f"discover blocked: {e}")
        log("discovered", refs=len(refs))

        if catalog.get_brand_state(brand.domain) != "active":
            catalog.set_brand_state(brand.domain, "calibrating")
            sample = refs[: sample_size]
            try:
                sample_records = [connector.fetch(r, transport) for r in sample]
            except Exception as e:  # calibration failure is cheap information, not damage
                return fail_plan(plan, f"calibration fetch failed: {e}")
            if sample and not all(r.product_title for r in sample_records):
                return fail_plan(plan, "calibration: empty product_title in sample")
            catalog.set_brand_state(brand.domain, "active")
            log("calibrated", sample=len(sample))

        hints = catalog.get_change_hints(brand.domain)
        first_run = not hints
        to_fetch = refs if (mode == "full" or first_run) else select_delta(refs, hints)
        log("selected", mode=mode, to_fetch=len(to_fetch), total=len(refs))

        records, errors = [], 0
        for r in to_fetch:
            try:
                rec = connector.fetch(r, transport)
            except SkipProduct as e:
                log("skip-product", url=r.url, reason=str(e))
                continue
            except Exception as e:
                errors += 1
                log("fetch-error", url=r.url, error=str(e))
                continue
            records.append(rec)
            catalog.record_product(brand.domain, run_id, rec, r.change_hint)

        # untouched (unchanged) products still count as seen this run
        touched = {r.canonical_url for r in records}
        for r in refs:
            if r.url not in touched and r.url in hints:
                catalog._db.execute(  # noqa: SLF001 — same-package seen-advance, kept in one txn
                    "UPDATE products SET last_seen_run=? WHERE domain=? AND canonical_url=?",
                    (run_id, brand.domain, r.url),
                )
        catalog._db.commit()  # noqa: SLF001

        coverage = assess(len(refs), {connector.kind: len(refs)}, field_fill_rates(records))
        exit_status = _EXIT[coverage.verdict]
        catalog.set_brand_state(brand.domain, "active" if exit_status == 0 else "degraded")
        catalog.finalize_run(run_id, exit_status, coverage)
        log("finalized", verdict=coverage.verdict, errors=errors, extracted=len(records))
        return exit_status
    finally:
        lock.unlink(missing_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_runner.py -v`
Expected: 5 PASS

- [ ] **Step 5: Refactor note + commit**

The two `# noqa: SLF001` calls flag a seam to clean: add `Catalog.mark_seen(domain, run_id, urls)` in Task 12's refactor step rather than leaving private-attribute access. Commit now:

```bash
git add backend/archive/runner/run.py tests/unit/archive/test_runner.py
git commit -m "feat(archive): lifecycle runner — calibrate, promote, delta, honest exits"
```

---

### Task 12: `Catalog.mark_seen` refactor

**Files:**
- Modify: `backend/archive/store/catalog.py`, `backend/archive/runner/run.py`
- Test: `tests/unit/archive/test_catalog_products.py` (add one test)

**Interfaces:**
- Produces: `Catalog.mark_seen(domain: str, run_id: int, urls: list[str]) -> None` advancing `last_seen_run` for the given canonical URLs; `runner/run.py` uses it and loses both `# noqa: SLF001` lines.

- [ ] **Step 1: Write the failing test** — append to `tests/unit/archive/test_catalog_products.py`:

```python
@pytest.mark.unit
def test_mark_seen_advances_last_seen_without_observation(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), "h1")
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "delta")
    cat.mark_seen("kuurth.com", r2, ["https://kuurth.com/products/nemo"])
    cat.finalize_run(r2, 0, COV)
    assert len(cat.current_products("kuurth.com", live_only=True)) == 1
    assert cat.observation_count("kuurth.com") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_catalog_products.py -v`
Expected: new test FAILS with `AttributeError`

- [ ] **Step 3: Implement and swap in**

Add to `Catalog`:

```python
    def mark_seen(self, domain: str, run_id: int, urls: list[str]) -> None:
        self._db.executemany(
            "UPDATE products SET last_seen_run=? WHERE domain=? AND canonical_url=?",
            [(run_id, domain, u) for u in urls],
        )
        self._db.commit()
```

In `backend/archive/runner/run.py`, replace the block between `touched = …` and `catalog._db.commit()` with:

```python
        touched = {r.canonical_url for r in records}
        catalog.mark_seen(brand.domain, run_id,
                          [r.url for r in refs if r.url not in touched and r.url in hints])
```

- [ ] **Step 4: Run runner + catalog tests**

Run: `python3 -m pytest tests/unit/archive/test_runner.py tests/unit/archive/test_catalog_products.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/store/catalog.py backend/archive/runner/run.py tests/unit/archive/test_catalog_products.py
git commit -m "refactor(archive): Catalog.mark_seen replaces runner's private DB access"
```

---

### Task 13: CLI + brands.yml

**Files:**
- Create: `backend/archive/runner/cli.py`, `backend/archive/brands.yml`
- Test: `tests/unit/archive/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `load_brands(path: Path) -> list[Brand]` from YAML shaped `brands: [{domain, homepage_url, display_name?, notes?}]`.
  - `main(argv: list[str] | None = None) -> int` with subcommands:
    - `plan <domain> [--db PATH]` — probe + compose, save, print `domain composition status`.
    - `scrape (<domain> | --all) [--delta|--full] [--db PATH] [--brands PATH] [--locks DIR] [--logs DIR]` — seeds brands from YAML into the DB, runs `run_brand` per target with one shared `HttpxTransport`; `--all` prints one line per brand and exits with the worst status.
    - `status [--db PATH]` — prints the coverage matrix from `Catalog.status_rows()` (columns: BRAND STATE PRODUCTS COVERAGE VERDICT FRESH).
  - Module runnable via `python -m backend.archive.runner.cli`.
  - `backend/archive/brands.yml` seeded with all 36 target brands (list below in Step 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_cli.py
from pathlib import Path

import pytest

from backend.archive.runner.cli import load_brands, main

YML = """
brands:
  - domain: kuurth.com
    homepage_url: https://kuurth.com
  - domain: coltmcr.com
    homepage_url: https://coltmcr.com
    notes: password-gated as of 2026-08-26
"""


@pytest.mark.unit
def test_load_brands(tmp_path):
    p = tmp_path / "brands.yml"
    p.write_text(YML)
    brands = load_brands(p)
    assert [b.domain for b in brands] == ["kuurth.com", "coltmcr.com"]
    assert brands[1].notes.startswith("password-gated")


@pytest.mark.unit
def test_status_on_empty_db_lists_seeded_brands(tmp_path, capsys):
    p = tmp_path / "brands.yml"
    p.write_text(YML)
    db = tmp_path / "catalog.db"
    # seed via scrape --all against an unroutable transport? No — status must not need network:
    code = main(["status", "--db", str(db), "--brands", str(p)])
    out = capsys.readouterr().out
    assert code == 0
    assert "kuurth.com" in out and "coltmcr.com" in out and "BRAND" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_cli.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# backend/archive/runner/cli.py
"""archive CLI: plan | scrape | status (spec §4.6). Run as python -m backend.archive.runner.cli."""
import argparse
from pathlib import Path

import yaml

from backend.archive.domain.brand import Brand
from backend.archive.fingerprint import probe
from backend.archive.planner import compose_plan
from backend.archive.runner.run import run_brand
from backend.archive.store.catalog import Catalog
from backend.archive.transport import HttpxTransport

_DEFAULT_BRANDS = Path(__file__).parent.parent / "brands.yml"
_DEFAULT_DB = Path("backend/archive/data/catalog.db")


def load_brands(path: Path) -> list[Brand]:
    data = yaml.safe_load(path.read_text())
    return [Brand(**b) for b in data.get("brands", [])]


def _seed(catalog: Catalog, brands_path: Path) -> list[Brand]:
    brands = load_brands(brands_path)
    for b in brands:
        catalog.upsert_brand(b)
    return brands


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archive")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "scrape", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--db", type=Path, default=_DEFAULT_DB)
        sp.add_argument("--brands", type=Path, default=_DEFAULT_BRANDS)
        if name == "plan":
            sp.add_argument("domain")
        if name == "scrape":
            sp.add_argument("domain", nargs="?")
            sp.add_argument("--all", action="store_true")
            group = sp.add_mutually_exclusive_group()
            group.add_argument("--delta", action="store_true")
            group.add_argument("--full", action="store_true")
            sp.add_argument("--locks", type=Path, default=Path("backend/archive/data/locks"))
            sp.add_argument("--logs", type=Path, default=Path("backend/archive/data/logs"))
    args = ap.parse_args(argv)

    catalog = Catalog(args.db)
    try:
        brands = _seed(catalog, args.brands) if args.brands.exists() else []

        if args.cmd == "plan":
            cap = probe(args.domain, HttpxTransport())
            plan = compose_plan(cap)
            catalog.upsert_brand(Brand(domain=args.domain, homepage_url=f"https://{args.domain}"))
            catalog.save_plan(plan)
            print(f"{plan.domain}  {plan.composition}  {plan.status}")
            return 0

        if args.cmd == "scrape":
            targets = brands if args.all else [b for b in brands if b.domain == args.domain]
            if not targets and args.domain:
                targets = [Brand(domain=args.domain, homepage_url=f"https://{args.domain}")]
                catalog.upsert_brand(targets[0])
            mode = "full" if args.full else "delta"
            transport = HttpxTransport()
            worst = 0
            for b in targets:
                code = run_brand(b, catalog, transport, mode=mode, locks_dir=args.locks, log_dir=args.logs)
                print(f"{b.domain}  exit={code}")
                worst = max(worst, code)
            return worst

        # status
        rows = catalog.status_rows()
        print(f"{'BRAND':<28}{'STATE':<16}{'PRODUCTS':>9}{'COVERAGE':>10}{'VERDICT':>10}  FRESH")
        for r in rows:
            cov = f"{r['coverage_pct']:.0%}" if r["coverage_pct"] is not None else "—"
            print(f"{r['domain']:<28}{r['state']:<16}{r['products']:>9}{cov:>10}"
                  f"{(r['verdict'] or '—'):>10}  {r['freshness'] or '—'}")
        return 0
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `backend/archive/brands.yml` with all 36 targets (normalized domains from the 2026-08-26 probe; notes record known states):

```yaml
brands:
  - {domain: twofoldvintage.com, homepage_url: "https://twofoldvintage.com"}
  - {domain: www.uniformalgarments.com, homepage_url: "https://www.uniformalgarments.com"}
  - {domain: www.outlw.xyz, homepage_url: "https://www.outlw.xyz", notes: webflow}
  - {domain: skidrowstudio.com, homepage_url: "https://skidrowstudio.com", notes: password-gated 2026-08-26}
  - {domain: channell97.com, homepage_url: "https://channell97.com"}
  - {domain: thegvgallery.com, homepage_url: "https://thegvgallery.com"}
  - {domain: coltmcr.com, homepage_url: "https://coltmcr.com", notes: password-gated 2026-08-26}
  - {domain: xsai.vision, homepage_url: "https://xsai.vision", notes: custom nextjs}
  - {domain: sadi.love, homepage_url: "https://sadi.love"}
  - {domain: degreeofdenim.com, homepage_url: "https://degreeofdenim.com"}
  - {domain: psylos1.com, homepage_url: "https://psylos1.com", notes: custom nextjs}
  - {domain: www.staystillz.com, homepage_url: "https://www.staystillz.com"}
  - {domain: kuurth.com, homepage_url: "https://kuurth.com"}
  - {domain: www.viviennewestwood.com, homepage_url: "https://www.viviennewestwood.com", notes: enterprise 403 to plain http}
  - {domain: www.vancleefarpels.com, homepage_url: "https://www.vancleefarpels.com", notes: TLS-level block}
  - {domain: eightonline.shop, homepage_url: "https://eightonline.shop", notes: password-gated 2026-08-26}
  - {domain: humanbynature.co, homepage_url: "https://humanbynature.co"}
  - {domain: hip3399.com, homepage_url: "https://hip3399.com"}
  - {domain: vondutch.com, homepage_url: "https://vondutch.com"}
  - {domain: www.yoru.studio, homepage_url: "https://www.yoru.studio"}
  - {domain: bu-bully.com, homepage_url: "https://bu-bully.com", notes: password-gated 2026-08-26}
  - {domain: www.thesupermade.com, homepage_url: "https://www.thesupermade.com"}
  - {domain: www.varenneofficial.com, homepage_url: "https://www.varenneofficial.com"}
  - {domain: lorinate.com, homepage_url: "https://lorinate.com"}
  - {domain: unnamed.nyc, homepage_url: "https://unnamed.nyc"}
  - {domain: www.ragamalak.com, homepage_url: "https://www.ragamalak.com", notes: shopify json challenged}
  - {domain: huelleyrose.com, homepage_url: "https://huelleyrose.com"}
  - {domain: prod.net, homepage_url: "https://prod.net"}
  - {domain: marrknull.com, homepage_url: "https://marrknull.com", notes: shopify json challenged}
  - {domain: wiacollections.com, homepage_url: "https://wiacollections.com", notes: woocommerce}
  - {domain: sickokittens.com, homepage_url: "https://sickokittens.com", notes: 429 to plain http}
  - {domain: byellenwithlove.com, homepage_url: "https://byellenwithlove.com", notes: password link; 429 to plain http}
  - {domain: staud.clothing, homepage_url: "https://staud.clothing", notes: 429 to plain http}
  - {domain: laluneofficial.com, homepage_url: "https://laluneofficial.com", notes: wordpress}
  - {domain: liniss.com, homepage_url: "https://liniss.com", notes: 429 to plain http}
  - {domain: www.gentlemonster.com, homepage_url: "https://www.gentlemonster.com", notes: enterprise challenge}
  - {domain: www.theoutnet.com, homepage_url: "https://www.theoutnet.com", notes: enterprise (YNAP multi-brand outlet), not yet probed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/archive/test_cli.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/archive/runner/cli.py backend/archive/brands.yml tests/unit/archive/test_cli.py
git commit -m "feat(archive): CLI (plan/scrape/status) and 36-brand target list"
```

---

### Task 14: End-to-end integration test, README, full-suite gate

**Files:**
- Create: `backend/archive/README.md`, `tests/unit/archive/test_end_to_end.py`
- Modify: `.gitignore` (add `backend/archive/data/`)

**Interfaces:**
- Consumes: everything.
- Produces: a hermetic end-to-end proof that `scrape` + `status` work through the CLI against a mocked Shopify brand, and the package's own README.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_end_to_end.py
"""Full-body test: CLI scrape of a mocked open-Shopify brand, then delta, then status."""
import json
from pathlib import Path

import httpx
import pytest

import backend.archive.runner.cli as cli
from backend.archive.transport import HttpxTransport

FIX = Path(__file__).parent / "fixtures"
YML = 'brands:\n  - {domain: kuurth.com, homepage_url: "https://kuurth.com"}\n'
HOME = '<html><head><title>KUURTH</title></head><body><script src="https://cdn.shopify.com/x"></script></body></html>'


def mock_transport() -> HttpxTransport:
    products = json.loads((FIX / "shopify_products_page1.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="Sitemap: https://kuurth.com/sitemap.xml\n")
        if path == "/":
            return httpx.Response(200, text=HOME)
        if path == "/products.json":
            page = request.url.params.get("page", "1")
            return httpx.Response(200, json=products if page == "1" else {"products": []})
        if path == "/sitemap.xml":
            return httpx.Response(200, text=(FIX / "sitemap_index.xml").read_text())
        if path == "/sitemap_products_1.xml":
            return httpx.Response(200, text=(FIX / "sitemap_products.xml").read_text())
        if path == "/sitemap_pages_1.xml":
            return httpx.Response(200, text='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>')
        return httpx.Response(404)

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


@pytest.mark.unit
def test_scrape_then_delta_then_status(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "HttpxTransport", mock_transport)  # CLI builds transports; swap in the mock
    brands = tmp_path / "brands.yml"; brands.write_text(YML)
    db = tmp_path / "catalog.db"
    common = ["--db", str(db), "--brands", str(brands),
              "--locks", str(tmp_path / "locks"), "--logs", str(tmp_path / "logs")]

    assert cli.main(["scrape", "kuurth.com", "--full", *common]) == 0
    assert cli.main(["scrape", "kuurth.com", "--delta", *common]) == 0  # nothing changed → still ok
    assert cli.main(["status", "--db", str(db), "--brands", str(brands)]) == 0
    out = capsys.readouterr().out
    assert "kuurth.com" in out and "active" in out and "100%" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_end_to_end.py -v`
Expected: FAIL — `monkeypatch.setattr` succeeds but `scrape` calls `HttpxTransport()` with no args returning the mock: if it errors instead, adjust `mock_transport` to accept and ignore call args by wrapping: `monkeypatch.setattr(cli, "HttpxTransport", lambda *a, **k: mock_transport())`. Use the lambda form in the final test.

- [ ] **Step 3: Fix the test to the lambda form, add README and .gitignore entry**

In the test replace the monkeypatch line with:

```python
    monkeypatch.setattr(cli, "HttpxTransport", lambda *a, **k: mock_transport())
```

Append to `.gitignore`:

```
# archive v2 runtime data
backend/archive/data/
```

Write `backend/archive/README.md`:

```markdown
# Archive v2

The scheduled brand-scraping body. Spec: `docs/superpowers/specs/2026-08-27-archive-v2-design.md`.
Plan: `docs/superpowers/plans/2026-08-27-archive-v2-milestone-1.md`.

## The one-paragraph map

`runner/cli.py` is the front door (`python -m backend.archive.runner.cli plan|scrape|status`).
`fingerprint.py` probes a domain (~4 GETs) into a `Capability`; `planner.py` composes it into a
`ScrapePlan` (transport × discovery × fetch × change-signal); `connectors/` implement the channels
(`shopify` bulk JSON, `sitemap` discovery; browser recipes and the agent arrive in milestones 2–3);
`runner/run.py` executes the lifecycle (scope → plan → calibrate → promote → monitor) with per-brand
locks and honest exit codes (0 ok / 1 degraded / 2 failed); `verify.py` turns channel counts into
verdicts; `store/catalog.py` is the only DB gateway — append-only runs and change-only observations
in SQLite (`backend/archive/data/catalog.db`), so price/stock history accumulates for free.

## Rules of the body

- Connectors never own transports or touch the DB.
- `domain/` imports nothing from the package; nothing imports from legacy `scraper/`, `stages/`, `prod_page_v2/`.
- Runs and observations are append-only; no code deletes prior data.
- All tests are hermetic (httpx.MockTransport, tmp_path). Live-site tests require explicit prior announcement.
```

- [ ] **Step 4: Run the entire archive suite and the repo's unit gate**

Run: `python3 -m pytest tests/unit/archive -v && python3 -m pytest -m unit`
Expected: all archive tests PASS; the pre-existing unit suite still PASSES (28 tests + new ones)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/archive/test_end_to_end.py backend/archive/README.md .gitignore
git commit -m "feat(archive): end-to-end CLI test, package README, ignore runtime data"
```

---

### Task 15: Image archiver

Images are first-class archive material (spec §4.4): CDNs delete images when products are delisted, so the archive downloads the files.

**Files:**
- Create: `backend/archive/images.py`
- Modify: `backend/archive/store/schema.sql` (add UNIQUE constraint), `backend/archive/store/catalog.py`, `backend/archive/runner/run.py`, `backend/archive/runner/cli.py`
- Test: `tests/unit/archive/test_images.py`

**Interfaces:**
- Consumes: `Catalog`, `Transport`, `ProductRecord`.
- Produces:
  - In `schema.sql`, the images table becomes:
    ```sql
    CREATE TABLE IF NOT EXISTS images (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id   INTEGER NOT NULL REFERENCES products(id),
      url          TEXT NOT NULL,
      local_path   TEXT NOT NULL,
      content_hash TEXT NOT NULL,
      UNIQUE (product_id, url)
    );
    ```
  - `Catalog.known_image_urls(product_id: int) -> set[str]`; `Catalog.record_image(product_id, url, local_path, content_hash) -> None` (INSERT OR IGNORE); `Catalog.product_id_for(domain, canonical_url) -> int | None`; `Catalog.image_count(domain) -> int`.
  - `class ImageStore(root: Path)` with `archive(transport, catalog: Catalog, product_id: int, domain: str, urls: list[str]) -> int` — for each URL not already known: GET through the transport; skip non-200 or non-image content-types with a logged warning (never fail the run); write bytes to `root/{domain}/{sha[:2]}/{sha}{ext}` (sha = sha256 hex of bytes; ext from content-type: `image/jpeg→.jpg`, `image/png→.png`, `image/webp→.webp`, else `.bin`); `record_image`; return count of newly saved files.
  - `run_brand(..., image_store: ImageStore | None = None)` — after each `record_product` call, when an observation was appended (i.e. `record_product` returned True — new or changed product), call `image_store.archive(...)` for that product's `record.images`. `None` disables archiving (tests that don't care stay unchanged).
  - CLI `scrape` gains `--no-images` (default: images on) and `--images-dir` (default `backend/archive/data/images`), constructing the `ImageStore` and passing it through.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/archive/test_images.py
import hashlib

import httpx
import pytest

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.images import ImageStore
from backend.archive.store.catalog import Catalog
from backend.archive.transport import HttpxTransport

JPEG_BYTES = b"\xff\xd8\xff\xe0FAKEJPEG"


def make_transport(counter: dict) -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        counter[str(request.url)] = counter.get(str(request.url), 0) + 1
        return httpx.Response(200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"})

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture()
def env(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    run = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", run,
                       ProductRecord(canonical_url="https://kuurth.com/products/nemo", product_title="Nemo",
                                     images=["https://cdn.shopify.com/nemo-1.jpg"]), None)
    pid = cat.product_id_for("kuurth.com", "https://kuurth.com/products/nemo")
    return cat, pid, ImageStore(tmp_path / "images"), tmp_path


@pytest.mark.unit
def test_archive_downloads_content_addressed_file(env):
    cat, pid, store, tmp = env
    counter: dict = {}
    saved = store.archive(make_transport(counter), cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"])
    assert saved == 1
    sha = hashlib.sha256(JPEG_BYTES).hexdigest()
    expected = tmp / "images" / "kuurth.com" / sha[:2] / f"{sha}.jpg"
    assert expected.read_bytes() == JPEG_BYTES
    assert cat.image_count("kuurth.com") == 1


@pytest.mark.unit
def test_known_urls_are_never_redownloaded(env):
    """Delta economics: an unchanged image costs zero requests on re-runs."""
    cat, pid, store, _ = env
    counter: dict = {}
    t = make_transport(counter)
    store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"])
    saved = store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"])
    assert saved == 0
    assert counter["https://cdn.shopify.com/nemo-1.jpg"] == 1


@pytest.mark.unit
def test_bad_response_is_skipped_not_fatal(env):
    cat, pid, store, _ = env
    t = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/gone.jpg"]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/archive/test_images.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write the implementation**

Apply the `schema.sql` change from the Interfaces block. Add to `Catalog`:

```python
    # --- images ---
    def product_id_for(self, domain: str, canonical_url: str) -> int | None:
        row = self._db.execute("SELECT id FROM products WHERE domain=? AND canonical_url=?",
                               (domain, canonical_url)).fetchone()
        return row["id"] if row else None

    def known_image_urls(self, product_id: int) -> set[str]:
        rows = self._db.execute("SELECT url FROM images WHERE product_id=?", (product_id,)).fetchall()
        return {r["url"] for r in rows}

    def record_image(self, product_id: int, url: str, local_path: str, content_hash: str) -> None:
        self._db.execute("INSERT OR IGNORE INTO images (product_id, url, local_path, content_hash) "
                         "VALUES (?,?,?,?)", (product_id, url, local_path, content_hash))
        self._db.commit()

    def image_count(self, domain: str) -> int:
        return self._db.execute(
            "SELECT COUNT(*) c FROM images i JOIN products p ON p.id=i.product_id WHERE p.domain=?",
            (domain,)).fetchone()["c"]
```

```python
# backend/archive/images.py
"""Image archiver: the files, not just the URLs — CDNs forget, archives don't (spec §4.4)."""
import hashlib
from pathlib import Path

from backend.archive.store.catalog import Catalog
from backend.archive.transport import Transport

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


class ImageStore:
    def __init__(self, root: Path):
        self.root = root

    def archive(self, transport: Transport, catalog: Catalog, product_id: int,
                domain: str, urls: list[str]) -> int:
        known = catalog.known_image_urls(product_id)
        saved = 0
        for url in urls:
            if url in known:
                continue
            try:
                resp = transport.get(url)
            except Exception:
                continue  # a missing image never fails a run
            ctype = resp.headers.get("content-type", "").split(";")[0].strip()
            if resp.status_code != 200 or not ctype.startswith("image/"):
                continue
            sha = hashlib.sha256(resp.content).hexdigest()
            path = self.root / domain / sha[:2] / f"{sha}{_EXT.get(ctype, '.bin')}"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(resp.content)
            catalog.record_image(product_id, url, str(path), sha)
            saved += 1
        return saved
```

In `backend/archive/runner/run.py`: add parameter `image_store=None` to `run_brand`, and inside the fetch loop, immediately after `catalog.record_product(...)`:

```python
            appended = catalog.record_product(brand.domain, run_id, rec, r.change_hint)
            if appended and image_store is not None and rec.images:
                pid = catalog.product_id_for(brand.domain, rec.canonical_url)
                n = image_store.archive(transport, catalog, pid, brand.domain, rec.images)
                if n:
                    log("images-archived", url=rec.canonical_url, count=n)
```

(The existing bare `catalog.record_product(...)` call is replaced by the `appended = ...` form.)

In `backend/archive/runner/cli.py` `scrape` subparser, add:

```python
            sp.add_argument("--no-images", action="store_true")
            sp.add_argument("--images-dir", type=Path, default=Path("backend/archive/data/images"))
```

and in the scrape branch build `image_store = None if args.no_images else ImageStore(args.images_dir)` (import `ImageStore` from `backend.archive.images`), passing `image_store=image_store` to `run_brand`.

- [ ] **Step 4: Run the image tests plus runner/e2e regressions**

Run: `python3 -m pytest tests/unit/archive/test_images.py tests/unit/archive/test_runner.py tests/unit/archive/test_end_to_end.py -v`
Expected: all PASS (runner tests pass `image_store=None` implicitly via the default)

- [ ] **Step 5: Commit**

```bash
git add backend/archive/images.py backend/archive/store tests/unit/archive/test_images.py backend/archive/runner
git commit -m "feat(archive): content-addressed image archiving wired into the runner"
```

---

## After milestone 1 (not in this plan)

- First live validation: run `archive plan` / `archive scrape` against 2–3 open-Shopify brands — **only after announcing to Bhavya exactly which domains and requests** (house rule), then `--all`.
- Schedule `python -m backend.archive.runner.cli scrape --all --delta` via launchd/cron or a Claude scheduled task.
- Milestone 2: browser transport (BrowserPool + stealth port), recipes connector (e0005 port with the memo/pool fix), structured-data fetch for sitemap discovery.
- Milestone 3: agent connector + drift-triggered recompilation. Milestone 4: the gut (delete legacy packages, point Flask reads at `catalog.py`).
```
