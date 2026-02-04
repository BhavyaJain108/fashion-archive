"""
LLM Handler Module
==================

Unified LLM interface for the entire pipeline.
All LLM calls should go through this module for:
- Consistent token tracking by operation
- Cost calculation
- Centralized metrics reporting
"""

import time
import json
import re
import sys
import os
from datetime import datetime
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


# Claude Sonnet 4 pricing (per 1M tokens)
INPUT_COST_PER_M = 3.0   # $3 per 1M input tokens
OUTPUT_COST_PER_M = 15.0  # $15 per 1M output tokens


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD from token counts."""
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_M
    output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_M
    return input_cost + output_cost


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


class LLMUsageTracker:
    """
    Centralized LLM usage tracking with operation-level granularity.

    Tracks all LLM calls by:
    - Stage (navigation, urls, products)
    - Operation name (e.g., "nav_tree_extraction", "gallery_discovery")

    Usage:
        # At start of stage
        LLMUsageTracker.set_stage("navigation")

        # During LLM calls
        handler = LLMHandler()
        result = handler.call(prompt, operation="nav_tree_extraction")

        # Get stage summary
        summary = LLMUsageTracker.get_stage_summary("navigation")
    """

    # Global state
    _current_stage: str = "unknown"
    _operations: Dict[str, Dict[str, Any]] = {}  # {stage: {operation: {calls, input, output, cost}}}
    _stage_start_times: Dict[str, float] = {}  # {stage: start_time}

    @classmethod
    def set_stage(cls, stage: str):
        """Set the current stage and reset its tracking."""
        cls._current_stage = stage
        cls._operations[stage] = {}
        cls._stage_start_times[stage] = time.time()

    @classmethod
    def get_current_stage(cls) -> str:
        """Get current stage name."""
        return cls._current_stage

    @classmethod
    def record_call(cls, operation: str, input_tokens: int, output_tokens: int,
                    stage: str = None):
        """Record an LLM call with its usage."""
        stage = stage or cls._current_stage

        if stage not in cls._operations:
            cls._operations[stage] = {}

        if operation not in cls._operations[stage]:
            cls._operations[stage][operation] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0
            }

        op = cls._operations[stage][operation]
        op["calls"] += 1
        op["input_tokens"] += input_tokens
        op["output_tokens"] += output_tokens
        op["cost"] += calculate_cost(input_tokens, output_tokens)

    @classmethod
    def get_stage_summary(cls, stage: str) -> Dict[str, Any]:
        """Get summary of all operations for a stage."""
        if stage not in cls._operations:
            return {
                "operations": [],
                "summary": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}
            }

        operations = []
        total_calls = 0
        total_input = 0
        total_output = 0
        total_cost = 0.0

        for op_name, op_data in cls._operations[stage].items():
            operations.append({
                "name": op_name,
                "calls": op_data["calls"],
                "input_tokens": op_data["input_tokens"],
                "output_tokens": op_data["output_tokens"],
                "cost": op_data["cost"]
            })
            total_calls += op_data["calls"]
            total_input += op_data["input_tokens"]
            total_output += op_data["output_tokens"]
            total_cost += op_data["cost"]

        return {
            "operations": operations,
            "summary": {
                "calls": total_calls,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cost": round(total_cost, 6)
            }
        }

    @classmethod
    def get_all_stages_summary(cls) -> Dict[str, Any]:
        """Get summary across all stages."""
        result = {}
        grand_total = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}

        for stage in cls._operations:
            stage_summary = cls.get_stage_summary(stage)
            result[stage] = stage_summary
            grand_total["calls"] += stage_summary["summary"]["calls"]
            grand_total["input_tokens"] += stage_summary["summary"]["input_tokens"]
            grand_total["output_tokens"] += stage_summary["summary"]["output_tokens"]
            grand_total["cost"] += stage_summary["summary"]["cost"]

        result["_total"] = {
            "summary": grand_total
        }
        return result

    @classmethod
    def reset_all(cls):
        """Reset all tracking data."""
        cls._current_stage = "unknown"
        cls._operations = {}
        cls._stage_start_times = {}

    @classmethod
    def reset_stage(cls, stage: str):
        """Reset tracking for a specific stage."""
        if stage in cls._operations:
            del cls._operations[stage]
        if stage in cls._stage_start_times:
            del cls._stage_start_times[stage]


class LLMHandler:
    """
    Unified handler for all LLM interactions in the pipeline.

    All LLM calls should go through this class for:
    - Consistent token tracking by operation
    - Cost calculation
    - Retry logic
    - Structured output parsing

    Usage:
        handler = LLMHandler()
        result = handler.call(prompt, operation="gallery_discovery")
    """

    # Class-level usage tracking (legacy - for backwards compatibility)
    _total_input_tokens = 0
    _total_output_tokens = 0
    _call_count = 0

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize LLM Handler.

        Args:
            model: Claude model to use (default: Sonnet 4)
        """
        self.model = model
        if ClaudeInterface:
            self.client = ClaudeInterface(model=model)
        else:
            self.client = None
            print("⚠️  ClaudeInterface not available - WebFetch calls will be used")

    @classmethod
    def get_total_usage(cls) -> Dict[str, Any]:
        """Get cumulative token usage across all calls (legacy method)."""
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
        """Reset usage counters (legacy method)."""
        cls._total_input_tokens = 0
        cls._total_output_tokens = 0
        cls._call_count = 0

    @classmethod
    def get_snapshot(cls) -> Dict[str, int]:
        """Return current usage state for delta calculation (legacy method)."""
        return {
            "input_tokens": cls._total_input_tokens,
            "output_tokens": cls._total_output_tokens,
            "call_count": cls._call_count
        }

    def _track_usage(self, usage: Optional[Dict[str, int]], operation: str = "unknown"):
        """Track usage from a call - updates both legacy counters and new tracker."""
        if usage:
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)

            # Legacy tracking
            LLMHandler._total_input_tokens += input_tokens
            LLMHandler._total_output_tokens += output_tokens
            LLMHandler._call_count += 1

            # New operation-level tracking
            LLMUsageTracker.record_call(operation, input_tokens, output_tokens)

    def call(self, prompt: str, expected_format: str = "json", response_model: BaseModel = None,
             max_tokens: int = 8192, max_retries: int = 4, debug: bool = False,
             operation: str = "llm_call") -> Dict[str, Any]:
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
                        self._track_usage(usage, operation)

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
                        self._track_usage(usage, operation)

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

    def call_with_image(self, prompt: str, image_b64: str, media_type: str = "image/png",
                        max_tokens: int = 8000, operation: str = "vision_call") -> Dict[str, Any]:
        """
        LLM call with an image (vision).

        Args:
            prompt: Text prompt to send
            image_b64: Base64-encoded image data
            media_type: Image media type (default: image/png)
            max_tokens: Maximum tokens for response
            operation: Operation name for tracking

        Returns:
            Dictionary with response text and metadata
        """
        import os
        from anthropic import Anthropic

        start_time = time.time()

        try:
            # Use Anthropic client directly for vision calls
            client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))

            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            latency_ms = (time.time() - start_time) * 1000

            # Track usage
            if response.usage:
                usage = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens
                }
                self._track_usage(usage, operation)
            else:
                usage = None

            result_text = response.content[0].text.strip()

            return {
                "response": result_text,
                "latency_ms": latency_ms,
                "success": True,
                "usage": usage
            }

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "error": str(e),
                "latency_ms": latency_ms,
                "success": False
            }

    def call_text(self, prompt: str, max_tokens: int = 1500,
                  operation: str = "text_call") -> Dict[str, Any]:
        """
        Simple text-only LLM call.

        Args:
            prompt: Text prompt to send
            max_tokens: Maximum tokens for response
            operation: Operation name for tracking

        Returns:
            Dictionary with response text and metadata
        """
        import os
        from anthropic import Anthropic

        start_time = time.time()

        try:
            client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY'))

            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )

            latency_ms = (time.time() - start_time) * 1000

            # Track usage
            if response.usage:
                usage = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens
                }
                self._track_usage(usage, operation)
            else:
                usage = None

            result_text = response.content[0].text.strip()

            return {
                "response": result_text,
                "latency_ms": latency_ms,
                "success": True,
                "usage": usage
            }

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "error": str(e),
                "latency_ms": latency_ms,
                "success": False
            }
    
