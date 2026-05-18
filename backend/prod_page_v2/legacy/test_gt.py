"""Test ground truth extraction on one URL per brand."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / 'config' / '.env')

from strategies.embedded_json import EmbeddedJsonStrategy
from page_loader import load_page

BRANDS = [
    ("032c", "https://www.032c.com/en-us/products/bambi-car-coat-1"),
    ("Alexander McQueen", "https://www.alexandermcqueen.com/en-us/pr/trompe-l'oeil-single-breasted-jacket-852956QUAAE1000.html"),
    ("Almada Label", "https://almadalabel.com/products/nessa-t-shirt-chocolate"),
    ("Balenciaga", "https://www.balenciaga.com/en-us/le-city-bag-medium-camel-8230582AB7D2533.html"),
    ("Devi Clothing", "https://devi-clothing.com/collections/the-sari-collection/products/nora-top-red-cherry"),
    ("Eckhaus Latta", "https://www.eckhauslatta.com/products/the-snap-green"),
    ("Entire Studios", "https://www.entirestudios.com/product/spar-shorts-old-blue"),
    ("Heaven Can Wait", "https://heavencanwait.store/collections/frontpage/products/tech-puffa-black-white"),
    ("Jukuhara", "https://jukuhara.jp/products/vietnamese-t-shirt-copy"),
    ("Kuurth", "https://kuurth.com/collections/armor%C2%AE-bag/products/armor-black-bag"),
    ("Satisfy Running", "https://satisfyrunning.com/products/merino-nylon-tube-socks-2"),
    ("Saya Gray", "https://store.sayagray.ca/release/568429-saya-gray-bootleg-tee"),
]


async def test_gt():
    strategy = EmbeddedJsonStrategy()

    for name, url in BRANDS:
        print(f"\n{'='*60}")
        print(f"  {name}: {url}")
        print(f"{'='*60}")

        try:
            page_data = await load_page(url, wait_time=5000)
            gt_data = strategy.extract_ground_truth(page_data)
            if gt_data:
                product = strategy._parse_product(gt_data, url, page_data)
                variants = len(product.variants) if product.variants else 0
                desc_len = len(product.description) if product.description else 0
                images = len(product.images) if product.images else 0
                print(f"  name:        {product.name}")
                print(f"  price:       {product.price}")
                print(f"  currency:    {product.currency}")
                print(f"  brand:       {product.brand}")
                print(f"  sku:         {product.sku}")
                print(f"  category:    {product.category}")
                print(f"\n  VARIANTS ({variants}):")
                if product.variants:
                    for i, v in enumerate(product.variants[:10]):
                        avail = "avail" if v.available else ("OOS" if v.available is False else "?")
                        print(f"    [{i+1}] size={v.size or '-'}, color={v.color or '-'}, price={v.price or '-'}, {avail}")
                    if len(product.variants) > 10:
                        print(f"    ... +{len(product.variants) - 10} more")
                print(f"\n  IMAGES ({images}):")
                if product.images:
                    for i, img in enumerate(product.images[:5]):
                        print(f"    [{i+1}] {img[:120]}")
                    if len(product.images) > 5:
                        print(f"    ... +{len(product.images) - 5} more")
                print(f"\n  DESCRIPTION ({desc_len} chars):")
                print(f"    {product.description or '(none)'}")
            else:
                print(f"  FAILED - no GT returned")
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(test_gt())
