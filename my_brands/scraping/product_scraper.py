#!/usr/bin/env python3
"""
Product Scraper for Fashion Brands
==================================

Comprehensive scraper that uses AI-determined strategies to extract products
from fashion brand websites using smart detection methods.
"""

import asyncio
import aiohttp
from typing import List, Dict, Any, Optional
import time
from dataclasses import dataclass, asdict
import json
from pathlib import Path

from .scraping_strategies import (
    get_scraping_strategy,
    ProductCandidate,
    ScrapingResult,
    HomepageAllProductsStrategy,
    CategoryBasedStrategy,
    ProductGridStrategy,
    PaginatedStrategy,
    ImageClickStrategy,
    SinglePageScrollStrategy
)
from .scraping_detector import analyze_brand_website_scraping
from ..brands_db import brands_db


@dataclass
class ScrapingJob:
    """Represents a scraping job for a brand"""
    brand_id: int
    brand_name: str
    brand_url: str
    strategy: str
    config: Dict[str, Any]
    status: str = 'pending'  # pending, running, completed, failed
    progress: int = 0
    products_found: int = 0
    error_message: str = ''
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ProductScraper:
    """Main product scraper orchestrator"""
    
    def __init__(self):
        self.active_jobs: Dict[int, ScrapingJob] = {}
        self.results_cache: Dict[int, ScrapingResult] = {}
    
    async def scrape_brand_products(self, brand_id: int, force_refresh: bool = False) -> ScrapingResult:
        """
        Scrape products for a specific brand using AI-determined strategy
        
        Args:
            brand_id: Database ID of the brand
            force_refresh: Force re-analysis of scraping strategy
            
        Returns:
            ScrapingResult with products found
        """
        # Get brand from database
        brand = brands_db.get_brand_by_id(brand_id)
        if not brand:
            return ScrapingResult(
                success=False,
                products=[],
                strategy_used="error",
                total_found=0,
                confidence=0.0,
                next_pages=[],
                errors=[f"Brand ID {brand_id} not found"]
            )
        
        # Check if we should refresh strategy
        scraping_strategy = brand.get('scraping_strategy')
        scraping_config = {}
        
        if brand.get('scraping_config'):
            try:
                scraping_config = json.loads(brand['scraping_config'])
            except:
                scraping_config = {}
        
        # If no strategy or force refresh, analyze the website
        if not scraping_strategy or force_refresh:
            print(f"🔍 Analyzing scraping strategy for {brand['name']}...")
            capability = analyze_brand_website_scraping(brand['url'])
            
            if not capability.is_scrapable:
                return ScrapingResult(
                    success=False,
                    products=[],
                    strategy_used="not-scrapable",
                    total_found=0,
                    confidence=0.0,
                    next_pages=[],
                    errors=capability.challenges
                )
            
            scraping_strategy = capability.primary_strategy
            scraping_config = {
                'strategy': capability.primary_strategy,
                'difficulty': capability.difficulty,
                'estimated_products': capability.estimated_products,
                'technical_details': capability.technical_details
            }
            
            # Update database with new strategy
            brands_db.update_brand_scraping_config(
                brand_id, scraping_strategy, scraping_config
            )
        
        # Create scraping job
        job = ScrapingJob(
            brand_id=brand_id,
            brand_name=brand['name'],
            brand_url=brand['url'],
            strategy=scraping_strategy,
            config=scraping_config,
            status='running',
            started_at=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
        self.active_jobs[brand_id] = job
        
        try:
            print(f"🚀 Starting scraping for {brand['name']} using {scraping_strategy} strategy")
            
            # Get appropriate strategy instance
            strategy_instance = get_scraping_strategy(scraping_strategy)
            
            # Perform scraping
            result = await self._execute_scraping_strategy(
                strategy_instance, brand['url'], scraping_config, job
            )
            
            # Store products in database
            if result.success and result.products:
                stored_count = await self._store_products(brand_id, result.products)
                print(f"✅ Stored {stored_count} products for {brand['name']}")
            
            # Update job status
            job.status = 'completed' if result.success else 'failed'
            job.products_found = len(result.products) if result.success else 0
            job.progress = 100
            job.completed_at = time.strftime("%Y-%m-%d %H:%M:%S")
            
            if not result.success:
                job.error_message = '; '.join(result.errors)
            
            # Cache result
            self.results_cache[brand_id] = result
            
            return result
            
        except Exception as e:
            print(f"❌ Scraping failed for {brand['name']}: {e}")
            job.status = 'failed'
            job.error_message = str(e)
            job.completed_at = time.strftime("%Y-%m-%d %H:%M:%S")
            
            return ScrapingResult(
                success=False,
                products=[],
                strategy_used=scraping_strategy,
                total_found=0,
                confidence=0.0,
                next_pages=[],
                errors=[str(e)]
            )
    
    async def _execute_scraping_strategy(self, strategy, url: str, config: Dict[str, Any], job: ScrapingJob) -> ScrapingResult:
        """Execute the scraping strategy with progress updates"""
        
        job.progress = 20
        
        if isinstance(strategy, HomepageAllProductsStrategy):
            result = await self._scrape_homepage_strategy(strategy, url, config, job)
        elif isinstance(strategy, CategoryBasedStrategy):
            result = await self._scrape_category_strategy(strategy, url, config, job)
        elif isinstance(strategy, ProductGridStrategy):
            result = await self._scrape_grid_strategy(strategy, url, config, job)
        elif isinstance(strategy, PaginatedStrategy):
            result = await self._scrape_paginated_strategy(strategy, url, config, job)
        else:
            # Default to homepage strategy
            result = await self._scrape_homepage_strategy(strategy, url, config, job)
        
        job.progress = 90
        return result
    
    async def _scrape_homepage_strategy(self, strategy, url: str, config: Dict[str, Any], job: ScrapingJob) -> ScrapingResult:
        """Execute homepage-all-products strategy"""
        job.progress = 30
        
        # Use the existing synchronous method but wrap it
        def sync_scrape():
            return strategy.scrape(url, config)
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, sync_scrape)
        
        job.progress = 80
        return result
    
    async def _scrape_category_strategy(self, strategy, url: str, config: Dict[str, Any], job: ScrapingJob) -> ScrapingResult:
        """Execute category-based scraping strategy"""
        # For now, fall back to homepage strategy
        # TODO: Implement full category navigation
        return await self._scrape_homepage_strategy(strategy, url, config, job)
    
    async def _scrape_grid_strategy(self, strategy, url: str, config: Dict[str, Any], job: ScrapingJob) -> ScrapingResult:
        """Execute product grid strategy"""
        # For now, fall back to homepage strategy
        # TODO: Implement grid-specific logic
        return await self._scrape_homepage_strategy(strategy, url, config, job)
    
    async def _scrape_paginated_strategy(self, strategy, url: str, config: Dict[str, Any], job: ScrapingJob) -> ScrapingResult:
        """Execute paginated scraping strategy"""
        # For now, fall back to homepage strategy
        # TODO: Implement pagination handling
        return await self._scrape_homepage_strategy(strategy, url, config, job)
    
    async def _store_products(self, brand_id: int, products: List[ProductCandidate]) -> int:
        """Store scraped products in database"""
        stored_count = 0
        
        for product in products:
            try:
                # Check if product already exists (by URL or title)
                existing_products = brands_db.get_brand_products(brand_id)
                if any(p['url'] == product.product_url or p['name'] == product.title for p in existing_products):
                    continue  # Skip duplicates
                
                product_id = brands_db.add_product(
                    brand_id=brand_id,
                    name=product.title,
                    url=product.product_url,
                    price=product.price,
                    currency='',  # Could be parsed from price
                    category='',
                    description=f'Scraped using {product.detection_method}',
                    images=[product.image_url] if product.image_url else [],
                    metadata={
                        'confidence': product.confidence,
                        'detection_method': product.detection_method,
                        'scraped_at': time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                )
                
                if product_id:
                    stored_count += 1
                    
            except Exception as e:
                print(f"Error storing product '{product.title}': {e}")
                continue
        
        # Update last scraped timestamp
        if stored_count > 0:
            brands_db._update_last_scraped(brand_id)
        
        return stored_count
    
    def get_job_status(self, brand_id: int) -> Optional[Dict[str, Any]]:
        """Get current status of a scraping job"""
        if brand_id in self.active_jobs:
            job = self.active_jobs[brand_id]
            return asdict(job)
        return None
    
    def get_cached_result(self, brand_id: int) -> Optional[ScrapingResult]:
        """Get cached scraping result"""
        return self.results_cache.get(brand_id)
    
    async def scrape_multiple_brands(self, brand_ids: List[int], max_concurrent: int = 3) -> Dict[int, ScrapingResult]:
        """Scrape multiple brands concurrently with rate limiting"""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(brand_id: int) -> tuple[int, ScrapingResult]:
            async with semaphore:
                result = await self.scrape_brand_products(brand_id)
                # Add delay to be respectful to servers
                await asyncio.sleep(2)
                return brand_id, result
        
        tasks = [scrape_with_semaphore(brand_id) for brand_id in brand_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        result_dict = {}
        for result in results:
            if isinstance(result, Exception):
                print(f"Error in concurrent scraping: {result}")
                continue
            
            brand_id, scraping_result = result
            result_dict[brand_id] = scraping_result
        
        return result_dict
    
    def export_results_to_json(self, brand_id: int, filepath: str) -> bool:
        """Export scraping results to JSON file"""
        try:
            result = self.get_cached_result(brand_id)
            if not result:
                return False
            
            # Convert to serializable format
            export_data = {
                'brand_id': brand_id,
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                'success': result.success,
                'strategy_used': result.strategy_used,
                'total_found': result.total_found,
                'confidence': result.confidence,
                'products': [
                    {
                        'title': p.title,
                        'price': p.price,
                        'image_url': p.image_url,
                        'product_url': p.product_url,
                        'confidence': p.confidence,
                        'detection_method': p.detection_method
                    }
                    for p in result.products
                ],
                'errors': result.errors
            }
            
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            return True
            
        except Exception as e:
            print(f"Error exporting results: {e}")
            return False


# Global scraper instance
product_scraper = ProductScraper()


# Convenience functions
async def scrape_brand(brand_id: int, force_refresh: bool = False) -> ScrapingResult:
    """Convenience function to scrape a single brand"""
    return await product_scraper.scrape_brand_products(brand_id, force_refresh)


async def scrape_all_brands(max_concurrent: int = 2) -> Dict[int, ScrapingResult]:
    """Convenience function to scrape all brands"""
    brands = brands_db.get_all_brands()
    brand_ids = [brand['id'] for brand in brands if brand.get('validation_status') == 'approved']
    
    if not brand_ids:
        print("No approved brands to scrape")
        return {}
    
    print(f"🚀 Starting batch scraping of {len(brand_ids)} brands...")
    results = await product_scraper.scrape_multiple_brands(brand_ids, max_concurrent)
    
    # Print summary
    successful = sum(1 for r in results.values() if r.success)
    total_products = sum(len(r.products) for r in results.values() if r.success)
    
    print(f"✅ Batch scraping completed:")
    print(f"   - {successful}/{len(brand_ids)} brands scraped successfully")
    print(f"   - {total_products} total products found")
    
    return results


if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def test_scraper():
        # Get first approved brand for testing
        brands = brands_db.get_all_brands()
        approved_brands = [b for b in brands if b.get('validation_status') == 'approved']
        
        if not approved_brands:
            print("No approved brands to test with")
            return
        
        brand = approved_brands[0]
        print(f"Testing scraper with: {brand['name']} ({brand['url']})")
        
        result = await scrape_brand(brand['id'])
        
        if result.success:
            print(f"✅ Successfully found {len(result.products)} products")
            for i, product in enumerate(result.products[:3], 1):  # Show first 3
                print(f"   {i}. {product.title} - {product.price}")
        else:
            print(f"❌ Scraping failed: {result.errors}")
    
    # Run test
    asyncio.run(test_scraper())