#!/usr/bin/env python3
"""
LLM Prompts for Fashion Brand Scraping
=====================================

All prompts for the LLM-driven scraping pipeline.
"""

# HTML truncation limit (characters)
HTML_TRUNCATE_LIMIT = 10000

def get_navigation_prompt(html_content: str, url: str) -> str:
    """
    Prompt for determining navigation strategy from homepage/current page
    """
    return f"""
Analyze this fashion brand webpage and determine the next step to get ALL products.

URL: {url}
HTML Content (first {HTML_TRUNCATE_LIMIT} chars):
{html_content[:HTML_TRUNCATE_LIMIT]}

You must respond with EXACTLY ONE of these options:
- "menu" - if there's a navigation menu to click first
- "all_products_link" - if there's a direct link to see all products (like "Shop All", "All Products", "Shop")
- "category_links" - if there are direct category links on this page (like "Tops", "Bottoms", "Accessories")
- "products_already_here" - if products are already visible on this page

Think step by step:
1. Look for navigation menus (hamburger menus, nav bars, etc.)
2. Look for "Shop All" or "All Products" type links
3. Look for category links that lead to product pages
4. Check if products are already displayed

Respond with only one word from the four options above.
""".strip()


def get_menu_navigation_prompt(html_content: str, url: str) -> str:
    """
    Prompt for determining navigation strategy from menu page
    """
    return f"""
Analyze this fashion brand menu/navigation page and determine how to get ALL products.

URL: {url}
HTML Content (first {HTML_TRUNCATE_LIMIT} chars):
{html_content[:HTML_TRUNCATE_LIMIT]}

You must respond with EXACTLY ONE of these options:
- "all_products_link" - if there's a direct link to see all products (like "Shop All", "All Products", "Shop")
- "category_links" - if there are category links that need to be visited individually

Look for:
1. Direct "Shop All" / "All Products" / "Shop" links first
2. If not found, identify all category links (Men, Women, Tops, Bottoms, etc.)

Respond with only one word: either "all_products_link" or "category_links".
""".strip()


def get_category_links_prompt(html_content: str, url: str) -> str:
    """
    Prompt for extracting all category links
    """
    return f"""
Extract ALL category/product page links from this page.

URL: {url}
HTML Content (first {HTML_TRUNCATE_LIMIT} chars):
{html_content[:HTML_TRUNCATE_LIMIT]}

Return a JSON array of objects, each containing:
- "text": The visible text of the link
- "url": The href attribute (full URL if possible, relative if not)
- "type": "category" or "collection" or "product_page"

Look for links that lead to:
- Product categories (Men, Women, Tops, Bottoms, Shoes, etc.)
- Collections (Spring 2024, Archive, New Arrivals, etc.)  
- Any section that would contain multiple products

Ignore:
- Footer links
- Social media links
- Account/login links
- Single product links
- About/Contact pages

Respond with only valid JSON array.
""".strip()


def get_all_products_link_prompt(html_content: str, url: str) -> str:
    """
    Prompt for finding the "Shop All" or "All Products" link
    """
    return f"""
Find the link that leads to ALL products on this fashion brand page.

URL: {url}
HTML Content (first {HTML_TRUNCATE_LIMIT} chars):
{html_content[:HTML_TRUNCATE_LIMIT]}

Look for links with text like:
- "Shop All"
- "All Products" 
- "Shop"
- "Products"
- "Collection"
- "Browse All"

Return a JSON object:
{{
    "text": "visible link text",
    "url": "href attribute"
}}

If no such link is found, return:
{{
    "text": null,
    "url": null
}}

Respond with only valid JSON.
""".strip()


def get_product_detection_prompt(html_content: str, url: str, sample_images: list = None) -> str:
    """
    Prompt for detecting what represents a product on the page
    """
    import re
    
    # Strategy 1: If we have product images, find their containers for better analysis
    sample_context = ""
    if sample_images:
        for i, img in enumerate(sample_images[:3]):  # Use first 3 images
            alt_match = re.search(r'alt="([^"]+)"', img)
            src_match = re.search(r'src="([^"]+)"', img)
            
            if alt_match:
                alt_text = alt_match.group(1)
                # Find context around this image (larger context)
                context_match = re.search(f'.{{1500}}{re.escape(alt_text)}.{{800}}', html_content, re.DOTALL)
                if context_match:
                    sample_context += f"\n\nSAMPLE PRODUCT {i+1} (Product: {alt_text}):\n{context_match.group()}\n"
            elif src_match:
                # If no alt text, try to find context around the src URL
                src_url = src_match.group(1)
                filename = src_url.split('/')[-1] if '/' in src_url else src_url
                if filename:
                    context_match = re.search(f'.{{1500}}{re.escape(filename)}.{{800}}', html_content, re.DOTALL)
                    if context_match:
                        sample_context += f"\n\nSAMPLE PRODUCT {i+1} (Image: {filename}):\n{context_match.group()}\n"
    
    # Strategy 2: Try to find the main content area that contains the product grid
    body_match = re.search(r'<body[^>]*>(.*)</body>', html_content, re.DOTALL | re.IGNORECASE)
    if body_match:
        body_content = body_match.group(1)
        
        # Look for product grid sections specifically
        grid_patterns = [
            r'<div[^>]*class="[^"]*(?:product-grid|products-grid|collection|grid)[^"]*"[^>]*>.*?</div>',
            r'<section[^>]*class="[^"]*(?:product|collection)[^"]*"[^>]*>.*?</section>',
            r'<main[^>]*>.*?</main>',
            r'<div[^>]*id="[^"]*(?:product|collection|main)[^"]*"[^>]*>.*?</div>'
        ]
        
        best_section = None
        max_product_indicators = 0
        
        for pattern in grid_patterns:
            matches = re.findall(pattern, body_content, re.DOTALL)
            for match in matches:
                # Count product indicators in this section
                product_count = (
                    len(re.findall(r'<[^>]*class="[^"]*(?:product|item|card)[^"]*"', match)) +
                    len(re.findall(r'<x-cell', match)) +
                    len(re.findall(r'data-product', match)) +
                    len(re.findall(r'product-', match))
                )
                
                if product_count > max_product_indicators:
                    max_product_indicators = product_count
                    best_section = match
        
        if best_section and max_product_indicators > 10:
            # Found a section with many product indicators - use it
            html_preview = best_section[:HTML_TRUNCATE_LIMIT] + sample_context
            print(f"🔍 Using product grid section with {max_product_indicators} product indicators")
        else:
            # Look for the middle section of body content (skip header/footer)
            body_lines = body_content.split('\n')
            start_idx = len(body_lines) // 4  # Skip first 25%
            end_idx = 3 * len(body_lines) // 4  # Use up to 75%
            middle_content = '\n'.join(body_lines[start_idx:end_idx])
            html_preview = middle_content[:HTML_TRUNCATE_LIMIT] + sample_context
            print(f"🔍 Using middle section of body content")
    else:
        # Fallback to original approach but skip scripts and styles
        content_no_scripts = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        content_no_styles = re.sub(r'<style[^>]*>.*?</style>', '', content_no_scripts, flags=re.DOTALL | re.IGNORECASE)
        html_preview = content_no_styles[:HTML_TRUNCATE_LIMIT] + sample_context
        print(f"🔍 Using cleaned HTML content (no scripts/styles)")
    
    return f"""
Look at this fashion brand page and help me identify the pattern for finding products.

URL: {url}
HTML Content:
{html_preview}

I need you to find 2-3 example products and tell me how to identify ALL products programmatically.

Your task:
1. Find 2-3 clear product examples from this page
2. For each example, show me:
   - The product name/title
   - The image URL
   - The HTML structure around that product

3. Tell me the pattern:
   - What CSS selector would find all product containers?
   - What CSS selector would find product images within each container?
   - What CSS selector would find product names within each container?

Return a JSON object:
{{
    "example_products": [
        {{
            "name": "product name",
            "image_url": "image URL",
            "html_snippet": "HTML around this product (200 chars)"
        }}
    ],
    "extraction_pattern": {{
        "container_selector": "CSS selector for product containers",
        "image_selector": "CSS selector for images within container",
        "name_selector": "CSS selector for names within container",
        "how_to_use": "brief explanation of how to use these selectors"
    }}
}}

Focus on giving me selectors I can use with document.querySelectorAll() to find ALL products.

Respond with only valid JSON.
""".strip()


def get_pagination_prompt(html_content: str, url: str) -> str:
    """
    Prompt for determining pagination/scrolling strategy
    """
    return f"""
Analyze this product page and determine how to get more products.

URL: {url}
HTML Content (first {HTML_TRUNCATE_LIMIT} chars):
{html_content[:HTML_TRUNCATE_LIMIT]}

You must respond with EXACTLY ONE of these options:
- "pagination" - if there are page numbers, "Next" buttons, or similar pagination controls
- "scrolling" - if more products load when scrolling down (infinite scroll)
- "load_more" - if there's a "Load More" or "Show More" button
- "done" - if all products are already visible on this page

Look for:
1. Pagination controls (page numbers, Next/Previous buttons)
2. "Load More" / "Show More" buttons
3. Signs of infinite scroll (products that seem to continue loading)
4. If the page appears to show all products already

If you choose "pagination" or "load_more", also provide the selector:

Return JSON:
{{
    "strategy": "pagination" | "scrolling" | "load_more" | "done",
    "selector": "CSS selector for next button or load more button" (if applicable),
    "notes": "brief explanation of why you chose this strategy"
}}

Respond with only valid JSON.
""".strip()