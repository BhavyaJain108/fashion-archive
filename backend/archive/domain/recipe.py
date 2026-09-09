"""Rules for pulling one field out of a product page.

A rule is written once per brand (by the field finder), checked against a page where we
already know the right answer, and then replayed on every other product page for free.
Rules are deterministic: no rule may call an LLM at replay time.
"""

from pydantic import BaseModel, Field

# What a rule can do. Kept small on purpose — every kind here is easy to replay and check.
RECIPE_KINDS = (
    "css_text",  # first element matching the selector → its text
    "css_all_text",  # every element matching → their texts, joined with ", "
    "css_attr",  # first element matching → the named attribute
    "css_all_attr",  # every element matching → that attribute on each, joined
    "regex",  # one capture group over the raw HTML
    "json_ld_path",  # dotted path into the page's Product JSON-LD node
)


class Recipe(BaseModel):
    field: str  # an E0005 field name, e.g. "size_info"
    kind: str
    expression: str  # the selector / regex / path
    attribute: str | None = None  # for css_attr and css_all_attr
    expected: str | None = None  # what it produced on the page it was learned from
    confidence: float = 1.0
    # How often this rule produced the value that was kept. A brand accumulates several
    # strategies per field and they are not equally good: a rule that fires on 2% of a
    # catalogue while its sibling fires on 60% was learned from one page's accident.
    hits: int = 0


class RecipeBook(BaseModel):
    domain: str
    learned_at: str
    learned_from_url: str | None = None
    recipes: list[Recipe] = Field(default_factory=list)
    # True when the rules were verified against a rendered page and will match
    # nothing in the static HTML. A learned fact, not a per-brand setting.
    rendered: bool = False

    def fields(self) -> set[str]:
        return {r.field for r in self.recipes}
