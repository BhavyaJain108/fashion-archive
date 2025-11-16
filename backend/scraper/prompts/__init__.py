"""
Centralized Prompt Management
============================

Provides easy access to all prompts and their response models.
"""

from . import product_pattern_analysis
from . import navigation_analysis
from . import product_link_finder


class PromptManager:
    """Central manager for all prompts and their models"""
    
    @staticmethod
    def get_product_pattern_prompt(product_link: str, context_html: str):
        """Get product pattern analysis prompt and model"""
        return {
            'prompt': product_pattern_analysis.get_prompt(product_link, context_html),
            'model': product_pattern_analysis.get_response_model()
        }
    
    @staticmethod
    def get_navigation_analysis_prompt(website_url: str, links: list):
        """Get navigation analysis prompt and model"""
        return {
            'prompt': navigation_analysis.get_prompt(website_url, links),
            'model': navigation_analysis.get_response_model()
        }
    
    
    @staticmethod
    def get_product_link_finder_prompt(base_url: str, all_links: list):
        """Get product link finder prompt and model"""
        return {
            'prompt': product_link_finder.get_prompt(base_url, all_links),
            'model': product_link_finder.get_response_model()
        }


# Export models for direct import
from .product_pattern_analysis import ProductPatternAnalysis
from .navigation_analysis import NavigationAnalysis, CategoryLink
from .product_link_finder import ProductLinkResponse