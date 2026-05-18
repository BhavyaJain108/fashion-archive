"""
Concrete extraction methods.

Importing this module side-effect-registers every Method class via the
@register_method decorator so `hydrate_catalog()` can deserialize stored
catalogs back into runnable Method instances.
"""

from .ld_json import LdJsonPathMethod
from .og_meta import OgMetaMethod
from .dom_selector import DomSelectorMethod, DomAttrMethod
from .accordion_read import AccordionReadMethod
from .nav_tree import NavTreeMethod
from .ld_offers import LdJsonOffersAvailabilityMethod
from .ld_images import LdJsonImagesMethod, NetworkImagesMethod
from .shopify_json import ShopifyProductJsonMethod
from .network_api import NetworkApiMethod
# text_regex deliberately NOT imported — regex-based content matching does
# not generalize across products. Use location-based methods only.
from .url_pattern import UrlPatternMethod
# url_pattern IS imported — regex over `memo.url` is the one allowed
# exception, restricted by the discovery prompt + verifier to the
# `product_code` field where SKUs live at a stable position in the slug.
from .compose import ComposeMethod
# LlmBatchExtractionMethod kept registered but no longer auto-attached;
# production is LLM-free by design.
from .llm_batch import LlmBatchExtractionMethod

__all__ = [
    "LdJsonPathMethod",
    "OgMetaMethod",
    "DomSelectorMethod",
    "DomAttrMethod",
    "AccordionReadMethod",
    "NavTreeMethod",
    "LdJsonOffersAvailabilityMethod",
    "LdJsonImagesMethod",
    "NetworkImagesMethod",
    "ShopifyProductJsonMethod",
    "NetworkApiMethod",
    "UrlPatternMethod",
    "ComposeMethod",
    "LlmBatchExtractionMethod",
]
