"""
Pagination Analysis Prompt
==========================

Analyzes page links to identify pagination patterns.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class PaginationAnalysis(BaseModel):
    """Structured output for pagination analysis"""
    pagination_detected: bool = Field(description="Whether pagination was found")
    type: str = Field(description="Type of pagination: numbered, next_button, or none")
    template: Optional[str] = Field(description="URL template for pagination")
    next_selector: Optional[str] = Field(description="CSS selector for next button if applicable")


def get_prompt(current_page_url: str, all_links: List[str]) -> str:
    """Generate pagination analysis prompt"""
    links_text = "\n".join(f"- {link}" for link in all_links)
    
    return f"""
Analyze these links from a product category page to identify pagination pattern:

Current Page: {current_page_url}
All links from page: {links_text}

Identify the pagination strategy used:

1. **numbered**: Uses ?page=2, ?page=3, /page/2, /page/3, etc.
2. **next_button**: Uses "Next" button with CSS selector (no page numbers)
3. **none**: No pagination detected

ANALYSIS PROCESS:
1. Look for links that follow pagination patterns
2. Identify if it's numbered pagination (page numbers in URLs)
3. Check for next/previous button patterns
4. If pagination exists, extract the URL template

For numbered pagination, provide template like:
- "?page=X" for query parameter pagination
- "/page/X" for path-based pagination

For next_button pagination, provide CSS selector for the next button.

Return "none" if no clear pagination pattern is found.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return PaginationAnalysis