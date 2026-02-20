"""
Static link extractor for sites where all nav links are already in DOM.
No clicking needed - just dump all links to LLM to organize into tree.
"""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent / 'config' / '.env')

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scraper.navigation.llm_popup_dismiss import dismiss_popups_with_llm
from scraper.llm_handler import LLMHandler, LLMUsageTracker

# Import hamburger detection from dynamic explorer
from scraper.navigation.dynamic_explorer import open_menu

# Match viewport with dynamic explorer (triggers hamburger menus)
VIEWPORT = {'width': 768, 'height': 900}


async def get_nav_links_with_structure(page) -> str:
    """
    Extract all links from DOM with depth indentation to preserve structure.
    """
    script = """
    () => {
        const allLinks = document.querySelectorAll('a[href]');
        const links = [];
        const seen = new Set();

        // Get depth of element in DOM (count parent elements)
        function getDepth(el) {
            let depth = 0;
            let parent = el.parentElement;
            while (parent && parent !== document.body) {
                depth++;
                parent = parent.parentElement;
            }
            return depth;
        }

        // Find min depth to normalize indentation
        let minDepth = Infinity;
        allLinks.forEach(link => {
            const href = link.getAttribute('href') || '';
            const text = link.innerText.trim();
            if (text && href && href !== '#' && !href.startsWith('javascript:')) {
                minDepth = Math.min(minDepth, getDepth(link));
            }
        });

        allLinks.forEach(link => {
            const href = link.getAttribute('href') || '';
            const text = link.innerText.trim().replace(/\\n/g, ' ').replace(/\\s+/g, ' ').substring(0, 80);
            if (!text || !href || href === '#' || href.startsWith('javascript:')) return;
            const key = href + '|' + text;
            if (seen.has(key)) return;
            seen.add(key);

            // Indent based on DOM depth (normalized)
            const depth = Math.max(0, getDepth(link) - minDepth);
            const indent = '  '.repeat(Math.min(depth, 5)); // Cap at 5 levels
            links.push(indent + text + ' | ' + href);
        });

        return links.join('\\n');
    }
    """

    result = await page.evaluate(script)
    return result


def resolve_urls_in_tree(node, base_url: str):
    """Recursively resolve relative URLs to absolute URLs in the tree."""
    from urllib.parse import urljoin

    if isinstance(node, list):
        for item in node:
            resolve_urls_in_tree(item, base_url)
    elif isinstance(node, dict):
        url = node.get('url')
        if url and not url.startswith('http'):
            node['url'] = urljoin(base_url, url)
        children = node.get('children', [])
        if children:
            resolve_urls_in_tree(children, base_url)


async def extract_tree(url: str, output_dir: Path = None) -> tuple:
    """Extract navigation tree using LLM to interpret DOM structure.
    Returns (tree, links_text)
    """
    from urllib.parse import urlparse

    print(f"\n{'='*70}")
    print("STATIC NAV EXTRACTOR")
    print(f"{'='*70}")
    print(f"URL: {url}\n")

    # Setup output dir early so we can save raw links before LLM
    if output_dir is None:
        domain = urlparse(url).netloc.replace('www.', '').replace('.', '_')
        output_dir = Path(__file__).parent.parent.parent / 'extractions' / domain
    output_dir.mkdir(parents=True, exist_ok=True)

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page(viewport=VIEWPORT)
    links_text = ""
    llm_usage = {"input_tokens": 0, "output_tokens": 0}  # Initialize for tracking

    try:
        print("[1] Loading page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        print("[2] Dismissing popups...")
        await dismiss_popups_with_llm(page)

        print("[3] Opening hamburger menu if present...")
        menu_opened = await open_menu(page)
        if menu_opened:
            print("    Hamburger menu opened")
            await page.wait_for_timeout(500)
        else:
            print("    No hamburger menu found (or already open)")

        print("[4] Extracting nav links with structure...")
        links_text = await get_nav_links_with_structure(page)

        # Save raw links immediately (before LLM) for quick review
        links_file = output_dir / 'raw_links.txt'
        with open(links_file, 'w') as f:
            f.write(links_text)
        print(f"    Saved: {links_file}")

        print(f"    Found {len(links_text.split(chr(10)))} links")
        print(f"\n    First 30 lines:")
        for line in links_text.split('\n')[:30]:
            print(f"    {line}")
        if len(links_text.split('\n')) > 30:
            print(f"    ... and {len(links_text.split(chr(10))) - 30} more")

        print("\n[5] Asking LLM to build tree...")

        screenshot = await page.screenshot()
        screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')

        prompt = f"""Here are navigation links from a fashion website. Each "=== SECTION ===" header shows a top-level category, and indentation within shows hierarchy.

{links_text}

Build a JSON array of ALL shopping/product links.

SCHEMA (follow exactly):
[
  {{
    "name": "Category Name",
    "url": "/path/to/category",
    "children": [
      {{
        "name": "Subcategory",
        "url": "/path/to/subcategory",
        "children": []
      }}
    ]
  }}
]

RULES:
- Return a JSON array (not object)
- INCLUDE: Category/collection pages - this includes traditional categories (Women, Men, Shoes) AND brand-specific collection names (seasonal drops, collaborations, style names, etc.)
- INCLUDE: URLs like /collections/*, /shop/*, /category/*, /c/* (category pages)
- EXCLUDE: Individual product pages - URLs like /products/*, /product/*, /p/* that link to a SINGLE item (these have specific product names/SKUs in the URL)
- EXCLUDE: About, Contact, FAQ, Terms, Privacy, Careers, Press, Customer Service, Account, Cart, Wishlist, Search, Social media links
- KEY DISTINCTION: "/collections/tees" = category (INCLUDE), "/products/vintage-tee-12345" = single product (EXCLUDE)
- If the site has a single "Store" or "Shop" link (even to a subdomain), include it as a top-level category
- Every node MUST have: "name" (string), "url" (string or null), "children" (array, can be empty)
- IMPORTANT: Copy URLs exactly as they appear - do NOT decode URL-encoded characters like %C2%A0, %20, etc.

Respond with ONLY the JSON array, no markdown, no explanation:
"""

        # Use LLMHandler for unified tracking
        llm = LLMHandler()
        llm_response = llm.call_with_image(
            prompt=prompt,
            image_b64=screenshot_b64,
            media_type="image/png",
            max_tokens=8000,
            operation="nav_tree_extraction"
        )

        # Extract usage from response
        if llm_response.get("usage"):
            llm_usage["input_tokens"] += llm_response["usage"].get("input_tokens", 0)
            llm_usage["output_tokens"] += llm_response["usage"].get("output_tokens", 0)

        if not llm_response.get("success"):
            print(f"\n[ERROR] LLM call failed: {llm_response.get('error')}")
            return None, links_text, llm_usage

        result = llm_response.get("response", "").strip()

        # Save raw LLM response for debugging
        raw_response_file = output_dir / 'llm_response_raw.txt'
        with open(raw_response_file, 'w') as f:
            f.write(result)
        print(f"    Saved raw LLM response: {raw_response_file}")

        # Try to parse JSON
        try:
            import re

            # Find JSON in response
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]

            result = result.strip()

            # Clean up common JSON issues
            # Remove trailing commas before ] or }
            result = re.sub(r',(\s*[\]\}])', r'\1', result)
            # Fix missing commas between } and {
            result = re.sub(r'\}(\s*)\{', r'},\1{', result)
            # Fix missing commas between ] and {
            result = re.sub(r'\](\s*)\{', r'],\1{', result)
            # Fix missing commas between " and {
            result = re.sub(r'"(\s*)\{', r'",\1{', result)

            tree = json.loads(result)

            # Resolve relative URLs to absolute URLs
            resolve_urls_in_tree(tree, url)

            print("\n[6] Tree extracted:")
            print(json.dumps(tree, indent=2))
            return tree, links_text, llm_usage

        except json.JSONDecodeError as e:
            print(f"\n[ERROR] Could not parse JSON: {e}")
            print(f"Raw response saved to: {raw_response_file}")
            return None, links_text, llm_usage

    finally:
        await page.wait_for_timeout(2000)
        await browser.close()
        await playwright.stop()


def tree_to_readable(node, indent=0) -> str:
    """Convert tree to readable text format."""
    lines = []
    prefix = "  " * indent

    if isinstance(node, list):
        for item in node:
            lines.append(tree_to_readable(item, indent))
    elif isinstance(node, dict):
        name = node.get('name', 'Unknown')
        url = node.get('url', '')
        if url:
            lines.append(f"{prefix}{name} | {url}")
        else:
            lines.append(f"{prefix}{name}")
        children = node.get('children', [])
        if children:
            for child in children:
                lines.append(tree_to_readable(child, indent + 1))

    return '\n'.join(lines)


async def main():
    if len(sys.argv) < 2:
        print("Usage: python static_extractor.py <url>")
        sys.exit(1)

    url = sys.argv[1]

    # Extract domain for filenames
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.replace('www.', '').replace('.', '_')

    output_dir = Path(__file__).parent.parent.parent / 'extractions' / domain
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run extraction (raw_links.txt saved immediately during extraction)
    tree, links_text, _ = await extract_tree(url, output_dir)

    if tree:
        # Save JSON tree
        json_file = output_dir / 'tree.json'
        with open(json_file, 'w') as f:
            json.dump(tree, f, indent=2)
        print(f"Saved JSON tree: {json_file}")

        # Save readable tree
        readable = tree_to_readable(tree)
        readable_file = output_dir / 'tree_readable.txt'
        with open(readable_file, 'w') as f:
            f.write(readable)
        print(f"Saved readable tree: {readable_file}")


if __name__ == "__main__":
    asyncio.run(main())
