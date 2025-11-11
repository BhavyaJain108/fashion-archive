#!/usr/bin/env python3
"""
Test 5: Full Pipeline Test
===========================

Tests the complete brand scraping pipeline from homepage to all products.
"""

import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brand import Brand
from test_data import TEST_DATA
from test_utils import TestLogger, test_timer, print_brand_info, assert_with_logging


def test_full_pipeline(brand_key: str = "gullylabs"):
    """Test complete brand scraping pipeline"""
    
    # Setup
    logger = TestLogger(f"Full Pipeline - {brand_key}")
    brand_info = TEST_DATA.get_brand(brand_key)
    
    if not brand_info:
        logger.error(f"Brand '{brand_key}' not found in test data")
        return False
    
    logger.header(f"Testing full pipeline for {brand_info.name}")
    print_brand_info(brand_info, logger)
    
    try:
        # STEP 1: Initialize Brand and Extract Homepage Links
        logger.step("Initialize Brand and Extract Homepage Links")
        with test_timer(logger, "Brand initialization and link extraction"):
            brand = Brand(brand_info.homepage_url)
            homepage_links = brand.extract_page_links(brand.url)
            
            logger.data("Homepage Links Found", len(homepage_links))
            if homepage_links:
                logger.info("Sample homepage links:")
                for i, link in enumerate(homepage_links[:5]):
                    logger.info(f"  {i+1}. {link}")
                if len(homepage_links) > 5:
                    logger.info(f"  ... and {len(homepage_links) - 5} more links")
        
        # STEP 2: Analyze Navigation to Find Category Pages
        logger.step("Analyze Navigation to Find Category Pages")
        with test_timer(logger, "Navigation analysis"):
            from prompts import PromptManager
            prompt_data = PromptManager.get_navigation_analysis_prompt(brand.url, homepage_links)
            
            logger.info("Analyzing homepage links for categories...")
            navigation_result = brand.llm_handler.call(
                prompt_data['prompt'], 
                expected_format="json", 
                response_model=prompt_data['model']
            )
            
            logger.data("Navigation Analysis Success", navigation_result.get("success", False))
            
            category_urls = []
            if navigation_result.get("success"):
                nav_data = navigation_result.get("data", {})
                included_urls = nav_data.get("included_urls", [])
                
                # Extract URLs from navigation data
                for url_info in included_urls:
                    if isinstance(url_info, dict):
                        category_urls.append(url_info.get("url"))
                    else:
                        category_urls.append(url_info)
                
                # Remove None values
                category_urls = [url for url in category_urls if url]
                
                logger.data("Category URLs Found", len(category_urls))
                if category_urls:
                    logger.info("Category pages identified:")
                    for i, url in enumerate(category_urls):
                        logger.info(f"  {i+1}. {url}")
            else:
                logger.error(f"Navigation analysis failed: {navigation_result.get('error', 'Unknown error')}")
        
        # STEP 3: Extract Products from All Categories
        logger.step("Extract Products from All Categories")
        
        all_products = []
        categories_processed = 0
        category_results = {}
        
        with test_timer(logger, "Full product extraction"):
            if category_urls:
                logger.info(f"Processing {len(category_urls)} categories")
                
                for i, category_url in enumerate(category_urls):
                    logger.info(f"Processing category {i+1}/{len(category_urls)}: {category_url}")
                    
                    try:
                        # STEP 3a: Analyze Product Pattern for This Category
                        brand.starting_pages_queue = [category_url]
                        brand.product_pages = [category_url]
                        
                        pattern_result = brand.analyze_product_pattern()
                        
                        if not pattern_result:
                            logger.warning(f"  No pattern found for category {i+1}")
                            category_results[category_url] = {"products": 0, "error": "No pattern found"}
                            continue
                        
                        extraction_pattern = pattern_result.get("extraction_pattern", {})
                        logger.info(f"  Pattern found: {extraction_pattern.get('container_selector', 'N/A')}")
                        
                        # STEP 3b: Check for Pagination
                        pagination_result = brand.analyze_pagination_pattern(category_url)
                        has_pagination = pagination_result.get("has_pagination", False) if pagination_result else False
                        
                        logger.info(f"  Has pagination: {has_pagination}")
                        
                        # STEP 3c: Extract Products (with pagination if needed)
                        category_products = []
                        
                        if has_pagination and pagination_result:
                            # Multi-page extraction
                            page_urls = pagination_result.get("page_urls", [category_url])
                            if category_url not in page_urls:
                                page_urls.insert(0, category_url)
                            
                            logger.info(f"  Processing {len(page_urls)} pages")
                            
                            for page_url in page_urls:
                                from page_extractor import extract_products_from_page
                                page_result = extract_products_from_page(
                                    page_url,
                                    [extraction_pattern],
                                    brand_info.name
                                )
                                
                                page_products = page_result.get("products", [])
                                
                                # Stop if empty page
                                if not page_products:
                                    break
                                
                                category_products.extend(page_products)
                        
                        else:
                            # Single page extraction
                            from page_extractor import extract_products_from_page
                            single_result = extract_products_from_page(
                                category_url,
                                [extraction_pattern],
                                brand_info.name
                            )
                            
                            category_products = single_result.get("products", [])
                        
                        logger.info(f"  Products extracted: {len(category_products)}")
                        
                        # Store results
                        all_products.extend(category_products)
                        categories_processed += 1
                        category_results[category_url] = {
                            "products": len(category_products),
                            "has_pagination": has_pagination,
                            "pattern": extraction_pattern.get('container_selector', 'N/A')
                        }
                        
                    except Exception as e:
                        logger.warning(f"  Error processing category {i+1}: {e}")
                        category_results[category_url] = {"products": 0, "error": str(e)}
                        continue
            
            else:
                logger.error("No category URLs found - cannot extract products")
        
        logger.data("Pipeline Results", {
            "categories_found": len(category_urls),
            "categories_processed": categories_processed,
            "total_products": len(all_products)
        })
        
        # STEP 4: Analyze Full Pipeline Results
        logger.step("Analyze Full Pipeline Results")
        
        if all_products:
            # Show product distribution by category
            logger.info("Products by category:")
            for url, result in category_results.items():
                product_count = result.get("products", 0)
                error = result.get("error")
                if error:
                    logger.info(f"  {url}: ERROR - {error}")
                else:
                    logger.info(f"  {url}: {product_count} products")
            
            # Show sample products
            logger.info("Sample products from pipeline:")
            for i, product in enumerate(all_products[:10]):
                name = product.get("product_name", "N/A")
                url = product.get("product_url", "N/A")
                image = "✓" if product.get("image_url") else "✗"
                logger.info(f"  {i+1}. {name} | Image: {image}")
            
            if len(all_products) > 10:
                logger.info(f"  ... and {len(all_products) - 10} more products")
            
            # Quality analysis
            products_with_images = sum(1 for p in all_products if p.get("image_url"))
            products_with_names = sum(1 for p in all_products if p.get("product_name") and p.get("product_name") != "Unknown")
            unique_products = len(set(p.get("product_url", "") for p in all_products if p.get("product_url")))
            
            logger.data("Quality Analysis", {
                "total_products": len(all_products),
                "unique_products": unique_products,
                "products_with_images": f"{products_with_images}/{len(all_products)} ({products_with_images/len(all_products)*100:.1f}%)",
                "products_with_names": f"{products_with_names}/{len(all_products)} ({products_with_names/len(all_products)*100:.1f}%)"
            })
        
        # STEP 5: Validate Full Pipeline Results
        logger.step("Validate Full Pipeline Results")
        
        success = True
        
        # Basic pipeline validation
        success &= assert_with_logging(
            navigation_result.get("success", False),
            "Navigation analysis succeeded",
            logger
        )
        
        success &= assert_with_logging(
            len(category_urls) > 0,
            f"Category URLs found: {len(category_urls)}",
            logger
        )
        
        success &= assert_with_logging(
            categories_processed > 0,
            f"Categories processed: {categories_processed}",
            logger
        )
        
        success &= assert_with_logging(
            len(all_products) > 0,
            f"Products extracted: {len(all_products)}",
            logger
        )
        
        # Quality validation
        if all_products:
            # At least 70% should have images
            image_coverage = (products_with_images / len(all_products)) * 100
            success &= assert_with_logging(
                image_coverage >= 70,
                f"Good image coverage: {image_coverage:.1f}%",
                logger
            )
            
            # At least 80% should be unique (no major duplicates)
            uniqueness = (unique_products / len(all_products)) * 100
            success &= assert_with_logging(
                uniqueness >= 80,
                f"Good product uniqueness: {uniqueness:.1f}%",
                logger
            )
        
        # Brand-specific validation
        if brand_info.expected_categories:
            coverage = (len(category_urls) / brand_info.expected_categories) * 100
            success &= assert_with_logging(
                coverage >= 50,  # At least 50% of expected categories
                f"Reasonable category coverage: {coverage:.1f}% ({len(category_urls)}/{brand_info.expected_categories})",
                logger
            )
        
        # STEP 6: Final Results
        details = {
            "brand": brand_info.name,
            "homepage": brand_info.homepage_url,
            "navigation_success": navigation_result.get("success", False),
            "categories_found": len(category_urls),
            "categories_processed": categories_processed,
            "expected_categories": brand_info.expected_categories,
            "total_products": len(all_products),
            "unique_products": unique_products,
            "image_coverage": f"{image_coverage:.1f}%" if all_products else "0%",
            "pipeline_success": len(all_products) > 0
        }
        
        return logger.result(success, "Full pipeline test completed", details)
        
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        return logger.result(False, f"Exception occurred: {e}")


def test_multiple_brands():
    """Test full pipeline for multiple brands"""
    print(f"\n{'🏭' * 20} TESTING FULL PIPELINE {'🏭' * 20}")
    
    results = {}
    test_brands = ["gullylabs", "jukuhara", "iconaclub"]  # Start with smaller brands
    
    for brand_key in test_brands:
        if brand_key in TEST_DATA.brands:
            print(f"\n{'—' * 80}")
            results[brand_key] = test_full_pipeline(brand_key)
        else:
            logger = TestLogger(f"Pipeline Check - {brand_key}")
            logger.error(f"Brand '{brand_key}' not found in test data")
    
    # Summary
    print(f"\n{'📊' * 20} SUMMARY {'📊' * 20}")
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    print(f"Tests Passed: {passed}/{total}")
    for brand_key, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {brand_key}: {status}")
    
    return passed == total


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Test specific brand
        brand_key = sys.argv[1]
        test_full_pipeline(brand_key)
    else:
        # Test multiple brands
        test_multiple_brands()