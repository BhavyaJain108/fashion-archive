"""Quick test: gallery selector discovery + image extraction on 4 product pages."""

import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "prod_page_v2"))
sys.path.insert(0, str(Path(__file__).parent / "scraper"))
sys.path.insert(0, str(Path(__file__).parent / "stages"))

from prod_page_v2.browser_pool import BrowserPool
from prod_page_v2.page_loader import load_page_on_existing, extract_gallery_images
from prod_page_v2.extractor import ProductExtractor

URLS = [
    "https://intl.thisisneverthat.com/products/fw25-flannel-country-shirt?variantId=44567613702351",
    "https://ca.stussy.com/collections/new-arrivals/products/115872-stussy-alpha-winter-parka-black",
    "https://www.entirestudios.com/product/margin-drape-top-ace",
    "https://www.acnestudios.com/us/en/satin-trousers-black/BK0688-900.html?g=man",
]


async def main():
    pool = BrowserPool(size=1, pages_per_recycle=50, headless=True)
    await pool.start()
    extractor = ProductExtractor()

    try:
        for url in URLS:
            print(f"\n{'='*70}")
            print(f"URL: {url}")
            print(f"{'='*70}")

            # Load page
            async with pool.acquire() as page:
                page_data = await load_page_on_existing(page, url, wait_time=3000)

                if not page_data.loaded:
                    print(f"  FAILED to load (status={page_data.status_code})")
                    continue

                print(f"  Page loaded (status={page_data.status_code}, html={len(page_data.html)} chars)")

                # Discover gallery config
                gallery_config = await extractor.discover_gallery_selector(url, page=page)
                print(f"  Gallery config: {json.dumps(gallery_config, indent=4) if isinstance(gallery_config, dict) else gallery_config}")

                if gallery_config:
                    images = await extract_gallery_images(page, gallery_config)
                    print(f"  Gallery images ({len(images)}):")
                    for img in images:
                        print(f"    {img}")
                else:
                    print(f"  No gallery selector found")

                print()

    finally:
        await pool.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
