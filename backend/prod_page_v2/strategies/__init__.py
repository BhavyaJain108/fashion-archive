"""
Extraction strategies for different platform types.
"""

from .base import BaseStrategy
from .shopify import ShopifyStrategy
from .shopify_graphql import ShopifyGraphQLStrategy
from .ld_json import LdJsonStrategy
from .api_intercept import ApiInterceptStrategy
from .html_meta import HtmlMetaStrategy
from .embedded_json import EmbeddedJsonStrategy

__all__ = [
    'BaseStrategy',
    'ShopifyStrategy',
    'ShopifyGraphQLStrategy',
    'LdJsonStrategy',
    'ApiInterceptStrategy',
    'HtmlMetaStrategy',
    'EmbeddedJsonStrategy',
]
