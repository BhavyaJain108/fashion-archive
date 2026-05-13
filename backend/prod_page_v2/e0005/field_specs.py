"""
Field-by-field semantic descriptions for the one-shot discovery prompt.

Three things live here, all as plain Python data:

1. SCHEMA_DESCRIPTIONS — for each E0005 product field, what the LLM should
   produce (description / format / pitfall). Deliberately no "where to look"
   guidance — the LLM decides which PageMemo source to mine; we just tell it
   what the value should look like.

2. PRODUCT_TYPE_PRESETS — per-product-type field subsets. Truncates the
   schema before building the prompt so the LLM doesn't get asked about
   fields that don't apply (e.g. ppu/unit_type/package_desc on a clothing
   site).

3. Helpers to build the LLM-facing schema section from these tables.
"""

from __future__ import annotations

from typing import Dict, List


# ---------------------------------------------------------------------------
# Field specifications
# ---------------------------------------------------------------------------

# Each entry is keyed by the E0005 field name and has:
#   description : what the value should represent
#   format      : the expected output format / type
#   pitfall     : the most common LLM mistake to avoid
SCHEMA_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    # --- Identity ---
    "product_title": {
        "description": "Page-displayed product name.",
        "format": "string",
        "pitfall": "Sources differ in completeness; some append color/SKU. Pick the cleanest, most user-facing form.",
    },
    "product_code": {
        "description": "Brand's internal SKU for THIS specific variant being shown.",
        "format": "string",
        "pitfall": "Drop any 'SKU:' prefix. If page distinguishes base vs variant SKU, prefer the variant.",
    },
    "brand": {
        "description": "Brand name as plain text.",
        "format": "string",
        "pitfall": "Some sites only render the brand as a logo (SVG). Look for textContent equivalents — vendor field, header text.",
    },
    "description": {
        "description": "Long-form product description.",
        "format": "prose string",
        "pitfall": "Exclude shipping/returns/care blurbs unless they're truly part of the description prose.",
    },
    "specifications": {
        "description": "Technical / visual specifications listed for the product.",
        "format": "semicolon-joined string of distinct spec points",
        "pitfall": "Composition/material belongs in material_info, not here. Size & fit notes belong here.",
    },

    # --- Codes ---
    "additional_code_1": {
        "description": "A barcode-style identifier (GTIN / UPC / EAN / ASIN / MPN / ISBN).",
        "format": "digits-only string",
        "pitfall": "Almost never published by fashion DTC brands. Leave null unless directly visible/structured.",
    },
    "additional_code_1_type": {
        "description": "The type label paired with additional_code_1.",
        "format": "one of: GTIN13, GTIN8, UPC, EAN, ASIN, MPN, ISBN",
        "pitfall": "Must be set when additional_code_1 is set, null when it is null.",
    },
    "additional_code_2": {
        "description": "A second barcode-style identifier, if a different one is published.",
        "format": "digits-only string",
        "pitfall": "Almost always null on fashion.",
    },
    "additional_code_2_type": {
        "description": "The type label paired with additional_code_2.",
        "format": "one of: GTIN13, GTIN8, UPC, EAN, ASIN, MPN, ISBN",
        "pitfall": "Null when additional_code_2 is null.",
    },
    "additional_code_3": {
        "description": "A third barcode-style identifier.",
        "format": "digits-only string",
        "pitfall": "Almost always null on fashion.",
    },
    "additional_code_3_type": {
        "description": "The type label paired with additional_code_3.",
        "format": "one of: GTIN13, GTIN8, UPC, EAN, ASIN, MPN, ISBN",
        "pitfall": "Null when additional_code_3 is null.",
    },

    # --- Variants ---
    "size_info": {
        "description": "The sizes a customer can select for this product.",
        "format": "comma-separated string, in the display order shown on the page",
        "pitfall": "Exclude placeholder labels like 'Select a size'. When dual-system labels are shown (e.g. '40 / US 4'), keep both joined.",
    },
    "size_availability": {
        "description": "Per-size in-stock state, aligned 1:1 with size_info order.",
        "format": "comma-separated list of 'in_stock' / 'out_of_stock' (one entry per size, same order as size_info)",
        "pitfall": "Must align with size_info ordering. If the API returns booleans, map true → 'in_stock', false → 'out_of_stock'. Null only when sizes themselves are null.",
    },
    "size_stock_counts": {
        "description": "Remaining inventory quantity per size, aligned with size_info order.",
        "format": "comma-separated list of integers (one per size, same order as size_info)",
        "pitfall": "Many brands don't expose precise counts; if a size is in stock but count is hidden, use empty entry rather than guessing. Null when no per-size count is available anywhere.",
    },
    "color_info": {
        "description": "The color name(s) the customer sees for this product.",
        "format": "comma-separated capitalized string",
        "pitfall": "Brand-internal codes (e.g. 'BLACK') vs marketing names (e.g. 'Onyx') — prefer the customer-facing form.",
    },
    "material_info": {
        "description": "Fabric / material composition of the garment.",
        "format": "free text, e.g. '100% Cotton' or 'Cotton Silk Organza (53% Silk, 47% Cotton)'",
        "pitfall": "Care instructions are NOT material. If textile name and percentages are both available, combine them.",
    },
    "variant_info": {
        "description": "Variant axes that are NOT size and NOT color (e.g. width for shoes, stone for jewelry).",
        "format": "free text",
        "pitfall": "Usually null on fashion. Don't duplicate size_info or color_info.",
    },

    # --- Pricing ---
    "price": {
        "description": "The current customer-paying price for the product.",
        "format": "float, 2 decimal precision",
        "pitfall": "When on sale, this is the SALE price. When variants have different prices, use the displayed default (or lowest if no default shown).",
    },
    "full_price": {
        "description": "The original / pre-discount price.",
        "format": "float",
        "pitfall": "When no discount is visible, set equal to price. Do NOT fabricate a discount.",
    },
    "promotion_type": {
        "description": "The kind of promotion currently active.",
        "format": "short string, e.g. '20% off', 'BOGO', 'Final Sale'",
        "pitfall": "Null when no promotion visible.",
    },
    "promotion_end_date": {
        "description": "Date when the promotion ends.",
        "format": "YYYY-MM-DD",
        "pitfall": "Almost always unstructured. Leave null unless an explicit date is shown.",
    },
    "ppu": {
        "description": "Price per unit (used for grocery / bulk items).",
        "format": "float",
        "pitfall": "N/A for fashion → null.",
    },
    "unit_type": {
        "description": "The unit of measure that ppu is expressed in.",
        "format": "string (e.g. 'L', 'kg', 'oz')",
        "pitfall": "Null when ppu is null.",
    },
    "package_desc": {
        "description": "Multipack or packaging info.",
        "format": "string",
        "pitfall": "Usually N/A for fashion.",
    },

    # --- Stock ---
    "in_stock": {
        "description": "1 if at least one variant of this product is currently purchasable, else 0.",
        "format": "integer 1 or 0",
        "pitfall": "A single sold-out variant doesn't mean the product is OOS. Only when every variant is unavailable → 0.",
    },
    "quantity": {
        "description": "Actual stock count shown on the page (rare).",
        "format": "integer",
        "pitfall": "Usually unavailable on fashion. Leave null unless explicitly shown.",
    },

    # --- Taxonomy ---
    "category1": {"description": "Top-level navigation category for this product.",  "format": "string", "pitfall": "Exclude 'Home' and the product name itself."},
    "category2": {"description": "2nd-level navigation category.",                    "format": "string", "pitfall": "Null if the breadcrumb is shallower."},
    "category3": {"description": "3rd-level navigation category.",                    "format": "string", "pitfall": "Null if shallower."},
    "category4": {"description": "4th-level navigation category.",                    "format": "string", "pitfall": "Null if shallower."},
    "category5": {"description": "5th-level navigation category.",                    "format": "string", "pitfall": "Null if shallower."},
    "category6": {"description": "6th-level navigation category.",                    "format": "string", "pitfall": "Null if shallower."},
    "category7": {"description": "7th-level navigation category.",                    "format": "string", "pitfall": "Null if shallower."},
    "category8": {"description": "8th-level navigation category.",                    "format": "string", "pitfall": "Null if shallower."},
    "category9": {"description": "9th-level navigation category.",                    "format": "string", "pitfall": "Null if shallower."},
    "category10": {"description": "10th-level navigation category.",                  "format": "string", "pitfall": "Null if shallower."},

    # --- Media ---
    "main_image_url": {
        "description": "Primary product image URL.",
        "format": "full URL",
        "pitfall": "Don't pick a lifestyle/banner/model-carousel image — pick a clear product photo.",
    },
    "all_images": {
        "description": "Every product image URL.",
        "format": "JSON-encoded array of URL strings",
        "pitfall": "Exclude thumbnail duplicates of the same image and unrelated images (related products, model carousels).",
    },

    # --- Marketing / catch-all ---
    "additional_tags": {
        "description": "Product attribution labels / badges visible on the page.",
        "format": "comma-separated string (e.g. 'New, Best Seller, Final Sale')",
        "pitfall": "Only product-attribution labels, not UI controls or section headers.",
    },
    "delivery": {
        "description": "Shipping / delivery info text shown on this product's page.",
        "format": "free text, cap ~500 chars",
        "pitfall": "Don't pull in unrelated FAQ content.",
    },
    "additional_content": {
        "description": "Any important product information not captured by another field.",
        "format": "free text",
        "pitfall": "Be selective. Only populate when there is clearly important content that no other field covers.",
    },

    # --- Passthrough ---
    "itemurl": {
        "description": "URL of THIS product page.",
        "format": "full URL",
        "pitfall": "Always the input URL — never invent.",
    },
}


# ---------------------------------------------------------------------------
# Per-product-type schema subsets
# ---------------------------------------------------------------------------

PRODUCT_TYPE_PRESETS: Dict[str, List[str]] = {
    # The default subset for clothing / accessories / footwear / bags.
    # 21 fields. Drops 17 fields that are reliably N/A:
    #   additional_code_1/2/3 + types (6), variant_info, quantity,
    #   category6-10 (5), ppu, unit_type, promotion_end_date, package_desc.
    "fashion": [
        # identity
        "product_title", "product_code", "brand", "description", "specifications",
        # variants
        "size_info", "size_availability", "size_stock_counts",
        "color_info", "material_info",
        # pricing
        "price", "full_price", "promotion_type",
        # stock
        "in_stock",
        # taxonomy (5 levels of depth is plenty for fashion)
        "category1", "category2", "category3", "category4", "category5",
        # marketing
        "delivery", "additional_tags", "additional_content",
        # passthrough + media
        "itemurl", "main_image_url", "all_images",
    ],

    # Used for non-DTC discovery — Amazon, Walmart, etc. Add when needed.
    # "marketplace": [...],
    # "grocery": [...],

    # Full E0005 product group — every field. Use for exploratory discovery
    # or for marketplaces that genuinely publish barcodes.
    "all": list(SCHEMA_DESCRIPTIONS.keys()),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fields_for_product_type(product_type: str) -> List[str]:
    """Return the field subset for `product_type`, falling back to 'fashion'."""
    return PRODUCT_TYPE_PRESETS.get(product_type, PRODUCT_TYPE_PRESETS["fashion"])


def build_schema_section(fields: List[str]) -> str:
    """Render the LLM-facing schema description as one block of markdown-style
    text. The LLM gets the *meaning* of every field, but no hint about which
    PageMemo source to look in — that's its job."""
    lines: List[str] = []
    for f in fields:
        spec = SCHEMA_DESCRIPTIONS.get(f)
        if spec is None:
            continue
        lines.append(f"- `{f}` — {spec['description']}")
        lines.append(f"    format: {spec['format']}")
        lines.append(f"    pitfall: {spec['pitfall']}")
    return "\n".join(lines)
