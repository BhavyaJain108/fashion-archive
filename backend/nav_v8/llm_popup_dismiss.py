"""
LLM-based popup dismissal.

Uses Claude to identify and dismiss popups/modals/overlays.
"""

import asyncio
import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / 'config' / '.env')

from anthropic import Anthropic
from playwright.async_api import async_playwright, Page


client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))


async def ask_llm_for_popup(page: Page) -> dict | None:
    """
    Ask LLM if there's a popup and how to dismiss it.

    Returns:
        dict with 'role' and 'name' of element to click, or None if no popup
    """
    # Get screenshot and ARIA
    screenshot = await page.screenshot()
    screenshot_b64 = base64.standard_b64encode(screenshot).decode('utf-8')
    aria = await page.locator('body').aria_snapshot()

    prompt = """Look at this webpage. Is there a popup, modal, cookie banner, or overlay blocking the main content?

If YES, tell me what element to click to dismiss/close it.
If NO, say "no popup".

Respond in this EXACT format (no other text):

POPUP: yes/no
ROLE: button/link (only if yes)
NAME: exact text of the element to click (only if yes)

Examples of POPUPS (should dismiss):
- Cookie banner with "Accept All" button
- Newsletter signup modal
- Location/country selector overlay
- Welcome modal, age gate, promo popup
- "Continue without accepting" for privacy

Examples of things that are NOT POPUPS (never dismiss):
- "Close menu" / "Close Menu" - this is navigation, not a popup
- "Open menu" / "Menu" / "Navigation" - navigation controls
- "Close" button that's part of the main navigation header
- Search close buttons
- Cart/bag close buttons
- Any menu-related controls (hamburger menu, nav menu, etc.)

CRITICAL RULE: If you see "Close menu" or similar menu controls, that is NOT a popup.
Navigation menus are NEVER popups even if they have close buttons.

ARIA Snapshot:
""" + aria[:8000]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    )

    result = response.content[0].text.strip()
    print(f"    LLM response:\n{result}")

    # Parse response
    if "popup: no" in result.lower():
        return None

    if "popup: yes" in result.lower():
        lines = result.split('\n')
        role = None
        name = None
        for line in lines:
            line = line.strip()
            if line.upper().startswith("ROLE:"):
                role = line.split(":", 1)[1].strip().lower()
            if line.upper().startswith("NAME:"):
                name = line.split(":", 1)[1].strip()

        print(f"    Parsed: role={role}, name={name}")

        if role and name:
            return {"role": role, "name": name}

    return None


async def dismiss_popups_with_llm(page: Page, max_attempts: int = 3) -> int:
    """
    Use LLM to identify and dismiss popups.

    Args:
        page: Playwright page
        max_attempts: Maximum number of popups to try dismissing

    Returns:
        Number of popups dismissed
    """
    dismissed = 0

    for attempt in range(max_attempts):
        print(f"  [Popup check {attempt + 1}/{max_attempts}]")

        popup_info = await ask_llm_for_popup(page)

        if popup_info is None:
            print(f"    No popup detected")
            break

        role = popup_info["role"]
        name = popup_info["name"]
        print(f"    Found popup - clicking {role} \"{name}\"")

        try:
            # Try to find and click the element
            locator = page.get_by_role(role, name=name, exact=False)
            if await locator.count() > 0:
                await locator.first.click()
                await page.wait_for_timeout(1000)
                dismissed += 1
                print(f"    ✓ Dismissed")
            else:
                print(f"    ✗ Element not found")
                break
        except Exception as e:
            print(f"    ✗ Error: {e}")
            break

    return dismissed


async def test_popup_dismiss(url: str):
    """Test LLM popup dismissal on a URL"""

    print(f"\n{'='*70}")
    print(f"LLM POPUP DISMISSAL TEST")
    print(f"URL: {url}")
    print(f"{'='*70}\n")

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()

    try:
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        print("\n[2] Checking for popups with LLM...")
        dismissed = await dismiss_popups_with_llm(page)

        print(f"\n{'='*70}")
        print(f"RESULT: Dismissed {dismissed} popup(s)")
        print(f"{'='*70}")

        # Show final ARIA
        aria = await page.locator('body').aria_snapshot()
        print(f"\nFinal ARIA ({len(aria.splitlines())} lines):")
        print("-" * 40)
        for line in aria.splitlines()[:30]:
            print(line)

        await page.wait_for_timeout(3000)

    finally:
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python llm_popup_dismiss.py <url>")
        sys.exit(1)

    await test_popup_dismiss(sys.argv[1])


if __name__ == "__main__":
    asyncio.run(main())
