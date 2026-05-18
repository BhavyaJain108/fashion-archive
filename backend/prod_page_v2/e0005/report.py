"""
Markdown report generators for the 4 validation gates.

Each gate produces a self-contained markdown section. The driver scripts
(run_gate1.py, run_gate2.py, ...) call these helpers and write the
result to disk + stdout so the user can scroll through.

Format is intentionally verbose: URL printed in full at the top of every
product, every field listed even if blank, method column for ≥ Gate 2.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional

from .ground_truth import GroundTruthResult, Hideaway
from .orchestrator import ExtractionTrace
from .schema import EXTRACTABLE_FIELDS, ProductFields


def _fmt_value(v: Any, max_len: int = 200) -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        s = v.strip().replace("\n", " / ").replace("|", "\\|")
        return s if len(s) <= max_len else s[:max_len] + "…"
    if isinstance(v, (list, dict)):
        s = json.dumps(v, ensure_ascii=False)
        return s if len(s) <= max_len else s[:max_len] + "…"
    return str(v)


def _fill_stats(product: ProductFields) -> tuple[int, int, List[str]]:
    filled = 0
    blank: List[str] = []
    for f in EXTRACTABLE_FIELDS:
        if product.is_field_blank(f):
            blank.append(f)
        else:
            filled += 1
    return filled, len(EXTRACTABLE_FIELDS), blank


# ---------------------------------------------------------------------------
# Gate 1 — LLM ground-truth on the seed product
# ---------------------------------------------------------------------------

def gate1_section(brand: str, url: str, gt: GroundTruthResult, model: str) -> str:
    out: List[str] = []
    out.append(f"## Gate 1 — LLM ground-truth extraction\n")
    out.append(f"**Brand:** {brand}  ")
    out.append(f"**Seed URL:** {url}  ")
    out.append(f"**Vision model:** `{model}`  ")
    out.append(
        f"**LLM cost:** ${gt.llm_cost_usd:.4f} "
        f"({gt.llm_calls} calls, {gt.llm_input_tokens} in / {gt.llm_output_tokens} out)\n"
    )

    # Hideaways
    out.append("### Hideaways identified (Phase A)\n")
    if not gt.hideaways:
        out.append("_(none — page had no accordion/tab content to reveal)_\n")
    else:
        out.append("| Label | Kind | Trigger | Revealed? | Panel preview |")
        out.append("|---|---|---|---|---|")
        for h in gt.hideaways:
            revealed = "✓" if h.panel_text else "✗"
            preview = _fmt_value(h.panel_text or "", 120)
            out.append(
                f"| {h.label} | {h.expected_kind} | `{h.trigger_selector}` | {revealed} | {preview} |"
            )
        out.append("")

    # All 38 fields
    out.append("### Extracted E0005 fields\n")
    out.append("| Field | LLM-extracted value |")
    out.append("|---|---|")
    p = gt.product_fields
    for f in EXTRACTABLE_FIELDS:
        out.append(f"| `{f}` | {_fmt_value(getattr(p, f, None))} |")
    out.append("")

    # Stats footer
    filled, total, blank = _fill_stats(p)
    out.append(f"**Fields filled:** {filled}/{total}  ")
    if blank:
        out.append(f"**Fields blank:** {', '.join(f'`{x}`' for x in blank)}  ")
    out.append("")
    for note in gt.notes:
        out.append(f"_{note}_  ")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Gate 2 — method derivation on the same product
# ---------------------------------------------------------------------------

def gate2_section(
    url: str,
    gt: ProductFields,
    method_results: dict,  # field_name -> list[(method_kind, value, matched_bool)]
    catalog_rows: list,    # list[CatalogRow]
) -> str:
    out: List[str] = []
    out.append("## Gate 2 — Cheap-method derivation on the seed product\n")
    out.append(f"**Seed URL:** {url}\n")
    out.append("| Field | LLM ground truth | Tried methods | Catalog row |")
    out.append("|---|---|---|---|")
    rows_by_field = {}
    for r in catalog_rows:
        rows_by_field.setdefault(r.field, []).append(r.method.kind)

    for f in EXTRACTABLE_FIELDS:
        truth = _fmt_value(getattr(gt, f, None), 80)
        tried = method_results.get(f, [])
        tried_cell = "<br>".join(
            f"{'✓' if matched else '✗'} {kind}: {_fmt_value(val, 60)}"
            for kind, val, matched in tried
        ) or "—"
        catalog_cell = ", ".join(rows_by_field.get(f, [])) or "—"
        out.append(f"| `{f}` | {truth} | {tried_cell} | {catalog_cell} |")
    out.append("")
    out.append(f"**Catalog rows persisted:** {len(catalog_rows)}  ")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Gate 3 / 4 — per-product extraction with catalog
# ---------------------------------------------------------------------------

def product_extraction_section(
    title: str,
    url: str,
    product: ProductFields,
    trace: ExtractionTrace,
) -> str:
    out: List[str] = []
    out.append(f"### {title}\n")
    out.append(f"**URL:** {url}\n")
    out.append("| Field | Value | Method |")
    out.append("|---|---|---|")
    for f in EXTRACTABLE_FIELDS:
        val = _fmt_value(getattr(product, f, None))
        method = trace.fields.get(f).chosen_method if f in trace.fields else None
        out.append(f"| `{f}` | {val} | {method or '—'} |")
    filled, total, blank = _fill_stats(product)
    out.append("")
    out.append(f"**Fields filled:** {filled}/{total}  ")
    if blank:
        out.append(f"**Fields blank:** {', '.join(f'`{x}`' for x in blank)}  ")
    out.append("")
    return "\n".join(out)


def gate3_header(brand: str, count: int) -> str:
    return f"## Gate 3 — Catalog generalization on {count} more {brand} products\n"


def gate3_summary(per_product_filled: List[int], total: int) -> str:
    if not per_product_filled:
        return ""
    avg = sum(per_product_filled) / len(per_product_filled)
    return f"\n**Average fill rate across {len(per_product_filled)} products:** {avg:.1f}/{total}\n"
