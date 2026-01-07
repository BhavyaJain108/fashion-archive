"""
Simple script to capture and view ARIA snapshots from brand landing pages.
No LLM, no logic - just observation.
"""

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright


async def capture_aria(url: str, wait_seconds: int = 5):
    """Just load a page and save its ARIA snapshot"""

    print(f"\n{'='*80}")
    print(f"URL: {url}")
    print(f"{'='*80}\n")

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)  # headful to avoid bot detection
    page = await browser.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(wait_seconds * 1000)

        # Get ARIA snapshot
        aria = await page.locator('body').aria_snapshot()

        # Save to file
        domain = urlparse(url).netloc.replace("www.", "").replace(".", "_")
        output_dir = Path(__file__).parent / "snapshots"
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"{domain}_aria.txt"

        with open(output_file, "w") as f:
            f.write(f"URL: {url}\n")
            f.write(f"{'='*80}\n\n")
            f.write(aria)

        print(f"ARIA SNAPSHOT (first 150 lines):")
        print("-" * 80)
        lines = aria.splitlines()
        for line in lines[:150]:
            print(line)
        if len(lines) > 150:
            print(f"\n... ({len(lines) - 150} more lines)")
        print("-" * 80)
        print(f"\nTotal lines: {len(lines)}")
        print(f"Total chars: {len(aria)}")
        print(f"Saved to: {output_file}")

    finally:
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python explore_aria.py <url>")
        print("Example: python explore_aria.py https://www.jacquemus.com")
        sys.exit(1)

    url = sys.argv[1]
    await capture_aria(url)


if __name__ == "__main__":
    asyncio.run(main())
