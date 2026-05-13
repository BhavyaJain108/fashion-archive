"""
Streaming-pipeline adapter for e0005.

Exposes a `ProductExtractor` class whose method surface matches the
legacy `prod_page_v2.extractor.ProductExtractor` so `stages/streaming.py`
can swap to e0005 via a single import. Internally:

  - discover_and_verify  → e0005.discover_oneshot on the first seed URL
                           (one Claude call per brand, builds SiteCatalog)
  - extract_single       → PageMemo + FieldOrchestrator (owns its browser)
  - extract_single_pooled → PageMemo with an external page from
                           BrowserPool + FieldOrchestrator
  - calibrate_wait_time  → no-op (PageMemo waits for networkidle)
  - discover_gallery_selector → no-op (ld_json_images / network_api cover it)

`_product_to_dict` in streaming.py reads from `result.product.{name,
price, currency, images, description, url, brand, sku, category,
variants}`. We construct a tiny `_Product` shim with exactly those
attributes from the e0005 ProductFields output.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from . import methods  # noqa: F401 — registers all method kinds
from .catalog import SiteCatalog, hydrate_catalog
from .field_specs import fields_for_product_type
from .memo import PageMemo
from .oneshot import discover_oneshot
from .orchestrator import FieldOrchestrator


# ---------------------------------------------------------------------------
# Shim types matching the legacy result/product shape that streaming.py reads
# ---------------------------------------------------------------------------

@dataclass
class _Variant:
    size: Optional[str] = None
    color: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[float] = None
    available: Optional[bool] = None


@dataclass
class _Product:
    """Subset of fields read by streaming.py's _product_to_dict."""
    name: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    images: List[str] = dc_field(default_factory=list)
    description: Optional[str] = None
    url: Optional[str] = None
    brand: Optional[str] = None
    sku: Optional[str] = None
    category: Optional[str] = None
    variants: List[_Variant] = dc_field(default_factory=list)
    # All-fields dump so downstream consumers can grab the rest of E0005.
    e0005: Dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class ExtractionResult:
    success: bool
    product: Optional[_Product] = None
    error: Optional[str] = None
    status_code: int = 0


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

# Catalog cache root. Each brand's catalog persists to disk so re-runs of
# the pipeline don't re-pay the discovery LLM cost.
_CATALOG_ROOT = Path(__file__).resolve().parents[1] / "extractions"


class ProductExtractor:
    """Drop-in replacement for the legacy ProductExtractor.

    Lifecycle (called by stages/streaming.py):

      extractor = ProductExtractor()
      cfg = await extractor.discover_and_verify(domain, [seed_url, ...])
      _   = await extractor.calibrate_wait_time(url, cfg)
      _   = await extractor.discover_gallery_selector(url)
      for url in product_urls:
          result = await extractor.extract_single_pooled(
              url, page, cfg, wait_time=..., gallery_selector=..., prefill=...
          )
    """

    def __init__(self):
        self.catalog: Optional[SiteCatalog] = None
        self.product_type: str = "fashion"

    # ---- Discovery ----------------------------------------------------

    async def discover_and_verify(
        self,
        domain: str,
        urls: List[str],
        product_type: str = "fashion",
    ) -> Optional[SiteCatalog]:
        """Build (or load) the SiteCatalog for `domain`.

        Discovery is ONE Claude call per brand. The catalog is cached
        to `extractions/<domain>/e0005_oneshot/<domain>_catalog.json` so
        repeated pipeline runs reuse it. Pass urls=[seed_url] — only the
        first URL is used as the discovery seed.
        """
        self.product_type = product_type
        cached = self._load_catalog(domain)
        if cached:
            self.catalog = cached
            return cached

        if not urls:
            return None
        seed_url = urls[0]

        memo = PageMemo(seed_url)
        try:
            result = await discover_oneshot(memo, product_type=product_type, domain=domain)
            self.catalog = result.catalog
            self._save_catalog(domain, result.catalog)
            return self.catalog
        finally:
            await memo.close()

    def _catalog_path(self, domain: str) -> Path:
        slug = domain.replace(".", "_")
        return _CATALOG_ROOT / slug / "e0005_oneshot" / f"{slug}_catalog.json"

    def _load_catalog(self, domain: str) -> Optional[SiteCatalog]:
        path = self._catalog_path(domain)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return hydrate_catalog(data)
        except Exception as exc:
            print(f"[e0005.extractor] could not load catalog {path}: {exc!r}")
            return None

    def _save_catalog(self, domain: str, catalog: SiteCatalog) -> None:
        path = self._catalog_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog.to_dict(), indent=2, ensure_ascii=False))

    # ---- Pipeline knobs (legacy API; no-op for e0005) -----------------

    async def calibrate_wait_time(self, url: str, config: Any) -> int:
        """Legacy: pick optimal post-render wait. e0005 handles its own
        networkidle wait inside PageMemo; this returns a reasonable
        default so the streaming pipeline's metric still has a number."""
        return 2000

    async def discover_gallery_selector(self, url: str) -> Optional[str]:
        """Legacy: find an image-carousel selector. e0005 reads images
        via ld_json_images and network_api, no selector needed."""
        return None

    # ---- Per-product extraction --------------------------------------

    async def extract_single(
        self,
        url: str,
        config: Optional[SiteCatalog] = None,
        prefill: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        """Extract one product, owning a fresh browser for the duration."""
        catalog = config or self.catalog
        if catalog is None:
            return ExtractionResult(success=False, error="no catalog (discovery skipped)")
        memo = PageMemo(url)
        try:
            return await self._run_orchestrator(memo, url, catalog, prefill)
        finally:
            await memo.close()

    async def extract_single_pooled(
        self,
        url: str,
        page: Any,                              # Playwright Page from BrowserPool
        config: Optional[SiteCatalog] = None,
        wait_time: int = 2000,                  # accepted for signature parity; ignored
        gallery_selector: Optional[str] = None, # accepted for signature parity; ignored
        prefill: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        """Extract one product using a pooled Playwright page (no own
        browser launched). The pool owns the page; we just navigate it.
        """
        catalog = config or self.catalog
        if catalog is None:
            return ExtractionResult(success=False, error="no catalog (discovery skipped)")
        memo = PageMemo(url, external_page=page, render_wait_ms=wait_time)
        try:
            return await self._run_orchestrator(memo, url, catalog, prefill)
        finally:
            await memo.close()  # no-op when external_page used; owner closes page

    async def _run_orchestrator(
        self,
        memo: PageMemo,
        url: str,
        catalog: SiteCatalog,
        prefill: Optional[Dict[str, Any]],
    ) -> ExtractionResult:
        orchestrator = FieldOrchestrator(catalog=catalog)
        try:
            row, trace = await orchestrator.extract(url, prefill=prefill or {})
        except Exception as exc:
            return ExtractionResult(success=False, error=f"{type(exc).__name__}: {exc}")

        p = row.product
        # At least a title is required to call it a successful extraction.
        if not p.product_title:
            return ExtractionResult(success=False, error="no product_title extracted")

        product = _Product(
            name=p.product_title,
            price=p.price,
            currency=None,
            images=list(p.all_images or ([p.main_image_url] if p.main_image_url else [])),
            description=p.description,
            url=p.itemurl or url,
            brand=p.brand,
            sku=p.product_code,
            category=" / ".join(filter(None, [p.category1, p.category2, p.category3, p.category4, p.category5])) or None,
            variants=[
                _Variant(size=s) for s in (p.size_info.split(", ") if p.size_info else [])
            ],
            e0005=p.model_dump() if hasattr(p, "model_dump") else dict(p.__dict__),
        )
        return ExtractionResult(success=True, product=product, status_code=200)


# ---------------------------------------------------------------------------
# Helper: build prefill from upstream pipeline state
# ---------------------------------------------------------------------------

def prefill_from_pipeline(
    *,
    url: str,
    brand: Optional[str] = None,
    category_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct an orchestrator `prefill` dict from upstream stage state.

    - itemurl    ← url
    - brand      ← caller (resolved from domain → display-name elsewhere)
    - categoryN  ← split of category_path on "/" (e.g. "women/tops/shirts"
                   → category1="women", category2="tops", category3="shirts")
    """
    out: Dict[str, Any] = {"itemurl": url}
    if brand:
        out["brand"] = brand
    if category_path:
        parts = [p for p in category_path.strip("/").split("/") if p]
        for i, part in enumerate(parts[:5], start=1):
            out[f"category{i}"] = part.replace("-", " ").strip().title()
    return out
