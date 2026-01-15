"""
Test stealth patches against bot detection.
"""

import asyncio
from playwright.async_api import async_playwright
from . import StealthBrowser
from .diagnose import DETECTION_CHECKS


async def compare_detection():
    """Compare detection vectors: vanilla vs stealth."""

    print("=" * 70)
    print("COMPARING DETECTION VECTORS")
    print("=" * 70)

    # Test vanilla Playwright
    print("\n[1] VANILLA PLAYWRIGHT (no stealth)")
    print("-" * 50)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        vanilla_results = await page.evaluate(DETECTION_CHECKS)
        await browser.close()

    print(f"   navigator.webdriver: {vanilla_results['webdriver']['navigator_webdriver']}")
    print(f"   plugins: {vanilla_results['plugins']['count']}")
    print(f"   window.chrome: {vanilla_results['chrome']['exists']}")
    print(f"   WebGL renderer: {vanilla_results['webgl'].get('renderer', 'N/A')[:50]}...")

    # Test stealth Playwright
    print("\n[2] STEALTH PLAYWRIGHT (with patches)")
    print("-" * 50)

    async with StealthBrowser() as sb:
        page = await sb.new_page()
        stealth_results = await page.evaluate(DETECTION_CHECKS)

    print(f"   navigator.webdriver: {stealth_results['webdriver']['navigator_webdriver']}")
    print(f"   plugins: {stealth_results['plugins']['count']}")
    print(f"   window.chrome: {stealth_results['chrome']['exists']}")
    print(f"   WebGL renderer: {stealth_results['webgl'].get('renderer', 'N/A')[:50]}...")

    # Summary
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)

    checks = [
        ('navigator.webdriver',
         vanilla_results['webdriver']['navigator_webdriver'],
         stealth_results['webdriver']['navigator_webdriver'],
         'undefined or false'),
        ('plugins count',
         vanilla_results['plugins']['count'],
         stealth_results['plugins']['count'],
         '3+'),
        ('window.chrome exists',
         vanilla_results['chrome']['exists'],
         stealth_results['chrome']['exists'],
         'True'),
        ('Has SwiftShader',
         vanilla_results['webgl'].get('hasSwiftShader', False),
         stealth_results['webgl'].get('hasSwiftShader', False),
         'False'),
    ]

    print(f"\n{'Check':<25} {'Vanilla':<15} {'Stealth':<15} {'Expected':<15}")
    print("-" * 70)

    fixed = 0
    for check, vanilla, stealth, expected in checks:
        vanilla_str = str(vanilla)[:12]
        stealth_str = str(stealth)[:12]
        status = "✅" if str(stealth).lower() in expected.lower() or stealth == expected else "❌"
        if vanilla != stealth:
            fixed += 1
        print(f"{check:<25} {vanilla_str:<15} {stealth_str:<15} {expected:<15} {status}")

    print(f"\n{fixed}/{len(checks)} vectors patched")

    return vanilla_results, stealth_results


async def test_blocked_sites():
    """Test if stealth mode can bypass blocked sites."""

    print("\n\n" + "=" * 70)
    print("TESTING BLOCKED SITES WITH STEALTH")
    print("=" * 70)

    sites = [
        ('Aritzia', 'https://www.aritzia.com/us/en/product/the-super-puff/126464.html'),
        ('COS', 'https://www.cos.com/en-us/men/menswear/coatsjackets/denim/product/denim-overshirt-dark-blue-1315149001'),
    ]

    async with StealthBrowser() as sb:
        for name, url in sites:
            print(f"\n[{name}] {url[:50]}...")
            print("-" * 50)

            page = await sb.new_page()

            try:
                response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_timeout(5000)  # Wait for JS

                html = await page.content()
                title = await page.title()

                print(f"   Status: {response.status}")
                print(f"   Title: {title[:50]}")
                print(f"   HTML length: {len(html)}")

                # Check for blocks
                if 'Just a moment' in title or 'Just a moment' in html[:1000]:
                    print("   🚫 STILL BLOCKED (Cloudflare challenge)")
                elif 'Access Denied' in title or 'Access Denied' in html[:1000]:
                    print("   🚫 STILL BLOCKED (Access Denied)")
                elif len(html) < 5000:
                    print("   ⚠️  Partial load (suspicious)")
                else:
                    print("   ✅ SUCCESS - Page loaded!")

                    # Try to find product name
                    if 'Super Puff' in html or 'Overshirt' in html:
                        print("   ✅ Product content found!")

            except Exception as e:
                print(f"   ❌ Error: {e}")

            await page.close()


if __name__ == "__main__":
    async def main():
        await compare_detection()
        await test_blocked_sites()

    asyncio.run(main())
