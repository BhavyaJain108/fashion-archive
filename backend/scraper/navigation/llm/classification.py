"""
LLM-based classification functions for navigation exploration.

Uses Pydantic structured outputs to guarantee response format.

WHY PYDANTIC?
- Free-text parsing is fragile
- LLM says "1. THESE ARE SEPARATE" → regex extracts "1" → wrong result
- Pydantic schema guarantees {"expands": []} format
- No parsing code, no regex, no edge cases

See ARCHITECTURE.md "Why Pydantic structured outputs" for full explanation.
"""
from pydantic import BaseModel, Field
from scraper.navigation.llm.client import get_llm_handler, track_llm_result


class ButtonClassification(BaseModel):
    """Response format for button classification."""
    expands: list[int] = Field(default=[], description="List of 1-indexed pair numbers that EXPAND (empty if all are SEPARATE)")


async def classify_button_relationships_batch(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """
    Batch classify button-link relationships.

    Takes list of (button_name, nearby_link) pairs.
    Returns dict {button_name: 'EXPANDS' or 'SEPARATE'}.

    Optimization: LLM only reports EXPANDS cases. All others assumed SEPARATE.
    """
    if not pairs:
        return {}

    # Build list for prompt
    pairs_text = "\n".join(f"{i+1}. Button \"{btn}\" near link \"{link}\"" for i, (btn, link) in enumerate(pairs))

    prompt = f"""In a website navigation menu, classify these button-link pairs.

{pairs_text}

For each pair, does the button EXPAND/SHOW MORE of the nearby link's category?
- EXPANDS: button reveals more items within the link's category (e.g., "See More" near "CATEGORIES")
- SEPARATE: button is its own distinct category (e.g., "Dresses" near "Shoes")

Return the 1-indexed numbers of pairs where the button EXPANDS the link's category.
Most buttons are SEPARATE (their own distinct category), so the list is usually empty."""

    # Default: all SEPARATE
    result = {btn: 'SEPARATE' for btn, _ in pairs}

    try:
        llm = get_llm_handler()
        llm_result = llm.call(
            prompt,
            expected_format="json",
            response_model=ButtonClassification,
            max_tokens=100,
            operation="classify_buttons_batch"
        )

        if llm_result.get('success') and llm_result.get('data'):
            expands_list = llm_result['data'].get('expands', [])
            print(f"    [LLM] Batch classification: expands={expands_list}")

            for num in expands_list:
                idx = num - 1  # 1-indexed
                if 0 <= idx < len(pairs):
                    btn_name = pairs[idx][0]
                    result[btn_name] = 'EXPANDS'
        else:
            print(f"    [LLM] Classification failed: {llm_result.get('error', 'unknown')}")

    except Exception as e:
        print(f"    [LLM] Error in batch classification: {e}")

    return result


class SingleButtonClassification(BaseModel):
    """Response format for single button classification."""
    expands: bool = Field(description="True if button expands the link's category, False if separate")


async def classify_button_relationship(button_name: str, link_name: str) -> str:
    """
    Use LLM to determine if a button expands the nearby link's category,
    or is a separate category itself.

    Returns: 'EXPANDS' if button expands the link's category
             'SEPARATE' if button is its own category

    Examples:
    - ("See More", "CATEGORIES") → EXPANDS (button reveals more of that category)
    - ("Lingerie & Intimates", "Bikinis & Swimsuits") → SEPARATE (different categories)
    """
    prompt = f"""In a website navigation menu, there's a button "{button_name}" near a link "{link_name}".

Does this button EXPAND/SHOW MORE of the "{link_name}" category, or is it a SEPARATE category?

- EXPANDS: button reveals more items within the link's category
- SEPARATE: button is its own distinct category"""

    try:
        llm = get_llm_handler()
        result = llm.call(
            prompt,
            expected_format="json",
            response_model=SingleButtonClassification,
            max_tokens=50,
            operation="classify_button"
        )

        if result.get('success') and result.get('data'):
            expands = result['data'].get('expands', False)
            return 'EXPANDS' if expands else 'SEPARATE'
        else:
            print(f"    [LLM] Classification failed: {result.get('error', 'unknown')}")
            return 'SEPARATE'

    except Exception as e:
        print(f"    [LLM] Error classifying button: {e}")
        return 'SEPARATE'
