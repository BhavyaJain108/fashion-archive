"""
Pagination Detection Prompt
============================

Analyzes bottom page links after scrolling to detect pagination patterns for multi-page extraction.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class PaginationDetection(BaseModel):
    """Structured output for Stage 4 pagination detection"""
    pagination_found: bool = Field(description="Whether pagination links were detected at bottom of page")
    pagination_type: str = Field(description="Type: 'page_links', 'next_button', or 'none'")
    url_template: Optional[str] = Field(description="URL template for page_links (e.g., '?page=X', '/page/X')")
    next_button_selector: Optional[str] = Field(description="CSS selector for next button if applicable")
    max_page_detected: Optional[int] = Field(description="Highest page number found, or None if not determinable")
    reasoning: str = Field(description="Explanation of pagination pattern detected")


def get_prompt(current_page_url: str, bottom_links: List[str]) -> str:
    """Generate pagination detection prompt"""
    links_text = "\n".join(f"- {link}" for link in bottom_links)
    
    return f"""
You are analyzing the bottom section links of a product category page to detect pagination patterns for multi-page product extraction.

**CONTEXT:**
- Current page: {current_page_url}
- This page has been fully scrolled and all dynamic content loaded
- We need to detect if there are additional pages with more products

**BOTTOM PAGE LINKS:**
{links_text}

**ANALYSIS TASK:**
Examine these bottom-of-page links to identify pagination patterns. Look for:

1. **PAGE_LINKS**: Numbered page links (e.g., page 2, page 3, ?page=2, /page/3/)
   - Provide URL template (e.g., "?page=X", "/page/X/", "/page/X")
   - Identify highest page number visible

2. **NEXT_BUTTON**: "Next", ">" or similar navigation button (no numbered pages)
   - Provide CSS selector for the next button
   - Set max_page_detected to None (unknown)

3. **NONE**: No pagination detected - single page only

**IMPORTANT GUIDELINES:**
- Focus only on pagination links, ignore other footer links (About, Contact, etc.)
- Look for patterns in URLs with page numbers or pagination keywords
- For page_links: extract the URL pattern that can be templated with "X"
- For next_button: provide a CSS selector that can find the next button
- If unsure between types, prefer page_links if any numbered pages exist

**EXAMPLES:**
- Links like "/category/shoes?page=2", "/category/shoes?page=3" → page_links, template "?page=X"
- Links like "/category/page/2/", "/category/page/3/" → page_links, template "/page/X/"
- Only "Next >" button visible → next_button, provide selector like "a[aria-label='Next']"
- No pagination indicators → none

Return your analysis focusing on enabling multi-page product extraction.
""".strip()


def get_response_model():
    """Get the Pydantic model for response validation"""
    return PaginationDetection