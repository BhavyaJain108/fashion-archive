"""
Test smart interaction: hover first, then click if needed.

This script:
1. Loads a page, dismisses popups
2. Finds the target element
3. Hovers - checks if menu appeared
4. If not, clicks - checks if menu appeared or if we navigated

Usage:
  python test_smart_interact.py <url> <role> <name>

Examples:
  python test_smart_interact.py "https://www.eckhauslatta.com" button "Shop menu"
  python test_smart_interact.py "https://www.acnestudios.com" button "Woman"
  python test_smart_interact.py "https://www.zara.com/us/" button "Open Menu"
"""

import asyncio
import sys
import re
from pathlib import Path
from playwright.async_api import async_playwright

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from nav_v8.aria_utils import menu_appeared, url_changed, extract_new_content, get_element_url
from nav_v8.llm_popup_dismiss import dismiss_popups_with_llm


async def smart_interact(url: str, role: str, name: str):
    """
    Smart interaction: try hover first, then click.
    """
    print(f"\n{'='*70}")
    print(f"SMART INTERACT TEST")
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

        # Dismiss popups with LLM
        print("[2] LLM popup dismissal...")
        dismissed = await dismiss_popups_with_llm(page)
        print(f"    Total dismissed: {dismissed} popup(s)")

        # Capture baseline ARIA
        print("[3] Capturing baseline ARIA...")
        aria_baseline = await page.locator('body').aria_snapshot()
        print(f"    {len(aria_baseline.splitlines())} lines")

        # Find element
        print(f"\n[4] Finding element: {role} \"{name}\"...")
        locator = page.get_by_role(role, name=name, exact=False)
        count = await locator.count()

        if count == 0:
            locator = page.get_by_role(role, name=re.compile(name, re.IGNORECASE))
            count = await locator.count()

        if count == 0:
            print("    ERROR: Element not found!")
            return

        element = locator.first
        print(f"    Found {count} match(es), using first")

        # Check if this link has a URL (for later use)
        element_url = None
        if role == "link":
            element_url = get_element_url(aria_baseline, name)
            if element_url:
                print(f"    Link has URL: {element_url}")

        # =====================================================================
        # STEP 1: TRY HOVER
        # =====================================================================
        print(f"\n[5] HOVER...")
        await element.hover()
        await page.wait_for_timeout(1000)

        aria_after_hover = await page.locator('body').aria_snapshot()
        url_after_hover = page.url

        # Check results
        appeared, reason = menu_appeared(aria_baseline, aria_after_hover, name)

        if appeared:
            print(f"    ✓ MENU APPEARED on hover! ({reason})")
            new_lines = extract_new_content(aria_baseline, aria_after_hover)
            print(f"    New content ({len(new_lines)} lines):")
            for line in new_lines[:15]:
                print(f"      {line}")
            if len(new_lines) > 15:
                print(f"      ... and {len(new_lines) - 15} more")

            print(f"\n{'='*70}")
            print("RESULT: HOVER worked - menu revealed")
            print(f"{'='*70}")
            await page.wait_for_timeout(3000)
            return

        if url_changed(url_initial, url_after_hover):
            print(f"    ✗ URL changed on hover (unexpected)")
            print(f"      Before: {url_initial}")
            print(f"      After:  {url_after_hover}")
            return

        print(f"    No change on hover")

        # =====================================================================
        # STEP 2: TRY CLICK (or navigate directly for links with URLs)
        # =====================================================================

        if element_url:
            # For links with URLs, navigate directly instead of clicking
            print(f"\n[6] NAVIGATE (link has URL)...")

            # Build full URL if relative
            if element_url.startswith('/'):
                from urllib.parse import urljoin
                full_url = urljoin(url_initial, element_url)
            else:
                full_url = element_url

            print(f"    Going to: {full_url}")
            await page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
        else:
            # For buttons/tabs, click
            print(f"\n[6] CLICK...")
            element = page.get_by_role(role, name=name, exact=False).first
            await element.click()
            await page.wait_for_timeout(1500)

        aria_after_click = await page.locator('body').aria_snapshot()
        url_after_click = page.url

        # Check if we navigated
        if url_changed(url_initial, url_after_click):
            print(f"    → NAVIGATED to different page")
            print(f"      Before: {url_initial}")
            print(f"      After:  {url_after_click}")

            print(f"\n{'='*70}")
            print("RESULT: CLICK navigated away - not a dropdown menu")
            print(f"{'='*70}")
            await page.wait_for_timeout(3000)
            return

        # Check if menu appeared
        appeared, reason = menu_appeared(aria_baseline, aria_after_click, name)

        if appeared:
            print(f"    ✓ MENU APPEARED on click! ({reason})")
            new_lines = extract_new_content(aria_baseline, aria_after_click)
            print(f"    New content ({len(new_lines)} lines):")
            for line in new_lines[:15]:
                print(f"      {line}")
            if len(new_lines) > 15:
                print(f"      ... and {len(new_lines) - 15} more")

            print(f"\n{'='*70}")
            print("RESULT: CLICK worked - menu revealed")
            print(f"{'='*70}")
            await page.wait_for_timeout(3000)
            return

        print(f"    No change on click either")

        print(f"\n{'='*70}")
        print("RESULT: Neither hover nor click revealed a menu")
        print(f"{'='*70}")
        await page.wait_for_timeout(3000)

    finally:
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    role = sys.argv[2]
    name = sys.argv[3]

    await smart_interact(url, role, name)


if __name__ == "__main__":
    asyncio.run(main())
