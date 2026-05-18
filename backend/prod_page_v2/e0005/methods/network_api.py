"""
NetworkApiMethod — fetch a brand's product API and read fields from the JSON.

Many brands ship a clean product API alongside their HTML pages — e.g.
  /api/v1/availability/<SKU>
  /api/inventory?pid=<SKU>
  /_next/data/<buildId>/product/<slug>.json
  /gql with a known query body

Discovery captures the response bodies of every same-host JSON GET on
page load. Whichever ones contain field values become candidates; the
LLM picks paths into them and proposes `network_api` recipes.

At production time:
  1. Resolve {sku} (or other placeholders) from the new product's page.
  2. Substitute into url_template.
  3. HTTP GET. Parse JSON. Read json_path.
  4. Cache the parsed response on memo scratch — multiple fields from
     the same endpoint share one HTTP call.

Currently GET-only. POST endpoints are skipped at discovery (they tend
to be bot-protection beacons; we don't want to fire them at production).

Path resolution shares syntax with shopify_product_json:
  foo.bar              dot-walk
  foo[].bar            list-enumerate
  foo[0]               index
  :join_comma          flatten + comma-join
  :dedupe_join_comma   distinct + comma-join
  :first               first non-empty
  :any_truthy          1 if any non-null known, else None
  :json                serialize to JSON
"""

from __future__ import annotations

import asyncio
import gzip
import json as _json
import re
import urllib.request
from typing import Any, Dict, Optional

from ..catalog import Method, MethodResult, register_method
from ..memo import PageMemo, USER_AGENT
from .shopify_json import _resolve_path, _apply_transform


# ---------------------------------------------------------------------------
# SKU resolvers — `sku_source` syntax: "<kind>:<arg>" where kind is one of
#   ld_json       arg = JSONPath into the LD+JSON Product blob ("$.sku")
#   url_pattern   arg = regex with one capture group, applied to memo.url
#   meta          arg = meta tag name
#   literal       arg = the literal SKU string (rare, e.g. site-wide endpoints)
# ---------------------------------------------------------------------------

async def _resolve_sku(memo: PageMemo, sku_source: str) -> Optional[str]:
    """Return the resolved {sku} value for this page, or None on failure."""
    if not sku_source or ":" not in sku_source:
        return None
    kind, _, arg = sku_source.partition(":")
    kind = kind.strip()
    arg = arg.strip()

    if kind == "literal":
        return arg

    if kind == "ld_json":
        blob = await memo.ld_json_product()
        if not blob:
            return None
        v = _resolve_path(blob, arg[2:] if arg.startswith("$.") else arg)
        return str(v) if v not in (None, "", []) else None

    if kind == "url_pattern":
        try:
            m = re.search(arg, memo.url)
            if m:
                return m.group(1)
        except re.error:
            return None
        return None

    if kind == "meta":
        tags = await memo.meta_tags()
        v = tags.get(arg.lower())
        return v if v else None

    return None


# ---------------------------------------------------------------------------
# Method
# ---------------------------------------------------------------------------

@register_method
class NetworkApiMethod(Method):
    """Fetch a brand product API endpoint and read a field from the JSON."""

    kind = "network_api"
    cost_usd = 0.0
    latency_ms = 150

    # Scratch namespace; one cached response per (url_template, sku) pair.
    _SCRATCH_PREFIX = "network_api"

    def __init__(self,
                 url_template: str,
                 sku_source: str,
                 json_path: str,
                 method: str = "GET",
                 headers: Optional[Dict[str, str]] = None,
                 transform: Optional[str] = None):
        self.url_template = url_template
        self.sku_source = sku_source
        self.json_path = json_path
        self.method = (method or "GET").upper()
        self.headers = headers or {}
        self.transform = transform

    def _config_dict(self) -> Dict[str, Any]:
        return {
            "url_template": self.url_template,
            "sku_source": self.sku_source,
            "json_path": self.json_path,
            "method": self.method,
            "headers": self.headers,
            "transform": self.transform,
        }

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        if self.method != "GET":
            # GET-only at production. POSTs at discovery were captured for
            # context but never auto-fired against new products.
            return MethodResult(value=None)
        sku = await _resolve_sku(memo, self.sku_source)
        if not sku:
            return MethodResult(value=None)
        url = self.url_template.replace("{sku}", sku)
        blob = await self._cached_fetch(memo, url)
        if blob is None:
            return MethodResult(value=None)
        value = _resolve_path(blob, self.json_path)
        if value is None or (isinstance(value, (list, str)) and len(value) == 0):
            return MethodResult(value=None)
        value = _apply_transform(value, self.transform)
        if value is None:
            return MethodResult(value=None)
        return MethodResult(value=value, confidence=1.0)

    async def _cached_fetch(self, memo: PageMemo, url: str) -> Optional[Any]:
        scratch = memo.scratch()
        key = f"{self._SCRATCH_PREFIX}::{url}"
        if key in scratch:
            return scratch[key]
        try:
            data = await asyncio.to_thread(self._fetch, url, self.headers)
            blob = _json.loads(data)
            scratch[key] = blob
            return blob
        except Exception:
            scratch[key] = None
            return None

    @staticmethod
    def _fetch(url: str, extra_headers: Dict[str, str]) -> str:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        headers.update(extra_headers or {})
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
            if r.headers.get("content-encoding") == "gzip":
                data = gzip.decompress(data)
            return data.decode("utf-8", errors="ignore")
