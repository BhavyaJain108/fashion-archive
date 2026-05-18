"""
E0005 field-first extraction module.

Public API:
  - E0005Row, ProductFields, DatasetMetadata, ... (schema.py)
  - PageMemo (memo.py)
  - Method, CatalogRow, SiteCatalog, register_method, hydrate_catalog (catalog.py)
  - FieldOrchestrator, ExtractionTrace, FieldTrace (orchestrator.py)

No method implementations yet — those live in `e0005/methods/` and
register themselves via `@register_method` when imported.
"""

from .schema import (
    E0005Row,
    ProductFields,
    DatasetMetadata,
    StoreContext,
    MerchantContext,
    EXTRACTABLE_FIELDS,
)
from .memo import PageMemo, NetworkCapture
from .catalog import (
    Artifact,
    Method,
    MethodResult,
    CatalogRow,
    SiteCatalog,
    register_method,
    hydrate_method,
    hydrate_catalog,
)
from .orchestrator import FieldOrchestrator, ExtractionTrace, FieldTrace
from .oneshot import (
    MethodAttempt, FieldAnswer, AskResult, VerifyResult, OneShotResult,
    ask_llm, verify, discover_oneshot,
    METHOD_KINDS_TEXT,
)
from .field_specs import (
    SCHEMA_DESCRIPTIONS, PRODUCT_TYPE_PRESETS,
    fields_for_product_type, build_schema_section,
)
from .source_costs import (
    STATIC_SOURCE_COST_MS, source_cost_ms, cost_class, CostMeter,
)

__all__ = [
    # schema
    "E0005Row", "ProductFields", "DatasetMetadata", "StoreContext",
    "MerchantContext", "EXTRACTABLE_FIELDS",
    # memo
    "PageMemo", "NetworkCapture",
    # catalog
    "Artifact", "Method", "MethodResult", "CatalogRow", "SiteCatalog",
    "register_method", "hydrate_method", "hydrate_catalog",
    # orchestrator
    "FieldOrchestrator", "ExtractionTrace", "FieldTrace",
    # oneshot
    "MethodAttempt", "FieldAnswer", "AskResult", "VerifyResult", "OneShotResult",
    "ask_llm", "verify", "discover_oneshot", "METHOD_KINDS_TEXT",
    # field specs
    "SCHEMA_DESCRIPTIONS", "PRODUCT_TYPE_PRESETS",
    "fields_for_product_type", "build_schema_section",
    # source costs
    "STATIC_SOURCE_COST_MS", "source_cost_ms", "cost_class", "CostMeter",
]
