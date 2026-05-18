"""
Many-shot LLM prompt for product image extraction.

Given image data with container paths, the LLM:
1. Identifies which images belong to the product gallery
2. Derives a CSS selector pattern for future non-LLM extraction
"""

SYSTEM_PROMPT = """You are an expert at analyzing e-commerce product pages to identify product gallery images.

Given a list of images from a product page, you must:
1. Identify which images are the PRODUCT GALLERY images (the main product photos)
2. Derive a CSS selector pattern that targets the gallery container

EXCLUDE these image types:
- Logos and brand images
- Navigation icons
- Social media icons
- Recommendation/related product images
- Color swatches (small, uniform size)
- Footer images
- Lookbook/editorial section images (unless they show the specific product)

SIGNALS to identify product gallery images:
1. Alt text often contains or matches the product name
2. Link context: NO_LINK usually means gallery image (clicking doesn't navigate away)
3. PRODUCT_LINK means it links to another product (recommendation)
4. OTHER_LINK means navigation/external link (logo, social)
5. Container paths: Gallery images share common ancestor patterns (look for slider/carousel classes like swiper, splide, slick, flickity, or gallery-related class names)
6. Product images typically appear early in DOM order

Return JSON with:
- product_image_indices: array of image indices that are product gallery images
- gallery_selector: CSS selector to target the gallery container (use classes/IDs from container paths)
- reasoning: brief explanation of your logic"""


def create_example(product_name: str, product_url: str, images: list, expected_indices: list, expected_selector: str, reasoning: str) -> dict:
    """Create a many-shot example."""
    return {
        "input": {
            "product_name": product_name,
            "product_url": product_url,
            "images": images
        },
        "output": {
            "product_image_indices": expected_indices,
            "gallery_selector": expected_selector,
            "reasoning": reasoning
        }
    }


# Many-shot examples from different brands
EXAMPLES = [
    # Example 1: Kuurth (Shopify with Splide slider)
    create_example(
        product_name="The creation of Adam - Ring V2",
        product_url="https://kuurth.com/collections/all/products/the-creation-of-adam-ring-v2",
        images=[
            {"i": 0, "alt": "KUURTH", "link": "OTHER_LINK", "containers": "div.max-w-[var(--logo-max-width)] < a.break-word < header"},
            {"i": 1, "alt": "KUURTH", "link": "OTHER_LINK", "containers": "div.max-w-[var(--logo-max-width)] < a.break-word < header"},
            {"i": 2, "alt": "The creation of Adam - Ring V2", "link": "NO_LINK", "containers": "image-with-placeholder.relative < div.relative.w-full < li#splide01-slide01"},
            {"i": 3, "alt": "The creation of Adam - Ring V2", "link": "NO_LINK", "containers": "image-with-placeholder.relative < div.relative.w-full < li#splide01-slide02"},
            {"i": 4, "alt": "The creation of Adam - Ring V2", "link": "NO_LINK", "containers": "image-with-placeholder.relative < div.relative.w-full < li#splide01-slide03"},
            {"i": 5, "alt": "The creation of Adam - Ring V2", "link": "NO_LINK", "containers": "image-with-placeholder.relative < div.relative.w-full < li#splide01-slide04"},
            {"i": 6, "alt": "The creation of Adam - Ring V2", "link": "NO_LINK", "containers": "image-with-placeholder.relative < div.relative.w-full < li#splide01-slide05"},
            {"i": 7, "alt": "", "link": "OTHER_LINK", "containers": "div.pl-swatches__color < div.pl-swatches__swatch"},
            {"i": 8, "alt": "", "link": "PRODUCT_LINK", "containers": "div.pl-swatches__color < div.pl-swatches__swatch"},
            {"i": 10, "alt": "Sakura - Necklace", "link": "NO_LINK", "containers": "image-with-placeholder < div.relative.prod-card__media"},
            {"i": 12, "alt": "Baco - Ring", "link": "NO_LINK", "containers": "image-with-placeholder < div.relative.prod-card__media"},
        ],
        expected_indices=[2, 3, 4, 5, 6],
        expected_selector="li[id^='splide'] img",
        reasoning="Images 2-6 have alt text matching product name, NO_LINK context, and share container pattern with 'splide' slider. Excluded: logos (0-1, OTHER_LINK in header), swatches (7-8), recommendations (10+, different product names, prod-card__media container)."
    ),

    # Example 2: Devi Clothing (Shopify standard)
    create_example(
        product_name="Nora top - Cherry - S/M",
        product_url="https://devi-clothing.com/collections/the-sari-collection/products/nora-top-red-cherry",
        images=[
            {"i": 0, "alt": "Devï Studios SARL", "link": "OTHER_LINK", "containers": "div < a < div.header__logo"},
            {"i": 1, "alt": "Devï Studios SARL", "link": "OTHER_LINK", "containers": "div < a < div.header__logo"},
            {"i": 2, "alt": "", "link": "NO_LINK", "containers": "div < div.announcement-bar"},
            {"i": 3, "alt": "Nora top - Cherry - S/M", "link": "OTHER_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 4, "alt": "Nora top - Cherry - S/M", "link": "OTHER_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 5, "alt": "Nora top - Cherry - S/M", "link": "OTHER_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 6, "alt": "Nora top - Cherry - S/M", "link": "OTHER_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 7, "alt": "Nora top - Cherry - S/M", "link": "OTHER_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 27, "alt": "Nora top - Sea coast - S/M", "link": "NO_LINK", "containers": "div < div.card__media < div.card-wrapper"},
            {"i": 29, "alt": "Nora top - Cappucino - M/L", "link": "NO_LINK", "containers": "div < div.card__media < div.card-wrapper"},
        ],
        expected_indices=[3, 4, 5, 6, 7],
        expected_selector="ul.product__media-list img",
        reasoning="Images 3-7 have alt text matching product name and share container 'product__media-list'. Excluded: logos (0-1, header), announcement (2), recommendations (27+, different product names in alt, card__media container)."
    ),

    # Example 3: Heaven Can Wait (Shopify with thumbnails)
    create_example(
        product_name="V2 TRACK JEANS (BLUE)",
        product_url="https://heavencanwait.store/collections/frontpage/products/track-jeans-blue",
        images=[
            {"i": 0, "alt": "heavencanwait.store", "link": "OTHER_LINK", "containers": "div < a < div.header__logo"},
            {"i": 1, "alt": "Search", "link": "NO_LINK", "containers": "span < button.header__icon"},
            {"i": 2, "alt": "Account", "link": "OTHER_LINK", "containers": "span < a.header__icon"},
            {"i": 3, "alt": "TRACK JEANS (BLUE) heavencanwait.store", "link": "NO_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 4, "alt": "TRACK JEANS (BLUE) heavencanwait.store", "link": "NO_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 5, "alt": "TRACK JEANS (BLUE) heavencanwait.store", "link": "NO_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 6, "alt": "TRACK JEANS (BLUE) heavencanwait.store", "link": "NO_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 7, "alt": "TRACK JEANS (BLUE) heavencanwait.store", "link": "NO_LINK", "containers": "div < div.product__media-item < ul.product__media-list"},
            {"i": 15, "alt": "Shipping icon", "link": "NO_LINK", "containers": "div < div.product__info-icon"},
            {"i": 18, "alt": "V2 TRACK JEANS (BLUE)", "link": "NO_LINK", "containers": "button < div.thumbnail-list__item"},
            {"i": 25, "alt": "", "link": "NO_LINK", "containers": "div < div.collection-hero__image"},
        ],
        expected_indices=[3, 4, 5, 6, 7],
        expected_selector="ul.product__media-list img",
        reasoning="Images 3-7 have alt containing product name and share container 'product__media-list'. Excluded: logo (0), icons (1-2, 15), thumbnails (18, smaller duplicates in thumbnail-list), lookbook images (25+, no alt, collection-hero container)."
    ),

    # Example 4: Entire Studios (Custom with Sanity CDN)
    create_example(
        product_name="Optime Short Training Leggings Active Maroon",
        product_url="https://www.entirestudios.com/product/adidas-x-entire-studios-optime-short-training-leggings-medium-red-8",
        images=[
            {"i": 0, "alt": "Character 1", "link": "NO_LINK", "containers": "div < div.relative < div.w-1/2.relative < div.flex.items-center < div.w-full < div.swiper-slide"},
            {"i": 1, "alt": "Character 2", "link": "NO_LINK", "containers": "div < div.relative < div.w-1/2.relative < div.flex.items-center < div.w-full < div.swiper-slide"},
            {"i": 2, "alt": "Character 3", "link": "NO_LINK", "containers": "div < div.relative < div.w-1/2.relative < div.flex.items-center < div.w-full < div.swiper-slide"},
            {"i": 3, "alt": "Character 4", "link": "NO_LINK", "containers": "div < div.relative < div.w-1/2.relative < div.flex.items-center < div.w-full < div.swiper-slide"},
            {"i": 4, "alt": "Optime Short Training Leggings Active Maroon - Ima", "link": "NO_LINK", "containers": "div < div.w-full < div.swiper-slide < div.swiper-wrapper < div.swiper"},
            {"i": 5, "alt": "Optime Short Training Leggings Active Maroon - Ima", "link": "NO_LINK", "containers": "div < div.w-full < div.swiper-slide < div.swiper-wrapper < div.swiper"},
            {"i": 10, "alt": "Optime Short Training Leggings Active Maroon - Ima", "link": "NO_LINK", "containers": "div < div.hidden.mx-auto.w-8/10 < div.md:w-6/10 < div.flex.flex-col.items-start"},
            {"i": 11, "alt": "Optime Short Training Leggings Active Maroon - Ima", "link": "NO_LINK", "containers": "div < div.hidden.mx-auto.w-8/10 < div.md:w-6/10 < div.flex.flex-col.items-start"},
            {"i": 20, "alt": "Product thumbnail", "link": "PRODUCT_LINK", "containers": "div < a < div.product-card"},
            {"i": 21, "alt": "Styled with thumbnail", "link": "PRODUCT_LINK", "containers": "div < a < div.product-card"},
        ],
        expected_indices=[0, 1, 2, 3, 4, 5, 10, 11],
        expected_selector="div.swiper-slide img, div.flex.flex-col.items-start img",
        reasoning="Images 0-5 are in swiper carousel (campaign characters showing the product), 10-11 are in main product grid. All have NO_LINK. Excluded: recommendations (20+, PRODUCT_LINK, product-card container). Note: Entire Studios uses editorial 'Character' images as part of product gallery."
    ),
]


def build_prompt(product_name: str, product_url: str, images: list) -> str:
    """Build the full many-shot prompt for a new product."""

    # Format examples
    examples_text = ""
    for i, ex in enumerate(EXAMPLES, 1):
        examples_text += f"\n--- EXAMPLE {i} ---\n"
        examples_text += f"INPUT:\n"
        examples_text += f"Product: {ex['input']['product_name']}\n"
        examples_text += f"URL: {ex['input']['product_url']}\n"
        examples_text += f"Images:\n"
        for img in ex['input']['images']:
            examples_text += f"  {img}\n"
        examples_text += f"\nOUTPUT:\n"
        examples_text += f"{ex['output']}\n"

    # Format the new input
    new_input = f"\n--- YOUR TASK ---\n"
    new_input += f"INPUT:\n"
    new_input += f"Product: {product_name}\n"
    new_input += f"URL: {product_url}\n"
    new_input += f"Images:\n"
    for img in images:
        new_input += f"  {img}\n"
    new_input += f"\nOUTPUT (respond with JSON only):\n"

    return SYSTEM_PROMPT + "\n\n" + examples_text + new_input


if __name__ == "__main__":
    # Test with a sample
    test_images = [
        {"i": 0, "alt": "Logo", "link": "OTHER_LINK", "containers": "div < header"},
        {"i": 1, "alt": "Test Product", "link": "NO_LINK", "containers": "div < div.gallery"},
        {"i": 2, "alt": "Test Product", "link": "NO_LINK", "containers": "div < div.gallery"},
        {"i": 3, "alt": "Other Item", "link": "PRODUCT_LINK", "containers": "div < div.recommendations"},
    ]

    prompt = build_prompt("Test Product", "https://example.com/product/test", test_images)
    print(prompt[:2000])
    print("...\n[truncated]")
