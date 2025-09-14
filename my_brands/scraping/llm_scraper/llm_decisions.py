#!/usr/bin/env python3
"""
LLM Decision Making for Fashion Brand Scraping
==============================================

This module handles all pattern matching and decision making through LLM calls
instead of hardcoded patterns, making the scraper more adaptable to different sites.
"""

from typing import List, Dict, Any, Optional
import json


class LLMDecisionMaker:
    """Handles all LLM-based decision making for the scraper"""
    
    def __init__(self, llm_interface):
        """
        Initialize with an LLM interface
        
        Args:
            llm_interface: The LLM interface to use for decisions
        """
        self.llm = llm_interface
    
    # ==========================================
    # NAVIGATION STRATEGY DECISIONS
    # ==========================================
    
    def get_navigation_strategy_validation_prompt(self, strategy: str) -> str:
        """
        Validate if a navigation strategy response is valid
        """
        return f"""
Is this a valid navigation strategy response: "{strategy}"?

Valid strategies are:
1. "menu" - User needs to click a menu first
2. "all_products_link" - There's a link to all products
3. "category_links" - There are category/collection links
4. "products_already_here" - Products are already visible

Respond with JSON:
{{
    "is_valid": true/false,
    "corrected_strategy": "the correct strategy if invalid, or the same if valid"
}}

Only respond with valid JSON.
""".strip()
    
    # ==========================================
    # PAGINATION DETECTION DECISIONS
    # ==========================================
    
    def get_pagination_url_classification_prompt(self, url: str, link_text: str, current_page_url: str) -> str:
        """
        Determine if a URL is a pagination/collection link that should be followed
        """
        return f"""
Analyze this link from a fashion brand website and determine if it leads to more products.

Current page URL: {current_page_url}
Link URL: {url}
Link text: "{link_text}"

Is this link likely to lead to more products? Consider:
1. Pagination links (next page, page numbers, load more)
2. Collection/category pages (different product groups)
3. Lookbook pages (seasonal collections)
4. Shop/catalog sections

But AVOID:
1. Individual product pages
2. About/contact/policy pages
3. Account/login pages
4. Blog/news pages
5. External links

Respond with JSON:
{{
    "is_product_page": true/false,
    "confidence": 0.0-1.0,
    "type": "pagination" | "collection" | "category" | "lookbook" | "other",
    "reasoning": "brief explanation"
}}

Only respond with valid JSON.
""".strip()
    
    def get_bulk_link_classification_prompt(self, links: List[Dict[str, str]], current_page_url: str) -> str:
        """
        Classify multiple links at once for efficiency
        """
        return f"""
Analyze these links from a fashion brand website and identify which lead to more products.

Current page URL: {current_page_url}

Links to analyze:
{json.dumps(links, indent=2)}

For each link, determine if it leads to more products (pagination, collections, categories, lookbooks).

Respond with JSON array where each item has:
{{
    "url": "the URL",
    "is_product_page": true/false,
    "confidence": 0.0-1.0,
    "type": "pagination" | "collection" | "category" | "lookbook" | "skip",
    "reasoning": "brief explanation"
}}

Focus on links that lead to MORE products, not individual items.

Only respond with valid JSON array.
""".strip()
    
    # ==========================================
    # MENU STRATEGY DECISIONS
    # ==========================================
    
    def get_menu_strategy_validation_prompt(self, strategy: str) -> str:
        """
        Validate menu navigation strategy
        """
        return f"""
Is this a valid menu strategy response: "{strategy}"?

Valid strategies are:
1. "all_products_link" - There's a link to see all products
2. "category_links" - There are separate category links to visit

Respond with JSON:
{{
    "is_valid": true/false,
    "corrected_strategy": "the correct strategy if invalid, or the same if valid"
}}

Only respond with valid JSON.
""".strip()
    
    # ==========================================
    # PRODUCT EXTRACTION METHOD DECISIONS
    # ==========================================
    
    def get_extraction_method_classification_prompt(self, method: str) -> str:
        """
        Validate product extraction method
        """
        return f"""
Is this a valid image extraction method: "{method}"?

Valid methods are:
1. "img_src" - Image URL is in src attribute of img tag
2. "img_data_src" - Image URL is in data-src or similar lazy-load attribute
3. "background_image" - Image URL is in CSS background-image style

Respond with JSON:
{{
    "is_valid": true/false,
    "corrected_method": "the correct method if invalid, or the same if valid"
}}

Only respond with valid JSON.
""".strip()
    
    # ==========================================
    # LINK TEXT ANALYSIS
    # ==========================================
    
    def get_link_text_analysis_prompt(self, link_text: str) -> str:
        """
        Analyze link text to determine its purpose
        """
        return f"""
Analyze this link text from a fashion website: "{link_text}"

What type of link is this most likely to be?

Options:
1. "pagination" - Next page, page number, load more
2. "collection" - Product collection or category
3. "product" - Individual product
4. "navigation" - Site navigation (about, contact, etc.)
5. "action" - User action (login, cart, etc.)

Respond with JSON:
{{
    "type": "pagination" | "collection" | "product" | "navigation" | "action",
    "confidence": 0.0-1.0
}}

Only respond with valid JSON.
""".strip()
    
    # ==========================================
    # CSS SELECTOR VALIDATION
    # ==========================================
    
    def get_selector_purpose_prompt(self, selector: str, sample_html: str = "") -> str:
        """
        Determine what a CSS selector is likely selecting
        """
        return f"""
Analyze this CSS selector from a fashion website: "{selector}"

{f"Sample HTML context: {sample_html[:500]}" if sample_html else ""}

What is this selector most likely targeting?

Options:
1. "product_container" - Container for product cards
2. "product_image" - Product images
3. "product_name" - Product titles/names
4. "pagination" - Pagination controls
5. "navigation" - Navigation elements
6. "other" - Something else

Respond with JSON:
{{
    "purpose": "product_container" | "product_image" | "product_name" | "pagination" | "navigation" | "other",
    "confidence": 0.0-1.0
}}

Only respond with valid JSON.
""".strip()
    
    # ==========================================
    # PAGINATION STRATEGY DECISIONS
    # ==========================================
    
    def get_pagination_strategy_analysis_prompt(self, html_snippet: str, current_url: str) -> str:
        """
        Analyze HTML to determine pagination strategy
        """
        return f"""
Analyze this HTML snippet from a product page to determine how to load more products.

Current URL: {current_url}
HTML (first 2000 chars): {html_snippet[:2000]}

Look for:
1. Page numbers or next/previous buttons
2. "Load More" or "Show More" buttons
3. Infinite scroll indicators
4. Signs that all products are already loaded

Respond with JSON:
{{
    "strategy": "pagination" | "load_more" | "infinite_scroll" | "all_loaded",
    "selector": "CSS selector if applicable",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}

Only respond with valid JSON.
""".strip()
    
    # ==========================================
    # UTILITY METHODS
    # ==========================================
    
    async def decide(self, prompt: str) -> Dict[str, Any]:
        """
        Make a decision using the LLM
        
        Args:
            prompt: The decision prompt
            
        Returns:
            Parsed JSON response from LLM
        """
        try:
            # Use asyncio to run the synchronous LLM call
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.llm.generate,
                prompt,
                200,  # max_tokens
                0.1   # temperature
            )
            # Clean and parse response
            response = response.strip()
            
            # Try to extract JSON from response
            try:
                if response.startswith('{'):
                    return json.loads(response)
                elif response.startswith('['):
                    return json.loads(response)
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON decode error, attempting to fix: {e}")
                
            # Try to find and extract JSON from response
            import re
            
            # First try to find complete JSON object or array
            json_patterns = [
                r'\{[^{}]*\}',  # Simple JSON object
                r'\[[^\[\]]*\]',  # Simple JSON array
                r'\{.*?\}(?=\s*$)',  # JSON object at end
                r'\[.*?\](?=\s*$)',  # JSON array at end
            ]
            
            for pattern in json_patterns:
                json_match = re.search(pattern, response, re.DOTALL)
                if json_match:
                    try:
                        return json.loads(json_match.group(0))
                    except json.JSONDecodeError:
                        continue
            
            # If still no luck, try to fix common issues
            # Remove any text before first { or [
            if '{' in response:
                response = response[response.find('{'):]
                # Remove any text after last }
                if response.rfind('}') != -1:
                    response = response[:response.rfind('}')+1]
                    try:
                        return json.loads(response)
                    except json.JSONDecodeError:
                        pass
                        
            raise ValueError(f"Could not parse JSON from response: {response[:200]}...")
            
        except Exception as e:
            print(f"⚠️ LLM decision error: {e}")
            # Return safe default
            return {"error": str(e), "is_valid": False, "confidence": 0.0}
    
    async def batch_decide(self, prompts: List[str]) -> List[Dict[str, Any]]:
        """
        Make multiple decisions in parallel
        
        Args:
            prompts: List of decision prompts
            
        Returns:
            List of parsed JSON responses
        """
        import asyncio
        tasks = [self.decide(prompt) for prompt in prompts]
        return await asyncio.gather(*tasks)