"""
Gate 3 runner — apply a learned catalog to N additional products from the
same brand. Zero LLM calls (the catalog has cheap methods only).

Usage:
    cd backend && python -m prod_page_v2.e0005.run_gate3 <catalog_json> <url1> [<url2> ...]

Output:
    - Markdown report with per-product field tables
    - Aggregate fill rate across all products
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    for env_path in (BACKEND.parent / "config" / ".env", BACKEND.parent / ".env"):
        if env_path.exists():
            load_dotenv(env_path)
            break
except Exception:
    pass

from prod_page_v2.e0005 import methods  # registers all methods  # noqa
from prod_page_v2.e0005.catalog import hydrate_catalog
from prod_page_v2.e0005.orchestrator import FieldOrchestrator
from prod_page_v2.e0005.report import (
    gate3_header, gate3_summary, product_extraction_section,
)
from prod_page_v2.e0005.memo import PageMemo
from prod_page_v2.e0005.schema import EXTRACTABLE_FIELDS


async def extract_one(orch: FieldOrchestrator, url: str):
    """Override the orchestrator's no-memo construction so it uses a real one.
    The skeleton orchestrator builds its own PageMemo internally — we need to
    set up the memo per URL and run extract through it."""
    # Patch the orchestrator's extract to use a fresh PageMemo for this URL.
    memo = PageMemo(url)
    try:
        # Trigger render once so cheap methods can hit the same artifacts.
        await memo.rendered_html()
        product, trace = await _run_extract_with_memo(orch, memo, url)
    finally:
        await memo.close()
    return product, trace


async def _run_extract_with_memo(orch: FieldOrchestrator, memo: PageMemo, url: str):
    """The orchestrator's extract() currently constructs its own PageMemo.
    We bypass it by running the same loop here against our pre-built memo."""
    from prod_page_v2.e0005.orchestrator import ExtractionTrace, FieldTrace
    from prod_page_v2.e0005.schema import ProductFields

    product = ProductFields(itemurl=url)
    trace = ExtractionTrace(url=url, domain=orch.catalog.domain)
    for field_name in EXTRACTABLE_FIELDS:
        ftrace = FieldTrace(field=field_name)
        trace.fields[field_name] = ftrace
        if field_name == "itemurl":
            ftrace.chosen_method = "url_passthrough"
            ftrace.chosen_value = url
            continue
        rows = orch.catalog.rows_for(field_name)
        if not rows:
            continue
        for row in rows[: orch.max_attempts_per_field]:
            attempt = {"kind": row.method.kind, "confidence": row.confidence}
            try:
                result = await row.method.produce(memo, field_name)
            except Exception as exc:
                attempt["result"] = "error"
                attempt["error"] = repr(exc)
                ftrace.attempted.append(attempt)
                continue
            if orch._is_blank(result.value):
                attempt["result"] = "blank"
                ftrace.attempted.append(attempt)
                continue
            attempt["result"] = "ok"
            ftrace.attempted.append(attempt)
            orch._set_field(product, field_name, result.value)
            ftrace.chosen_method = row.method.kind
            ftrace.chosen_value = result.value
            break

    for fname in EXTRACTABLE_FIELDS:
        if product.is_field_blank(fname):
            trace.fields_blank += 1
        else:
            trace.fields_filled += 1
    trace.artifacts_used = memo.artifacts_loaded()
    return product, trace


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    catalog_path = Path(sys.argv[1])
    urls = sys.argv[2:]

    catalog = hydrate_catalog(json.loads(catalog_path.read_text()))
    brand = catalog.site_meta.get("brand_label", catalog.domain)
    orch = FieldOrchestrator(catalog=catalog)

    out_dir = BACKEND / "prod_page_v2" / "extractions" / catalog.domain.replace(".", "_") / "e0005_gate3"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Gate 3] Brand: {brand}")
    print(f"[Gate 3] Catalog: {catalog_path}  ({len(catalog.rows)} rows, {len(catalog.fields_covered())} fields)")
    print(f"[Gate 3] Testing {len(urls)} products (no LLM, catalog-only)...")
    print()

    md_parts = [
        f"# E0005 Gate 3 — catalog generalization ({brand})",
        f"_Generated {datetime.now().isoformat()}_",
        "",
        f"**Catalog:** `{catalog_path.name}` — {len(catalog.rows)} rows covering "
        f"{', '.join(sorted(catalog.fields_covered()))}",
        "",
        gate3_header(brand=brand, count=len(urls)),
    ]
    per_filled = []
    for i, url in enumerate(urls, 1):
        print(f"[Gate 3] {i}/{len(urls)}: {url}")
        try:
            product, trace = await extract_one(orch, url)
        except Exception as e:
            print(f"  ERROR: {e!r}")
            md_parts.append(f"### Product {i}\n**URL:** {url}\n\n_Error: {e!r}_\n")
            continue
        per_filled.append(trace.fields_filled)
        title = f"Product {i}"
        md_parts.append(product_extraction_section(title=title, url=url,
                                                   product=product, trace=trace))
        print(f"  filled {trace.fields_filled}/{len(EXTRACTABLE_FIELDS)}")

    md_parts.append(gate3_summary(per_filled, len(EXTRACTABLE_FIELDS)))
    md = "\n".join(md_parts)
    report_path = out_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(md)

    print()
    print("=" * 80)
    print(md)
    print("=" * 80)
    print(f"\n[Gate 3] Report: {report_path}")
    print(f"[Gate 3] Avg fill rate: {sum(per_filled)/len(per_filled):.1f}/{len(EXTRACTABLE_FIELDS)}" if per_filled else "")


if __name__ == "__main__":
    asyncio.run(main())
