"""
Gate 2 runner — discover cheap methods on a seed product and report
which ones reproduce the LLM ground truth.

Usage:
    cd backend && python -m prod_page_v2.e0005.run_gate2 <seed_url> [<brand_label>] [<nav_json_path>]

Output:
    - Prints markdown report (Gate 1 + Gate 2 sections) to stdout
    - Writes catalog to prod_page_v2/extractions/<domain>/e0005_catalog/<domain>_catalog.json
"""

import asyncio
import json
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

# Ensure all methods register
from prod_page_v2.e0005 import methods  # noqa: F401
from prod_page_v2.e0005.discovery import discover_for_brand, save_catalog
from prod_page_v2.e0005.ground_truth import _CLAUDE_MODEL
from prod_page_v2.e0005.report import gate1_section, gate2_section


def _domain_slug(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "").replace(".", "_")


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1]
    brand = sys.argv[2] if len(sys.argv) > 2 else _domain_slug(url)
    nav_json = sys.argv[3] if len(sys.argv) > 3 else None
    if not nav_json:
        # Try the conventional location.
        candidate = BACKEND / "extractions" / _domain_slug(url) / "nav.json"
        if candidate.exists():
            nav_json = str(candidate)

    out_dir = BACKEND / "prod_page_v2" / "extractions" / _domain_slug(url) / "e0005_gate2"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Gate 2] URL: {url}")
    print(f"[Gate 2] Brand: {brand}")
    print(f"[Gate 2] Nav JSON: {nav_json}")
    print(f"[Gate 2] Discovery (LLM ground truth + cheap method validation)...")

    catalog, gt_result, method_results = await discover_for_brand(
        seed_url=url, brand_label=brand, nav_json_path=nav_json,
    )

    catalog_path = save_catalog(catalog, out_dir)
    (out_dir / "ground_truth.json").write_text(
        json.dumps(gt_result.product_fields.model_dump(), indent=2, ensure_ascii=False)
    )

    # Compose report (Gate 1 + Gate 2)
    md_parts = [
        f"# E0005 discovery report — {brand}",
        f"_Generated {datetime.now().isoformat()}_",
        "",
        gate1_section(brand=brand, url=url, gt=gt_result, model=_CLAUDE_MODEL),
        gate2_section(
            url=url, gt=gt_result.product_fields,
            method_results=method_results, catalog_rows=catalog.rows,
        ),
    ]
    md = "\n".join(md_parts)
    report_path = out_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(md)

    print()
    print("=" * 80)
    print(md)
    print("=" * 80)
    print(f"\n[Gate 2] Catalog: {catalog_path}")
    print(f"[Gate 2] Catalog rows: {len(catalog.rows)}")
    print(f"[Gate 2] Fields covered: {len(catalog.fields_covered())}")
    print(f"[Gate 2] Report: {report_path}")
    print(f"[Gate 2] Discovery cost: ${gt_result.llm_cost_usd:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
