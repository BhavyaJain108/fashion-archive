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
    - Tracks latency and token usage
    """

    # Class-level usage tracking (shared across all instances)
    _total_input_tokens = 0
    _total_output_tokens = 0
    _call_count = 0

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

    @classmethod
    def get_total_usage(cls) -> Dict[str, Any]:
        """Get cumulative token usage across all calls."""
        # Claude Sonnet 4 pricing (per 1M tokens)
        INPUT_COST_PER_M = 3.0   # $3 per 1M input tokens
        OUTPUT_COST_PER_M = 15.0  # $15 per 1M output tokens

        input_cost = (cls._total_input_tokens / 1_000_000) * INPUT_COST_PER_M
        output_cost = (cls._total_output_tokens / 1_000_000) * OUTPUT_COST_PER_M

        return {
            "input_tokens": cls._total_input_tokens,
            "output_tokens": cls._total_output_tokens,
            "total_tokens": cls._total_input_tokens + cls._total_output_tokens,
            "call_count": cls._call_count,
            "estimated_cost_usd": round(input_cost + output_cost, 4),
            "input_cost_usd": round(input_cost, 4),
            "output_cost_usd": round(output_cost, 4),
        }

    @classmethod
    def reset_usage(cls):
        """Reset usage counters."""
        cls._total_input_tokens = 0
        cls._total_output_tokens = 0
        cls._call_count = 0

    def _track_usage(self, usage: Optional[Dict[str, int]]):
        """Track usage from a call."""
        if usage:
            LLMHandler._total_input_tokens += usage.get('input_tokens', 0)
            LLMHandler._total_output_tokens += usage.get('output_tokens', 0)
            LLMHandler._call_count += 1
    
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

                        # Get token usage if available
                        usage = self.client.get_last_usage() if hasattr(self.client, 'get_last_usage') else None
                        self._track_usage(usage)

                        return {
                            "data": result,
                            "latency_ms": latency_ms,
                            "success": True,
                            "attempts": attempt + 1,
                            "usage": usage
                        }
                    else:
                        # Regular text generation
                        response = self.client.generate(prompt, max_tokens=max_tokens)
                        latency_ms = (time.time() - start_time) * 1000

                        # Get token usage if available
                        usage = self.client.get_last_usage() if hasattr(self.client, 'get_last_usage') else None
                        self._track_usage(usage)

                        return {
                            "response": response,
                            "latency_ms": latency_ms,
                            "success": True,
                            "attempts": attempt + 1,
                            "usage": usage
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
    
