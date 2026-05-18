"""
LLM client wrapper with usage tracking.

Provides centralized LLM access for the navigation scraper.
Process-level singleton - shared across all sessions.

Usage:
    # New way (preferred)
    client = LLMClient()
    result = client.call(prompt, ...)

    # Old way (backwards compatible)
    llm = get_llm_handler()
    result = llm.call(prompt, ...)
    track_llm_result(result)
"""

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class UsageTracker:
    """
    Track LLM token usage.

    Accumulates usage across calls for cost monitoring.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0

    def track(self, result: dict):
        """Track usage from an LLM call result."""
        if result.get("usage"):
            self.input_tokens += result["usage"].get("input_tokens", 0)
            self.output_tokens += result["usage"].get("output_tokens", 0)
        self.call_count += 1

    def reset(self):
        """Reset all tracking."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.call_count = 0

    def to_dict(self) -> dict:
        """Export as dictionary."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "call_count": self.call_count
        }

    def __str__(self) -> str:
        return f"LLM Usage: {self.call_count} calls, {self.input_tokens} in, {self.output_tokens} out"


class LLMClient:
    """
    Singleton LLM client with usage tracking.

    Process-level - shared across all sessions for efficiency.
    The LLMHandler is expensive to create (loads config, sets up client).

    Usage:
        client = LLMClient()  # Always returns same instance
        result = client.call(prompt, max_tokens=100)
        print(client.usage)  # See accumulated stats
    """
    _instance: Optional['LLMClient'] = None

    def __new__(cls) -> 'LLMClient':
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._handler = None
            instance._usage = UsageTracker()
            cls._instance = instance
        return cls._instance

    @property
    def handler(self):
        """Lazy-load LLMHandler on first use."""
        if self._handler is None:
            from scraper.llm_handler import LLMHandler
            self._handler = LLMHandler()
        return self._handler

    @property
    def usage(self) -> UsageTracker:
        """Get usage tracker."""
        return self._usage

    def call(self, prompt: str, **kwargs) -> dict:
        """
        Call LLM with structured output support.

        Wraps handler.call() with automatic usage tracking.
        """
        result = self.handler.call(prompt, **kwargs)
        self._usage.track(result)
        return result

    def call_text(self, prompt: str, **kwargs) -> dict:
        """
        Call LLM for text response.

        Wraps handler.call_text() with automatic usage tracking.
        """
        result = self.handler.call_text(prompt, **kwargs)
        self._usage.track(result)
        return result

    def call_with_image(self, prompt: str, image_b64: str, **kwargs) -> dict:
        """
        Call LLM with image input.

        Wraps handler.call_with_image() with automatic usage tracking.
        """
        result = self.handler.call_with_image(prompt, image_b64, **kwargs)
        self._usage.track(result)
        return result

    def reset_usage(self):
        """Reset usage tracking."""
        self._usage.reset()

    def get_usage(self) -> dict:
        """Get usage as dictionary."""
        return self._usage.to_dict()


# =============================================================================
# Backwards Compatibility Layer
# =============================================================================
# These match the old API exactly. New code should use LLMClient directly.

# Keep old module-level state for code that imports it directly
_llm_handler = None
_llm_usage = {"input_tokens": 0, "output_tokens": 0}


def get_llm_handler():
    """
    Get or create the module-level LLMHandler.

    DEPRECATED: Use LLMClient() instead.
    Kept for backwards compatibility.
    """
    # Use the singleton's handler to avoid duplicate instances
    return LLMClient().handler


def track_llm_result(result: dict):
    """
    Track LLM usage from a call result.

    DEPRECATED: Use LLMClient() which tracks automatically.
    Kept for backwards compatibility.
    """
    # Track in both places during migration
    global _llm_usage
    if result.get("usage"):
        _llm_usage["input_tokens"] += result["usage"].get("input_tokens", 0)
        _llm_usage["output_tokens"] += result["usage"].get("output_tokens", 0)
    # Also track in singleton
    LLMClient()._usage.track(result)


def get_llm_usage() -> dict:
    """
    Get current LLM usage stats.

    Returns combined stats from both old and new tracking.
    """
    # Return from singleton (authoritative source)
    return LLMClient().get_usage()


def reset_llm_usage():
    """Reset LLM usage tracking."""
    global _llm_usage
    _llm_usage = {"input_tokens": 0, "output_tokens": 0}
    LLMClient().reset_usage()


def call_llm(prompt: str, max_tokens: int = 500, **kwargs) -> dict:
    """
    Call LLM with the given prompt and track usage.

    DEPRECATED: Use LLMClient().call_text() instead.
    """
    return LLMClient().call_text(prompt=prompt, max_tokens=max_tokens, **kwargs)
