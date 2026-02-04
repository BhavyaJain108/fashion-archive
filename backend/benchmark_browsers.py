"""
Benchmark: How does browser count affect throughput?

Tests extraction with 5, 15, and 25 browsers on a sample of 30 URLs.
Uses saved discovery config (skips discovery phase).

This tells us whether the bottleneck is:
  a) Site rate limit  → throughput same regardless of browsers
  b) Browser count    → throughput scales with browsers
  c) CPU/RAM          → throughput degrades with more browsers
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent / "prod_page_v2"))
sys.path.insert(0, str(Path(__file__).parent / "stages"))

from prod_page_v2.extractor import ProductExtractor, MultiStrategyConfig
from prod_page_v2.browser_pool import BrowserPool


DOMAIN = "kuurth.com"
SAMPLE_SIZE = 30  # URLs per test
BROWSER_COUNTS = [5, 15, 25]


def load_sample_urls() -> list:
    """Load a sample of product URLs from saved urls.json."""
    urls_path = Path(__file__).parent / "extractions" / "kuurth_com" / "urls.json"
    with open(urls_path) as f:
        data = json.load(f)

    all_urls = []
    for cat in data.get("category_tree", []):
        all_urls.extend(cat.get("products", []))

    # Take evenly spaced sample
    if len(all_urls) <= SAMPLE_SIZE:
        return all_urls

    step = len(all_urls) // SAMPLE_SIZE
    return [all_urls[i * step] for i in range(SAMPLE_SIZE)]


def load_config() -> MultiStrategyConfig:
    """Load saved extraction config (skip discovery)."""
    config_path = Path(__file__).parent / "prod_page_v2" / "extractions" / "kuurth_com" / "config.json"
    with open(config_path) as f:
        data = json.load(f)
    return MultiStrategyConfig.from_dict(data)


async def benchmark_with_browsers(num_browsers: int, urls: list, config: MultiStrategyConfig) -> dict:
    """
    Run extraction with N browsers, measure throughput.
    No rate limiter - pure browser pool throughput test.
    """
    extractor = ProductExtractor()
    pool = BrowserPool(size=num_browsers, pages_per_recycle=100, headless=True)

    await pool.start()

    successes = 0
    failures = 0
    start_time = time.time()

    # Create a queue of URLs
    url_queue = asyncio.Queue()
    for url in urls:
        await url_queue.put(url)

    async def worker(worker_id: int):
        nonlocal successes, failures
        while not url_queue.empty():
            try:
                url = url_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            try:
                async with pool.acquire() as page:
                    result = await extractor.extract_single_pooled(url, page, config)

                if result.success and result.product:
                    successes += 1
                else:
                    failures += 1
            except Exception as e:
                failures += 1

            done = successes + failures
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed > 0 else 0
            print(f"  [{done}/{len(urls)}] rate={rate:.2f}/s (✓{successes} ✗{failures})")

    # Launch workers (one per browser - each worker holds a browser)
    workers = [asyncio.create_task(worker(i)) for i in range(num_browsers)]
    await asyncio.gather(*workers)

    await pool.shutdown()

    elapsed = time.time() - start_time
    throughput = (successes + failures) / elapsed if elapsed > 0 else 0

    return {
        "browsers": num_browsers,
        "urls": len(urls),
        "successes": successes,
        "failures": failures,
        "elapsed": elapsed,
        "throughput": throughput,
    }


async def main():
    print("=" * 60)
    print("BROWSER THROUGHPUT BENCHMARK")
    print("=" * 60)

    urls = load_sample_urls()
    config = load_config()

    print(f"Sample: {len(urls)} URLs from kuurth.com")
    print(f"Config: {len(config.contributions)} strategies")
    print(f"Tests:  {BROWSER_COUNTS} browsers")
    print("=" * 60)

    results = []

    for count in BROWSER_COUNTS:
        print(f"\n{'─' * 60}")
        print(f"TEST: {count} browsers, {len(urls)} URLs")
        print(f"{'─' * 60}")

        result = await benchmark_with_browsers(count, urls, config)
        results.append(result)

        print(f"\nResult: {result['throughput']:.2f} products/sec "
              f"({result['successes']}/{result['urls']} succeeded in {result['elapsed']:.1f}s)")

    # Summary
    print(f"\n{'=' * 60}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 60}")
    print(f"{'Browsers':<12} {'Throughput':<15} {'Time':<10} {'Success':<10}")
    print(f"{'─' * 47}")
    for r in results:
        print(f"{r['browsers']:<12} {r['throughput']:.2f}/s{'':<9} {r['elapsed']:.1f}s{'':<4} {r['successes']}/{r['urls']}")

    # Analysis
    print(f"\n{'─' * 60}")
    if len(results) >= 2:
        r1, r2 = results[0], results[1]
        browser_ratio = r2["browsers"] / r1["browsers"]
        throughput_ratio = r2["throughput"] / r1["throughput"] if r1["throughput"] > 0 else 0

        if throughput_ratio > browser_ratio * 0.7:
            print("VERDICT: Throughput scales with browsers → MORE BROWSERS WILL HELP")
        elif throughput_ratio > 1.1:
            print("VERDICT: Some scaling but diminishing returns → PARTIAL BENEFIT")
        else:
            print("VERDICT: Throughput doesn't scale → SITE IS THE BOTTLENECK")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
