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


# Fields we track for merge strategy (images handled separately by gallery pipeline)
TRACKED_FIELDS = ['name', 'price', 'currency', 'description', 'variants', 'brand', 'sku', 'category']


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
    field_sources: Dict[str, str] = field(default_factory=dict)  # field_name -> strategy_value (validated)

    def get_strategies_for_field(self, field_name: str) -> List[ExtractionStrategy]:
        """Get strategies that provide a specific field."""
        return [c.strategy for c in self.contributions if field_name in c.fields]

    def get_active_strategies(self) -> List[ExtractionStrategy]:
        """Get all strategies that contribute at least one field."""
        if self.field_sources:
            # Use strategies referenced in field_sources
            strat_values = set(self.field_sources.values())
            return [ExtractionStrategy(v) for v in strat_values]
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
        if self.field_sources:
            result["field_sources"] = self.field_sources
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
            field_sources=data.get("field_sources", {}),
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

        # Stealth preference: detected during discovery, cached for entire brand run.
        # True = use stealth (default), False = stealth triggers WAF, use vanilla
        self.use_stealth: bool = True

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
        """Determine which fields a product extraction contributed (images excluded - gallery pipeline)."""
        fields = set()
        if product.name:
            fields.add('name')
        if product.price is not None:
            fields.add('price')
        if product.currency:
            fields.add('currency')
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

    # Strategy cost order: cheapest first (no LLM < LLM)
    STRATEGY_COST_ORDER = [
        ExtractionStrategy.SHOPIFY_JSON,
        ExtractionStrategy.SHOPIFY_GRAPHQL,
        ExtractionStrategy.LD_JSON,
        ExtractionStrategy.API_INTERCEPT,
        ExtractionStrategy.HTML_META,
        ExtractionStrategy.LLM_SCHEMA,
        ExtractionStrategy.DOM_FALLBACK,
    ]

    def _validate_field(self, field_name: str, product: Product, gt: Product) -> bool:
        """Check if a strategy's field value matches ground truth Product."""
        if field_name == 'price':
            if product.price is None:
                return False
            if not gt.price:  # None or 0 means GT couldn't determine price
                return True
            return abs(product.price - gt.price) < 0.02

        if field_name == 'currency':
            gt_currency = gt.currency or ''
            if not gt_currency:
                return bool(product.currency)
            return bool(product.currency) and product.currency.upper() == gt_currency.upper()

        if field_name == 'name':
            gt_name = gt.name or ''
            if not gt_name:
                return bool(product.name)
            if not product.name:
                return False
            a, b = product.name.lower(), gt_name.lower()
            return a in b or b in a or a == b

        if field_name == 'description':
            gt_desc = gt.description or ''
            desc = product.description or ''
            if not gt_desc:
                return bool(desc)
            return len(desc) >= len(gt_desc) * 0.3

        if field_name == 'variants':
            gt_count = len(gt.variants) if gt.variants else 0
            count = len(product.variants) if product.variants else 0
            if gt_count == 0:
                return count >= 0
            return count > 0 and abs(count - gt_count) <= max(2, gt_count * 0.3)

        # brand, sku, category: accept if present
        return True

    def _compute_field_sources(
        self,
        results: List[ExtractionResult],
        ground_truth: Product
    ) -> Dict[str, str]:
        """
        For each field, find the cheapest strategy that passes ground truth validation.

        Returns: {field_name: strategy_value}
        """
        # Build strategy -> product map
        strat_products = {}
        for r in results:
            if r.success and r.product:
                strat_products[r.strategy] = r.product

        field_sources = {}

        for field_name in TRACKED_FIELDS:
            # Try strategies in cost order (cheapest first)
            for strat in self.STRATEGY_COST_ORDER:
                product = strat_products.get(strat)
                if not product:
                    continue
                # Check field is present
                fields = self._get_contributed_fields(product)
                if field_name not in fields:
                    continue
                # Validate against ground truth
                if self._validate_field(field_name, product, ground_truth):
                    field_sources[field_name] = strat.value
                    break

        return field_sources

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

    def _minimal_from_field_sources(
        self,
        field_sources: Dict[str, str],
        contributions: List[StrategyContribution]
    ) -> List[StrategyContribution]:
        """
        Compute minimal strategies based on field_sources (GT-validated field assignments).

        Instead of greedy score-based selection, include only strategies that are
        actually needed according to field_sources.
        """
        # Build mapping: strategy_name -> fields it's responsible for
        strategy_fields: Dict[str, Set[str]] = {}
        for field, strategy_name in field_sources.items():
            if strategy_name not in strategy_fields:
                strategy_fields[strategy_name] = set()
            strategy_fields[strategy_name].add(field)

        # Build minimal contributions from strategies that have assigned fields
        minimal_set = []
        contrib_by_name = {c.strategy.value: c for c in contributions}

        print(f"\n  [MINIMAL SET] Computing from field_sources:")

        for strategy_name, fields in strategy_fields.items():
            if strategy_name in contrib_by_name:
                orig = contrib_by_name[strategy_name]
                minimal_contrib = StrategyContribution(
                    strategy=orig.strategy,
                    fields=fields,
                    score=orig.score
                )
                minimal_set.append(minimal_contrib)
                print(f"    ✓ {strategy_name}: {', '.join(sorted(fields))}")
            else:
                print(f"    ✗ {strategy_name}: strategy not in contributions (skipped)")

        print(f"  [MINIMAL SET] Result: {len(minimal_set)} strategies")
        return minimal_set

    def _merge_products(self, results: List[ExtractionResult], url: str, field_sources: Optional[Dict[str, str]] = None) -> Product:
        """Merge multiple extraction results into one product.

        If field_sources is provided, pick each field from its designated strategy.
        Otherwise, fall back to score-based first-wins merge.
        """
        successful = [r for r in results if r.success and r.product]

        if not successful:
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

        # Build strategy -> product lookup
        strat_map = {}
        for r in successful:
            strat_map[r.strategy.value] = r.product

        # Sort by score for fallback
        sorted_results = sorted(successful, key=lambda r: r.score, reverse=True)
        base = sorted_results[0].product

        if field_sources:
            # Field-level source picking (validated by ground truth)
            def pick(field_name, attr, default=None):
                strat_val = field_sources.get(field_name)
                if strat_val and strat_val in strat_map:
                    val = getattr(strat_map[strat_val], attr, default)
                    if val is not None and val != '' and val != []:
                        return val
                # Fallback: score-based
                for r in sorted_results:
                    val = getattr(r.product, attr, default)
                    if val is not None and val != '' and val != []:
                        return val
                return default

            # Images: just use best available (gallery pipeline overrides at extraction time)
            imgs = None
            for r in sorted_results:
                if r.product.images:
                    imgs = r.product.images
                    break
            vrnts = pick('variants', 'variants', [])
            merged = Product(
                name=pick('name', 'name', ''),
                price=pick('price', 'price'),
                currency=pick('currency', 'currency', ''),
                images=list(imgs) if imgs else [],
                description=pick('description', 'description', ''),
                url=url,
                variants=list(vrnts) if vrnts else [],
                brand=pick('brand', 'brand', ''),
                sku=pick('sku', 'sku', ''),
                category=pick('category', 'category', ''),
                raw_description=base.raw_description,
                extraction_strategy=base.extraction_strategy,
            )
        else:
            # Legacy: score-based first-wins merge
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

            for result in sorted_results[1:]:
                product = result.product
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
        page_data = await load_page(url, stealth=self.use_stealth)

        # Cache WAF detection at brand level — all subsequent loads skip stealth
        if page_data.waf_detected:
            self.use_stealth = False
            print(f"  [WAF] Stealth triggers WAF for this brand — switching to vanilla for all pages")

        print(f"  Captured {len(page_data.json_responses)} JSON responses")
        print(f"  HTML length: {len(page_data.html)} chars")

        results = []
        contributions = []
        best_score = 0

        for strategy in self.strategies:
            # Skip dom_fallback during discovery — GT extraction handles it
            if strategy.strategy_type == ExtractionStrategy.DOM_FALLBACK:
                print(f"\n  Skipping {strategy.strategy_type.value} (GT extraction will handle)")
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

        # Ground truth: single LLM extraction that validates strategies AND serves as dom_fallback
        ground_truth = None
        field_sources = {}
        dom_fallback = None
        for s in self.strategies:
            if s.strategy_type == ExtractionStrategy.DOM_FALLBACK:
                dom_fallback = s
                break

        print(f"\n  [GROUND TRUTH] Running LLM extraction...")
        if dom_fallback:
            gt_data = dom_fallback.extract_ground_truth(page_data)
            if gt_data:
                ground_truth = dom_fallback._parse_product(gt_data, url, page_data)

                # Add GT result as dom_fallback contribution
                gt_result = ExtractionResult.from_product(ground_truth, ExtractionStrategy.DOM_FALLBACK)
                results.append(gt_result)
                gt_fields = self._get_contributed_fields(ground_truth)
                contributions.append(StrategyContribution(
                    strategy=ExtractionStrategy.DOM_FALLBACK,
                    fields=gt_fields,
                    score=gt_result.score
                ))

        if ground_truth and contributions:
            gt_variants = len(ground_truth.variants) if ground_truth.variants else 0
            gt_desc_len = len(ground_truth.description) if ground_truth.description else 0
            print(f"    GT: name={ground_truth.name}, price={ground_truth.price} {ground_truth.currency}")
            print(f"    GT: variants={gt_variants}, desc_len={gt_desc_len}")
            field_sources = self._compute_field_sources(results, ground_truth)
            print(f"    Field sources: {field_sources}")

            # If dom_fallback is selected for any field, discover and save regex patterns
            # so future extractions can use them without LLM
            if dom_fallback and any(v == ExtractionStrategy.DOM_FALLBACK.value for v in field_sources.values()):
                dom_fields = [k for k, v in field_sources.items() if v == ExtractionStrategy.DOM_FALLBACK.value]
                print(f"\n  [PATTERNS] dom_fallback selected for {dom_fields}, discovering patterns...")
                patterns = dom_fallback._discover_patterns(page_data.html, url, domain=dom_fallback._get_domain(url))
                if patterns:
                    dom_fallback._save_patterns(dom_fallback._get_domain(url), patterns)
                    print(f"    Saved patterns for {dom_fallback._get_domain(url)}")
                else:
                    print(f"    Pattern discovery failed (dom_fallback will use LLM at runtime)")
        else:
            print(f"    Ground truth LLM call failed, falling back to score-based merge")

        return contributions, results, ground_truth, field_sources

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
        page1 = await load_page(url1, stealth=self.use_stealth)
        page2 = await load_page(url2, stealth=self.use_stealth)

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

        page_data = await load_page(url, stealth=self.use_stealth)
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

        contributions, discovery_results, ground_truth, field_sources = await self.discover(product_urls[0])

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

        # Phase 3: Gallery discovery
        print(f"\n{'='*60}")
        print(f"GALLERY DISCOVERY - {domain}")
        print('='*60)

        # Get product name from ground truth or merged result for better LLM accuracy
        product_name = ground_truth.name if ground_truth else None
        if not product_name:
            merged = self._merge_products(discovery_results, product_urls[0], field_sources)
            product_name = merged.name

        gallery_config = await self.discover_gallery_selector(product_urls[0], product_name=product_name)
        if gallery_config:
            print(f"  Gallery selectors: {gallery_config.get('image_selectors', '?')}")
            print(f"  Image count: {gallery_config.get('image_count', '?')}")
        else:
            print(f"  No gallery selector found — will use strategy images")

        # Create config with MINIMAL strategy set
        # If field_sources exist, derive minimal set from them (not greedy score)
        if field_sources:
            minimal_contributions = self._minimal_from_field_sources(field_sources, contributions)
        else:
            minimal_contributions = self._compute_minimal_strategies(contributions)

        config = MultiStrategyConfig(
            domain=domain,
            contributions=minimal_contributions,
            verified=True,
            field_sources=field_sources,
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
        if field_sources:
            print(f"  Field sources (ground-truth validated):")
            for fname, sval in sorted(field_sources.items()):
                print(f"    - {fname} → {sval}")
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

        page_data = await load_page(url, stealth=self.use_stealth)
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

        # Merge results (use field_sources if available)
        fs = config.field_sources if config else None
        merged_product = self._merge_products(results, url, field_sources=fs)

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
        import time as _time

        domain = self._get_domain(url)

        # Try to load config if not provided
        if not config:
            config = self._load_config(domain)

        # Load page using the provided page object
        t0 = _time.monotonic()
        page_data = await load_page_on_existing(page, url, wait_time=wait_time)
        t_load = _time.monotonic()

        # Fix 2: Don't run extraction on failed/error pages (including 404s)
        if not page_data.loaded or page_data.status_code in (404, 403, 410, 429, 500, 502, 503):
            return ExtractionResult(
                success=False,
                error=f"Page load failed (status={page_data.status_code})",
                strategy=ExtractionStrategy.SHOPIFY_JSON,
                status_code=page_data.status_code,
            )

        import asyncio as _asyncio

        if config and config.verified:
            active_strategies = config.get_active_strategies()
            tasks = [s.extract(url, page_data) for s in self.strategies if s.strategy_type in active_strategies]
        else:
            tasks = [s.extract(url, page_data) for s in self.strategies]

        results = await _asyncio.gather(*tasks) if tasks else []
        t_strat = _time.monotonic()

        # Merge results (use field_sources if available)
        fs = config.field_sources if config else None
        merged_product = self._merge_products(list(results), url, field_sources=fs)

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
            t_gallery = _time.monotonic()

            total = t_gallery - t0
            if total > 3.0:
                import sys as _sys
                slug = url.split('/')[-1][:30]
                print(f"[Extractor SLOW] {slug}: load={t_load-t0:.1f}s strat={t_strat-t_load:.1f}s gallery={t_gallery-t_strat:.1f}s TOTAL={total:.1f}s", file=_sys.stderr)

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

        Tests progressively: 300ms → 800ms → 2000ms
        Returns the first wait time that yields a product with name + price.
        Uses networkidle so actual waits are often shorter than the ceiling.

        Called during discovery phase so we only pay this cost once per domain.
        """
        from page_loader import load_page_on_existing
        from browser_pool import BrowserPool

        WAIT_TIMES = [300, 800, 2000]

        pool = BrowserPool(size=1, pages_per_recycle=100, headless=True)
        await pool.start()

        try:
            for wait_ms in WAIT_TIMES:
                async with pool.acquire() as page:
                    page_data = await load_page_on_existing(page, url, wait_time=wait_ms)

                import asyncio as _asyncio
                if config and config.verified:
                    active = config.get_active_strategies()
                    tasks = [s.extract(url, page_data) for s in self.strategies if s.strategy_type in active]
                else:
                    tasks = [s.extract(url, page_data) for s in self.strategies]
                results = await _asyncio.gather(*tasks) if tasks else []

                fs = config.field_sources if config else None
                merged = self._merge_products(list(results), url, field_sources=fs)

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

    async def discover_gallery_selector(self, url: str, page=None, product_name: str = None) -> Optional[dict]:
        """
        Use LLM to find how to extract product images from the gallery.

        Called once during discovery. Uses many-shot prompting with examples
        from multiple brands for better accuracy.

        Returns a config dict with:
        - "image_selectors": list of CSS selectors targeting gallery images
        - "url_attribute": which attribute holds the image URL (src, data-src, etc.)

        Args:
            url: A product page URL
            page: Optional Playwright page (already loaded). If None, loads one.
            product_name: Product name (improves LLM accuracy)

        Returns:
            Gallery config dict or None
        """
        domain = self._get_domain(url)

        # Check saved config first
        saved = self.load_gallery_selector(domain)
        if saved:
            print(f"[GalleryDiscovery] Using saved config for {domain}")
            return saved

        from page_loader import load_page_on_existing
        from browser_pool import BrowserPool
        from llm_image_extractor import extract_product_images_with_llm

        # Load the page if not provided
        own_pool = None
        if page is None:
            own_pool = BrowserPool(size=1, pages_per_recycle=10, headless=True)
            await own_pool.start()

        try:
            if own_pool:
                async with own_pool.acquire() as p:
                    await load_page_on_existing(p, url, wait_time=2000)
                    return await self._discover_gallery_with_manyshot(p, url, product_name)
            else:
                return await self._discover_gallery_with_manyshot(page, url, product_name)
        finally:
            if own_pool:
                await own_pool.shutdown()

    async def _discover_gallery_with_manyshot(self, page, url: str, product_name: str = None) -> Optional[dict]:
        """
        Use many-shot LLM prompting to identify product images and derive a selector.

        This approach uses examples from multiple brands to improve accuracy.
        """
        from llm_image_extractor import extract_product_images_with_llm

        domain = self._get_domain(url)

        # Use product name if provided, otherwise try to extract from page
        if not product_name:
            try:
                product_name = await page.evaluate("document.querySelector('h1')?.textContent?.trim() || ''")
            except Exception:
                product_name = ""

        print(f"[GalleryDiscovery] Using many-shot approach for: {product_name or 'unknown product'}")

        result = await extract_product_images_with_llm(page, product_name, url, max_images=50)

        if not result.get("gallery_selector"):
            print("[GalleryDiscovery] No selector derived, trying common selectors")
            return await self._try_common_gallery_selectors_on_page(page)

        selector = result["gallery_selector"]
        selector_valid = result.get("selector_valid", False)
        selector_count = result.get("selector_count", 0)

        print(f"[GalleryDiscovery] Derived selector: {selector}")
        print(f"[GalleryDiscovery] Selector valid: {selector_valid} ({selector_count} elements)")
        print(f"[GalleryDiscovery] Found {len(result.get('product_image_urls', []))} unique images")

        if not selector_valid:
            print("[GalleryDiscovery] Selector invalid, trying common selectors")
            return await self._try_common_gallery_selectors_on_page(page)

        # Convert to standard config format
        # Handle multiple selectors (comma-separated)
        if ", " in selector:
            selectors = [s.strip() for s in selector.split(", ")]
        else:
            selectors = [selector]

        config = {
            "image_selectors": selectors,
            "url_attribute": "src",
            "image_count": len(result.get("product_image_urls", [])),
        }

        self.save_gallery_selector(domain, config)
        return config

    async def _discover_gallery_with_llm(self, llm, html: str, url: str, page) -> Optional[dict]:
        """
        Two-step gallery discovery:
        1. LLM identifies which images are product images (returns list of indices + reasoning)
        2. We analyze those images to find their common DOM pattern and derive a selector
        """

        # Step 1: Extract image snapshot with link context
        image_snapshot = await page.evaluate("""(currentUrl) => {
            const results = [];
            const imgs = document.querySelectorAll('img');

            for (const el of imgs) {
                const src = el.src || el.dataset.src || '';
                if (!src || src.includes('data:')) continue;

                const alt = el.alt || '';

                // Check if image is wrapped in a link
                let linkInfo = null;
                let node = el.parentElement;
                for (let i = 0; i < 6 && node && node !== document.body; i++) {
                    if (node.tagName === 'A' && node.href) {
                        const href = node.href;
                        if (href === currentUrl || href === currentUrl + '#' || href.endsWith('#')) {
                            linkInfo = { type: 'SAME_PAGE', href: null };
                        } else if (href.includes('/product/') || href.includes('/products/')) {
                            const match = href.match(/\\/products?\\/([^/?#]+)/);
                            linkInfo = {
                                type: 'PRODUCT_LINK',
                                href: match ? match[1].slice(0, 40) : href.slice(0, 50)
                            };
                        } else {
                            linkInfo = { type: 'OTHER_LINK', href: href.slice(0, 50) };
                        }
                        break;
                    }
                    node = node.parentElement;
                }

                // Get container path (for later analysis)
                // Filter out Tailwind utility classes with special characters
                const containerPath = [];
                node = el.parentElement;
                for (let i = 0; i < 5 && node && node !== document.body; i++) {
                    const tag = node.tagName.toLowerCase();
                    const cls = node.className && typeof node.className === 'string'
                        ? node.className.split(' ').filter(c =>
                            c && !c.includes(':') && !c.includes('/') &&
                            !c.includes('[') && !c.includes(']') &&
                            !c.includes('(') && !c.includes(')') &&
                            c.length > 2 && c.length < 30
                          ).slice(0, 2).join('.')
                        : '';
                    const id = node.id || '';
                    containerPath.push({ tag, cls, id });
                    node = node.parentElement;
                }

                results.push({
                    src: src,
                    alt: alt,
                    link: linkInfo,
                    containerPath: containerPath,
                });
            }
            return results;
        }""", url)

        if not image_snapshot:
            print("[GalleryDiscovery] No image elements found on page")
            return None

        # Limit to first 60 images
        if len(image_snapshot) > 60:
            image_snapshot = image_snapshot[:60]

        # Format snapshot for LLM - just the info needed to identify product images
        snapshot_text = ""
        for i, img in enumerate(image_snapshot):
            alt = img['alt'][:50] if img['alt'] else '(no alt)'
            src_end = img['src'].split('/')[-1][:30] if img['src'] else ''

            # Link info
            link = img.get('link')
            if link:
                if link['type'] == 'PRODUCT_LINK':
                    link_str = f"LINK→product:{link['href']}"
                elif link['type'] == 'SAME_PAGE':
                    link_str = "LINK→same_page"
                else:
                    link_str = f"LINK→other"
            else:
                link_str = "NO_LINK"

            # Container summary
            containers = [f"{c['tag']}.{c['cls']}" if c['cls'] else c['tag'] for c in img['containerPath'][:3]]

            snapshot_text += f"[{i}] {link_str} | alt=\"{alt}\" | containers: {' > '.join(containers)}\n"

        print(f"[GalleryDiscovery] Snapshot: {len(image_snapshot)} images")

        # Step 2: Ask LLM to identify product images by index
        prompt = f"""This is a product page. Here are all images on the page:

{snapshot_text}

Which images belong to the PRODUCT GALLERY (photos of the product being sold)?

Exclude:
- Recommendation/related product images (usually link to other products)
- Logos, icons, UI elements

Return JSON with:
- "product_image_indices": list of image numbers that are product gallery images, e.g. [8, 9, 10, 11]
- "reasoning": brief explanation of how you identified them"""

        from pydantic import BaseModel, Field
        from typing import List

        class ImageSelection(BaseModel):
            product_image_indices: List[int] = Field(description="List of image indices that are product images")
            reasoning: str = Field(description="Explanation of pattern used")

        result = llm.call(
            prompt=prompt,
            expected_format="json",
            response_model=ImageSelection,
            max_tokens=300,
            operation="gallery_discovery",
        )

        if not result.get("success") or not result.get("data"):
            print("[GalleryDiscovery] LLM call failed")
            return None

        data = result["data"]
        indices = data.get("product_image_indices", [])
        reasoning = data.get("reasoning", "")

        print(f"[GalleryDiscovery] LLM selected {len(indices)} images: {indices}")
        print(f"[GalleryDiscovery] Reasoning: {reasoning}")

        if not indices:
            print("[GalleryDiscovery] No product images identified")
            return None

        # Step 3: Analyze selected images to find common container pattern
        selected_images = [image_snapshot[i] for i in indices if i < len(image_snapshot)]
        if not selected_images:
            print("[GalleryDiscovery] Invalid indices")
            return None

        # Find common container pattern among selected images
        # Look for the most common class at each level of the container path
        config = self._derive_selector_from_images(selected_images, page, url)
        return config

    def _derive_selector_from_images(self, selected_images: list, page, url: str) -> Optional[dict]:
        """
        Group selected images by their full container path signature.
        Derive a selector for each distinct group.
        """
        from collections import defaultdict

        if not selected_images:
            return None

        # Build full path signature for each image
        # e.g., "swiper-slide > swiper-wrapper > swiper"
        def get_path_signature(img):
            parts = []
            for c in img['containerPath'][:4]:
                if c['cls']:
                    # Use all classes (joined), not just the first one
                    parts.append(c['cls'])
                elif c['id']:
                    parts.append(f"#{c['id']}")
                else:
                    parts.append(c['tag'])
            return " > ".join(parts)

        # Group by path signature
        groups = defaultdict(list)
        for img in selected_images:
            sig = get_path_signature(img)
            groups[sig].append(img)

        print(f"[GalleryDiscovery] Grouped by full path into {len(groups)} types:")
        for sig, imgs in groups.items():
            print(f"  [{len(imgs)} imgs] {sig}")

        # Gallery-related class patterns (prefer these over utility classes)
        GALLERY_PATTERNS = ['swiper', 'carousel', 'gallery', 'slider', 'splide',
                           'product-media', 'product-image', 'media-list', 'lightbox']
        UTILITY_CLASSES = {'div', 'span', 'relative', 'flex', 'hidden', 'w-full',
                          'h-full', 'block', 'inline', 'absolute', 'overflow'}

        # For each group, find the best selector
        selectors = []
        for sig, imgs in groups.items():
            path = imgs[0]['containerPath']
            print(f"  Finding selector for path: {sig}")

            best_selector = None

            # First: look for ID anywhere in path
            for c in path[:4]:
                if c['id']:
                    best_selector = f"#{c['id']} img"
                    break

            # Second: look for gallery-related classes anywhere in path
            if not best_selector:
                for c in path[:4]:
                    if c['cls']:
                        for pattern in GALLERY_PATTERNS:
                            if pattern in c['cls'].lower():
                                # Found a gallery-related class
                                first_cls = c['cls'].split('.')[0]
                                best_selector = f".{first_cls} img"
                                break
                    if best_selector:
                        break

            # Third: use full class combination, preferring non-utility classes
            if not best_selector:
                for c in path[:3]:
                    if c['cls']:
                        classes = c['cls'].split('.')
                        # Filter to non-utility classes
                        meaningful = [cl for cl in classes if cl and cl not in UTILITY_CLASSES]
                        if meaningful:
                            best_selector = f".{'.'.join(meaningful[:2])} img"
                            break
                        elif classes:
                            # Fallback: use full class combo
                            best_selector = f".{'.'.join(classes[:2])} img"
                            break

            if best_selector and best_selector not in selectors:
                selectors.append(best_selector)
                print(f"  → Selector: {best_selector}")

        print(f"[GalleryDiscovery] Derived selectors: {selectors}")

        if not selectors:
            print("[GalleryDiscovery] No distinctive selectors found")
            return None

        config = {
            "image_selectors": selectors,
            "url_attribute": "src",
        }

        domain = self._get_domain(url)
        self.save_gallery_selector(domain, config)
        print(f"[GalleryDiscovery] Saved config for {domain}")

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
