"""
Stage 3: Product Extraction

Extracts full product details from URLs using prod_page_v2.
Saves products organized by category folder structure.
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))  # stages/
sys.path.insert(0, str(Path(__file__).parent.parent / "prod_page_v2"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))

from stages.storage import load_urls, save_config, save_product, get_category_path_for_url, ensure_domain_dir
from llm_handler import LLMHandler
from stages.metrics import update_stage_metrics, calculate_cost, set_current_stage, get_stage_metrics_from_tracker


def flatten_urls(urls_tree: dict) -> List[str]:
    """Extract all unique product URLs from tree."""
    seen: Set[str] = set()
    urls: List[str] = []

    def extract_from_node(node):
        for url in node.get("products", []):
            if url not in seen:
                seen.add(url)
                urls.append(url)

        for child in node.get("children", []):
            extract_from_node(child)

    tree = urls_tree.get("category_tree", [])
    for node in tree:
        extract_from_node(node)

    return urls


async def extract_products(domain: str, concurrency: int = 10) -> dict:
    """
    Extract full product details from all URLs.

    Loads urls.json, runs discovery on first 2 URLs,
    batch extracts remaining, saves products by category.

    Args:
        domain: Domain name
        concurrency: Parallel product extractions

    Returns:
        Extraction result dict
    """
    from extractor import ProductExtractor

    # Normalize domain
    if '_' in domain:
        clean_domain = domain
        domain = domain.replace('_', '.')
    else:
        clean_domain = domain.replace('.', '_')

    print(f"\n{'='*60}")
    print(f"STAGE 3: PRODUCT EXTRACTION")
    print(f"{'='*60}")
    print(f"Domain: {domain}")
    print(f"{'='*60}\n")

    # Track timing and LLM usage
    stage_start_time = time.time()
    set_current_stage("products")
    LLMHandler.reset_usage()
    discovery_start_time = None
    discovery_end_time = None
    batch_start_time = None
    batch_end_time = None

    # Load URLs tree
    urls_tree = load_urls(clean_domain)
    if not urls_tree:
        print(f"Error: urls.json not found for {clean_domain}")
        print(f"Run stage 2 first: python pipeline.py urls <domain>")
        return None

    # Flatten all unique URLs
    all_urls = flatten_urls(urls_tree)
    print(f"Found {len(all_urls)} unique product URLs\n")

    if len(all_urls) < 2:
        print("Need at least 2 product URLs for discovery")
        return {"success": False, "error": "Insufficient URLs"}

    print(f"Discovery URLs:")
    print(f"  1. {all_urls[0][:70]}...")
    print(f"  2. {all_urls[1][:70]}...")

    # Initialize extractor (without default output dir)
    extractor = ProductExtractor()

    # Discovery + verification with first 2 URLs
    print(f"\nRunning discovery and verification...")
    discovery_start_time = time.time()
    config = await extractor.discover_and_verify(domain, all_urls[:2])
    discovery_end_time = time.time()

    if not config:
        print("Discovery/verification failed")
        return {"success": False, "error": "Discovery failed"}

    # Save config
    config_dict = config.to_dict()
    save_config(clean_domain, config_dict)

    # Batch extract remaining URLs
    products_extracted = 0
    products_successful = 0
    products_saved = []

    if len(all_urls) > 2:
        print(f"\nExtracting {len(all_urls) - 2} remaining products (concurrency={concurrency})...")
        batch_start_time = time.time()
        batch_urls = all_urls[2:]
        results = await extractor.extract_batch(config, batch_urls, concurrency=concurrency)
        batch_end_time = time.time()

        # Zip results with original URLs (asyncio.gather preserves order)
        for source_url, result in zip(batch_urls, results):
            products_extracted += 1
            if result.success and result.product:
                products_successful += 1

                # Get category path using original URL (for correct category mapping)
                category_path = get_category_path_for_url(source_url, urls_tree)

                # Convert product to dict
                product_dict = {
                    "name": result.product.name,
                    "price": result.product.price,
                    "currency": result.product.currency,
                    "images": result.product.images,
                    "description": result.product.description,
                    "url": result.product.url,
                    "source_url": source_url,  # Original URL from urls.json
                    "brand": result.product.brand,
                    "sku": result.product.sku,
                    "category": result.product.category,
                    "variants": [
                        {
                            "size": v.size,
                            "color": v.color,
                            "sku": v.sku,
                            "price": v.price,
                            "available": v.available,
                        }
                        for v in result.product.variants
                    ],
                }

                # Save product using source_url for filename (preserves variants)
                filepath = save_product(clean_domain, product_dict, category_path, source_url=source_url)
                products_saved.append(str(filepath))

    # Also save the discovery products
    for i, source_url in enumerate(all_urls[:2]):
        result = await extractor.extract_single(source_url, config)
        if result.success and result.product:
            products_successful += 1
            category_path = get_category_path_for_url(source_url, urls_tree)

            product_dict = {
                "name": result.product.name,
                "price": result.product.price,
                "currency": result.product.currency,
                "images": result.product.images,
                "description": result.product.description,
                "url": result.product.url,
                "source_url": source_url,  # Original URL from urls.json
                "brand": result.product.brand,
                "sku": result.product.sku,
                "category": result.product.category,
                "variants": [
                    {
                        "size": v.size,
                        "color": v.color,
                        "sku": v.sku,
                        "price": v.price,
                        "available": v.available,
                    }
                    for v in result.product.variants
                ],
            }

            filepath = save_product(clean_domain, product_dict, category_path, source_url=source_url)
            products_saved.append(str(filepath))

    # Update config with counts
    config_dict["products_extracted"] = len(all_urls)
    config_dict["products_successful"] = products_successful
    save_config(clean_domain, config_dict)

    # Calculate timing and LLM usage
    stage_duration = time.time() - stage_start_time
    discovery_duration = (discovery_end_time - discovery_start_time) if discovery_start_time else 0
    batch_duration = (batch_end_time - batch_start_time) if batch_start_time else 0

    # Get operation-level metrics from the unified tracker
    tracker_data = get_stage_metrics_from_tracker("products")
    operations = tracker_data.get("operations", [])
    summary = tracker_data.get("summary", {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})

    # Fall back to legacy method if tracker has no data
    if not operations:
        llm_usage = LLMHandler.get_total_usage()
        llm_input = llm_usage.get("input_tokens", 0)
        llm_output = llm_usage.get("output_tokens", 0)
        llm_calls = llm_usage.get("call_count", 0)
        llm_cost = calculate_cost(llm_input, llm_output)
        operations = [
            {
                "name": "product_extraction",
                "calls": llm_calls,
                "input_tokens": llm_input,
                "output_tokens": llm_output,
                "cost": llm_cost
            }
        ]
        summary = {
            "calls": llm_calls,
            "input_tokens": llm_input,
            "output_tokens": llm_output,
            "cost": llm_cost
        }

    # Build and save metrics
    stage_data = {
        "run_time": datetime.now().isoformat(),
        "duration": stage_duration,
        "extra_fields": {
            "Products Attempted": len(all_urls),
            "Products Successful": products_successful
        },
        "operations": operations,
        "latency_breakdown": {
            "Discovery": discovery_duration,
            "Batch Extraction": batch_duration
        },
        "summary": summary,
        "products": products_successful
    }

    metrics_path = update_stage_metrics(clean_domain, "stage_3", stage_data)

    print(f"\n{'='*60}")
    print(f"PRODUCT EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Products extracted: {len(all_urls)}")
    print(f"Products successful: {products_successful}")
    print(f"Products saved: {len(products_saved)}")
    print(f"Duration: {stage_duration:.1f}s (discovery: {discovery_duration:.1f}s, batch: {batch_duration:.1f}s)")
    print(f"LLM Cost: ${summary.get('cost', 0):.4f} ({summary.get('calls', 0)} calls, {summary.get('input_tokens', 0) + summary.get('output_tokens', 0):,} tokens)")
    print(f"Metrics: {metrics_path}")
    print(f"{'='*60}\n")

    return {
        "success": True,
        "products_extracted": len(all_urls),
        "products_successful": products_successful,
        "products_saved": products_saved
    }


def run_extract_products(domain: str, concurrency: int = 10) -> dict:
    """Sync wrapper for extract_products."""
    return asyncio.run(extract_products(domain, concurrency))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python products.py <domain>")
        print("Example: python products.py eckhauslatta_com")
        sys.exit(1)

    domain = sys.argv[1]
    result = run_extract_products(domain)

    if result and result.get("success"):
        print(f"Success: {result['products_successful']} products extracted")
    else:
        print("Failed to extract products")
        sys.exit(1)
