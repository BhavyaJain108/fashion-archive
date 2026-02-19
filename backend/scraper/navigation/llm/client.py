"""
LLM client wrapper with usage tracking.
"""
from typing import Optional

# Module-level state for LLM handler and usage tracking
_llm_handler = None
_llm_usage = {"input_tokens": 0, "output_tokens": 0}


def get_llm_handler():
    """Get or create the module-level LLMHandler."""
    global _llm_handler
    if _llm_handler is None:
        from scraper.llm_handler import LLMHandler
        _llm_handler = LLMHandler()
    return _llm_handler


def track_llm_result(result: dict):
    """Track LLM usage from a call result."""
    global _llm_usage
    if result.get("usage"):
        _llm_usage["input_tokens"] += result["usage"].get("input_tokens", 0)
        _llm_usage["output_tokens"] += result["usage"].get("output_tokens", 0)


def get_llm_usage() -> dict:
    """Get current LLM usage stats."""
    return _llm_usage.copy()


def reset_llm_usage():
    """Reset LLM usage tracking."""
    global _llm_usage
    _llm_usage = {"input_tokens": 0, "output_tokens": 0}


def call_llm(prompt: str, max_tokens: int = 500) -> dict:
    """
    Call LLM with the given prompt and track usage.

    Returns dict with 'text' and 'usage' keys.
    """
    llm = get_llm_handler()
    result = llm.call_text(prompt=prompt, max_tokens=max_tokens)
    track_llm_result(result)
    return result
