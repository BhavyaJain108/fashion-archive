"""
Dump all buttons on a page with their ARIA attributes.
"""

import asyncio
import sys
from playwright.async_api import async_playwright


async def dump_buttons(url: str):
    """List all buttons with their ARIA attributes"""

    print(f"\nURL: {url}\n")
    print("="*80)

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        buttons = await page.evaluate("""
            () => {
                const results = [];

                // Native buttons
                document.querySelectorAll('button').forEach(el => {
                    results.push({
                        type: 'native button',
                        text: el.textContent.trim().substring(0, 40),
                        ariaLabel: el.getAttribute('aria-label'),
                        ariaExpanded: el.getAttribute('aria-expanded'),
                        ariaHaspopup: el.getAttribute('aria-haspopup'),
                        ariaControls: el.getAttribute('aria-controls'),
                    });
                });

                // Elements with role="button"
                document.querySelectorAll('[role="button"]').forEach(el => {
                    results.push({
                        type: 'role=button',
                        text: el.textContent.trim().substring(0, 40),
                        ariaLabel: el.getAttribute('aria-label'),
                        ariaExpanded: el.getAttribute('aria-expanded'),
                        ariaHaspopup: el.getAttribute('aria-haspopup'),
                        ariaControls: el.getAttribute('aria-controls'),
                    });
                });

                return results;
            }
        """)

        print(f"Found {len(buttons)} buttons:\n")

        for i, btn in enumerate(buttons[:30]):  # First 30
            name = btn['ariaLabel'] or btn['text'] or '(no name)'
            expanded = btn['ariaExpanded']
            haspopup = btn['ariaHaspopup']
            controls = btn['ariaControls']

            flags = []
            if expanded: flags.append(f"expanded={expanded}")
            if haspopup: flags.append(f"haspopup={haspopup}")
            if controls: flags.append(f"controls={controls[:30]}")

            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"{i+1}. [{btn['type']}] \"{name}\"{flag_str}")

        if len(buttons) > 30:
            print(f"\n... and {len(buttons) - 30} more")

        await page.wait_for_timeout(2000)

    finally:
        await browser.close()
        await playwright.stop()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python dump_buttons.py <url>")
        sys.exit(1)

    await dump_buttons(sys.argv[1])


if __name__ == "__main__":
    asyncio.run(main())
