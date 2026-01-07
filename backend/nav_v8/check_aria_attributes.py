"""
Check what ARIA attributes are actually on elements vs what the snapshot shows.
"""

import asyncio
import sys
from playwright.async_api import async_playwright


async def check_aria(url: str, role: str, name: str):
    """Check full ARIA attributes on an element"""

    print(f"\n{'='*70}")
    print(f"Checking ARIA attributes for: {role} \"{name}\"")
    print(f"URL: {url}")
    print(f"{'='*70}\n")

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        # Get all ARIA attributes from the element
        aria_info = await page.evaluate(f"""
            () => {{
                // Find element by role and name
                const elements = document.querySelectorAll('[role="{role}"]');
                for (const el of elements) {{
                    const accessibleName = el.getAttribute('aria-label') || el.textContent.trim();
                    if (accessibleName.includes("{name}")) {{
                        return {{
                            tagName: el.tagName,
                            role: el.getAttribute('role'),
                            ariaLabel: el.getAttribute('aria-label'),
                            ariaExpanded: el.getAttribute('aria-expanded'),
                            ariaHaspopup: el.getAttribute('aria-haspopup'),
                            ariaPressed: el.getAttribute('aria-pressed'),
                            ariaControls: el.getAttribute('aria-controls'),
                            ariaSelected: el.getAttribute('aria-selected'),
                            ariaDisabled: el.getAttribute('aria-disabled'),
                            textContent: el.textContent.trim().substring(0, 50),
                            allAttributes: Array.from(el.attributes).map(a => ({{name: a.name, value: a.value}}))
                        }};
                    }}
                }}

                // Also try native buttons
                const buttons = document.querySelectorAll('button');
                for (const el of buttons) {{
                    if (el.textContent.trim().includes("{name}")) {{
                        return {{
                            tagName: el.tagName,
                            role: el.getAttribute('role') || 'button (native)',
                            ariaLabel: el.getAttribute('aria-label'),
                            ariaExpanded: el.getAttribute('aria-expanded'),
                            ariaHaspopup: el.getAttribute('aria-haspopup'),
                            ariaPressed: el.getAttribute('aria-pressed'),
                            ariaControls: el.getAttribute('aria-controls'),
                            ariaSelected: el.getAttribute('aria-selected'),
                            ariaDisabled: el.getAttribute('aria-disabled'),
                            textContent: el.textContent.trim().substring(0, 50),
                            allAttributes: Array.from(el.attributes).map(a => ({{name: a.name, value: a.value}}))
                        }};
                    }}
                }}

                return null;
            }}
        """)

        if aria_info:
            print("Element found!\n")
            print(f"Tag: {aria_info['tagName']}")
            print(f"Role: {aria_info['role']}")
            print(f"Text: {aria_info['textContent']}")
            print()
            print("ARIA Attributes:")
            print(f"  aria-expanded: {aria_info['ariaExpanded']}")
            print(f"  aria-haspopup: {aria_info['ariaHaspopup']}")
            print(f"  aria-pressed: {aria_info['ariaPressed']}")
            print(f"  aria-controls: {aria_info['ariaControls']}")
            print(f"  aria-selected: {aria_info['ariaSelected']}")
            print(f"  aria-disabled: {aria_info['ariaDisabled']}")
            print()
            print("All attributes:")
            for attr in aria_info['allAttributes']:
                print(f"  {attr['name']}: {attr['value'][:80] if len(attr['value']) > 80 else attr['value']}")
        else:
            print("Element not found!")

        await page.wait_for_timeout(2000)

    finally:
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 4:
        print("Usage: python check_aria_attributes.py <url> <role> <name>")
        sys.exit(1)

    await check_aria(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    asyncio.run(main())
