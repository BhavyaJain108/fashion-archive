"""
Method catalog + base Method abstraction.

A `Method` is the smallest unit of capability: "given a PageMemo, produce
a value for field X." Methods don't know which field they're answering
when constructed — that's done by binding them into a `CatalogRow` with
the target field name. The same method *kind* (e.g. `LdJsonPathMethod`)
appears in multiple rows when it provides multiple fields from one shared
LD+JSON parse.

A `SiteCatalog` is a per-domain list of CatalogRows learned at discovery
time. The orchestrator walks it: for each field, try rows in order until
one yields a non-blank value.

Cost is reported in dollars (LLM/API calls cost money, scrapers ~0).
Latency in milliseconds is informational — used for telemetry, not for
ordering during production (catalogs are already ordered).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from .memo import PageMemo


# Artifact kinds a method can declare it needs. Used so the orchestrator
# (or a planner) can decide whether to skip a method when its required
# artifacts are unavailable or too expensive on this run.
class Artifact:
    RAW_HTML = "raw_html"
    LD_JSON = "ld_json"
    META_TAGS = "meta_tags"
    MICRODATA = "microdata"
    RENDERED_HTML = "rendered_html"
    NETWORK = "network"
    SCREENSHOT = "screenshot"
    ACCORDION = "accordion"  # method clicks something — increments cost


@dataclass
class MethodResult:
    """What a Method returns when called for one field."""

    value: Optional[Any]
    confidence: float = 1.0     # 0.0–1.0 — used during discovery to compare candidates
    notes: Optional[str] = None  # debugging only


class Method(ABC):
    """Base class for every extraction method.

    Subclasses implement one `kind` (e.g. `ld_json_path`, `dom_selector`).
    They take method-specific config in __init__ (jsonpath, CSS selector,
    URL pattern, etc.) and return a value for one field via `produce`.

    Identifying a method costs the orchestrator nothing — only `produce`
    triggers any work.
    """

    # Class-level identifier — must be unique per method kind.
    kind: str = "abstract"

    # Approximate per-call cost in USD. Real cost lives in the bound
    # method instance (e.g. llm calls override based on token count).
    cost_usd: float = 0.0

    # Approximate latency in milliseconds. Informational only.
    latency_ms: int = 1

    # Which PageMemo artifacts this method needs. The memo provisions
    # them lazily; this set is informational + used to skip impossible
    # methods (e.g. screenshot-required method on a non-render run).
    requires: Set[str] = frozenset()

    @abstractmethod
    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        """Produce a value for `field_name` using artifacts from `memo`.

        Implementations should:
        - Be idempotent (orchestrator may retry).
        - Return `MethodResult(value=None)` when they can't produce —
          NOT raise. Exceptions are surfaced as orchestrator failures.
        - Respect the memo's lazy contract — `await memo.ld_json_product()`
          etc. The memo handles caching.
        """
        ...

    def to_config(self) -> Dict[str, Any]:
        """Serialize the bound method so we can persist a SiteCatalog to disk."""
        return {"kind": self.kind, **self._config_dict()}

    def _config_dict(self) -> Dict[str, Any]:
        """Subclass hook — return method-specific config (selector,
        jsonpath, regex, etc.). Default: empty (config-less method)."""
        return {}


@dataclass
class CatalogRow:
    """One field's binding to one method instance.

    The orchestrator tries rows in list order for a given field; first
    non-blank value wins.
    """

    field: str
    method: Method
    # Confidence learned during discovery. Higher = more reliable; used
    # to break ties when ordering multiple rows for the same field.
    confidence: float = 1.0
    # Free-form notes — e.g. "discovered via vision LLM 2026-05-12".
    notes: Optional[str] = None


@dataclass
class SiteCatalog:
    """Per-domain catalog: which methods produce which fields for this site."""

    domain: str
    discovered_at: datetime
    discovery_url: str
    rows: List[CatalogRow] = field(default_factory=list)
    # Free-form per-site metadata (e.g. detected platform, locale).
    site_meta: Dict[str, Any] = field(default_factory=dict)

    def rows_for(self, field_name: str) -> List[CatalogRow]:
        """Return rows for `field_name` in production-time preference order.

        Sort key: (source_cost_ms ascending, -confidence). Cost is the
        property of the method kind, looked up from the global source-cost
        table — with the per-site measured_costs_ms override applied when
        site_meta has recorded one.
        """
        from .source_costs import source_cost_ms
        measured = self.site_meta.get("measured_costs_ms") if self.site_meta else None
        matching = [r for r in self.rows if r.field == field_name]
        matching.sort(key=lambda r: (
            source_cost_ms(r.method.kind, measured),
            -r.confidence,
        ))
        return matching

    def fields_covered(self) -> Set[str]:
        return {r.field for r in self.rows}

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "discovered_at": self.discovered_at.isoformat(),
            "discovery_url": self.discovery_url,
            "site_meta": self.site_meta,
            "rows": [
                {
                    "field": r.field,
                    "method": r.method.to_config(),
                    "confidence": r.confidence,
                    "notes": r.notes,
                }
                for r in self.rows
            ],
        }


# Method registry — maps `kind` strings to method classes so we can
# rehydrate a SiteCatalog from disk. Methods register themselves via
# `register_method` (decorator pattern) when their module is imported.
_METHOD_REGISTRY: Dict[str, type] = {}


def register_method(cls: type) -> type:
    """Decorator: register a Method subclass by its `kind` so catalogs
    can be deserialized from JSON."""
    if not hasattr(cls, "kind") or cls.kind == "abstract":
        raise ValueError(f"{cls.__name__} must override `kind`")
    if cls.kind in _METHOD_REGISTRY:
        raise ValueError(f"method kind {cls.kind!r} already registered")
    _METHOD_REGISTRY[cls.kind] = cls
    return cls


def hydrate_method(config: Dict[str, Any]) -> Method:
    """Build a Method instance from its serialized config."""
    kind = config["kind"]
    if kind not in _METHOD_REGISTRY:
        raise KeyError(f"unknown method kind {kind!r}; registered: {list(_METHOD_REGISTRY)}")
    cls = _METHOD_REGISTRY[kind]
    # Pass everything except `kind` as kwargs. Each method's __init__
    # is responsible for accepting its config keys.
    init_kwargs = {k: v for k, v in config.items() if k != "kind"}
    return cls(**init_kwargs)


def hydrate_catalog(data: dict) -> SiteCatalog:
    """Build a SiteCatalog from its serialized form."""
    return SiteCatalog(
        domain=data["domain"],
        discovered_at=datetime.fromisoformat(data["discovered_at"]),
        discovery_url=data["discovery_url"],
        site_meta=data.get("site_meta", {}),
        rows=[
            CatalogRow(
                field=r["field"],
                method=hydrate_method(r["method"]),
                confidence=r.get("confidence", 1.0),
                notes=r.get("notes"),
            )
            for r in data["rows"]
        ],
    )
