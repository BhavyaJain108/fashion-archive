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
from typing import Dict, Any

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from llm_interface import ClaudeInterface
except ImportError:
    ClaudeInterface = None


class LLMHandler:
    """
    Generic handler for LLM interactions.
    
    Simple utility that:
    - Takes a prompt and expected output format
    - Returns parsed JSON response
    - Tracks latency
    """
    
    def __init__(self, model: str = "claude-3-5-sonnet-20241022"):
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
    
    def call(self, prompt: str, expected_format: str = "json") -> Dict[str, Any]:
        """
        Generic LLM call with response parsing
        
        Args:
            prompt: The prompt to send
            expected_format: Expected response format ("json", "text")
            
        Returns:
            Dictionary with parsed response and metadata
        """
        start_time = time.time()
        
        try:
            if self.client:
                # Use ClaudeInterface if available
                response = self.client.generate(prompt, max_tokens=8192)
            else:
                # Fallback - caller should handle WebFetch
                raise NotImplementedError("No LLM client available - use WebFetch externally")
            
            latency_ms = (time.time() - start_time) * 1000
            
            if expected_format == "json":
                return self._parse_json_response(response, latency_ms)
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
    
    def _parse_json_response(self, response: str, latency_ms: float) -> Dict[str, Any]:
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
                    
                    result = json.loads(json_str)
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
