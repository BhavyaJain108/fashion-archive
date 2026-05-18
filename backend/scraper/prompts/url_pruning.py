"""
URL Pruning Prompt
==================

Second-pass LLM call: when the per-lineage classifier returns MORE product
URLs than the page actually displays, this prompt asks the LLM to identify
which of those candidates truly belong to the category and which are
contamination (typically cross-category variant/swatch links picked up from
shared lineages on product cards).

Trigger condition (in the caller):
    extracted_count > expected_count

Inputs to the LLM:
    - The category name and optional navigation path
    - The expected_count (what the page itself displays)
    - ALL candidate URLs (no sampling — the question is exactly which N belong)

Output:
    - PruneDecision.indices_to_keep — a subset of indices from the input list
    - reasoning — one sentence on the pruning logic
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PruneDecision(BaseModel):
    """Structured output for the prune-to-expected-count call."""
    indices_to_keep: List[int] = Field(
        description=(
            "Indices (0-based) of the URLs that actually belong to the category. "
            "Aim for exactly `expected_count` indices. If you're confident some "
            "candidates are contamination but unsure about others, prefer "
            "returning fewer rather than including doubtful ones."
        )
    )
    reasoning: str = Field(
        description=(
            "One sentence on how you decided which URLs to keep. Reference the "
            "slug patterns or link-text patterns that signaled contamination."
        )
    )


def get_prompt(category_name: str,
               candidates: List[Dict],
               expected_count: int,
               nav_path: Optional[str] = None,
               page_url: Optional[str] = None) -> str:
    """
    Build the pruning prompt.

    Args:
        category_name: The leaf category name (e.g. "Hoodies").
        candidates: List of dicts, each {"url": str, "link_text": str}.
            Index in this list is what the LLM will return.
        expected_count: How many products the page actually displays.
        nav_path: Full navigation path if known (e.g. "Women > Tops > Hoodies").
        page_url: The category page URL, for context.
    """
    nav_line = f"- Full nav path: {nav_path}\n" if nav_path else ""
    page_url_line = f"- Page URL: {page_url}\n" if page_url else ""

    # Format candidates with their indices and link text.
    lines = []
    for i, c in enumerate(candidates):
        url = c.get("url", "")
        text = (c.get("link_text") or "").strip()[:80]
        if text:
            lines.append(f"[{i:>3}] {url}\n      text: \"{text}\"")
        else:
            lines.append(f"[{i:>3}] {url}")
    candidates_block = "\n".join(lines)

    extra = len(candidates) - expected_count

    return f"""
The previous classifier returned more product URLs than this category actually contains. You need to prune the list down to the products that genuinely belong to "{category_name}".

**Context:**
- Category: {category_name}
{nav_line}{page_url_line}- Page displays: {expected_count} products
- Candidates returned by classifier: {len(candidates)}
- Excess to prune: {extra}

**Why this happens:** product cards on these sites often share a lineage with variant/swatch links that point to color variants of related products in OTHER categories. Those links pass the first-pass lineage classifier because they look like /products/ links, but their slugs reveal they're not actually "{category_name}".

**Your task:** Look at each candidate's URL slug and link text. Identify the {expected_count} (or fewer) URLs whose slug or link text describes a "{category_name}" item. Reject any whose slug describes something else (e.g. for "Hoodies", reject slugs like "...bikini...", "...shorts...", "...boxers...").

**Candidates:**

{candidates_block}

**Output rules:**
- Return indices that genuinely belong to "{category_name}".
- Aim for {expected_count} indices total — that's the page's displayed count.
- If you're not sure whether a borderline candidate belongs, EXCLUDE it. Better to ship slightly under {expected_count} than to keep contamination.
- Reference slug patterns in your reasoning (e.g. "kept all slugs containing 'hoodie', rejected slugs containing 'bikini' and 'shorts'").
""".strip()


def get_response_model():
    return PruneDecision
