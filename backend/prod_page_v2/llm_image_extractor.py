"""
LLM-based product image extraction using many-shot prompting.

This module:
1. Extracts enriched image data from a page (with container paths)
2. Sends to LLM with many-shot examples
3. Returns identified product images AND a derived CSS selector

Uses the existing LLMHandler from scraper/llm_handler.py for API calls.
"""

import json
import re
import sys
import os
from typing import Optional
from playwright.async_api import Page

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from image_extraction_prompt import build_prompt, SYSTEM_PROMPT

# Import existing LLM handler
try:
    from scraper.llm_handler import LLMHandler
except ImportError:
    LLMHandler = None


async def extract_image_data_from_page(page: Page, max_images: int = 50) -> list:
    """
    Extract enriched image data from a loaded page.

    Returns list of dicts with: i, alt, link, url, containers
    """
    return await page.evaluate(f"""(maxImages) => {{
        const images = document.querySelectorAll('img');
        const results = [];
        const currentPath = window.location.pathname;

        for (let i = 0; i < Math.min(images.length, maxImages); i++) {{
            const img = images[i];

            // Get URL
            let url = img.src || img.dataset?.src || '';
            if (!url || url.startsWith('data:')) {{
                const srcset = img.srcset || img.dataset?.srcset || '';
                if (srcset) {{
                    const parts = srcset.split(',')[0].trim().split(' ');
                    url = parts[0] || '';
                }}
            }}

            // Determine link context
            let linkType = 'NO_LINK';
            let parent = img.parentElement;

            while (parent && parent !== document.body) {{
                if (parent.tagName === 'A') {{
                    try {{
                        const linkPath = new URL(parent.href, window.location.origin).pathname;
                        if (linkPath === currentPath || parent.href.includes('#')) {{
                            linkType = 'NO_LINK';
                        }} else if (linkPath.includes('/product') || (linkPath.includes('/collections') && linkPath.includes('/products'))) {{
                            linkType = 'PRODUCT_LINK';
                        }} else {{
                            linkType = 'OTHER_LINK';
                        }}
                    }} catch (e) {{
                        linkType = 'OTHER_LINK';
                    }}
                    break;
                }}
                parent = parent.parentElement;
            }}

            // Build container path
            const ancestry = [];
            let node = img.parentElement;
            const maxDepth = 5;

            for (let j = 0; j < maxDepth && node && node !== document.body; j++) {{
                const tag = node.tagName.toLowerCase();
                const classes = node.className && typeof node.className === 'string'
                    ? node.className.trim().split(/\\s+/).slice(0, 3).join('.')
                    : '';
                const id = node.id ? '#' + node.id : '';

                let signature = tag;
                if (id) signature += id;
                else if (classes) signature += '.' + classes;

                ancestry.push(signature);
                node = node.parentElement;
            }}

            results.push({{
                i: i,
                alt: (img.alt || '').substring(0, 50),
                link: linkType,
                url: url,
                containers: ancestry.join(' < ')
            }});
        }}

        return results;
    }}""", max_images)


async def extract_product_images_with_llm(
    page: Page,
    product_name: str,
    product_url: str,
    max_images: int = 50
) -> dict:
    """
    Use LLM to identify product images and derive a CSS selector.

    Uses existing LLMHandler from scraper/llm_handler.py.

    Args:
        page: Loaded Playwright page
        product_name: The product title (from metadata)
        product_url: The page URL
        max_images: Max images to analyze

    Returns:
        {
            "product_image_indices": [int, ...],
            "product_image_urls": [str, ...],
            "gallery_selector": str,
            "reasoning": str
        }
    """
    if not LLMHandler:
        raise ImportError("LLMHandler not available - check scraper/llm_handler.py")

    # Extract image data with container paths
    images = await extract_image_data_from_page(page, max_images)

    if not images:
        return {
            "product_image_indices": [],
            "product_image_urls": [],
            "gallery_selector": "",
            "reasoning": "No images found on page"
        }

    # Build prompt (without URLs in LLM input to save tokens)
    images_for_llm = [
        {"i": img["i"], "alt": img["alt"], "link": img["link"], "containers": img["containers"]}
        for img in images
    ]

    prompt = build_prompt(product_name, product_url, images_for_llm)

    # Call LLM using existing handler
    handler = LLMHandler()
    result = handler.call_text(prompt, max_tokens=1024, operation="product_image_extraction")

    if not result.get("success"):
        return {
            "product_image_indices": [],
            "product_image_urls": [],
            "gallery_selector": "",
            "reasoning": f"LLM call failed: {result.get('error', 'unknown error')}"
        }

    response_text = result.get("response", "")

    # Parse response - handle both JSON and Python dict syntax
    parsed = None
    try:
        # Try direct JSON parse first
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        pass

    if not parsed:
        try:
            # Try Python literal eval (handles single quotes)
            import ast
            parsed = ast.literal_eval(response_text)
        except (ValueError, SyntaxError):
            pass

    if not parsed:
        try:
            # Try to find JSON in the response with double quotes
            json_match = re.search(r'\{[^{}]*"product_image_indices"[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    if not parsed:
        # Fallback: extract indices manually using regex
        indices_match = re.search(r'["\']?product_image_indices["\']?\s*:\s*\[([\d,\s]+)\]', response_text)
        if indices_match:
            indices = [int(x.strip()) for x in indices_match.group(1).split(',') if x.strip()]
        else:
            indices = []

        selector_match = re.search(r'["\']?gallery_selector["\']?\s*:\s*["\']([^"\']+)["\']', response_text)
        selector = selector_match.group(1) if selector_match else ""

        parsed = {
            "product_image_indices": indices,
            "gallery_selector": selector,
            "reasoning": "Parsed from non-standard response"
        }

    # Map indices to URLs
    index_to_url = {img["i"]: img["url"] for img in images}
    product_urls = [
        index_to_url[i] for i in parsed.get("product_image_indices", [])
        if i in index_to_url and index_to_url[i]
    ]

    gallery_selector = parsed.get("gallery_selector", "")

    # Validate selector on the same page
    selector_valid = False
    selector_count = 0
    if gallery_selector:
        try:
            selector_count = await page.evaluate(
                """(sel) => document.querySelectorAll(sel).length""",
                gallery_selector
            )
            # Valid if it finds images (within reasonable range of expected)
            selector_valid = selector_count > 0 and selector_count <= len(product_urls) * 2
        except Exception:
            selector_valid = False

    return {
        "product_image_indices": parsed.get("product_image_indices", []),
        "product_image_urls": dedupe_image_urls(product_urls),
        "gallery_selector": gallery_selector,
        "selector_valid": selector_valid,
        "selector_count": selector_count,
        "reasoning": parsed.get("reasoning", "")
    }


def dedupe_image_urls(urls: list) -> list:
    """Deduplicate image URLs by filename."""
    seen = set()
    deduped = []
    for url in urls:
        # Extract filename as identity
        filename = url.split('?')[0].split('/')[-1]
        if filename not in seen:
            seen.add(filename)
            deduped.append(url)
    return deduped


# For testing without LLM
async def extract_product_images_heuristic(
    page: Page,
    product_name: str
) -> dict:
    """
    Heuristic fallback: identify product images without LLM.

    Uses simple rules:
    1. Alt text contains product name → likely product image
    2. NO_LINK context → not a recommendation
    3. Most common container pattern among matching images → gallery selector
    """
    images = await extract_image_data_from_page(page, 60)

    if not images:
        return {"product_image_indices": [], "product_image_urls": [], "gallery_selector": ""}

    # Normalize product name for matching
    product_name_lower = product_name.lower()
    product_words = set(product_name_lower.split())

    # Score each image
    candidates = []
    for img in images:
        score = 0

        # Alt text matching
        alt_lower = img["alt"].lower()
        if product_name_lower in alt_lower:
            score += 3
        elif any(word in alt_lower for word in product_words if len(word) > 3):
            score += 1

        # Link context
        if img["link"] == "NO_LINK":
            score += 2
        elif img["link"] == "PRODUCT_LINK":
            score -= 5  # Strong signal this is a recommendation
        elif img["link"] == "OTHER_LINK":
            score -= 1

        # Container patterns suggesting gallery
        containers = img["containers"].lower()
        if any(x in containers for x in ["gallery", "product__media", "swiper", "splide", "slider"]):
            score += 2
        if any(x in containers for x in ["prod-card", "product-card", "recommend", "related", "card__media"]):
            score -= 3
        if any(x in containers for x in ["header", "footer", "logo", "icon", "swatch"]):
            score -= 2

        if score > 0:
            candidates.append((img, score))

    # Sort by score, then DOM order
    candidates.sort(key=lambda x: (-x[1], x[0]["i"]))

    # Take top candidates
    product_images = [c[0] for c in candidates if c[1] > 1]

    # Find common container pattern
    if product_images:
        containers = [img["containers"] for img in product_images]
        # Find most common container
        from collections import Counter
        container_counts = Counter(containers)
        most_common = container_counts.most_common(1)[0][0] if container_counts else ""

        # Derive selector from container
        if most_common:
            parts = most_common.split(" < ")
            if parts:
                # Use first meaningful class
                for part in parts:
                    if "." in part and not part.startswith("div."):
                        selector = part.replace(".", " .").replace("#", " #").strip() + " img"
                        break
                else:
                    selector = parts[0] + " img" if parts else "img"
            else:
                selector = ""
        else:
            selector = ""
    else:
        selector = ""

    return {
        "product_image_indices": [img["i"] for img in product_images],
        "product_image_urls": dedupe_image_urls([img["url"] for img in product_images if img["url"]]),
        "gallery_selector": selector,
        "reasoning": "Heuristic extraction based on alt text and container patterns"
    }
