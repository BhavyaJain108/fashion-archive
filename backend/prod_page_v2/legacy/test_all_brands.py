"""
Full audit: discover + verify with ground truth, then extract one product
with gallery images to show the complete picture per brand.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / 'config' / '.env')

from extractor import ProductExtractor
from page_loader import extract_gallery_images
from models import ExtractionStrategy

BRANDS = [
    ("032c", "032c.com", [
        "https://www.032c.com/en-us/products/bambi-car-coat-1",
        "https://www.032c.com/en-us/products/issue-48-winter-2025-26-nine-inch-nails"
    ]),
    ("Alexander McQueen", "alexandermcqueen.com", [
        "https://www.alexandermcqueen.com/en-us/pr/trompe-l'oeil-single-breasted-jacket-852956QUAAE1000.html",
        "https://www.alexandermcqueen.com/en-us/pr/crystal-embroidery-mini-jewelled-satchel-85484817HLI1090.html"
    ]),
    ("Almada Label", "almadalabel.com", [
        "https://almadalabel.com/products/nessa-t-shirt-chocolate",
        "https://almadalabel.com/products/coco-brushed-cardigan-vanilla"
    ]),
    ("Balenciaga", "balenciaga.com", [
        "https://www.balenciaga.com/en-us/le-city-bag-medium-camel-8230582AB7D2533.html",
        "https://www.balenciaga.com/en-us/balenciaga-%7C-nba-collaboration-tracksuit-jacket-red-864835TROA56417.html"
    ]),
    ("Devi Clothing", "devi-clothing.com", [
        "https://devi-clothing.com/collections/the-sari-collection/products/nora-top-red-cherry",
        "https://devi-clothing.com/collections/the-sari-collection/products/nora-top-pumpkin-spice-s-m-copy"
    ]),
    ("Eckhaus Latta", "eckhauslatta.com", [
        "https://www.eckhauslatta.com/products/the-snap-green",
        "https://www.eckhauslatta.com/products/drift-hoodie-pink-sand"
    ]),
    ("Entire Studios", "entirestudios.com", [
        "https://www.entirestudios.com/product/spar-shorts-old-blue",
        "https://www.entirestudios.com/product/a-4-bomber-army"
    ]),
    ("Heaven Can Wait", "heavencanwait.store", [
        "https://heavencanwait.store/collections/frontpage/products/tech-puffa-black-white",
        "https://heavencanwait.store/collections/frontpage/products/heat-reactive-ski-jacket-black-blue"
    ]),
    ("Jukuhara", "jukuhara.jp", [
        "https://jukuhara.jp/products/vietnamese-t-shirt-copy",
        "https://jukuhara.jp/products/jp-sounds-zip-up-jacket-black"
    ]),
    ("Kuurth", "kuurth.com", [
        "https://kuurth.com/collections/armor%C2%AE-bag/products/armor-black-bag",
        "https://kuurth.com/collections/all-gold/products/delirium-gold-ring"
    ]),
    ("Satisfy Running", "satisfyrunning.com", [
        "https://satisfyrunning.com/products/merino-nylon-tube-socks-2",
        "https://satisfyrunning.com/products/possessed-magazine-63"
    ]),
    ("Saya Gray", "sayagray.ca", [
        "https://store.sayagray.ca/release/568429-saya-gray-bootleg-tee",
        "https://store.sayagray.ca/release/560646-saya-gray-wish-you-picked-me-long-sleeve-black"
    ]),
]


async def full_audit(name, domain, urls, extractor):
    """Run discovery, then do a full extraction (with gallery) on URL1."""
    from playwright.async_api import async_playwright
    from page_loader import load_page_on_existing

    print(f"\n{'='*80}")
    print(f"  {name} ({domain})")
    print(f"{'='*80}")

    # Step 1: Use existing config (don't redo discovery)
    config = extractor._load_config(domain)
    if not config:
        print(f"  NO CONFIG - skipping")
        return {"brand": name, "status": "NO_CONFIG"}

    # Step 2: Load gallery config
    gallery_config = extractor.load_gallery_selector(domain)

    # Step 3: Full extraction on URL1 using pooled path (like production)
    url = urls[0]
    print(f"\n  --- FULL EXTRACTION on {url} ---")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        result = await extractor.extract_single_pooled(
            url, page, config=config, gallery_selector=gallery_config
        )

        await browser.close()

    if not result.success:
        print(f"  EXTRACTION FAILED: {result.error}")
        return {"brand": name, "status": "EXTRACTION_FAILED"}

    p = result.product

    # Step 4: Print the full picture
    print(f"\n  PRODUCT DETAILS:")
    print(f"    Name:        {p.name}")
    print(f"    Price:       {p.price} {p.currency}")
    print(f"    Brand:       {p.brand}")
    print(f"    SKU:         {p.sku}")
    print(f"    Category:    {p.category}")
    print(f"    Description: {(p.description or '')[:120]}{'...' if p.description and len(p.description) > 120 else ''}")
    print(f"    Desc length: {len(p.description) if p.description else 0} chars")

    print(f"\n  VARIANTS ({len(p.variants) if p.variants else 0}):")
    if p.variants:
        for i, v in enumerate(p.variants[:10]):
            avail = "avail" if v.available else ("OOS" if v.available is False else "?")
            print(f"    [{i+1}] size={v.size or '-'}, color={v.color or '-'}, price={v.price or '-'}, {avail}")
        if len(p.variants) > 10:
            print(f"    ... +{len(p.variants) - 10} more")
    else:
        print(f"    (none)")

    print(f"\n  IMAGES ({len(p.images) if p.images else 0}):")
    if gallery_config:
        print(f"    Gallery config: {gallery_config}")
    else:
        print(f"    (no gallery config - using strategy images)")
    if p.images:
        for i, img in enumerate(p.images[:10]):
            print(f"    [{i+1}] {img[:120]}")
        if len(p.images) > 10:
            print(f"    ... +{len(p.images) - 10} more")
    else:
        print(f"    (none)")

    print(f"\n  FIELD SOURCES: {config.field_sources}")
    print(f"  SCORE: {result.score}")

    return {
        "brand": name,
        "status": "OK",
        "name": p.name,
        "price": f"{p.price} {p.currency}",
        "images": len(p.images) if p.images else 0,
        "variants": len(p.variants) if p.variants else 0,
        "desc_len": len(p.description) if p.description else 0,
        "field_sources": config.field_sources,
    }


async def main():
    extractor = ProductExtractor()

    name_filter = sys.argv[1].lower() if len(sys.argv) > 1 else None
    brands = BRANDS
    if name_filter:
        brands = [b for b in BRANDS if name_filter in b[0].lower() or name_filter in b[1].lower()]

    results = []
    for name, domain, urls in brands:
        r = await full_audit(name, domain, urls, extractor)
        results.append(r)

    # Final summary table
    print(f"\n\n{'='*80}")
    print(f"  SUMMARY")
    print(f"{'='*80}")
    print(f"  {'Brand':<22s} {'Status':<10s} {'Price':<14s} {'Imgs':>4s} {'Vars':>4s} {'Desc':>5s}")
    print(f"  {'-'*22} {'-'*10} {'-'*14} {'-'*4} {'-'*4} {'-'*5}")
    for r in results:
        if r["status"] == "OK":
            print(f"  {r['brand']:<22s} {'OK':<10s} {r['price']:<14s} {r['images']:>4d} {r['variants']:>4d} {r['desc_len']:>5d}")
        else:
            print(f"  {r['brand']:<22s} {r['status']:<10s}")

    ok = sum(1 for r in results if r["status"] == "OK")
    print(f"\n  {ok}/{len(results)} brands fully extracted")


if __name__ == "__main__":
    asyncio.run(main())
