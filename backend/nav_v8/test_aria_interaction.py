"""
Test ARIA-based element interaction reliability.

This script:
1. Loads a page
2. Dismisses popups
3. Captures ARIA snapshot
4. Attempts to find and interact with elements using get_by_role()
5. Reports what changed after interaction

Usage:
  python test_aria_interaction.py <url> <role> <name> [hover|click]

Examples:
  python test_aria_interaction.py "https://www.acnestudios.com" button "Woman" hover
  python test_aria_interaction.py "https://www.zara.com/us/" button "Open Menu" click
"""

import asyncio
import sys
import re
from pathlib import Path
from playwright.async_api import async_playwright

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from nav_v5.popup_blocker import PopupBlocker


async def test_interaction(url: str, role: str, name: str, action: str = "hover"):
    """
    Test finding and interacting with an element.

    Args:
        url: Page URL
        role: ARIA role (button, tab, link, etc.)
        name: Element name/label
        action: "hover" or "click"
    """
    print(f"\n{'='*70}")
    print(f"URL: {url}")
    print(f"Target: {role} \"{name}\"")
    print(f"Action: {action}")
    print(f"{'='*70}\n")

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()

    try:
        # Load page
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        # Dismiss popups
        print("[2] Dismissing popups...")
        dismissed = await PopupBlocker.dismiss_all(page, verbose=True)
        if dismissed:
            await page.wait_for_timeout(500)
        print(f"    Dismissed {dismissed} popup(s)")

        # Capture ARIA before
        print("[3] Capturing ARIA snapshot BEFORE interaction...")
        aria_before = await page.locator('body').aria_snapshot()
        lines_before = len(aria_before.splitlines())
        print(f"    Snapshot: {lines_before} lines, {len(aria_before)} chars")

        # Try to find the element
        print(f"\n[4] Finding element: {role} \"{name}\"...")

        # Try exact match first
        locator = page.get_by_role(role, name=name, exact=True)
        count = await locator.count()

        if count == 0:
            # Try non-exact match
            print(f"    Exact match not found, trying flexible match...")
            locator = page.get_by_role(role, name=name, exact=False)
            count = await locator.count()

        if count == 0:
            # Try regex (case insensitive)
            print(f"    Flexible match not found, trying regex...")
            locator = page.get_by_role(role, name=re.compile(name, re.IGNORECASE))
            count = await locator.count()

        print(f"    Found {count} matching element(s)")

        if count == 0:
            print("\n[ERROR] Element not found!")
            print("\nARIA snapshot (first 100 lines):")
            print("-" * 50)
            for line in aria_before.splitlines()[:100]:
                print(line)
            return

        # Use first match
        element = locator.first

        # Check visibility
        is_visible = await element.is_visible()
        print(f"    Visible: {is_visible}")

        if not is_visible:
            print("\n[ERROR] Element found but not visible!")
            return

        # Perform interaction
        print(f"\n[5] Performing {action}...")

        if action == "hover":
            await element.hover()
            await page.wait_for_timeout(1000)  # Wait for hover effects
        elif action == "click":
            await element.click()
            await page.wait_for_timeout(1500)  # Wait for click effects
        else:
            print(f"[ERROR] Unknown action: {action}")
            return

        print(f"    {action.capitalize()} completed")

        # Capture ARIA after
        print("\n[6] Capturing ARIA snapshot AFTER interaction...")
        aria_after = await page.locator('body').aria_snapshot()
        lines_after = len(aria_after.splitlines())
        print(f"    Snapshot: {lines_after} lines, {len(aria_after)} chars")

        # Compare
        print("\n[7] Comparison:")
        print(f"    Lines before: {lines_before}")
        print(f"    Lines after:  {lines_after}")
        print(f"    Difference:   {lines_after - lines_before:+d} lines")

        changed = aria_before != aria_after
        print(f"    Content changed: {changed}")

        if changed:
            # Show what's new
            lines_before_set = set(aria_before.splitlines())
            lines_after_list = aria_after.splitlines()
            new_lines = [l for l in lines_after_list if l not in lines_before_set]

            if new_lines:
                print(f"\n[8] NEW content after {action} (first 30 lines):")
                print("-" * 50)
                for line in new_lines[:30]:
                    print(line)
                if len(new_lines) > 30:
                    print(f"    ... and {len(new_lines) - 30} more new lines")
        else:
            print(f"\n[8] No change detected after {action}")

        # Keep browser open briefly for visual confirmation
        print("\n" + "=" * 70)
        print("Waiting 3 seconds for visual confirmation...")
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
    action = sys.argv[4] if len(sys.argv) > 4 else "hover"

    await test_interaction(url, role, name, action)


if __name__ == "__main__":
    asyncio.run(main())
