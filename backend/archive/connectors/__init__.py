"""Connector registry: plans name channels, this resolves them (spec §4.1)."""

from backend.archive.connectors.shopify import ShopifyConnector
from backend.archive.connectors.sitemap import SitemapConnector
from backend.archive.connectors.structured import StructuredConnector
from backend.archive.connectors.woocommerce import WooConnector
from backend.archive.domain.brand import DiscoveryChannel, FetchChannel, ScrapePlan


def get_connector(plan: ScrapePlan, sitemap_url: str | None = None, limit: int | None = None):
    sitemap_url = sitemap_url or plan.sitemap_url
    if plan.discovery == DiscoveryChannel.BULK_JSON:
        return ShopifyConnector(plan.currency)
    if plan.discovery == DiscoveryChannel.WOO_API:
        return WooConnector()
    if plan.discovery == DiscoveryChannel.SITEMAP:
        if not sitemap_url:
            raise ValueError("sitemap discovery requires a sitemap_url")
        if plan.fetch == FetchChannel.STRUCTURED_DATA:
            return StructuredConnector(sitemap_url, plan.product_url_prefix, limit)
        return SitemapConnector(sitemap_url, plan.product_url_prefix, limit)
    raise ValueError(f"no connector for {plan.discovery} in milestone 2")
