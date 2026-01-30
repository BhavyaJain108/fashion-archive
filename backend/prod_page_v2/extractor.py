"""
Product Extractor - Main extraction pipeline.

Handles discovery, verification, and batch extraction.
Uses multi-strategy merge approach for maximum coverage.
"""

import asyncio
import json
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Set
from urllib.parse import urlparse
from dataclasses import dataclass, field

from models import (
    Product, Variant, ExtractionResult, ExtractionStrategy, BrandConfig, MissingFields, PageData
)
from strategies import (
    ShopifyStrategy, ShopifyGraphQLStrategy, LdJsonStrategy,
    ApiInterceptStrategy, HtmlMetaStrategy, EmbeddedJsonStrategy
)
from strategies.llm_schema import LlmSchemaStrategy
from page_loader import load_page


# Fields we track for merge strategy
TRACKED_FIELDS = ['name', 'price', 'currency', 'images', 'description', 'variants', 'brand', 'sku', 'category']


@dataclass
class StrategyContribution:
    """Tracks what fields a strategy contributed."""
    strategy: ExtractionStrategy
    fields: Set[str] = field(default_factory=set)
    score: int = 0

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "fields": list(self.fields),
            "score": self.score
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'StrategyContribution':
        return cls(
            strategy=ExtractionStrategy(data["strategy"]),
            fields=set(data.get("fields", [])),
            score=data.get("score", 0)
        )


@dataclass
class MultiStrategyConfig:
    """Config that tracks multiple strategies and their contributions."""
    domain: str
    contributions: List[StrategyContribution] = field(default_factory=list)
    verified: bool = False
    discovery_url: Optional[str] = None
    verification_url: Optional[str] = None
    site_images: List[str] = field(default_factory=list)  # Images to exclude (appear on multiple products)

    def get_strategies_for_field(self, field_name: str) -> List[ExtractionStrategy]:
        """Get strategies that provide a specific field."""
        return [c.strategy for c in self.contributions if field_name in c.fields]

    def get_active_strategies(self) -> List[ExtractionStrategy]:
        """Get all strategies that contribute at least one field."""
        return [c.strategy for c in self.contributions if c.fields]

    def to_dict(self) -> dict:
        result = {
            "domain": self.domain,
            "contributions": [c.to_dict() for c in self.contributions],
            "verified": self.verified,
            "discovery_url": self.discovery_url,
            "verification_url": self.verification_url,
        }
        if self.site_images:
            result["site_images"] = self.site_images
        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'MultiStrategyConfig':
        return cls(
            domain=data["domain"],
            contributions=[StrategyContribution.from_dict(c) for c in data.get("contributions", [])],
            verified=data.get("verified", False),
            discovery_url=data.get("discovery_url"),
            verification_url=data.get("verification_url"),
            site_images=data.get("site_images", []),
        )


class ProductExtractor:
    """
    Main product extraction pipeline with multi-strategy merge.

    Usage:
        extractor = ProductExtractor()

        # Discovery + verification on first 2 products
        config = await extractor.discover_and_verify(
            domain="khaite.com",
            product_urls=["url1", "url2"]
        )

        # Extract remaining products
        products = await extractor.extract_batch(config, remaining_urls)
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path(__file__).parent / "extractions"

        # Initialize strategies (order = priority for field conflicts)
        self.strategies = [
            ShopifyStrategy(),        # .json endpoint (most reliable)
            ShopifyGraphQLStrategy(), # Storefront GraphQL API
            LdJsonStrategy(),         # LD+JSON in HTML
            ApiInterceptStrategy(),   # Captured API responses
            LlmSchemaStrategy(),      # LLM-discovered API schema (universal)
            EmbeddedJsonStrategy(),   # LLM parses embedded scripts (fallback)
            HtmlMetaStrategy(),       # HTML meta tags (last resort)
        ]

    def _get_contributed_fields(self, product: Product) -> Set[str]:
        """Determine which fields a product extraction contributed."""
        fields = set()
        if product.name:
            fields.add('name')
        if product.price is not None:
            fields.add('price')
        if product.currency:
            fields.add('currency')
        if product.images:
            fields.add('images')
        if product.description:
            fields.add('description')
        if product.variants:
            fields.add('variants')
        if product.brand:
            fields.add('brand')
        if product.sku:
            fields.add('sku')
        if product.category:
            fields.add('category')
        return fields

    def _compute_minimal_strategies(self, contributions: List[StrategyContribution]) -> List[StrategyContribution]:
        """
        Compute the minimal set of strategies needed to cover all available fields.

        Algorithm (greedy set cover):
        1. Sort by score (highest first)
        2. For each strategy, check what NEW fields it provides (not already covered)
        3. Only keep strategies that provide at least one new field
        4. Skip strategies that only provide fields already covered by higher-scoring ones

        Returns:
            Minimal list of StrategyContribution, each with only the fields it's responsible for
        """
        if not contributions:
            return []

        # Sort by score descending
        sorted_contribs = sorted(contributions, key=lambda c: c.score, reverse=True)

        minimal_set = []
        covered_fields = set()

        print(f"\n  [MINIMAL SET] Computing optimal strategy set:")

        for contrib in sorted_contribs:
            # What new fields does this strategy provide?
            new_fields = contrib.fields - covered_fields

            if new_fields:
                # This strategy provides value - include it
                minimal_contrib = StrategyContribution(
                    strategy=contrib.strategy,
                    fields=new_fields,  # Only the NEW fields it uniquely provides
                    score=contrib.score
                )
                minimal_set.append(minimal_contrib)
                covered_fields.update(new_fields)

                print(f"    ✓ {contrib.strategy.value} (score {contrib.score}): +{', '.join(sorted(new_fields))}")
            else:
                print(f"    ✗ {contrib.strategy.value} (score {contrib.score}): SKIPPED (all fields already covered)")

        print(f"  [MINIMAL SET] Result: {len(minimal_set)} strategies (was {len(contributions)})")

        return minimal_set

    def _merge_products(self, results: List[ExtractionResult], url: str) -> Product:
        """Merge multiple extraction results into one product."""
        # Sort by score (highest first) - higher score = more trustworthy
        sorted_results = sorted(
            [r for r in results if r.success and r.product],
            key=lambda r: r.score,
            reverse=True
        )

        if not sorted_results:
            # Return empty product with all fields missing
            return Product(
                name="",
                price=0.0,
                currency="USD",
                images=[],
                description="",
                url=url,
                missing_fields=MissingFields(
                    name=True, price=True, currency=True,
                    images=True, description=True, variants=True
                )
            )

        # Start with the best result as base
        base = sorted_results[0].product
        merged = Product(
            name=base.name,
            price=base.price,
            currency=base.currency,
            images=base.images.copy() if base.images else [],
            description=base.description,
            url=url,
            variants=base.variants.copy() if base.variants else [],
            brand=base.brand,
            sku=base.sku,
            category=base.category,
            raw_description=base.raw_description,
            extraction_strategy=base.extraction_strategy,
        )

        # Fill in gaps from other results
        for result in sorted_results[1:]:
            product = result.product

            # Fill missing fields
            if not merged.name and product.name:
                merged.name = product.name
            if merged.price is None and product.price is not None:
                merged.price = product.price
            if not merged.currency and product.currency:
                merged.currency = product.currency
            if not merged.images and product.images:
                merged.images = product.images.copy()
            if not merged.description and product.description:
                merged.description = product.description
            if not merged.variants and product.variants:
                merged.variants = product.variants.copy()
            if not merged.brand and product.brand:
                merged.brand = product.brand
            if not merged.sku and product.sku:
                merged.sku = product.sku
            if not merged.category and product.category:
                merged.category = product.category

        # Update missing fields
        merged.missing_fields = MissingFields(
            name=not bool(merged.name),
            price=merged.price is None,
            currency=not bool(merged.currency),
            images=not bool(merged.images),
            description=not bool(merged.description),
            variants=not bool(merged.variants),
        )

        return merged

    async def discover(self, url: str) -> Tuple[List[StrategyContribution], List[ExtractionResult]]:
        """
        Discovery phase: Try all strategies and track contributions.

        Returns:
            (contributions, all_results)
        """
        print(f"\n[DISCOVER] Loading page: {url}")
        page_data = await load_page(url)

        print(f"  Captured {len(page_data.json_responses)} JSON responses")
        print(f"  HTML length: {len(page_data.html)} chars")

        results = []
        contributions = []
        best_score = 0

        for strategy in self.strategies:
            # Skip expensive dom_fallback if we already have a great result
            if strategy.strategy_type == ExtractionStrategy.DOM_FALLBACK and best_score >= 95:
                print(f"\n  Skipping {strategy.strategy_type.value}... (already have score {best_score})")
                continue

            print(f"\n  Trying {strategy.strategy_type.value}...")
            result = await strategy.extract(url, page_data)
            results.append(result)

            if result.success and result.product:
                fields = self._get_contributed_fields(result.product)
                contribution = StrategyContribution(
                    strategy=strategy.strategy_type,
                    fields=fields,
                    score=result.score
                )
                contributions.append(contribution)
                best_score = max(best_score, result.score)

                print(f"    ✓ Success! Score: {result.score}")
                print(f"    → Fields: {', '.join(sorted(fields))}")
                if result.product.missing_fields.any_missing():
                    print(f"    ⚠ Missing: {result.product.missing_fields.to_list()}")
            else:
                print(f"    ✗ Failed: {result.error}")

        # Sort contributions by score
        contributions.sort(key=lambda c: c.score, reverse=True)

        if contributions:
            # Show merged result preview
            merged = self._merge_products(results, url)
            merged_fields = self._get_contributed_fields(merged)
            print(f"\n  ✓ Merged result: {len(merged_fields)} fields")
            print(f"    Fields: {', '.join(sorted(merged_fields))}")
            if merged.missing_fields.any_missing():
                print(f"    Still missing: {merged.missing_fields.to_list()}")
        else:
            print("\n  ❌ All strategies failed")

        return contributions, results

    async def discover_site_images(self, url1: str, url2: str) -> List[str]:
        """
        Discover site-wide images by comparing two product pages.

        Images that appear on both pages are likely site-wide (logos, banners, etc.)
        not product-specific images.

        Args:
            url1: First product URL
            url2: Second product URL (different product, same site)

        Returns:
            List of image URLs that appear on both pages (site-wide images)
        """
        from strategies.base import BaseStrategy

        print(f"\n[SITE IMAGES] Comparing two products to find site-wide images")
        print(f"  Product 1: {url1}")
        print(f"  Product 2: {url2}")

        # Load both pages
        page1 = await load_page(url1)
        page2 = await load_page(url2)

        print(f"  Page 1 images: {len(page1.image_urls)}")
        print(f"  Page 2 images: {len(page2.image_urls)}")

        # Get image identities for both pages
        # Use a strategy instance to access _get_image_identity
        strategy = self.strategies[0]  # Any strategy will do

        ids1 = {strategy._get_image_identity(url): url for url in page1.image_urls}
        ids2 = {strategy._get_image_identity(url): url for url in page2.image_urls}

        # Find common images (appear on both)
        common_ids = set(ids1.keys()) & set(ids2.keys())
        site_images = [ids1[id] for id in common_ids]

        print(f"  Common images (site-wide): {len(site_images)}")
        for img in site_images[:5]:
            print(f"    - {img[:80]}...")
        if len(site_images) > 5:
            print(f"    ... and {len(site_images) - 5} more")

        return site_images

    async def verify(
        self,
        contributions: List[StrategyContribution],
        url: str
    ) -> Tuple[bool, List[ExtractionResult]]:
        """
        Verification phase: Confirm strategies work on second product.

        Returns:
            (verified, results)
        """
        active_strategies = [c.strategy for c in contributions if c.fields]

        if not active_strategies:
            print("  No strategies to verify")
            return False, []

        print(f"\n[VERIFY] Testing {len(active_strategies)} strategies on: {url}")

        page_data = await load_page(url)
        results = []
        verified_contributions = []

        for contribution in contributions:
            if not contribution.fields:
                continue

            # Find and run the strategy
            for s in self.strategies:
                if s.strategy_type == contribution.strategy:
                    result = await s.extract(url, page_data)
                    results.append(result)

                    if result.success and result.product:
                        fields = self._get_contributed_fields(result.product)
                        # Check if it still provides the same fields
                        common_fields = fields & contribution.fields
                        if common_fields:
                            print(f"  ✓ {contribution.strategy.value}: {', '.join(sorted(common_fields))}")
                            verified_contributions.append(StrategyContribution(
                                strategy=contribution.strategy,
                                fields=common_fields,
                                score=result.score
                            ))
                        else:
                            print(f"  ⚠ {contribution.strategy.value}: different fields (was: {contribution.fields}, now: {fields})")
                    else:
                        print(f"  ✗ {contribution.strategy.value}: failed")
                    break

        if verified_contributions:
            merged = self._merge_products(results, url)
            merged_fields = self._get_contributed_fields(merged)
            print(f"\n  ✓ Verified {len(verified_contributions)} strategies")
            print(f"    Merged fields: {', '.join(sorted(merged_fields))}")
            return True, results

        return False, results

    async def discover_and_verify(
        self,
        domain: str,
        product_urls: List[str]
    ) -> Optional[MultiStrategyConfig]:
        """
        Run discovery and verification phases.

        Args:
            domain: Brand domain (e.g., "khaite.com")
            product_urls: List of product URLs (need at least 2)

        Returns:
            MultiStrategyConfig if successful, None if failed
        """
        if len(product_urls) < 2:
            print("Need at least 2 product URLs for discovery + verification")
            return None

        # Phase 1: Discovery
        print(f"\n{'='*60}")
        print(f"DISCOVERY PHASE - {domain}")
        print('='*60)

        contributions, discovery_results = await self.discover(product_urls[0])

        if not contributions:
            print(f"\n❌ Discovery failed for {domain}")
            return None

        # Phase 2: Verification
        print(f"\n{'='*60}")
        print(f"VERIFICATION PHASE - {domain}")
        print('='*60)

        verified, verify_results = await self.verify(contributions, product_urls[1])

        if not verified:
            print(f"\n❌ Verification failed for {domain}")
            return None

        # Create config with MINIMAL strategy set (skip redundant strategies)
        minimal_contributions = self._compute_minimal_strategies(contributions)

        config = MultiStrategyConfig(
            domain=domain,
            contributions=minimal_contributions,
            verified=True,
            discovery_url=product_urls[0],
            verification_url=product_urls[1],
        )

        # Save config
        self._save_config(config)

        print(f"\n{'='*60}")
        print(f"SUCCESS - {domain}")
        print(f"  Active strategies:")
        for c in minimal_contributions:
            print(f"    - {c.strategy.value}: {', '.join(sorted(c.fields))}")
        print(f"  Config saved to: {self._get_config_path(domain)}")
        print('='*60)

        return config

    async def extract_single(
        self,
        url: str,
        config: Optional[MultiStrategyConfig] = None
    ) -> ExtractionResult:
        """
        Extract a single product using merge strategy.

        If config is provided, uses only active strategies.
        Otherwise, tries to find existing config for domain.
        """
        domain = self._get_domain(url)

        # Try to load config if not provided
        if not config:
            config = self._load_config(domain)

        page_data = await load_page(url)
        results = []

        if config and config.verified:
            # Run only strategies that contributed fields
            active_strategies = config.get_active_strategies()

            for strategy in self.strategies:
                if strategy.strategy_type in active_strategies:
                    result = await strategy.extract(url, page_data)
                    results.append(result)
        else:
            # No config - run all strategies
            for strategy in self.strategies:
                result = await strategy.extract(url, page_data)
                results.append(result)

        # Merge results
        merged_product = self._merge_products(results, url)

        if merged_product.name:  # At least got a name
            return ExtractionResult(
                success=True,
                product=merged_product,
                strategy=ExtractionStrategy.SHOPIFY_JSON,  # placeholder
                score=merged_product.completeness_score()
            )

        return ExtractionResult.failure(
            ExtractionStrategy.SHOPIFY_JSON,
            "No strategy succeeded"
        )

    async def extract_single_pooled(
        self,
        url: str,
        page: 'Page',
        config: Optional[MultiStrategyConfig] = None,
        wait_time: int = 500,
        gallery_selector=None,
    ) -> ExtractionResult:
        """
        Extract a single product using a pre-acquired page from BrowserPool.

        Args:
            url: Product URL to extract
            page: Playwright Page from BrowserPool
            config: Optional MultiStrategyConfig for this domain
            wait_time: ms to wait for dynamic content (default 500, calibrated during discovery)
            gallery_selector: CSS selector for product gallery (discovered once per domain)

        Returns:
            ExtractionResult with extracted product data
        """
        from page_loader import load_page_on_existing, extract_gallery_images

        domain = self._get_domain(url)

        # Try to load config if not provided
        if not config:
            config = self._load_config(domain)

        # Load page using the provided page object
        page_data = await load_page_on_existing(page, url, wait_time=wait_time)

        # Fix 2: Don't run extraction on failed/error pages
        if not page_data.loaded:
            return ExtractionResult(
                success=False,
                error=f"Page load failed (status={page_data.status_code})",
                strategy=ExtractionStrategy.SHOPIFY_JSON,
                status_code=page_data.status_code,
            )

        results = []

        if config and config.verified:
            active_strategies = config.get_active_strategies()
            for strategy in self.strategies:
                if strategy.strategy_type in active_strategies:
                    result = await strategy.extract(url, page_data)
                    results.append(result)
        else:
            for strategy in self.strategies:
                result = await strategy.extract(url, page_data)
                results.append(result)

        # Merge results
        merged_product = self._merge_products(results, url)

        # Fix 3: Stronger success criteria
        # Require a real name + at least one substantive field (price, images, or description)
        GARBAGE_NAMES = {
            "access denied", "too many requests", "page not found", "404",
            "error", "not found", "forbidden", "blocked", "please try again",
            "just a moment", "attention required", "checking your browser",
            "service unavailable", "temporarily unavailable",
        }

        has_real_name = (
            merged_product.name
            and len(merged_product.name.strip()) > 1
            and merged_product.name.strip().lower() not in GARBAGE_NAMES
        )
        has_substance = (
            merged_product.price
            or (merged_product.images and len(merged_product.images) > 0)
            or (merged_product.description and len(merged_product.description) > 10)
        )

        if has_real_name and has_substance:
            # Override images with gallery-extracted images if selector available
            if gallery_selector:
                gallery_images = await extract_gallery_images(page, gallery_selector)
                if gallery_images:
                    merged_product.images = gallery_images

            return ExtractionResult(
                success=True,
                product=merged_product,
                strategy=ExtractionStrategy.SHOPIFY_JSON,  # placeholder
                score=merged_product.completeness_score(),
                status_code=page_data.status_code,
            )

        reason = "No product name" if not has_real_name else "Name only, no price/images/description"
        return ExtractionResult(
            success=False,
            error=reason,
            strategy=ExtractionStrategy.SHOPIFY_JSON,
            status_code=page_data.status_code,
        )

    async def calibrate_wait_time(
        self,
        url: str,
        config: Optional[MultiStrategyConfig] = None,
    ) -> int:
        """
        Find the minimum wait time that produces a good extraction.

        Tests progressively: 500ms → 1000ms → 2000ms → 3000ms → 5000ms
        Returns the first wait time that yields a product with name + price.

        Called during discovery phase so we only pay this cost once per domain.
        """
        from page_loader import load_page_on_existing
        from browser_pool import BrowserPool

        WAIT_TIMES = [500, 1000, 2000, 3000, 5000]

        pool = BrowserPool(size=1, pages_per_recycle=100, headless=True)
        await pool.start()

        try:
            for wait_ms in WAIT_TIMES:
                async with pool.acquire() as page:
                    page_data = await load_page_on_existing(page, url, wait_time=wait_ms)

                results = []
                if config and config.verified:
                    active = config.get_active_strategies()
                    for strategy in self.strategies:
                        if strategy.strategy_type in active:
                            result = await strategy.extract(url, page_data)
                            results.append(result)
                else:
                    for strategy in self.strategies:
                        result = await strategy.extract(url, page_data)
                        results.append(result)

                merged = self._merge_products(results, url)

                has_name = bool(merged.name and len(merged.name) > 1)
                has_price = bool(merged.price and merged.price != "0")

                if has_name and has_price:
                    print(f"[Calibration] {wait_ms}ms → ✓ name + price found")
                    return wait_ms
                else:
                    print(f"[Calibration] {wait_ms}ms → ✗ missing {'name' if not has_name else 'price'}")

            print(f"[Calibration] Falling back to 5000ms")
            return 5000
        finally:
            await pool.shutdown()

    def _gallery_schema_path(self, domain: str) -> Path:
        """Path to the gallery selector file for a domain."""
        schema_dir = Path(__file__).parent / "schemas"
        schema_dir.mkdir(exist_ok=True)
        return schema_dir / f"{domain.replace('.', '_')}_gallery.json"

    def load_gallery_selector(self, domain: str) -> Optional[dict]:
        """Load saved gallery config for a domain."""
        path = self._gallery_schema_path(domain)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                # Migrate old format: {"gallery_selector": "..."} -> new dict format
                if "gallery_selector" in data and "image_selector" not in data:
                    old = data["gallery_selector"]
                    data = {"image_selector": "", "url_attribute": "src", "container_selector": old}
                    path.write_text(json.dumps(data, indent=2))
                return data
            except Exception:
                pass
        return None

    def save_gallery_selector(self, domain: str, config: dict):
        """Save gallery config for a domain."""
        path = self._gallery_schema_path(domain)
        path.write_text(json.dumps(config, indent=2))
        print(f"[GalleryDiscovery] Saved config for {domain}: {config}")

    async def discover_gallery_selector(self, url: str, page=None) -> Optional[dict]:
        """
        Use LLM to find how to extract product images from the gallery.

        Called once during discovery. Returns a config dict with:
        - "image_selector": CSS selector targeting image elements directly
        - "url_attribute": which attribute holds the image URL (src, data-src, etc.)
        - "container_selector": the gallery container (for context)

        Args:
            url: A product page URL
            page: Optional Playwright page (already loaded). If None, loads one.

        Returns:
            Gallery config dict or None
        """
        domain = self._get_domain(url)

        # Check saved config first
        saved = self.load_gallery_selector(domain)
        if saved:
            print(f"[GalleryDiscovery] Using saved config for {domain}")
            return saved
        from page_loader import load_page_on_existing, extract_gallery_images
        from browser_pool import BrowserPool

        try:
            from scraper.llm_handler import LLMHandler
        except ImportError:
            try:
                from backend.scraper.llm_handler import LLMHandler
            except ImportError:
                print("[GalleryDiscovery] LLM not available, trying common selectors")
                return await self._try_common_gallery_selectors(url)

        llm = LLMHandler()

        # Load the page if not provided
        own_pool = None
        if page is None:
            own_pool = BrowserPool(size=1, pages_per_recycle=10, headless=True)
            await own_pool.start()

        try:
            if own_pool:
                async with own_pool.acquire() as p:
                    page_data = await load_page_on_existing(p, url, wait_time=2000)
                    html = page_data.html
                    test_page = p
                    return await self._discover_gallery_with_llm(llm, html, url, test_page)
            else:
                html = await page.content()
                return await self._discover_gallery_with_llm(llm, html, url, page)
        finally:
            if own_pool:
                await own_pool.shutdown()

    async def _discover_gallery_with_llm(self, llm, html: str, url: str, page) -> Optional[dict]:
        """Extract image DOM context from the live page, send to LLM, verify result."""

        # Use Playwright to grab every image element + its ancestor chain
        # This gives the LLM a focused view: just images and their structural context
        image_snapshot = await page.evaluate("""() => {
            const results = [];
            const imgs = document.querySelectorAll('img, source, [style*="background-image"]');
            for (const el of imgs) {
                // Get the image's own attributes
                const attrs = {};
                for (const attr of el.attributes) {
                    attrs[attr.name] = attr.value.length > 200 ? attr.value.slice(0, 200) + '...' : attr.value;
                }

                // Walk up the ancestor chain (up to 4 levels) to capture structural context
                const ancestors = [];
                let node = el.parentElement;
                for (let i = 0; i < 4 && node && node !== document.body; i++) {
                    const a = {};
                    for (const attr of node.attributes) {
                        // Only keep structural attrs, skip long values
                        if (['class', 'id', 'role', 'data-component', 'data-testid',
                             'data-section', 'data-product-media', 'data-product-media-container',
                             'data-media-type', 'aria-label', 'data-gallery', 'data-carousel',
                             'data-slider', 'data-swiper'].includes(attr.name) ||
                            attr.name.startsWith('data-')) {
                            a[attr.name] = attr.value.length > 100 ? attr.value.slice(0, 100) + '...' : attr.value;
                        }
                    }
                    ancestors.push({ tag: node.tagName.toLowerCase(), attrs: a });
                    node = node.parentElement;
                }

                results.push({
                    tag: el.tagName.toLowerCase(),
                    attrs: attrs,
                    ancestors: ancestors,
                });
            }
            return results;
        }""")

        if not image_snapshot:
            print("[GalleryDiscovery] No image elements found on page")
            return None

        # If too many images, keep only the first 50 — product galleries are near
        # the top of the page, the rest are recommendations/footer/etc.
        if len(image_snapshot) > 50:
            image_snapshot = image_snapshot[:50]

        # Format the snapshot for the LLM
        snapshot_text = f"Found {len(image_snapshot)} image elements on {url}:\n\n"
        for i, img in enumerate(image_snapshot):
            snapshot_text += f"[{i}] <{img['tag']}"
            for k, v in img['attrs'].items():
                snapshot_text += f' {k}="{v}"'
            snapshot_text += ">\n"
            for j, anc in enumerate(img['ancestors']):
                indent = "  " * (j + 1)
                attr_str = " ".join(f'{k}="{v}"' for k, v in anc['attrs'].items())
                snapshot_text += f"{indent}parent: <{anc['tag']} {attr_str}>\n"
            snapshot_text += "\n"

        print(f"[GalleryDiscovery] Snapshot: {len(image_snapshot)} images, {len(snapshot_text)} chars")

        prompt = f"""Here are all the image elements on a product page, with their parent elements for context.

{snapshot_text}

Which of these images are the MAIN PRODUCT GALLERY photos?

Tell me:
1. A CSS selector that targets ONLY these product gallery image elements (not logos, not recommended products, not thumbnails)
2. Which attribute holds the best image URL (src, data-src, srcset, etc.)

Return a JSON object with:
- "image_selector": CSS selector targeting the product gallery image elements
- "url_attribute": which attribute has the image URL ("src", "data-src", "srcset", etc.)
- "container_selector": the gallery container selector (for context)
- "notes": brief explanation"""

        from pydantic import BaseModel, Field

        class GalleryConfig(BaseModel):
            image_selector: str = Field(description="CSS selector targeting image elements directly")
            url_attribute: str = Field(default="src", description="Attribute holding the image URL")
            container_selector: str = Field(default="", description="Gallery container selector")
            notes: str = Field(default="", description="Brief explanation of gallery structure")

        result = llm.call(
            prompt=prompt,
            expected_format="json",
            response_model=GalleryConfig,
            max_tokens=400,
        )

        if not result.get("success") or not result.get("data"):
            print("[GalleryDiscovery] LLM call failed")
            return None

        data = result["data"]
        image_selector = data.get("image_selector", "")
        url_attribute = data.get("url_attribute", "src")
        notes = data.get("notes", "")
        print(f"[GalleryDiscovery] LLM returned:")
        print(f"  image_selector: '{image_selector}'")
        print(f"  url_attribute: '{url_attribute}'")
        print(f"  notes: {notes}")

        # Validate selector looks like CSS
        if not image_selector or image_selector.startswith("<") or len(image_selector) > 200:
            print(f"[GalleryDiscovery] Invalid selector: '{image_selector}'")
            return None

        # Verify on the live page
        try:
            elements = await page.query_selector_all(image_selector)
        except Exception as e:
            print(f"[GalleryDiscovery] Selector error: {e}")
            return None

        if not elements:
            print(f"[GalleryDiscovery] Selector '{image_selector}' matched 0 elements")
            return None

        # Try to get a URL from the first element
        sample_url = None
        for attr in [url_attribute, "src", "data-src", "srcset"]:
            sample_url = await elements[0].get_attribute(attr)
            if sample_url:
                break

        if not sample_url:
            print(f"[GalleryDiscovery] Selector matched {len(elements)} elements but no URLs found")
            return None

        config = {
            "image_selector": image_selector,
            "url_attribute": url_attribute,
            "container_selector": data.get("container_selector", ""),
        }
        print(f"[GalleryDiscovery] Verified: {len(elements)} elements, sample: {sample_url[:80]}")
        domain = self._get_domain(url)
        self.save_gallery_selector(domain, config)
        return config

    async def _try_common_gallery_selectors_on_page(self, page) -> Optional[dict]:
        """Try common gallery selectors as fallback."""
        from page_loader import extract_gallery_images

        COMMON_SELECTORS = [
            "[data-product-media-container]",
            "[data-product-media]",
            ".product-gallery",
            ".product-images",
            ".product__media",
            ".product-media",
            ".gallery",
            ".product-photos",
            ".swiper-wrapper",
            ".slider",
            ".carousel",
        ]

        for selector in COMMON_SELECTORS:
            config = {"image_selector": "", "url_attribute": "src", "container_selector": selector}
            images = await extract_gallery_images(page, config)
            if len(images) >= 1:
                print(f"[GalleryDiscovery] Fallback found: '{selector}' ({len(images)} images)")
                try:
                    domain = urlparse(page.url).netloc.replace("www.", "")
                    self.save_gallery_selector(domain, config)
                except Exception:
                    pass
                return config

        print("[GalleryDiscovery] No gallery selector found")
        return None

    async def _try_common_gallery_selectors(self, url: str) -> Optional[dict]:
        """Try common selectors by loading a page (no LLM available)."""
        from browser_pool import BrowserPool
        from page_loader import load_page_on_existing

        pool = BrowserPool(size=1, pages_per_recycle=10, headless=True)
        await pool.start()
        try:
            async with pool.acquire() as page:
                await load_page_on_existing(page, url, wait_time=2000)
                return await self._try_common_gallery_selectors_on_page(page)
        finally:
            await pool.shutdown()

    async def extract_batch(
        self,
        config: MultiStrategyConfig,
        urls: List[str],
        concurrency: int = 3
    ) -> List[ExtractionResult]:
        """
        Extract multiple products using verified config.
        """
        active = config.get_active_strategies()
        print(f"\n[BATCH] Extracting {len(urls)} products using {len(active)} strategies")
        print(f"  Strategies: {', '.join(s.value for s in active)}")

        results = []
        semaphore = asyncio.Semaphore(concurrency)

        async def extract_with_semaphore(url: str, idx: int) -> ExtractionResult:
            async with semaphore:
                print(f"  [{idx+1}/{len(urls)}] {url[:60]}...")
                result = await self.extract_single(url, config)
                if result.success:
                    print(f"    ✓ Score: {result.score}")
                else:
                    print(f"    ✗ {result.error}")
                return result

        tasks = [
            extract_with_semaphore(url, i)
            for i, url in enumerate(urls)
        ]

        results = await asyncio.gather(*tasks)

        # Summary
        successful = sum(1 for r in results if r.success)
        print(f"\n  Completed: {successful}/{len(urls)} successful")

        return results

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        return domain

    def _get_config_path(self, domain: str) -> Path:
        """Get path for brand config file."""
        clean_domain = domain.replace('.', '_')
        return self.output_dir / clean_domain / "config.json"

    def _save_config(self, config: MultiStrategyConfig):
        """Save brand config to file."""
        path = self._get_config_path(config.domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(config.to_dict(), f, indent=2)

    def _load_config(self, domain: str) -> Optional[MultiStrategyConfig]:
        """Load brand config from file. Handles both old and new formats."""
        path = self._get_config_path(domain)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)

            # Check if it's the new multi-strategy format
            if 'contributions' in data:
                return MultiStrategyConfig.from_dict(data)

            # Convert old single-strategy format to new format
            if 'strategy' in data:
                strategy_str = data['strategy']
                strategy = ExtractionStrategy(strategy_str)
                # Old format didn't track fields - assume all fields
                contribution = StrategyContribution(
                    strategy=strategy,
                    fields=set(TRACKED_FIELDS),
                    score=100
                )
                return MultiStrategyConfig(
                    domain=data.get('domain', domain),
                    contributions=[contribution],
                    verified=data.get('verified', False),
                    discovery_url=data.get('discovery_url'),
                    verification_url=data.get('verification_url'),
                )

            return None
        except Exception:
            return None

    def save_product(self, product: Product, output_dir: Optional[Path] = None):
        """Save extracted product to JSON file."""
        if output_dir is None:
            domain = self._get_domain(product.url)
            output_dir = self.output_dir / domain.replace('.', '_')

        output_dir.mkdir(parents=True, exist_ok=True)

        # Create filename from product name or URL
        filename = product.sku or product.name[:50].replace(' ', '_').replace('/', '_')
        filename = ''.join(c for c in filename if c.isalnum() or c in '_-')
        filepath = output_dir / f"{filename}.json"

        # Convert to dict
        product_dict = {
            "name": product.name,
            "price": product.price,
            "currency": product.currency,
            "images": product.images,
            "description": product.description,
            "url": product.url,
            "brand": product.brand,
            "sku": product.sku,
            "category": product.category,
            "variants": [
                {
                    "size": v.size,
                    "color": v.color,
                    "sku": v.sku,
                    "price": v.price,
                    "available": v.available,
                    "stock_count": v.stock_count,
                }
                for v in product.variants
            ],
            "extraction_strategy": product.extraction_strategy.value if product.extraction_strategy else None,
            "missing_fields": product.missing_fields.to_list(),
            "raw_description": product.raw_description,
        }

        with open(filepath, 'w') as f:
            json.dump(product_dict, f, indent=2)

        return filepath
