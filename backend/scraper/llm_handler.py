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
    # Import ClaudeInterface from high_fashion.tools.llm_interface
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from high_fashion.tools.llm_interface import ClaudeInterface
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
    
    def call(self, prompt: str, expected_format: str = "json", response_model: BaseModel = None, max_tokens: int = 8192, max_retries: int = 4, debug: bool = False) -> Dict[str, Any]:
        """
        Generic LLM call with response parsing and intelligent retry logic
        
        Args:
            prompt: The prompt to send
            expected_format: Expected response format ("json", "text")
            response_model: Pydantic model class for structured JSON output
            max_tokens: Maximum tokens for response (default: 8192)
            max_retries: Maximum number of retries on different errors (default: 4)
            
        Returns:
            Dictionary with parsed response and metadata
        """
        start_time = time.time()
        errors_seen = set()
        
        for attempt in range(max_retries + 1):
            try:
                if self.client:
                    if expected_format == "json" and response_model:
                        # Use structured output with native API
                        response = self.client.generate(prompt, max_tokens=max_tokens, response_model=response_model, debug=debug)

                        # Check for empty response (common LLM failure mode)
                        if not response or response == {}:
                            empty_error = "LLM returned empty structured output ({})"
                            print(f"⚠️  {empty_error}")

                            # Treat empty response as a retriable error
                            if attempt < max_retries:
                                wait_seconds = 2
                                print(f"🔄 Retry {attempt + 1}/{max_retries} after {wait_seconds}s due to empty response")
                                time.sleep(wait_seconds)
                                continue  # Retry
                            else:
                                # Last attempt failed, return error
                                latency_ms = (time.time() - start_time) * 1000
                                return {
                                    "error": empty_error,
                                    "latency_ms": latency_ms,
                                    "success": False,
                                    "attempts": attempt + 1
                                }

                        latency_ms = (time.time() - start_time) * 1000

                        # response is already the structured data
                        if response_model:
                            try:
                                validated_result = response_model(**response)
                                result = validated_result.model_dump()
                            except Exception as validation_error:
                                print(f"⚠️  Pydantic validation failed: {validation_error}")
                                print(f"    Raw response: {response}")

                                # If validation fails, treat as retriable error
                                if attempt < max_retries:
                                    wait_seconds = 2
                                    print(f"🔄 Retry {attempt + 1}/{max_retries} after {wait_seconds}s due to validation failure")
                                    time.sleep(wait_seconds)
                                    continue  # Retry
                                else:
                                    # Last attempt, return the error
                                    return {
                                        "error": f"Validation failed: {validation_error}",
                                        "latency_ms": latency_ms,
                                        "success": False,
                                        "attempts": attempt + 1,
                                        "raw_response": response
                                    }
                        else:
                            result = response

                        return {
                            "data": result,
                            "latency_ms": latency_ms,
                            "success": True,
                            "attempts": attempt + 1
                        }
                    else:
                        # Regular text generation
                        response = self.client.generate(prompt, max_tokens=max_tokens)
                        latency_ms = (time.time() - start_time) * 1000
                        
                        return {
                            "response": response,
                            "latency_ms": latency_ms,
                            "success": True,
                            "attempts": attempt + 1
                        }
                else:
                    raise NotImplementedError("No LLM client available - use WebFetch externally")
                    
            except Exception as e:
                error_str = str(e)
                error_type = type(e).__name__
                
                # Check if this is a new error we haven't seen
                error_signature = f"{error_type}: {error_str}"
                
                # Determine if we should retry
                should_retry = False
                wait_seconds = 0
                
                # Always retry on timeout/rate limit errors
                if any(keyword in error_str.lower() for keyword in ['timeout', 'rate limit', 'too many requests', 'overloaded']):
                    should_retry = True
                    wait_seconds = min(2 ** attempt, 30)  # Exponential backoff, max 30s
                    print(f"🔄 Retry {attempt + 1}/{max_retries} after {wait_seconds}s due to: {error_str}")
                
                # Retry on new errors (not seen before)
                elif error_signature not in errors_seen:
                    should_retry = True
                    errors_seen.add(error_signature)
                    wait_seconds = 1  # Short wait for new errors
                    print(f"🔄 Retry {attempt + 1}/{max_retries} on new error: {error_str}")
                
                # Don't retry if we've seen this exact error before (unless it's timeout/rate limit)
                else:
                    print(f"❌ Skipping retry - already seen error: {error_str}")
                
                # If this is the last attempt or we shouldn't retry, return error
                if attempt >= max_retries or not should_retry:
                    latency_ms = (time.time() - start_time) * 1000
                    return {
                        "error": error_str,
                        "latency_ms": latency_ms,
                        "success": False,
                        "attempts": attempt + 1,
                        "errors_seen": list(errors_seen)
                    }
                
                # Wait before retry
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
    
