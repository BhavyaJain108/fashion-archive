"""
Brand configuration with valid test URLs.

Run: python brands.py
to verify all URLs are accessible.
"""

BRANDS = {
    # Kering brands (same platform)
    'Alexander McQueen': {
        'url': "https://www.alexandermcqueen.com/en-us/pr/trompe-l'oeil-single-breasted-jacket-852956QUAAE1000.html",
        'platform': 'Kering/Next.js',
    },
    'Balenciaga': {
        'url': 'https://www.balenciaga.com/en-us/le-city-bag-medium-camel-8230582AB7D2533.html',
        'platform': 'Kering/Next.js',
    },

    # Shopify brands
    'Eckhaus Latta': {
        'url': 'https://www.eckhauslatta.com/products/the-snap-green',
        'platform': 'Shopify',
    },
    'Entire Studios': {
        'url': 'https://www.entirestudios.com/product/spar-shorts-old-blue',
        'platform': 'Shopify',
    },

    # Custom platforms
    'Acne Studios': {
        'url': 'https://www.acnestudios.com/us/en/loose-fit-jeans---1981-mid-blue/CK0138-AUZ.html?g=woman',
        'platform': 'Salesforce Commerce',
    },
    'Aritzia': {
        'url': 'https://www.aritzia.com/us/en/product/the-super-puff%E2%84%A2/126464.html?color=6038',
        'platform': 'Custom',
    },
    'Uniqlo': {
        'url': 'https://www.uniqlo.com/us/en/products/E478577-000/00',
        'platform': 'Custom',
    },
}


async def verify_urls():
    """Check which URLs are accessible."""
    import aiohttp
    import asyncio

    print(f"{'Brand':<20} | {'Status':>6} | {'Platform':<20}")
    print("-" * 55)

    async with aiohttp.ClientSession() as session:
        for brand, config in BRANDS.items():
            url = config['url']
            platform = config['platform']
            try:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True) as resp:
                    status = resp.status
                    print(f"{brand:<20} | {status:>6} | {platform:<20}")
            except Exception as e:
                print(f"{brand:<20} | {'ERROR':>6} | {str(e)[:20]}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(verify_urls())
