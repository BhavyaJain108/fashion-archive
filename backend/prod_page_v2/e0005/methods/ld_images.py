"""
Image extraction methods.

LD+JSON Product blobs carry one or more images at `$.image` but often
only the front-shot. Most fashion sites (McQueen / Shopify / Salesforce
Commerce) load the rest from a CDN via the same network call, so we also
expose a NetworkImagesMethod that scans captured network responses for
product-CDN URLs matching the SKU.
"""

from __future__ import annotations

import json as _json
from typing import Any, Dict, List

from ..catalog import Artifact, Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class LdJsonImagesMethod(Method):
    """All images from LD+JSON $.image (handles both string and array)."""

    kind = "ld_json_images"
    cost_usd = 0.0
    latency_ms = 1
    requires = frozenset({Artifact.LD_JSON})

    def _config_dict(self) -> Dict[str, Any]:
        return {}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        product = await memo.ld_json_product()
        if product is None:
            return MethodResult(value=None)
        images = product.get("image")
        if not images:
            return MethodResult(value=None)
        if isinstance(images, str):
            images = [images]
        # E0005 wants all_images as a JSON-encoded string; main_image_url as scalar.
        if field_name == "main_image_url":
            return MethodResult(value=images[0] if images else None, confidence=1.0)
        if field_name == "all_images":
            return MethodResult(value=_json.dumps(images, ensure_ascii=False), confidence=1.0)
        return MethodResult(value=None)


@register_method
class NetworkImagesMethod(Method):
    """Scan captured image URLs for ones matching the product SKU / containing
    /product/ or /eCom/ patterns. Use when LD+JSON only has the cover image."""

    kind = "network_images"
    cost_usd = 0.0
    latency_ms = 2
    requires = frozenset({Artifact.NETWORK})

    def __init__(self, sku_hint: str = "", path_pattern: str = "/eCom/"):
        self.sku_hint = sku_hint
        self.path_pattern = path_pattern

    def _config_dict(self) -> Dict[str, Any]:
        return {"sku_hint": self.sku_hint, "path_pattern": self.path_pattern}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        # We pull image URLs from the playwright on_response capture (network log).
        # PageMemo currently records all network captures; image URLs were also
        # accumulated by an older path — we re-scan here against the URL list.
        events = await memo.network()
        # Collect candidate URLs ending in image extensions.
        urls: List[str] = []
        seen = set()
        IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
        for e in events:
            u = e.url
            lower = u.lower()
            if not any(lower.endswith(ext) or f"{ext}?" in lower for ext in IMG_EXT):
                continue
            if self.path_pattern and self.path_pattern not in u:
                continue
            if self.sku_hint and self.sku_hint not in u:
                continue
            if u in seen:
                continue
            seen.add(u)
            urls.append(u)
        if not urls:
            return MethodResult(value=None)
        if field_name == "main_image_url":
            return MethodResult(value=urls[0], confidence=0.8)
        if field_name == "all_images":
            return MethodResult(value=_json.dumps(urls, ensure_ascii=False), confidence=0.9)
        return MethodResult(value=None)
