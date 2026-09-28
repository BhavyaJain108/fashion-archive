"""Capability axes and planning models (spec §4.0, §4.3)."""

from enum import Enum

from pydantic import BaseModel, Field

# The hreflang of the market whose prices the catalogue holds. We browse as a US visitor.
MARKET_HREFLANG = "en-us"


class TransportLevel(str, Enum):
    T0 = "t0"  # plain HTTP
    T1 = "t1"  # browser-grade headers
    # T1 through an egress proxy: the same request from an address the site does not
    # class as a datacenter. yeezy.com's Cloudflare rule blocks our ASN outright, before
    # any handshake or header is read (2026-09-27); no fingerprint answers that, only a
    # different address does. Costs money per request, so it is its own rung.
    T1P = "t1p"
    T2 = "t2"  # real browser + stealth
    # A T3 ("browser-only, TLS fingerprinting") sat here. Nothing ever produced or read
    # it — T1 turned out to be what that rung was for.
    T4 = "t4"  # gated (password/members): a verdict, not a way to connect


class DiscoveryChannel(str, Enum):
    BULK_JSON = "bulk_json"
    WOO_API = "woo_api"
    SITEMAP = "sitemap"
    # A Gatsby site's page data: every page as JSON beside the page. EQL's launch
    # platform (runfair) lists a retailer's products in the index's data.
    PAGE_DATA = "page_data"
    # Swell's storefront API (connectors/swell.py): the catalogue behind a headless
    # site, read with the publishable key the site's own page carries.
    SWELL_API = "swell_api"
    # A lane described as data (learn/recipes.py): discovery and fetch the model
    # proposed and the gate proved, run by a connector that already exists.
    RECIPE = "recipe"
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
    # Shopify with the bulk feed switched off still answers /products/<handle>.json.
    product_json: bool = False
    # A Gatsby site whose index page-data lists the products (runfair).
    page_data: bool = False
    # A Swell storefront: the store id (cdn.swell.store/<store>/) and the publishable
    # key the page embeds; together they open <store>.swell.store/api/products.
    swell_store: str | None = None
    swell_key: str | None = None
    product_url_prefix: str | None = None  # learned, e.g. '/products/' or '/assets/'
    sitemap_url: str | None = None
    password_gated: bool = False
    challenged: bool = False
    currency: str | None = None  # store-level, e.g. Shopify's /meta.json
    # Where the products actually are, when it is not the brand's own host: La Lune's
    # site is a portfolio and its "Shop" link goes to shop.laluneofficial.com.
    shop_domain: str | None = None
    evidence: dict[str, str] = Field(default_factory=dict)

    def readable(self) -> bool:
        """Did the probe find anything a connector could actually read? A sitemap does
        not count: it lists URLs without making any of them parseable."""
        return bool(
            self.bulk_json
            or self.woo_api
            or self.ldjson_product
            or self.product_json
            or self.page_data
            or bool(self.swell_store and self.swell_key)
        )


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
    swell_store: str | None = None  # carried for the Swell connector
    swell_key: str | None = None
    currency: str | None = None  # the store's currency, where it states one
    shop_domain: str | None = None  # the host discovery reads, when not the brand's own
    # The lane recipe, when discovery is RECIPE: carried on the plan so the connector
    # needs no second read to run it.
    recipe: dict | None = None

    @property
    def composition(self) -> str:
        return f"{self.transport.value}×{self.discovery.value}×{self.fetch.value}×{self.change_signal.value}"


def shop_target(brand: Brand, plan: ScrapePlan) -> Brand:
    """The brand as discovery should address it.

    The catalogue, the schedule and the deck all key on the brand's own domain; only
    the connector needs to know the shop lives on another host.
    """
    if not plan.shop_domain or plan.shop_domain == brand.domain:
        return brand
    return brand.model_copy(update={"domain": plan.shop_domain})
