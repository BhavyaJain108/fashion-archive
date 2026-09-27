"""Connector registry: plans name channels, this resolves them (spec §4.1)."""

import os

from backend.archive.connectors.runfair import RunfairConnector
from backend.archive.connectors.shopify import (
    DEFAULT_MARKET,
    ShopifyConnector,
    ShopifyPageConnector,
)
from backend.archive.connectors.sitemap import SitemapConnector
from backend.archive.connectors.structured import StructuredConnector
from backend.archive.connectors.woocommerce import WooConnector
from backend.archive.domain.brand import DiscoveryChannel, FetchChannel, ScrapePlan


def market() -> str | None:
    """The country the catalogue is priced for. ARCHIVE_MARKET=US by default; set it
    empty to take every shop's home prices instead."""
    value = os.environ.get("ARCHIVE_MARKET", DEFAULT_MARKET).strip().upper()
    return value or None


def get_connector(plan: ScrapePlan, sitemap_url: str | None = None, limit: int | None = None):
    sitemap_url = sitemap_url or plan.sitemap_url
    if plan.discovery == DiscoveryChannel.BULK_JSON:
        return ShopifyConnector(plan.currency, market=market())
    if plan.discovery == DiscoveryChannel.WOO_API:
        return WooConnector()
    if plan.discovery == DiscoveryChannel.PAGE_DATA:
        return RunfairConnector(market=market())
    if plan.discovery == DiscoveryChannel.RECIPE:
        from backend.archive.learn.recipes import LaneRecipe, RecipeConnector

        if not plan.recipe:
            raise ValueError("a recipe plan carries no recipe")
        return RecipeConnector(LaneRecipe(**plan.recipe), limit=limit, currency=plan.currency)
    if plan.discovery == DiscoveryChannel.SITEMAP:
        if not sitemap_url:
            raise ValueError("sitemap discovery requires a sitemap_url")
        if plan.fetch == FetchChannel.STRUCTURED_DATA:
            return StructuredConnector(sitemap_url, plan.product_url_prefix, limit)
        if plan.fetch == FetchChannel.PLATFORM_JSON:
            return ShopifyPageConnector(
                sitemap_url, plan.product_url_prefix, limit, currency=plan.currency
            )
        return SitemapConnector(sitemap_url, plan.product_url_prefix, limit)
    raise ValueError(f"no connector for {plan.discovery} in milestone 2")
