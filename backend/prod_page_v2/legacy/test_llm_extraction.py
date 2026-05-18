"""
Test the LLM-based image extraction on our example products.
"""

import asyncio
import sys
import json
from playwright.async_api import async_playwright

# Add parent to path
sys.path.insert(0, '.')

from llm_image_extractor import (
    extract_image_data_from_page,
    extract_product_images_heuristic,
    extract_product_images_with_llm,
    dedupe_image_urls
)
from image_extraction_prompt import build_prompt


# Test cases with expected outputs
TEST_CASES = [
    {
        "name": "Kuurth Ring",
        "url": "https://kuurth.com/collections/all/products/the-creation-of-adam-ring-v2",
        "product_name": "The creation of Adam - Ring V2",
        "expected_indices": [2, 3, 4, 5, 6],  # From our analysis
    },
    {
        "name": "Devi Nora Top",
        "url": "https://devi-clothing.com/collections/the-sari-collection/products/nora-top-red-cherry",
        "product_name": "Nora top - Cherry - S/M",
        "expected_indices": [3, 4, 5, 6, 7],
    },
    {
        "name": "Heaven Can Wait Jeans",
        "url": "https://heavencanwait.store/collections/frontpage/products/track-jeans-blue",
        "product_name": "V2 TRACK JEANS (BLUE)",
        "expected_indices": [3, 4, 5, 6, 7],
    },
]


async def test_heuristic_extraction():
    """Test the heuristic (non-LLM) extraction."""
    print("=" * 60)
    print("TESTING HEURISTIC EXTRACTION")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for tc in TEST_CASES:
            print(f"\n--- {tc['name']} ---")
            print(f"URL: {tc['url']}")
            print(f"Expected indices: {tc['expected_indices']}")

            page = await browser.new_page()
            try:
                await page.goto(tc['url'], wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_load_state('networkidle', timeout=10000)
            except Exception as e:
                print(f"Warning: {e}")

            result = await extract_product_images_heuristic(page, tc['product_name'])

            print(f"Found indices: {result['product_image_indices']}")
            print(f"Selector: {result['gallery_selector']}")
            print(f"URLs found: {len(result['product_image_urls'])}")

            # Check accuracy
            expected = set(tc['expected_indices'])
            found = set(result['product_image_indices'])
            correct = expected & found
            missed = expected - found
            extra = found - expected

            print(f"Accuracy: {len(correct)}/{len(expected)} correct")
            if missed:
                print(f"  Missed: {missed}")
            if extra:
                print(f"  Extra: {extra}")

            await page.close()

        await browser.close()


async def test_prompt_generation():
    """Test that we can generate prompts for the LLM."""
    print("\n" + "=" * 60)
    print("TESTING PROMPT GENERATION")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        tc = TEST_CASES[0]  # Use first test case
        print(f"\nGenerating prompt for: {tc['name']}")

        try:
            await page.goto(tc['url'], wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_load_state('networkidle', timeout=10000)
        except Exception as e:
            print(f"Warning: {e}")

        images = await extract_image_data_from_page(page, 30)

        # Build prompt (without URLs for LLM)
        images_for_llm = [
            {"i": img["i"], "alt": img["alt"], "link": img["link"], "containers": img["containers"]}
            for img in images
        ]

        prompt = build_prompt(tc['product_name'], tc['url'], images_for_llm)

        print(f"\nPrompt length: {len(prompt)} chars")
        print("\n--- PROMPT PREVIEW (first 3000 chars) ---")
        print(prompt[:3000])
        print("...[truncated]")

        await browser.close()


async def test_with_llm():
    """Test with actual LLM call (requires ANTHROPIC_API_KEY)."""
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n[SKIP] Set ANTHROPIC_API_KEY to test LLM extraction")
        return

    print("\n" + "=" * 60)
    print("TESTING LLM EXTRACTION")
    print("=" * 60)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for tc in TEST_CASES[:1]:  # Just test first case to save API calls
            print(f"\n--- {tc['name']} ---")
            page = await browser.new_page()

            try:
                await page.goto(tc['url'], wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_load_state('networkidle', timeout=10000)
            except Exception as e:
                print(f"Warning: {e}")

            result = await extract_product_images_with_llm(
                page, tc['product_name'], tc['url'], client
            )

            print(f"LLM found indices: {result['product_image_indices']}")
            print(f"LLM selector: {result['gallery_selector']}")
            print(f"LLM reasoning: {result['reasoning']}")

            # Check accuracy
            expected = set(tc['expected_indices'])
            found = set(result['product_image_indices'])
            correct = expected & found
            print(f"Accuracy: {len(correct)}/{len(expected)} correct")

            await page.close()

        await browser.close()


async def main():
    # Run heuristic test first (no API needed)
    await test_heuristic_extraction()

    # Show what the prompt looks like
    await test_prompt_generation()

    # Optionally test with LLM
    await test_with_llm()


if __name__ == "__main__":
    asyncio.run(main())
