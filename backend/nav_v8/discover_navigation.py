"""
Full navigation discovery pipeline.

1. Load page
2. Dismiss popups (LLM)
3. Capture baseline ARIA
4. Discover navigation entry point (LLM)
5. Interact with entry point (hover first, then click)
6. Extract revealed menu content

Usage:
  python discover_navigation.py <url>

Examples:
  python discover_navigation.py "https://www.gucci.com/us/en/"
  python discover_navigation.py "https://www.balenciaga.com/en-us"
"""

import asyncio
import sys
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent.parent))
from nav_v8.llm_popup_dismiss import dismiss_popups_with_llm
from nav_v8.llm_nav_discover import ask_llm_for_nav_entry
from nav_v8.aria_utils import menu_appeared, url_changed, extract_new_content, get_element_url


async def discover_navigation(url: str):
    """
    Full pipeline: popup dismiss -> nav discovery -> interaction -> extraction
    """
    print(f"\n{'='*70}")
    print(f"NAVIGATION DISCOVERY PIPELINE")
    print(f"{'='*70}")
    print(f"URL: {url}")
    print(f"{'='*70}\n")

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()

    try:
        # Step 1: Load page
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)
        url_initial = page.url

        # Step 2: Dismiss popups
        print("\n[2] LLM popup dismissal...")
        dismissed = await dismiss_popups_with_llm(page)
        print(f"    Dismissed {dismissed} popup(s)")

        # Step 3: Capture baseline ARIA
        print("\n[3] Capturing baseline ARIA...")
        aria_baseline = await page.locator('body').aria_snapshot()
        print(f"    {len(aria_baseline.splitlines())} lines")

        # Step 4: Discover navigation entry point
        print("\n[4] LLM navigation discovery...")
        nav_entry = await ask_llm_for_nav_entry(page)

        if nav_entry is None:
            print("    No entry point found - navigation may already be visible")
            print("\n    Current ARIA (first 50 lines):")
            for line in aria_baseline.splitlines()[:50]:
                print(f"      {line}")
            return

        role = nav_entry["role"]
        name = nav_entry["name"]
        print(f"\n    Entry point: {role} \"{name}\"")

        # Step 5: Find and interact with the element
        print(f"\n[5] Finding element: {role} \"{name}\"...")
        locator = page.get_by_role(role, name=name, exact=False)
        count = await locator.count()

        if count == 0:
            print(f"    ERROR: Element not found!")
            return

        print(f"    Found {count} match(es)")
        element = locator.first

        # Check if this is a link with URL
        element_url = None
        if role == "link":
            element_url = get_element_url(aria_baseline, name)

        # Step 5a: Try hover first
        print(f"\n[6] HOVER...")
        await element.hover()
        await page.wait_for_timeout(1000)

        aria_after_hover = await page.locator('body').aria_snapshot()
        url_after_hover = page.url

        appeared, reason = menu_appeared(aria_baseline, aria_after_hover, name)

        if appeared:
            print(f"    ✓ MENU APPEARED on hover ({reason})")
            new_lines = extract_new_content(aria_baseline, aria_after_hover)
            print(f"\n    Revealed content ({len(new_lines)} lines):")
            for line in new_lines[:30]:
                print(f"      {line}")
            if len(new_lines) > 30:
                print(f"      ... and {len(new_lines) - 30} more")

            print(f"\n{'='*70}")
            print("RESULT: Navigation revealed via HOVER")
            print(f"{'='*70}")
            await page.wait_for_timeout(3000)
            return

        if url_changed(url_initial, url_after_hover):
            print(f"    URL changed on hover: {url_after_hover}")
            return

        print("    No change on hover")

        # Step 5b: Try click (or navigate for links with URLs)
        if element_url:
            print(f"\n[7] NAVIGATE (link has URL)...")
            full_url = urljoin(url_initial, element_url) if element_url.startswith('/') else element_url
            print(f"    Going to: {full_url}")
            await page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
        else:
            print(f"\n[7] CLICK...")
            element = page.get_by_role(role, name=name, exact=False).first
            await element.click()
            await page.wait_for_timeout(1500)

        aria_after_click = await page.locator('body').aria_snapshot()
        url_after_click = page.url

        if url_changed(url_initial, url_after_click):
            print(f"    → NAVIGATED to: {url_after_click}")
            print(f"\n    New page ARIA (first 50 lines):")
            for line in aria_after_click.splitlines()[:50]:
                print(f"      {line}")

            print(f"\n{'='*70}")
            print("RESULT: Navigated to category page")
            print(f"{'='*70}")
            await page.wait_for_timeout(3000)
            return

        appeared, reason = menu_appeared(aria_baseline, aria_after_click, name)

        if appeared:
            print(f"    ✓ MENU APPEARED on click ({reason})")
            new_lines = extract_new_content(aria_baseline, aria_after_click)
            print(f"\n    Revealed content ({len(new_lines)} lines):")
            for line in new_lines[:30]:
                print(f"      {line}")
            if len(new_lines) > 30:
                print(f"      ... and {len(new_lines) - 30} more")

            print(f"\n{'='*70}")
            print("RESULT: Navigation revealed via CLICK")
            print(f"{'='*70}")
            await page.wait_for_timeout(3000)
            return

        print("    No menu appeared")
        print(f"\n{'='*70}")
        print("RESULT: Could not reveal navigation")
        print(f"{'='*70}")
        await page.wait_for_timeout(3000)

    finally:
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    await discover_navigation(sys.argv[1])


if __name__ == "__main__":
    asyncio.run(main())
