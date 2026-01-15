"""
Deterministic Navigation Extractor

Reads method_summary.json for each brand and extracts the full navigation tree.
No LLM needed at runtime.

Supports three extraction methods (in priority order):
1. API: Fetch JSON from API endpoint and parse
2. Embedded JSON: Extract from __NEXT_DATA__ or similar
3. DOM: Use Playwright to interact with page and run extraction script

Expected output structure:
{
  brand: string,
  extracted_at: ISO timestamp,
  url: string,
  method: string,
  tree: [{
    name: string,
    url: string | null,
    children: [recursive]
  }],
  stats: { total_categories, max_depth }
}
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import httpx

from playwright.async_api import async_playwright

# Try to import stealth, but make it optional
try:
    from undetected_playwright import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

EXTRACTIONS_DIR = Path(__file__).parent / "extractions"

# Standard viewport - must match what discovery agent uses
VIEWPORT = {"width": 1280, "height": 800}


def calculate_stats(tree, depth=1):
    """Calculate tree statistics"""
    count = len(tree)
    max_depth = depth

    for node in tree:
        if node.get("children") and len(node["children"]) > 0:
            child_stats = calculate_stats(node["children"], depth + 1)
            count += child_stats["total"]
            max_depth = max(max_depth, child_stats["max_depth"])

    return {"total": count, "max_depth": max_depth}


async def extract_via_api(method_data: dict, browser=None) -> list:
    """Extract navigation via API endpoint

    The api_parser is a JavaScript function that transforms the API response
    into our standard format: [{name, url, children}]

    If browser is provided, we execute the parser in the browser context.
    Otherwise, we use a simple Python fallback for common patterns.
    """
    api_endpoint = method_data.get("api_endpoint", "")
    api_parser = method_data.get("api_parser", "")
    base_url = method_data.get("url", "")

    if not api_endpoint:
        raise ValueError("No api_endpoint specified")

    # Build full URL
    if api_endpoint.startswith("/"):
        full_url = urljoin(base_url, api_endpoint)
    else:
        full_url = api_endpoint

    print(f"  Fetching API: {full_url}")

    # Fetch the API
    async with httpx.AsyncClient() as client:
        response = await client.get(
            full_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
            },
            follow_redirects=True,
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json()

    # If we have a parser function and browser, execute it in browser context
    if api_parser and browser:
        print(f"  Running api_parser in browser context...")
        context = await browser.new_context()
        page = await context.new_page()
        try:
            # Extract the function name from the parser code
            import re
            func_match = re.search(r'function\s+(\w+)', api_parser)
            func_name = func_match.group(1) if func_match else "parseNavigation"

            # Execute the parser with the data
            js_code = f"""
            (data) => {{
                {api_parser}
                return {func_name}(data);
            }}
            """
            tree = await page.evaluate(js_code, data)
            return tree
        finally:
            await context.close()

    # Fallback: Try to parse using generic Python logic
    print(f"  Using generic Python parser (no api_parser provided)")
    return parse_generic_api_response(data)


def parse_generic_api_response(data) -> list:
    """Generic parser that tries to extract navigation from common API formats"""
    tree = []

    # Handle dict with common keys
    if isinstance(data, dict):
        # Look for navigation-like keys
        for key in ["categories", "navigation", "menu", "items", "data"]:
            if key in data and isinstance(data[key], list):
                return parse_category_array(data[key])

        # If it looks like a single category, wrap it
        if "name" in data or "title" in data:
            return [parse_single_category(data)]

    # Handle array directly
    elif isinstance(data, list):
        return parse_category_array(data)

    return tree


def parse_single_category(cat: dict) -> dict:
    """Parse a single category object into our standard format"""
    node = {
        "name": cat.get("name") or cat.get("title") or cat.get("label") or "Unknown",
        "url": cat.get("url") or cat.get("href") or cat.get("link") or cat.get("seo", {}).get("url"),
        "children": []
    }

    # Check for nested children under various keys
    for key in ["children", "subcategories", "items", "subItems", "subCategories"]:
        if key in cat and isinstance(cat[key], list):
            node["children"] = parse_category_array(cat[key])
            break

    return node


def parse_category_array(categories: list) -> list:
    """Parse an array of category objects"""
    tree = []

    for cat in categories:
        if isinstance(cat, dict):
            tree.append(parse_single_category(cat))
        elif isinstance(cat, str):
            tree.append({"name": cat, "url": None, "children": []})

    return tree


async def dismiss_cookie_popups(page):
    """Try to dismiss common cookie consent popups"""
    cookie_selectors = [
        'button:has-text("Accept")',
        'button:has-text("Accept All")',
        'button:has-text("Accept Cookies")',
        'button:has-text("ACCEPT ALL COOKIES")',
        '[data-testid="cookie-accept"]',
        '#onetrust-accept-btn-handler',
    ]

    for selector in cookie_selectors:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await page.wait_for_timeout(500)
                return True
        except:
            continue
    return False


async def execute_pre_extraction_actions(page, actions: list):
    """Execute pre-extraction actions (hover, click, navigate) to reveal navigation"""
    if not actions:
        return

    for action_def in actions:
        action_type = action_def.get("action")

        # Handle navigate action (doesn't need selector)
        if action_type == "navigate":
            url = action_def.get("url")
            if url:
                print(f"    Navigating to: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(2000)
            else:
                print(f"    Warning: Navigate action missing url")
            continue

        # All other actions need a selector
        selector = action_def.get("selector")
        if not selector:
            print(f"    Warning: Invalid action (missing selector): {action_def}")
            continue

        try:
            element = page.locator(selector).first

            # Check if element exists
            if not await element.count():
                print(f"    Warning: Selector not found: {selector}")
                continue

            if action_type == "hover":
                print(f"    Hovering: {selector}")
                await element.hover(timeout=5000)
                await page.wait_for_timeout(800)
            elif action_type == "click":
                print(f"    Clicking: {selector}")
                await element.click(timeout=5000)
                await page.wait_for_timeout(500)
            else:
                print(f"    Warning: Unknown action: {action_type}")

        except Exception as e:
            print(f"    Warning: Action failed - {action_type} on {selector}: {e}")


async def extract_via_dom(page, method_data: dict) -> list:
    """Extract navigation via DOM script with Playwright"""
    url = method_data["url"]
    extraction_script = method_data.get("extraction_script", "")
    pre_actions = method_data.get("pre_extraction_actions", [])

    if not extraction_script:
        raise ValueError("No extraction_script specified for DOM method")

    print(f"  Navigating to: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)

    # Dismiss cookie popups
    await dismiss_cookie_popups(page)
    await page.wait_for_timeout(500)

    # Execute pre-extraction actions
    if pre_actions:
        print(f"  Executing {len(pre_actions)} pre-extraction action(s)...")
        await execute_pre_extraction_actions(page, pre_actions)

    # Run extraction script
    print(f"  Running extraction script...")
    tree = await page.evaluate(f"() => {{ {extraction_script}; return extractNavigation(); }}")

    return tree


async def extract_brand(brand_dir: Path, browser=None) -> dict:
    """Extract navigation for a single brand"""
    method_path = brand_dir / "method_summary.json"
    output_path = brand_dir / "navigation_tree.json"

    with open(method_path) as f:
        method_data = json.load(f)

    brand = method_data["brand"]
    url = method_data["url"]
    method = method_data.get("method", "dom")

    print(f"\nExtracting {brand}...")
    print(f"  Method: {method}")
    print(f"  URL: {url}")

    tree = []

    if method == "api":
        # API extraction - browser optional (for running custom api_parser)
        tree = await extract_via_api(method_data, browser)

    elif method == "embedded_json":
        # Embedded JSON - need browser to load page and extract
        if not browser:
            raise ValueError("Browser required for embedded_json method")
        # TODO: Implement embedded JSON extraction
        raise NotImplementedError("embedded_json method not yet implemented")

    elif method in ("dom", "script"):
        # DOM extraction - need browser
        if not browser:
            raise ValueError("Browser required for DOM method")

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport=VIEWPORT
        )
        page = await context.new_page()

        if HAS_STEALTH:
            await stealth_async(page)

        try:
            tree = await extract_via_dom(page, method_data)
        finally:
            await context.close()

    else:
        raise ValueError(f"Unknown method: {method}")

    # Calculate stats
    stats = calculate_stats(tree)

    # Build output
    output = {
        "brand": brand,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "method": method,
        "tree": tree,
        "stats": {
            "total_categories": stats["total"],
            "max_depth": stats["max_depth"]
        }
    }

    # Save
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"  ✓ Extracted {stats['total']} categories (depth: {stats['max_depth']})")
    print(f"  ✓ Saved to {output_path}")

    return output


async def main():
    args = sys.argv[1:]
    specific_brand = None
    headless = "--headless" in args or "-h" in args

    # Get brand name if provided
    for arg in args:
        if not arg.startswith("-"):
            specific_brand = arg
            break

    print("=== Navigation Tree Extractor ===\n")

    # Find brands with method_summary.json
    valid_brands = []
    for brand_dir in EXTRACTIONS_DIR.iterdir():
        if not brand_dir.is_dir():
            continue
        method_path = brand_dir / "method_summary.json"
        if method_path.exists():
            brand_name = brand_dir.name
            if specific_brand and brand_name != specific_brand:
                continue
            valid_brands.append(brand_name)

    if not valid_brands:
        print("No brands found to extract")
        return

    print(f"Found {len(valid_brands)} brand(s): {', '.join(valid_brands)}")
    print(f"Headless: {headless}")

    # Check which methods we need
    needs_browser = False
    for brand in valid_brands:
        method_path = EXTRACTIONS_DIR / brand / "method_summary.json"
        with open(method_path) as f:
            method_data = json.load(f)
            method = method_data.get("method", "dom")
            has_api_parser = bool(method_data.get("api_parser"))
        # Need browser for DOM methods, or API method with custom parser
        if method in ("dom", "script", "embedded_json") or (method == "api" and has_api_parser):
            needs_browser = True
            break

    results = {"success": [], "failed": []}
    browser = None

    try:
        # Launch browser only if needed
        if needs_browser:
            print("\nLaunching browser...")
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=headless)

        # Extract each brand
        for brand in valid_brands:
            brand_dir = EXTRACTIONS_DIR / brand
            try:
                await extract_brand(brand_dir, browser)
                results["success"].append(brand)
            except Exception as e:
                print(f"  ✗ Failed: {e}")
                import traceback
                traceback.print_exc()
                results["failed"].append({"brand": brand, "error": str(e)})

    finally:
        if browser:
            await browser.close()
            await playwright.stop()

    # Summary
    print("\n=== Summary ===")
    print(f"Success: {len(results['success'])} ({', '.join(results['success'])})")
    print(f"Failed: {len(results['failed'])}")
    for f in results["failed"]:
        print(f"  - {f['brand']}: {f['error']}")


if __name__ == "__main__":
    asyncio.run(main())
