"""
Gate 1 runner — LLM ground-truth on one seed product.

Usage:
    cd backend && python -m prod_page_v2.e0005.run_gate1 <seed_url> [<brand_label>]

Output:
    - Prints markdown report to stdout
    - Writes report + ground_truth.json + screenshot.png to
      prod_page_v2/extractions/<domain>/e0005_gate1/
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Allow `python -m prod_page_v2.e0005.run_gate1`
HERE = Path(__file__).resolve()
BACKEND = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

# Load .env so CLAUDE_API_KEY / OPENROUTER_API_KEY / etc. are available
try:
    from dotenv import load_dotenv
    for env_path in (BACKEND.parent / "config" / ".env", BACKEND.parent / ".env",
                     BACKEND / "config" / ".env"):
        if env_path.exists():
            load_dotenv(env_path)
            break
except Exception:
    pass

from prod_page_v2.e0005 import PageMemo
from prod_page_v2.e0005.ground_truth import extract_ground_truth, _CLAUDE_MODEL
from prod_page_v2.e0005.report import gate1_section


def _domain_slug(url: str) -> str:
    host = urlparse(url).netloc
    return host.replace("www.", "").replace(".", "_")


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1]
    brand = sys.argv[2] if len(sys.argv) > 2 else _domain_slug(url)

    out_dir = BACKEND / "prod_page_v2" / "extractions" / _domain_slug(url) / "e0005_gate1"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Gate 1] URL: {url}")
    print(f"[Gate 1] Brand: {brand}")
    print(f"[Gate 1] Vision model: {_CLAUDE_MODEL}")
    print(f"[Gate 1] Loading page (Playwright + screenshot)...")

    memo = PageMemo(url)
    try:
        # Trigger render so screenshot/rendered_html are ready
        await memo.rendered_html()
        print(f"[Gate 1] Artifacts after render: {memo.artifacts_loaded()}")

        # Save screenshot for hand verification
        shot = await memo.screenshot()
        (out_dir / "screenshot.png").write_bytes(shot)

        print(f"[Gate 1] Phase A — identifying hideaways...")
        print(f"[Gate 1] Phase B — revealing hideaways...")
        print(f"[Gate 1] Phase C — final extraction...")
        gt = await extract_ground_truth(memo)
    finally:
        await memo.close()

    # Persist raw output
    (out_dir / "ground_truth.json").write_text(
        json.dumps(gt.product_fields.model_dump(), indent=2, ensure_ascii=False)
    )
    (out_dir / "hideaways.json").write_text(
        json.dumps([
            {"label": h.label, "kind": h.expected_kind,
             "trigger": h.trigger_selector, "panel": h.panel_selector,
             "revealed": bool(h.panel_text),
             "panel_text_preview": (h.panel_text or "")[:500]}
            for h in gt.hideaways
        ], indent=2, ensure_ascii=False)
    )

    # Markdown report
    md = gate1_section(brand=brand, url=url, gt=gt, model=_CLAUDE_MODEL)
    report_path = out_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(md)

    print()
    print("=" * 80)
    print(md)
    print("=" * 80)
    print(f"\n[Gate 1] Saved to: {out_dir}/")
    print(f"  - report:  {report_path.name}")
    print(f"  - truth:   ground_truth.json")
    print(f"  - shots:   screenshot.png ({len(shot)} bytes)")
    print(f"[Gate 1] LLM cost: ${gt.llm_cost_usd:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
