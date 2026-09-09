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
    WOO_API = "woo_api"
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
    woo_api: bool = False
    ldjson_product: bool = False
    product_url_prefix: str | None = None  # learned, e.g. '/products/' or '/assets/'
    sitemap_url: str | None = None
    password_gated: bool = False
    challenged: bool = False
    currency: str | None = None  # store-level, e.g. Shopify's /meta.json
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
    sitemap_url: str | None = None  # carried for sitemap-discovery connectors
    product_url_prefix: str | None = None  # learned product URL shape
    currency: str | None = None  # the store's currency, where it states one

    @property
    def composition(self) -> str:
        return f"{self.transport.value}×{self.discovery.value}×{self.fetch.value}×{self.change_signal.value}"
