#!/usr/bin/env python3
"""
CLI for product extraction.

Usage:
    # Discover and verify for a brand
    python cli.py discover khaite.com url1 url2

    # Extract a single product
    python cli.py extract <url>

    # Extract from test_products.json
    python cli.py test <brand_name>
"""

import asyncio
import json
import sys
from pathlib import Path

from extractor import ProductExtractor


def print_product(product):
    """Pretty print a product."""
    print(f"\n{'─'*50}")
    print(f"Name: {product.name}")
    print(f"Price: {product.currency} {product.price}")
    print(f"Brand: {product.brand}")
    print(f"SKU: {product.sku}")
    print(f"Images: {len(product.images)}")
    print(f"Variants: {len(product.variants)}")

    if product.variants:
        print("\nVariants:")
        for v in product.variants[:5]:  # Show first 5
            status = "✓" if v.available else "✗" if v.available is False else "?"
            print(f"  {status} {v.size or 'N/A'} / {v.color or 'N/A'} - {v.sku}")
        if len(product.variants) > 5:
            print(f"  ... and {len(product.variants) - 5} more")

    print(f"\nDescription: {product.description[:200]}..." if len(product.description) > 200 else f"\nDescription: {product.description}")

    if product.missing_fields.any_missing():
        print(f"\n⚠ Missing: {product.missing_fields.to_list()}")

    print(f"{'─'*50}")


async def cmd_discover(args):
    """Run discovery and verification."""
    if len(args) < 3:
        print("Usage: python cli.py discover <domain> <url1> <url2>")
        return

    domain = args[0]
    urls = args[1:]

    extractor = ProductExtractor()
    config = await extractor.discover_and_verify(domain, urls)

    if config:
        print(f"\n✓ Config saved. Use 'extract' command for remaining products.")


async def cmd_extract(args):
    """Extract a single product."""
    if len(args) < 1:
        print("Usage: python cli.py extract <url>")
        return

    url = args[0]

    extractor = ProductExtractor()
    result = await extractor.extract_single(url)

    if result.success:
        print_product(result.product)

        # Save product
        filepath = extractor.save_product(result.product)
        print(f"\nSaved to: {filepath}")
    else:
        print(f"\n❌ Extraction failed: {result.error}")


async def cmd_test(args):
    """Test extraction on brands from test_products.json."""
    if len(args) < 1:
        print("Usage: python cli.py test <brand_name>")
        print("       python cli.py test --all")
        return

    # Load test products
    test_file = Path(__file__).parent / "test_products.json"
    with open(test_file) as f:
        test_data = json.load(f)

    brand_name = args[0]

    if brand_name == "--all":
        brands = test_data["brands"]
    else:
        brands = [b for b in test_data["brands"] if b["name"].lower() == brand_name.lower()]
        if not brands:
            print(f"Brand '{brand_name}' not found in test_products.json")
            print("Available brands:")
            for b in test_data["brands"]:
                print(f"  - {b['name']}")
            return

    extractor = ProductExtractor()

    for brand in brands:
        print(f"\n{'='*60}")
        print(f"TESTING: {brand['name']} ({brand['domain']})")
        print('='*60)

        urls = [p["url"] for p in brand["products"]]

        if len(urls) >= 2:
            # Discovery + verification
            config = await extractor.discover_and_verify(brand["domain"], urls[:2])

            if config and len(urls) > 2:
                # Extract remaining
                results = await extractor.extract_batch(config, urls[2:])

                for result in results:
                    if result.success:
                        extractor.save_product(result.product)
        else:
            # Single product
            result = await extractor.extract_single(urls[0])
            if result.success:
                print_product(result.product)


async def cmd_help():
    """Print help."""
    print(__doc__)


async def main():
    if len(sys.argv) < 2:
        await cmd_help()
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "discover": cmd_discover,
        "extract": cmd_extract,
        "test": cmd_test,
        "help": lambda _: cmd_help(),
    }

    if command in commands:
        await commands[command](args)
    else:
        print(f"Unknown command: {command}")
        await cmd_help()


if __name__ == "__main__":
    asyncio.run(main())
