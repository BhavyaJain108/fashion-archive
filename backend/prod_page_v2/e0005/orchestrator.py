"""
FieldOrchestrator — the top-level extraction loop.

Given a product URL and a SiteCatalog, produce one E0005Row:

  1. Spin up a PageMemo for the URL (lazy — no I/O yet).
  2. For each E0005 field, walk catalog rows in preference order.
  3. For each row, call `method.produce(memo, field)`. First row that
     returns a non-blank value wins; subsequent rows for that field are
     skipped.
  4. Merge dataset metadata (configured per pipeline run) into the row.
  5. Return the E0005Row.

The orchestrator is field-first. It does not know "strategies" exist.
It only knows fields and methods. Methods share work via the memo.

Discovery (building a SiteCatalog the first time we see a brand) is a
separate concern handled by a `Discoverer` — not in this skeleton.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .catalog import CatalogRow, MethodResult, SiteCatalog
from .memo import PageMemo
from .schema import (
    DatasetMetadata,
    E0005Row,
    EXTRACTABLE_FIELDS,
    MerchantContext,
    ProductFields,
    StoreContext,
)

log = logging.getLogger(__name__)


@dataclass
class FieldTrace:
    """Per-field decision trail. Useful for diagnostics + audit reports."""

    field: str
    chosen_method: Optional[str] = None
    chosen_value: Any = None
    attempted: List[Dict[str, Any]] = field(default_factory=list)
    # Each `attempted` entry: {"kind": str, "result": "ok"|"blank"|"error",
    # "error": str|None, "confidence": float}


@dataclass
class ExtractionTrace:
    """Per-URL trace assembled by the orchestrator. Stored alongside output."""

    url: str
    domain: str
    fields: Dict[str, FieldTrace] = field(default_factory=dict)
    artifacts_used: List[str] = field(default_factory=list)
    fields_filled: int = 0
    fields_blank: int = 0


class FieldOrchestrator:
    """Drives extraction for one URL against one catalog."""

    def __init__(
        self,
        catalog: SiteCatalog,
        dataset_metadata: Optional[DatasetMetadata] = None,
        store_context: Optional[StoreContext] = None,
        merchant_context: Optional[MerchantContext] = None,
        # Hard cap on field-attempts per URL to bound pathological catalogs.
        # In practice each field has 1-3 rows so this is rarely hit.
        max_attempts_per_field: int = 8,
    ):
        self.catalog = catalog
        self.dataset_metadata = dataset_metadata or DatasetMetadata()
        self.store_context = store_context or StoreContext()
        self.merchant_context = merchant_context or MerchantContext()
        self.max_attempts_per_field = max_attempts_per_field

    async def extract(self, url: str) -> tuple[E0005Row, ExtractionTrace]:
        """Run the extraction loop. Returns (row, trace)."""
        memo = PageMemo(url)
        product = ProductFields(itemurl=url)
        trace = ExtractionTrace(url=url, domain=self.catalog.domain)

        for field_name in EXTRACTABLE_FIELDS:
            ftrace = FieldTrace(field=field_name)
            trace.fields[field_name] = ftrace

            # itemurl is provided directly — short-circuit.
            if field_name == "itemurl":
                ftrace.chosen_method = "url_passthrough"
                ftrace.chosen_value = url
                continue

            rows = self.catalog.rows_for(field_name)
            if not rows:
                continue  # field not covered for this site — leave blank

            for row in rows[: self.max_attempts_per_field]:
                attempt: Dict[str, Any] = {
                    "kind": row.method.kind,
                    "confidence": row.confidence,
                }
                try:
                    result: MethodResult = await row.method.produce(memo, field_name)
                except Exception as exc:
                    attempt["result"] = "error"
                    attempt["error"] = repr(exc)
                    ftrace.attempted.append(attempt)
                    log.warning(
                        "method %s failed on field %s: %r",
                        row.method.kind, field_name, exc,
                    )
                    continue

                if self._is_blank(result.value):
                    attempt["result"] = "blank"
                    ftrace.attempted.append(attempt)
                    continue

                # Got a value — apply, stop walking this field's rows.
                attempt["result"] = "ok"
                ftrace.attempted.append(attempt)
                self._set_field(product, field_name, result.value)
                ftrace.chosen_method = row.method.kind
                ftrace.chosen_value = result.value
                break

        # Tally
        for fname in EXTRACTABLE_FIELDS:
            if product.is_field_blank(fname):
                trace.fields_blank += 1
            else:
                trace.fields_filled += 1
        trace.artifacts_used = memo.artifacts_loaded()

        row = E0005Row(
            dataset=self.dataset_metadata,
            store=self.store_context,
            merchant=self.merchant_context,
            product=product,
        )
        return row, trace

    @staticmethod
    def _is_blank(value: Any) -> bool:
        """A method result counts as 'no value' (try next row) when blank."""
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        if isinstance(value, (list, dict)):
            return len(value) == 0
        return False

    @staticmethod
    def _set_field(product: ProductFields, field_name: str, value: Any) -> None:
        """Coerce + assign. Pydantic will validate on assignment."""
        # Pydantic v2 models support direct attribute set; validation
        # fires automatically.
        try:
            setattr(product, field_name, value)
        except Exception as exc:
            log.warning("could not set %s=%r: %r", field_name, value, exc)
