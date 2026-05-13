"""Test extraction across multiple brands."""

import asyncio
from extractor import ProductExtractor

BRANDS = {
    'Alexander McQueen': "https://www.alexandermcqueen.com/en-us/pr/trompe-l'oeil-single-breasted-jacket-852956QUAAE1000.html",
    'Balenciaga': 'https://www.balenciaga.com/en-us/le-city-bag-medium-camel-8230582AB7D2533.html',
    'Acne Studios': 'https://www.acnestudios.com/us/en/loose-fit-jeans---1981-mid-blue/CK0138-AUZ.html?g=woman',
    'Eckhaus Latta': 'https://www.eckhauslatta.com/products/the-snap-green',
    'Entire Studios': 'https://www.entirestudios.com/product/spar-shorts-old-blue',
    'Aritzia': 'https://www.aritzia.com/us/en/product/the-super-puff%E2%84%A2/126464.html?color=6038',
    'Uniqlo': 'https://www.uniqlo.com/us/en/products/E478577-000/00',
}


async def test_all():
    extractor = ProductExtractor()

    print(f"{'Brand':<20} | {'Name':<30} | {'Price':>10} | {'Imgs':>4} | {'Vars':>4}")
    print("-" * 85)

    for brand, url in BRANDS.items():
        try:
            result = await extractor.extract_single(url)

            if result.success and result.product:
                p = result.product
                name = (p.name[:28] + '..') if p.name and len(p.name) > 30 else (p.name or 'N/A')
                price = f"${p.price:.0f}" if p.price else "N/A"
                print(f"{brand:<20} | {name:<30} | {price:>10} | {len(p.images):>4} | {len(p.variants):>4}")
            else:
                print(f"{brand:<20} | FAILED: {result.error[:50]}")
        except Exception as e:
            print(f"{brand:<20} | ERROR: {str(e)[:50]}")


if __name__ == "__main__":
    asyncio.run(test_all())
