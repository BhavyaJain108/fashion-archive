"""
LLM-based navigation discovery.

Uses Claude to identify navigation entry points from ARIA snapshot + screenshot.
"""

import base64
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / 'config' / '.env')

from anthropic import Anthropic
from playwright.async_api import Page


client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))


async def ask_llm_for_nav_entry(page: Page) -> dict | None:
    """
    Ask LLM to identify the navigation entry point.

    Returns:
        dict with 'role' and 'name' of element to interact with, or None
    """
    screenshot = await page.screenshot()
    screenshot_b64 = base64.standard_b64encode(screenshot).decode('utf-8')
    aria = await page.locator('body').aria_snapshot()

    prompt = """Look at this e-commerce/fashion website. I need to discover its product category navigation.

Find the MAIN navigation entry point - this could be:
- A hamburger menu button that reveals the full navigation
- A "Shop" or "Menu" button that opens category navigation
- Top-level category buttons (like "Women", "Men") if the nav is already visible

I want to find what will reveal the PRODUCT CATEGORIES (clothing, shoes, bags, etc.)

Respond in this EXACT format:
ENTRY_FOUND: yes/no
ROLE: button/link/tab (only if yes)
NAME: exact text of the element (only if yes)
REASON: brief explanation of why this is the entry point (only if yes)

Examples:
- Site with hamburger menu:
  ENTRY_FOUND: yes
  ROLE: button
  NAME: menu toggle
  REASON: hamburger menu will reveal full navigation

- Site with visible nav buttons:
  ENTRY_FOUND: yes
  ROLE: button
  NAME: Women
  REASON: top-level category button, will reveal subcategories

- Site where nav is already fully visible as links:
  ENTRY_FOUND: no
  REASON: navigation categories are already visible as direct links

ARIA Snapshot:
""" + aria[:10000]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    )

    result = response.content[0].text.strip()
    print(f"    LLM nav discovery response:\n{result}")

    # Parse response
    if "entry_found: no" in result.lower():
        return None

    if "entry_found: yes" in result.lower():
        lines = result.split('\n')
        role = None
        name = None
        for line in lines:
            line = line.strip()
            if line.upper().startswith("ROLE:"):
                role = line.split(":", 1)[1].strip().lower()
            if line.upper().startswith("NAME:"):
                name = line.split(":", 1)[1].strip()

        if role and name:
            return {"role": role, "name": name}

    return None
