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
    valid_lineage_numbers: List[int] = Field(description="List of numbers (1-indexed) corresponding to the lineages that represent genuine catalog products")
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
   - **Valid catalog product** - genuine "{page_category}" products from the main category listing, duplicate products, or variants.
   - **Invalid** - recommendations, ads, navigation, search suggestions, headers, footers, etc.
   - they will have the smiilar product card structure
   What we want to understand is that even with the similar product strucutre what lineage represents the actual category products vs promotional and recommended content.

2. Look for patterns that indicate non-catalog content:
   - Search modals, suggestions, recommendations containers
   - Header/footer navigation elements  
   - Sidebar widgets
   - Advertisement sections

3. Return the NUMBERS (1, 2, 3, etc.) of the lineages that represent genuine catalog products

4. You may encounter cases where: 
    - All the lineages are valid catalog products (return all numbers)
    - Very few or just one of the lineages are NOT valid catalog products (return subset of numbers. Ususally the case when there are a lot of products)
    - Only one lineage is valid catalog products (return single number)

**Important:** Return only the numbers from the numbered list above. For example, if lineages #1, #3, and #5 are valid, return [1, 3, 5].
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return LineageSelection