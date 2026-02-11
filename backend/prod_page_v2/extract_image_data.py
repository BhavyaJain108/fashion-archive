"""
Extract enriched image data from product pages for many-shot learning.

Output format for each image:
- index
- alt text
- link context (NO_LINK, PRODUCT_LINK, OTHER_LINK)
- full URL
- container path (DOM ancestry for pattern derivation)

Usage:
    python extract_image_data.py <url>
"""

import asyncio
import sys
import json
from playwright.async_api import async_playwright


async def extract_image_data(url: str) -> dict:
    """Extract all image data from a product page."""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_load_state('networkidle', timeout=10000)
        except Exception as e:
            print(f"Warning: {e}", file=sys.stderr)

        # Extract all images with enriched data
        data = await page.evaluate("""() => {
            const images = document.querySelectorAll('img');
            const results = [];

            for (let i = 0; i < images.length; i++) {
                const img = images[i];

                // Get URL from various attributes
                let url = img.src || img.dataset.src || '';
                if (!url || url.startsWith('data:')) {
                    // Try srcset
                    const srcset = img.srcset || img.dataset.srcset || '';
                    if (srcset) {
                        const parts = srcset.split(',')[0].trim().split(' ');
                        url = parts[0] || '';
                    }
                }

                // Determine link context
                let linkType = 'NO_LINK';
                let linkHref = null;
                let parent = img.parentElement;

                while (parent && parent !== document.body) {
                    if (parent.tagName === 'A') {
                        linkHref = parent.href;
                        const currentPath = window.location.pathname;
                        const linkPath = new URL(parent.href, window.location.origin).pathname;

                        if (linkPath === currentPath || linkHref.includes('#')) {
                            linkType = 'NO_LINK';  // Same page or anchor
                        } else if (linkPath.includes('/product') || linkPath.includes('/collections') && linkPath.includes('/products')) {
                            linkType = 'PRODUCT_LINK';
                        } else {
                            linkType = 'OTHER_LINK';
                        }
                        break;
                    }
                    parent = parent.parentElement;
                }

                // Build container path (ancestry)
                const ancestry = [];
                let node = img.parentElement;
                const maxDepth = 6;

                for (let j = 0; j < maxDepth && node && node !== document.body; j++) {
                    const tag = node.tagName.toLowerCase();
                    const classes = node.className && typeof node.className === 'string'
                        ? node.className.trim().split(/\s+/).slice(0, 3).join('.')
                        : '';
                    const id = node.id ? '#' + node.id : '';

                    let signature = tag;
                    if (id) signature += id;
                    else if (classes) signature += '.' + classes;

                    ancestry.push(signature);
                    node = node.parentElement;
                }

                results.push({
                    i: i,
                    alt: (img.alt || '').substring(0, 50),
                    link: linkType,
                    url: url,
                    containers: ancestry.join(' < ')
                });
            }

            return {
                pageUrl: window.location.href,
                title: document.title,
                productName: document.querySelector('h1')?.textContent?.trim() || '',
                images: results
            };
        }""")

        await browser.close()
        return data


def format_as_markdown_table(data: dict) -> str:
    """Format extracted data as markdown."""
    lines = []
    lines.append(f"# Product: {data['productName']}")
    lines.append(f"**URL:** {data['pageUrl']}")
    lines.append("")
    lines.append("| # | Alt | Link | Containers | URL |")
    lines.append("|---|-----|------|------------|-----|")

    for img in data['images']:
        alt = img['alt'][:30] + "..." if len(img['alt']) > 30 else img['alt']
        alt = alt.replace('|', '\\|')
        containers = img['containers'][:50] + "..." if len(img['containers']) > 50 else img['containers']
        containers = containers.replace('|', '\\|')
        url_display = f"[view]({img['url']})" if img['url'] else "(empty)"

        lines.append(f"| {img['i']} | {alt} | {img['link']} | `{containers}` | {url_display} |")

    return "\n".join(lines)


def format_as_json_input(data: dict) -> str:
    """Format as JSON input for LLM."""
    input_data = {
        "product_name": data['productName'],
        "product_url": data['pageUrl'],
        "images": data['images']
    }
    return json.dumps(input_data, indent=2)


async def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_image_data.py <url> [--json|--md]")
        sys.exit(1)

    url = sys.argv[1]
    output_format = sys.argv[2] if len(sys.argv) > 2 else "--json"

    print(f"Extracting from: {url}", file=sys.stderr)
    data = await extract_image_data(url)
    print(f"Found {len(data['images'])} images", file=sys.stderr)

    if output_format == "--md":
        print(format_as_markdown_table(data))
    else:
        print(format_as_json_input(data))


if __name__ == "__main__":
    asyncio.run(main())
