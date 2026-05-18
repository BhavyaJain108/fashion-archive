"""
E0005 product-row schema (Data Boutique standard).

One E0005Row = one product extraction output. The schema is flat per
product (variant info is carried as JSON-ish text in size_info /
color_info / variant_info rather than a nested array), matching the
upstream spec at data/E0005_schema.json.

Three concerns are deliberately separated:

- `DatasetMetadata`: fixed-per-delivery context. Set at pipeline-run
  time, not extracted from product pages. Merged into every row at
  write time.
- `StoreContext`, `MerchantContext`: optional, mostly N/A for DTC
  fashion brands. Reserved so we don't break the schema later.
- `ProductFields`: the per-product payload — every field the
  orchestrator tries to fill from page extraction.

The orchestrator works directly on `ProductFields`. Final output to disk
is the union (dataset_metadata + store + merchant + product), serialized
flat.
"""

from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field


# All field names the orchestrator considers extractable. Order is
# stable so reports/diffs line up across runs.
EXTRACTABLE_FIELDS: List[str] = [
    "product_code",
    "additional_code_1", "additional_code_1_type",
    "additional_code_2", "additional_code_2_type",
    "additional_code_3", "additional_code_3_type",
    "size_info",
    "size_availability",
    "size_stock_counts",
    "brand",
    "color_info",
    "material_info",
    "variant_info",
    "description",
    "product_title",
    "specifications",
    "delivery",
    "in_stock",
    "quantity",
    "category1", "category2", "category3", "category4", "category5",
    "category6", "category7", "category8", "category9", "category10",
    "full_price",
    "price",
    "ppu",
    "unit_type",
    "promotion_type",
    "promotion_end_date",
    "package_desc",
    "additional_tags",
    "additional_content",
    "itemurl",
    "main_image_url",
    "all_images",
]


class DatasetMetadata(BaseModel):
    """Fixed-per-delivery context. Not extracted — set from pipeline config."""

    dbq_prd_type: str = "E0005"
    website_name: Optional[str] = None
    competence_date: Optional[str] = None     # YYYY-MM-DD
    country_code: Optional[str] = None        # ISO 3-letter
    currency_code: Optional[str] = None       # ISO 3-letter
    contract_id: Optional[str] = None
    seller_id: Optional[str] = None
    delivery_id: Optional[float] = None       # unix epoch with fractional


class StoreContext(BaseModel):
    """Physical-store context. Optional, rarely populated for DTC brands."""

    store_id: Optional[str] = None
    store_name: Optional[str] = None
    store_address: Optional[str] = None
    store_zip: Optional[str] = None
    store_url: Optional[str] = None


class MerchantContext(BaseModel):
    """Marketplace-seller context. Optional, relevant on marketplaces."""

    merchant_id: Optional[str] = None
    merchant_name: Optional[str] = None
    merchant_url: Optional[str] = None
    merchant_image: Optional[str] = None
    merchant_descr: Optional[str] = None


class ProductFields(BaseModel):
    """Per-product extracted payload. Every field the orchestrator targets."""

    # Identity / codes
    product_code: Optional[str] = None
    additional_code_1: Optional[str] = None
    additional_code_1_type: Optional[str] = None  # GTIN | ASIN | MPN | ...
    additional_code_2: Optional[str] = None
    additional_code_2_type: Optional[str] = None
    additional_code_3: Optional[str] = None
    additional_code_3_type: Optional[str] = None

    # Descriptive
    product_title: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    specifications: Optional[str] = None
    additional_content: Optional[str] = None

    # Variant axes (carried as text per E0005, not nested)
    size_info: Optional[str] = None
    size_availability: Optional[str] = None    # "in_stock, out_of_stock, ..." aligned with size_info
    size_stock_counts: Optional[str] = None    # "0, 1, 3, 4" aligned with size_info
    color_info: Optional[str] = None
    material_info: Optional[str] = None
    variant_info: Optional[str] = None

    # Pricing
    price: Optional[float] = None
    full_price: Optional[float] = None
    ppu: Optional[float] = None
    unit_type: Optional[str] = None
    promotion_type: Optional[str] = None
    promotion_end_date: Optional[str] = None
    package_desc: Optional[str] = None

    # Stock
    in_stock: Optional[int] = None  # 1 = in stock, 0 = out (per E0005)
    quantity: Optional[int] = None

    # Taxonomy — nav-tree levels 1..10
    category1: Optional[str] = None
    category2: Optional[str] = None
    category3: Optional[str] = None
    category4: Optional[str] = None
    category5: Optional[str] = None
    category6: Optional[str] = None
    category7: Optional[str] = None
    category8: Optional[str] = None
    category9: Optional[str] = None
    category10: Optional[str] = None

    # Marketing
    additional_tags: Optional[str] = None
    delivery: Optional[str] = None

    # URLs / media
    itemurl: Optional[str] = None
    main_image_url: Optional[str] = None
    all_images: Optional[str] = None  # JSON-encoded list per E0005

    def is_field_blank(self, field: str) -> bool:
        """Used by the orchestrator to decide whether to escalate to the
        next method for a field. Treats None / empty-string / 0 as blank.
        Note: `in_stock` and `quantity` are int — 0 is meaningful so we
        treat them specially.
        """
        val = getattr(self, field, None)
        if val is None:
            return True
        if isinstance(val, str):
            return val.strip() == ""
        if field in ("in_stock", "quantity"):
            return False  # int 0 is meaningful, not blank
        if isinstance(val, (list, dict)):
            return len(val) == 0
        return False


class E0005Row(BaseModel):
    """Final flat row written to disk. Union of all four groups."""

    dataset: DatasetMetadata = Field(default_factory=DatasetMetadata)
    store: StoreContext = Field(default_factory=StoreContext)
    merchant: MerchantContext = Field(default_factory=MerchantContext)
    product: ProductFields = Field(default_factory=ProductFields)

    def to_flat_dict(self) -> dict:
        """Flatten all four groups to a single-level dict for CSV/JSON export."""
        out = {}
        out.update(self.dataset.model_dump(exclude_none=False))
        out.update(self.store.model_dump(exclude_none=False))
        out.update(self.merchant.model_dump(exclude_none=False))
        out.update(self.product.model_dump(exclude_none=False))
        return out
