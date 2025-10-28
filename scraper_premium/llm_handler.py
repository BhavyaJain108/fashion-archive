"""
LLM Handler Module
==================

Generic LLM utility for handling:
- Prompt execution
- JSON response parsing
- Latency measurement
"""

import time
import json
import re
import sys
import os
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from llm_interface import ClaudeInterface
except ImportError:
    ClaudeInterface = None


# Pydantic models for structured outputs
class ProductPatternAnalysis(BaseModel):
    """Structured output for product pattern analysis"""
    analysis: str = Field(description="Explanation of reasoning and selectors considered")
    container_selector: str = Field(description="CSS selector for product containers")
    image_selector: str = Field(description="CSS selector for images within container")
    name_selector: Optional[str] = Field(description="CSS selector for names within container")
    link_selector: str = Field(description="CSS selector for product links within container")
    image_name_extraction: str = Field(description="yes or no - whether image URLs contain extractable names")
    alternative_selectors: List[str] = Field(default=[], description="Other selectors considered but rejected")


class PaginationAnalysis(BaseModel):
    """Structured output for pagination analysis"""
    pagination_detected: bool = Field(description="Whether pagination was found")
    type: str = Field(description="Type of pagination: numbered, next_button, or none")
    template: Optional[str] = Field(description="URL template for pagination")
    next_selector: Optional[str] = Field(description="CSS selector for next button if applicable")


class CategoryLink(BaseModel):
    """Individual category URL with reasoning"""
    url: str = Field(description="The category URL")
    reasoning: str = Field(description="Why this URL was included")


class NavigationAnalysis(BaseModel):
    """Structured output for navigation/category analysis"""
    included_urls: List[CategoryLink] = Field(description="Product category URLs that should be included")
    excluded_urls: List[CategoryLink] = Field(description="URLs that were excluded and why")


class LLMHandler:
    """
    Generic handler for LLM interactions.
    
    Simple utility that:
    - Takes a prompt and expected output format
    - Returns parsed JSON response
    - Tracks latency
    """
    
    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize LLM Handler
        
        Args:
            model: Claude model to use (default: Sonnet 3.5 for quality)
        """
        self.model = model
        if ClaudeInterface:
            self.client = ClaudeInterface(model=model)
        else:
            self.client = None
            print("⚠️  ClaudeInterface not available - WebFetch calls will be used")
    
    def call(self, prompt: str, expected_format: str = "json", response_model: BaseModel = None, max_tokens: int = 8192) -> Dict[str, Any]:
        """
        Generic LLM call with response parsing
        
        Args:
            prompt: The prompt to send
            expected_format: Expected response format ("json", "text")
            response_model: Pydantic model class for structured JSON output
            max_tokens: Maximum tokens for response (default: 8192)
            
        Returns:
            Dictionary with parsed response and metadata
        """
        # If using structured output, append JSON schema to prompt
        if expected_format == "json" and response_model:
            schema = self._get_json_schema(response_model)
            prompt = f"{prompt}\n\nRespond with valid JSON matching this schema:\n{schema}"
        start_time = time.time()
        
        try:
            if self.client:
                # Use ClaudeInterface if available
                response = self.client.generate(prompt, max_tokens=max_tokens)
            else:
                # Fallback - caller should handle WebFetch
                raise NotImplementedError("No LLM client available - use WebFetch externally")
            
            latency_ms = (time.time() - start_time) * 1000
            
            if expected_format == "json":
                return self._parse_json_response(response, latency_ms, response_model)
            else:
                return {
                    "response": response,
                    "latency_ms": latency_ms,
                    "success": True
                }
                
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "error": str(e),
                "latency_ms": latency_ms,
                "success": False
            }
    
    def _get_json_schema(self, model_class: BaseModel) -> str:
        """Generate JSON schema from Pydantic model"""
        try:
            schema = model_class.model_json_schema()
            return json.dumps(schema, indent=2)
        except Exception as e:
            return f"Error generating schema: {e}"
    
    def _parse_json_response(self, response: str, latency_ms: float, response_model: BaseModel = None) -> Dict[str, Any]:
        """Parse JSON from LLM response with robust error handling"""
        try:
            # Try to extract JSON from response
            if isinstance(response, str):
                # Look for JSON in the response
                start_idx = response.find('{')
                end_idx = response.rfind('}') + 1
                if start_idx != -1 and end_idx != -1:
                    json_str = response[start_idx:end_idx]
                    
                    # Try to fix common JSON issues
                    json_str = self._fix_common_json_issues(json_str)
                    
                    # Parse JSON
                    raw_result = json.loads(json_str)
                    
                    # If we have a Pydantic model, validate and parse
                    if response_model:
                        try:
                            validated_result = response_model(**raw_result)
                            result = validated_result.model_dump()
                        except Exception as validation_error:
                            print(f"⚠️  Pydantic validation failed: {validation_error}")
                            result = raw_result  # Fall back to raw JSON
                    else:
                        result = raw_result
                else:
                    raise ValueError("No JSON found in response")
            else:
                result = response
            
            # Add metadata
            return {
                "data": result,
                "latency_ms": latency_ms,
                "success": True
            }
            
        except (json.JSONDecodeError, ValueError) as e:
            return {
                "error": f"Failed to parse JSON: {str(e)}",
                "raw_response": response,
                "latency_ms": latency_ms,
                "success": False
            }
    
    def _fix_common_json_issues(self, json_str: str) -> str:
        """Fix common JSON formatting issues"""
        # Remove trailing commas before closing brackets/braces
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        # Ensure double quotes around keys and string values
        # This is a simple fix - more complex scenarios might need better handling
        
        return json_str
