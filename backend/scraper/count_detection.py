"""
Collection Count Detection
==========================

Detects the displayed product count on collection pages using a three-stage
fallback: JSON-LD structured data, then a brand-cached CSS selector, then a
vision LLM call. Returns None when the count cannot be determined.

See docs/superpowers/specs/2026-05-14-collection-count-coverage-design.md
"""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class CountResult:
    """A detected product count and the stage that produced it."""
    count: int
    source: Literal["jsonld", "cached_selector", "vision"]
