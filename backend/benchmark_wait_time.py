"""
Benchmark: What's the minimum wait time that still extracts correctly?

Tests the SAME 10 URLs at wait times of 500ms, 1000ms, 2000ms, 3000ms, 5000ms.
Compares extraction quality (name, price, images) against the 5s baseline.

This tells us how much of the 5-second wait is wasted.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "prod_page_v2"))
sys.path.insert(0, str(Path(__file__).parent / "stages"))

from prod_page_v2.extractor import ProductExtractor, MultiStrategyConfig
from prod_page_v2.page_loader import load_page_on_existing
from prod_page_v2.browser_pool import BrowserPool


DOMAIN = "kuurth.com"
SAMPLE_SIZE = 10
WAIT_TIMES = [500, 1000, 2000, 3000, 5000]  # ms


def load_sample_urls() -> list:
    urls_path = Path(__file__).parent / "extractions" / "kuurth_com" / "urls.json"
    with open(urls_path) as f:
        data = json.load(f)
    all_urls = []
    for cat in data.get("category_tree", []):
        all_urls.extend(cat.get("products", []))
    step = max(1, len(all_urls) // SAMPLE_SIZE)
    return [all_urls[i * step] for i in range(min(SAMPLE_SIZE, len(all_urls)))]


def load_config() -> MultiStrategyConfig:
    config_path = Path(__file__).parent / "prod_page_v2" / "extractions" / "kuurth_com" / "config.json"
    with open(config_path) as f:
        data = json.load(f)
    return MultiStrategyConfig.from_dict(data)


def score_product(product) -> dict:
    """Score extraction quality - what fields did we get?"""
    if not product:
        return {"score": 0, "name": False, "price": False, "images": 0, "description": False}

    has_name = bool(product.name and len(product.name) > 1)
    has_price = bool(product.price and product.price != "0")
    num_images = len(product.images) if product.images else 0
    has_desc = bool(product.description and len(product.description) > 10)

    score = sum([
        has_name * 30,
        has_price * 30,
        min(num_images, 3) * 10,  # up to 30 points for images
        has_desc * 10,
    ])

    return {
        "score": score,
        "name": has_name,
        "price": has_price,
        "images": num_images,
        "description": has_desc,
    }


async def test_wait_time(wait_ms: int, urls: list, config: MultiStrategyConfig, extractor: ProductExtractor) -> dict:
    """Test extraction at a specific wait time."""
    pool = BrowserPool(size=5, pages_per_recycle=100, headless=True)
    await pool.start()

    results = []
    total_time = 0

    for i, url in enumerate(urls):
        start = time.time()
        async with pool.acquire() as page:
            page_data = await load_page_on_existing(page, url, wait_time=wait_ms)

            # Run extraction strategies
            extraction_results = []
            if config and config.verified:
                active = config.get_active_strategies()
                for strategy in extractor.strategies:
                    if strategy.strategy_type in active:
                        result = await strategy.extract(url, page_data)
                        extraction_results.append(result)
            else:
                for strategy in extractor.strategies:
                    result = await strategy.extract(url, page_data)
                    extraction_results.append(result)

            # Merge results
            product = None
            for r in extraction_results:
                if r.success and r.product:
                    product = r.product
                    break

        elapsed = time.time() - start
        total_time += elapsed
        quality = score_product(product)

        results.append({
            "url": url.split("/")[-1],
            "quality": quality,
            "time": elapsed,
        })

        status = "✓" if quality["score"] >= 60 else "✗"
        print(f"    {status} [{i+1}/{len(urls)}] {quality['score']:3d}pts "
              f"| name:{quality['name']} price:{quality['price']} "
              f"imgs:{quality['images']} | {elapsed:.1f}s")

    await pool.shutdown()

    scores = [r["quality"]["score"] for r in results]
    good = sum(1 for s in scores if s >= 60)

    return {
        "wait_ms": wait_ms,
        "avg_score": sum(scores) / len(scores),
        "good_count": good,
        "total": len(urls),
        "avg_time": total_time / len(urls),
        "total_time": total_time,
        "results": results,
    }


async def main():
    print("=" * 60)
    print("WAIT TIME BENCHMARK")
    print("=" * 60)

    urls = load_sample_urls()
    config = load_config()
    extractor = ProductExtractor()

    print(f"Sample: {len(urls)} URLs from kuurth.com")
    print(f"Wait times: {WAIT_TIMES}ms")
    print("=" * 60)

    all_results = []

    for wait_ms in WAIT_TIMES:
        print(f"\n{'─' * 60}")
        print(f"TEST: wait_time = {wait_ms}ms")
        print(f"{'─' * 60}")

        result = await test_wait_time(wait_ms, urls, config, extractor)
        all_results.append(result)

        print(f"\n  Avg score: {result['avg_score']:.0f}/100 | "
              f"Good: {result['good_count']}/{result['total']} | "
              f"Avg time: {result['avg_time']:.1f}s")

    # Summary
    print(f"\n{'=' * 60}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 60}")
    print(f"{'Wait (ms)':<12} {'Avg Score':<12} {'Good/Total':<12} {'Avg Time':<12} {'Throughput':<12}")
    print(f"{'─' * 60}")
    for r in all_results:
        tp = 1.0 / r["avg_time"] if r["avg_time"] > 0 else 0
        print(f"{r['wait_ms']:<12} {r['avg_score']:<12.0f} "
              f"{r['good_count']}/{r['total']:<10} "
              f"{r['avg_time']:<12.1f} {tp:<12.2f}/s")

    # Find optimal
    print(f"\n{'─' * 60}")
    baseline = all_results[-1]  # 5000ms
    for r in all_results:
        if r["avg_score"] >= baseline["avg_score"] * 0.95:  # within 5% of baseline quality
            speedup = baseline["avg_time"] / r["avg_time"] if r["avg_time"] > 0 else 0
            print(f"OPTIMAL: {r['wait_ms']}ms → {speedup:.1f}x faster than 5000ms at same quality")
            break
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
