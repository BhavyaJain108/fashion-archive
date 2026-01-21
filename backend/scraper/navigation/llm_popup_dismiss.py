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
load_dotenv(Path(__file__).parent.parent.parent.parent / 'config' / '.env')

from anthropic import Anthropic
from playwright.async_api import async_playwright, Page


client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))


async def ask_llm_for_popup(page: Page) -> dict | None:
    """
    Ask LLM if there's a popup and how to dismiss it.
    Returns ONE popup at a time - the highest priority one.

    Returns:
        dict with 'role' and 'name' of element to click, or None if no popup
    """
    screenshot = await page.screenshot()
    screenshot_b64 = base64.standard_b64encode(screenshot).decode('utf-8')
    aria = await page.locator('body').aria_snapshot()

    prompt = """Look at this webpage. Is there a popup, modal, cookie banner, or overlay blocking the main content?

If NO popup, respond: NONE

If YES, tell me the SINGLE most important one to dismiss first:
POPUP: <role> "<exact button text>"

Priority (what to dismiss first):
1. Cookie consent → "Accept All Cookies", "Accept All", "Allow All"
2. Newsletter/email signup → "Close", "X", "No thanks", "Maybe later"
3. Discount/promo code popup → "Close", "X", "No thanks", "Continue without"
4. Free gift/giveaway popup → "Close", "X", "No thanks", "Skip"
5. Spin-to-win/wheel popup → "Close", "X", "No thanks"
6. Country/region selector → "Continue", "Confirm", "Stay on site"
7. Age verification → "Yes", "I am over 18", "Enter"
8. Welcome/first-time visitor → "Close", "X", "Continue shopping"

Things that are NOT popups (never dismiss):
- "Close menu" / navigation controls
- Search/cart close buttons
- Menu-related controls
- Product quick-view modals
- Size guides

CRITICAL: "Close menu" is NEVER a popup.

ARIA Snapshot:
""" + aria[:8000]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    )

    result = response.content[0].text.strip()
    print(f"    LLM: {result}")

    if "none" in result.lower():
        return None

    import re
    match = re.search(r'POPUP:\s*(button|link)\s*["\']([^"\']+)["\']', result, re.IGNORECASE)
    if match:
        role, name = match.groups()
        return {"role": role.lower(), "name": name}

    return None


async def try_direct_popup_selectors(page: Page) -> int:
    """
    Try common popup selectors directly (faster than LLM, catches non-ARIA popups).
    Returns number dismissed.
    """
    from navigation.popup_selectors import POPUP_CLOSE_SELECTORS, POPUP_IFRAME_SELECTORS

    dismissed = 0
    selectors = POPUP_CLOSE_SELECTORS + POPUP_IFRAME_SELECTORS

    for sel in selectors:
        try:
            # Special handling for iframes - hide them
            if 'iframe' in sel:
                iframe = page.locator(sel)
                if await iframe.count() > 0 and await iframe.is_visible():
                    await page.evaluate(f'document.querySelector(\'{sel}\')?.parentElement?.remove()')
                    print(f"    [DIRECT] Removed iframe: {sel}")
                    dismissed += 1
                continue

            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click(timeout=2000)
                await page.wait_for_timeout(300)
                print(f"    [DIRECT] Clicked: {sel}")
                dismissed += 1
        except:
            continue

    return dismissed


async def remove_overlay_elements(page: Page) -> int:
    """
    Remove known popup/overlay elements from DOM entirely.
    This ensures they can't intercept clicks even if hidden.

    Returns number of elements removed.
    """
    from navigation.popup_selectors import OVERLAY_REMOVAL_SELECTORS

    removed = 0
    for selector in OVERLAY_REMOVAL_SELECTORS:
        try:
            count = await page.evaluate(f"""
                (() => {{
                    const els = document.querySelectorAll('{selector}');
                    const count = els.length;
                    els.forEach(el => el.remove());
                    return count;
                }})()
            """)
            if count > 0:
                print(f"    [DOM] Removed {count} elements: {selector}")
                removed += count
        except:
            continue

    return removed


async def dismiss_popups_with_llm(page: Page, max_attempts: int = 1) -> int:
    """
    Dismiss popups - first try direct selectors, then LLM fallback.

    Args:
        page: Playwright page
        max_attempts: Max LLM attempts (direct selectors don't count)

    Returns:
        Number of popups dismissed
    """
    dismissed = 0

    # First: try direct selectors (fast, catches non-ARIA popups)
    print("  [Direct popup check]")
    direct_dismissed = await try_direct_popup_selectors(page)
    dismissed += direct_dismissed
    if direct_dismissed > 0:
        await page.wait_for_timeout(500)

    # Then: LLM fallback for anything we missed
    for attempt in range(max_attempts):
        print(f"  [LLM check {attempt + 1}/{max_attempts}]")

        popup = await ask_llm_for_popup(page)

        if popup is None:
            print(f"    No popup")
            break

        role, name = popup["role"], popup["name"]
        print(f"    Dismissing: {role} \"{name}\"")

        try:
            locator = page.get_by_role(role, name=name, exact=False)
            if await locator.count() > 0:
                await locator.first.click(timeout=3000)
                dismissed += 1
                print(f"    ✓ Dismissed")
                await page.wait_for_timeout(300)
            else:
                print(f"    ✗ Not found")
                break
        except Exception as e:
            print(f"    ✗ Skip")
            break

    # Finally: remove overlay elements from DOM entirely
    # This ensures they can't intercept clicks even if hidden
    print("  [DOM removal]")
    removed = await remove_overlay_elements(page)
    if removed > 0:
        await page.wait_for_timeout(300)

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
