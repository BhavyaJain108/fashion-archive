"""
LlmBatchExtractionMethod — production-time per-product LLM fallback.

Discovery adds this as a catalog row for any field where:
  - the LLM had a ground-truth value, AND
  - every deterministic method proposed for it was discarded by verification.

At production time, one batched LLM call resolves all such "fallback fields"
for a product in one shot. The same Method instance covers N fields; the
per-page memo scratch dict caches the call's result so each per-field
produce() invocation shares one LLM call.

Cost: ~$0.0005-$0.002 per product on Qwen (text-only, with rendered DOM +
field specs in the prompt). Multiply by 1 per product, NOT per field — that's
the point of batching.

This method is NOT proposed by the discovery LLM. The Discovery code adds
it automatically as a fallback row. (Documenting it in the prompt would
encourage the LLM to lean on it instead of proposing cheap deterministic
methods.)
"""

from __future__ import annotations

import json as _json
import os
import re
from typing import Any, Dict, List, Optional

from ..catalog import Method, MethodResult, register_method
from ..field_specs import SCHEMA_DESCRIPTIONS
from ..memo import PageMemo


# Caps on context sent to the batch LLM call.
_CAP_VISIBLE_TEXT = 6000
_CAP_DOM_EXCERPT = 8000
_CAP_LD_JSON = 4000
_CAP_SHOPIFY_JSON = 4000


@register_method
class LlmBatchExtractionMethod(Method):
    """One-LLM-call-per-product fallback for fields no cheap method covers."""

    kind = "llm_batch_extraction"
    cost_usd = 0.002       # rough budget per product (Qwen text)
    latency_ms = 1500

    # Per-page scratch key prefix — all instances with the same `fields`
    # list share the cache, so first produce() pays the LLM cost and
    # subsequent ones hit the cache.
    _SCRATCH_PREFIX = "llm_batch_extraction"

    def __init__(self, fields: List[str], model: Optional[str] = None):
        if not fields:
            raise ValueError("LlmBatchExtractionMethod requires at least one field")
        self.fields = sorted(set(fields))
        self.model = model  # None → use whatever LLM_PROVIDER is configured

    def _config_dict(self) -> Dict[str, Any]:
        return {"fields": self.fields, "model": self.model}

    def _scratch_key(self) -> str:
        return f"{self._SCRATCH_PREFIX}::{self.model or 'default'}::{','.join(self.fields)}"

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        if field_name not in self.fields:
            return MethodResult(value=None)
        scratch = memo.scratch()
        key = self._scratch_key()
        if key not in scratch:
            scratch[key] = await self._run_batch(memo)
        results = scratch[key]
        value = results.get(field_name) if isinstance(results, dict) else None
        if value in (None, "", [], {}):
            return MethodResult(value=None)
        return MethodResult(value=value, confidence=0.7)

    # -------------------------------------------------------------
    # Internal: one LLM call that fills all this instance's `fields`
    # -------------------------------------------------------------

    async def _run_batch(self, memo: PageMemo) -> Dict[str, Any]:
        prompt = await self._build_prompt(memo)
        try:
            from scraper.llm_handler import LLMHandler
            handler = LLMHandler()
        except Exception as e:
            print(f"[LlmBatchExtractionMethod] handler init failed: {e!r}")
            return {}

        # Build a Pydantic model on-the-fly that matches the requested fields
        # so we can use the handler's structured-output path.
        from pydantic import BaseModel, create_model
        ann: Dict[str, Any] = {f: (Optional[str], None) for f in self.fields}
        BatchModel = create_model("BatchExtraction", **ann)  # type: ignore

        try:
            result = handler.call(
                prompt=prompt,
                expected_format="json",
                response_model=BatchModel,
                max_tokens=2000,
                operation="llm_batch_extraction",
            )
        except Exception as e:
            print(f"[LlmBatchExtractionMethod] LLM call failed: {e!r}")
            return {}

        if not result.get("success"):
            return {}

        # LLMHandler.call returns structured output under 'data' (Pydantic) or
        # 'response' (raw text). Pick whichever is present.
        out = result.get("data") or result.get("response") or {}
        # When the handler returns a Pydantic model instance, normalize to dict.
        if hasattr(out, "model_dump"):
            out = out.model_dump()
        if isinstance(out, dict):
            return {k: v for k, v in out.items()
                    if v not in (None, "", [], {}) and k in self.fields}
        return {}

    async def _build_prompt(self, memo: PageMemo) -> str:
        # Per-field specs the LLM should follow.
        field_lines: List[str] = []
        for f in self.fields:
            spec = SCHEMA_DESCRIPTIONS.get(f, {})
            field_lines.append(
                f"- `{f}`: {spec.get('description', '')} "
                f"(format: {spec.get('format', 'string')})"
            )
            if spec.get("pitfall"):
                field_lines.append(f"    pitfall: {spec['pitfall']}")
        fields_section = "\n".join(field_lines)

        visible_text = (await memo.visible_text())[:_CAP_VISIBLE_TEXT]

        # Compact PageMemo dump — visible text + LD+JSON + Shopify JSON (when present).
        ld_blob = await memo.ld_json_product()
        ld_section = _json.dumps(ld_blob, indent=2)[:_CAP_LD_JSON] if ld_blob else "(none)"

        shopify_blob = None
        try:
            from .shopify_json import ShopifyProductJsonMethod
            shopify_blob = await ShopifyProductJsonMethod._get_blob(memo)
        except Exception:
            shopify_blob = None
        shopify_section = _json.dumps(shopify_blob, indent=2)[:_CAP_SHOPIFY_JSON] if shopify_blob else "(none)"

        # Revealed accordion panels.
        panels = []
        for k, v in (memo._accordion_text or {}).items():
            if v:
                panels.append(f"=== Revealed: {k} ===\n{v[:1500]}")
        panels_section = "\n\n".join(panels) if panels else "(none)"

        return f"""Extract the following product page fields. Return null for any field
that is genuinely not present on this page.

URL: {memo.url}

Fields to fill:
{fields_section}

=== Visible text (post-render, post-reveal) ===
{visible_text}

=== LD+JSON Product blob ===
{ld_section}

=== Shopify product.json ===
{shopify_section}

=== Revealed panels (accordion content) ===
{panels_section}

Return strictly the structured object with one key per requested field."""
