"""
DOM-walker selector finder.

Given a ground-truth value for an E0005 field, scan the rendered DOM for
elements that contain that value, then synthesize a stable selector for
the best match. Pure Python, no LLM calls.

Used by Discovery as the cheap fallback when:
  - structured-source enumeration (LD+JSON, OG meta) didn't match, AND
  - the LLM-proposed selectors also missed.

Stable-selector heuristic:
  1. Prefer the element itself if it has a stable identifying attribute
     (data-test, data-testid, data-region, id, role, aria-label).
  2. Else combine the element's tag with the nearest ancestor that has
     one of those attributes: `[data-region='details'] p` style.
  3. Else combine tag with the element's *meaningful* class names
     (non-auto-generated — stripped of hash patterns like `c-aBc123`).
  4. Fallback to the nth child of the nearest meaningful ancestor.

Selectors are then VALIDATED by re-running them through Playwright on the
live page and comparing the extracted text against the ground truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag


# Class names that look auto-generated (CSS-in-JS, CSS Modules, Radix UI etc.)
_AUTOGEN_CLASS_RE = re.compile(r"^(c|css|jsx|sc|emotion|module)-[A-Za-z0-9]+$|^[a-z]+-[A-Za-z0-9]{6,}$")
# Stable identifying attributes, in preference order.
_STABLE_ATTRS = (
    "data-testid", "data-test", "data-test-id",
    "data-region", "data-component", "data-cy", "data-qa",
    "id", "aria-label", "role", "itemprop",
)


@dataclass
class SelectorCandidate:
    selector: str
    mode: str = "first"      # "first" | "all_join"
    score: float = 0.0
    notes: str = ""


def find_selectors_for_value(
    html: str,
    target: str,
    field: str,
    max_candidates: int = 5,
) -> List[SelectorCandidate]:
    """Return ranked CSS selector candidates whose innerText matches `target`.

    For multi-value fields (size_info has multiple sizes joined), the function
    also proposes `all_join` selectors when several sibling elements together
    reproduce the value.
    """
    if not target or not isinstance(target, str):
        return []
    soup = BeautifulSoup(html, "html.parser")
    target_norm = _norm(target)

    # 1. Find elements whose textContent ≈ target.
    direct_matches = _find_direct_matches(soup, target_norm)
    candidates: List[SelectorCandidate] = []
    for el in direct_matches[:10]:
        sel, score = _build_selector_for(el, soup)
        if sel:
            candidates.append(SelectorCandidate(selector=sel, mode="first", score=score,
                                                notes=f"direct match in <{el.name}>"))

    # 2. For multi-value fields, look for sibling groups where joined text matches.
    if field in ("size_info", "all_images", "additional_tags"):
        sibling_candidates = _find_sibling_group_matches(soup, target_norm)
        for sel, score in sibling_candidates[:5]:
            candidates.append(SelectorCandidate(selector=sel, mode="all_join", score=score,
                                                notes="multi-element join"))

    # Dedupe by selector, keep highest score.
    by_sel: dict[str, SelectorCandidate] = {}
    for c in candidates:
        if c.selector not in by_sel or c.score > by_sel[c.selector].score:
            by_sel[c.selector] = c
    sorted_cands = sorted(by_sel.values(), key=lambda c: -c.score)
    return sorted_cands[:max_candidates]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _find_direct_matches(soup: BeautifulSoup, target_norm: str) -> List[Tag]:
    """Elements whose own textContent matches the target — preferring the
    smallest such element (most specific)."""
    matches: List[Tuple[int, Tag]] = []
    for el in soup.find_all(True):
        # Skip nodes whose text is much bigger than the target — we want a tight wrapper.
        text = el.get_text(separator=" ", strip=True)
        if not text:
            continue
        text_norm = _norm(text)
        if text_norm == target_norm:
            matches.append((len(text), el))
        elif target_norm and target_norm in text_norm and len(text_norm) < len(target_norm) * 2.5:
            matches.append((len(text), el))
    matches.sort(key=lambda t: t[0])  # smallest match first
    return [el for _, el in matches]


def _find_sibling_group_matches(soup: BeautifulSoup, target_norm: str) -> List[Tuple[str, float]]:
    """Find parent elements whose direct children (joined) reproduce the target.
    Useful for size lists where each size lives in its own button."""
    results: List[Tuple[str, float]] = []
    target_pieces = [p.strip() for p in re.split(r"[,;]", target_norm) if p.strip()]
    if len(target_pieces) < 2:
        return results
    target_set = set(target_pieces)
    for parent in soup.find_all(True):
        children = [c for c in parent.find_all(True, recursive=False) if c.name]
        if len(children) < len(target_pieces) - 1:
            continue
        child_texts = [_norm(c.get_text(separator=" ", strip=True)) for c in children]
        # All target pieces must appear in some child.
        coverage = sum(1 for piece in target_pieces if any(piece in ct for ct in child_texts))
        if coverage < max(2, int(0.8 * len(target_pieces))):
            continue
        # Use parent + ":scope > tag" form.
        if not children:
            continue
        child_tag = children[0].name
        parent_sel, parent_score = _build_selector_for(parent, soup, max_depth=3)
        if parent_sel:
            sel = f"{parent_sel} > {child_tag}"
            results.append((sel, parent_score + coverage / max(1, len(target_pieces))))
    results.sort(key=lambda t: -t[1])
    return results


def _build_selector_for(el: Tag, soup: BeautifulSoup, max_depth: int = 4) -> Tuple[str, float]:
    """Synthesize a CSS selector for `el`. Returns (selector, score).
    Higher score = more stable / specific."""
    # 1. Element-level stable attribute.
    sel, score = _self_selector(el)
    if score >= 5.0:
        # Confirm uniqueness in the soup.
        if _selector_uniqueness(soup, sel) <= 1:
            return sel, score
        # Not unique alone; combine with parent context below.

    # 2. Walk up looking for a stable ancestor; combine with element tag (+ class).
    cur = el.parent
    depth = 0
    self_part = _self_selector(el, allow_class=True)[0]
    while cur is not None and cur.name and depth < max_depth:
        anc_sel, anc_score = _self_selector(cur)
        if anc_score >= 4.0:
            combined = f"{anc_sel} {self_part}"
            if _selector_uniqueness(soup, combined) <= 2:
                return combined, anc_score + 1.0
        cur = cur.parent
        depth += 1

    # 3. Last-resort: tag.class chain.
    if score >= 1.0:
        return sel, score
    return self_part, 1.0


def _self_selector(el: Tag, allow_class: bool = True) -> Tuple[str, float]:
    """Build a selector for an element from its own attributes/classes."""
    tag = el.name
    # Stable attributes first.
    for a in _STABLE_ATTRS:
        if el.has_attr(a):
            val = el[a]
            if isinstance(val, list):
                val = " ".join(val)
            if val and len(val) < 100:
                # Build [attr='val'] form, escape quotes.
                v = val.replace("'", "\\'")
                return f"{tag}[{a}='{v}']", 7.0 if a in ("id", "data-testid", "data-test", "data-region") else 5.5
    # Class names (non-auto-generated).
    if allow_class and el.has_attr("class"):
        classes = el["class"] if isinstance(el["class"], list) else el["class"].split()
        stable = [c for c in classes if c and not _AUTOGEN_CLASS_RE.match(c)]
        if stable:
            return f"{tag}." + ".".join(stable[:2]), 3.0
    return tag, 0.5


def _selector_uniqueness(soup: BeautifulSoup, selector: str) -> int:
    """Approximate Playwright selector cardinality using BeautifulSoup's CSS
    support. Returns count of matching elements."""
    try:
        return len(soup.select(selector))
    except Exception:
        return 99
