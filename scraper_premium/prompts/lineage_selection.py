"""
Lineage Selection Prompt
========================

Analyzes product lineage frequency data to select the best ancestry path for filtering.
"""

from typing import Dict, List
from pydantic import BaseModel, Field


class LineageSelection(BaseModel):
    """Structured output for lineage selection analysis"""
    analysis: str = Field(description="Reasoning for identifying which lineages represent genuine catalog products vs recommendations/ads")
    valid_lineages: List[str] = Field(description="List of exact lineage strings that represent genuine catalog products for this category")
    confidence: str = Field(description="High/Medium/Low confidence in this selection")


def get_prompt(page_url: str, page_category: str, lineage_frequencies: Dict[str, int]) -> str:
    """Generate lineage selection prompt"""
    
    # Sort lineages by frequency (highest first)
    sorted_lineages = sorted(lineage_frequencies.items(), key=lambda x: x[1], reverse=True)
    
    # Format lineage frequency list
    lineage_list = ""
    for i, (lineage, count) in enumerate(sorted_lineages, 1):
        lineage_list += f"{i}. \"{lineage}\" ({count} products)\n"
    
    return f"""
You are analyzing product extraction results from an e-commerce category page to identify the best lineage path for filtering genuine catalog products.

**Context:**
- Page URL: {page_url}
- Category: {page_category}
- Total lineages found: {len(lineage_frequencies)}

**Goal:** Identify which lineages represent genuine catalog products for "{page_category}" vs recommendations/ads/navigation.

**Complete Lineage Frequencies (ranked by count):**
{lineage_list.strip()}

**Analysis Instructions:**
1. Classify each lineage as either:
   - **Valid catalog product** - genuine "{page_category}" products from the main category listing
   - **Invalid** - recommendations, ads, navigation, search suggestions, headers, footers, etc.

2. Look for patterns that indicate non-catalog content:
   - Search modals, suggestions, recommendations containers
   - Header/footer navigation elements  
   - Sidebar widgets
   - Advertisement sections

3. Return the exact lineage strings (from the list above) that represent genuine catalog products

**Important:** Return the complete lineage strings exactly as they appear above - no modifications. Include ALL lineages that represent legitimate "{page_category}" products.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return LineageSelection