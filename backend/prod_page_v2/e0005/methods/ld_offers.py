"""
LdJsonOffersAvailabilityMethod — convert schema.org Offer.availability into
the E0005 `in_stock` integer (1 / 0).

Lives separately from LdJsonPathMethod because Offer.availability uses
schema.org IRIs ("https://schema.org/InStock") that need parsing, not
just a raw extraction.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..catalog import Artifact, Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class LdJsonOffersAvailabilityMethod(Method):
    kind = "ld_json_offers_availability"
    cost_usd = 0.0
    latency_ms = 1
    requires = frozenset({Artifact.LD_JSON})

    def _config_dict(self) -> Dict[str, Any]:
        return {}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        product = await memo.ld_json_product()
        if product is None:
            return MethodResult(value=None)
        offers = product.get("offers")
        if not offers:
            return MethodResult(value=None)
        if isinstance(offers, dict):
            offers = [offers]
        # In stock if ANY offer is in-stock.
        any_in = False
        any_known = False
        for offer in offers:
            avail = (offer.get("availability") or "").lower()
            if "instock" in avail or "in_stock" in avail or "preorder" in avail:
                any_in = True
                any_known = True
            elif "outofstock" in avail or "out_of_stock" in avail or "discontinued" in avail:
                any_known = True
        if not any_known:
            return MethodResult(value=None)
        return MethodResult(value=1 if any_in else 0, confidence=0.95)
