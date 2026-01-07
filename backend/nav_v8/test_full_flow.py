"""
Test full flow: LLM popup dismiss + smart interact
"""

import asyncio
import sys
import re
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent.parent))
from nav_v8.llm_popup_dismiss import dismiss_popups_with_llm
from nav_v8.aria_utils import menu_appeared, url_changed, extract_new_content, get_element_url


async def test_full_flow(url: str, role: str, name: str):
    """Test LLM popup dismiss + smart interact"""

    print(f"\n{'='*70}")
    print(f"FULL FLOW TEST")
    print(f"{'='*70}")
    print(f"URL: {url}")
    print(f"Target: {role} \"{name}\"")
    print(f"{'='*70}\n")

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()

    try:
        # Load page
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)
        url_initial = page.url

        # LLM popup dismiss
        print("\n[2] LLM popup dismissal...")
        dismissed = await dismiss_popups_with_llm(page)
        print(f"    Dismissed {dismissed} popup(s)")

        # Capture baseline
        print("\n[3] Capturing baseline ARIA...")
        aria_baseline = await page.locator('body').aria_snapshot()
        print(f"    {len(aria_baseline.splitlines())} lines")

        # Find element
        print(f"\n[4] Finding: {role} \"{name}\"...")
        locator = page.get_by_role(role, name=name, exact=False)
        count = await locator.count()

        if count == 0:
            locator = page.get_by_role(role, name=re.compile(name, re.IGNORECASE))
            count = await locator.count()

        if count == 0:
            print("    ERROR: Element not found!")
            return

        print(f"    Found {count} match(es)")

        # Check for URL if link
        element_url = None
        if role == "link":
            element_url = get_element_url(aria_baseline, name)

        # Try hover
        print(f"\n[5] HOVER...")
        await locator.first.hover()
        await page.wait_for_timeout(1000)

        aria_after_hover = await page.locator('body').aria_snapshot()
        appeared, reason = menu_appeared(aria_baseline, aria_after_hover, name)

        if appeared:
            print(f"    ✓ MENU on hover ({reason})")
            new_lines = extract_new_content(aria_baseline, aria_after_hover)
            print(f"    {len(new_lines)} new lines")
            for line in new_lines[:10]:
                print(f"      {line}")
            return

        print("    No change on hover")

        # Try click or navigate
        if element_url:
            print(f"\n[6] NAVIGATE to {element_url}...")
            from urllib.parse import urljoin
            full_url = urljoin(url_initial, element_url) if element_url.startswith('/') else element_url
            await page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
        else:
            print(f"\n[6] CLICK...")
            await locator.first.click()
            await page.wait_for_timeout(1500)

        aria_after = await page.locator('body').aria_snapshot()
        url_after = page.url

        if url_changed(url_initial, url_after):
            print(f"    → NAVIGATED: {url_after}")
            return

        appeared, reason = menu_appeared(aria_baseline, aria_after, name)
        if appeared:
            print(f"    ✓ MENU on click ({reason})")
            new_lines = extract_new_content(aria_baseline, aria_after)
            print(f"    {len(new_lines)} new lines")
            for line in new_lines[:10]:
                print(f"      {line}")
            return

        print("    No menu found")

    finally:
        await page.wait_for_timeout(3000)
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 4:
        print("Usage: python test_full_flow.py <url> <role> <name>")
        sys.exit(1)

    await test_full_flow(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    asyncio.run(main())
