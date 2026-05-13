"""
One-shot discovery runner.

Usage:
    cd backend && python -m prod_page_v2.e0005.run_oneshot <seed_url> [<brand_label>] [<product_type>]

Steps:
    1. LOAD       — PageMemo renders the seed page (Playwright) with cookie
                    banner dismissal.
    2. REVEAL     — best-effort: tap any obvious "Select a size" / "View
                    details" / "Composition" buttons so the post-reveal DOM
                    is what we hand to the LLM. (Skipped if you want pure
                    static state; tweak below.)
    3. ASK+VERIFY+SAVE  — discover_oneshot() does it all in one LLM call.
    4. REPORT     — prints catalog summary + discarded proposals + cost.
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

# Register all methods so hydrate_method works for whatever the LLM proposes.
from prod_page_v2.e0005 import methods  # noqa: F401
from prod_page_v2.e0005 import discover_oneshot
from prod_page_v2.e0005.memo import PageMemo


def _domain_slug(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "").replace(".", "_")


async def _best_effort_reveal(memo: PageMemo) -> None:
    """No-op. The structural explorer in `interactive_explore.explore_clickables`
    (invoked by `discover_oneshot`) now does this job better — it picks
    triggers by DOM structure (aria-expanded, role=tab, details>summary,
    accordion-class) rather than a hardcoded text-keyword list, and
    dismisses each opened dialog before the next click so the budget
    isn't burned on overlay-blocked retries. Kept as a stub for callers
    that still import it.
    """
    return


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1]
    brand_label = sys.argv[2] if len(sys.argv) > 2 else _domain_slug(url)
    product_type = sys.argv[3] if len(sys.argv) > 3 else "fashion"

    out_dir = BACKEND / "prod_page_v2" / "extractions" / _domain_slug(url) / "e0005_oneshot"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[OneShot] URL: {url}")
    print(f"[OneShot] Brand: {brand_label}")
    print(f"[OneShot] Product type: {product_type}")
    print(f"[OneShot] Loading page + revealing hideaways...")

    memo = PageMemo(url)
    try:
        await memo.rendered_html()
        await _best_effort_reveal(memo)
        print(f"[OneShot] Artifacts: {memo.artifacts_loaded()}")

        print(f"[OneShot] Discovering (one LLM call)...")
        result = await discover_oneshot(memo, product_type=product_type, domain=_domain_slug(url).replace("_", "."))
    finally:
        await memo.close()

    # Save catalog + answers + diagnostics
    catalog_path = out_dir / f"{result.catalog.domain.replace('.', '_')}_catalog.json"
    catalog_path.write_text(json.dumps(result.catalog.to_dict(), indent=2, ensure_ascii=False))
    answers_path = out_dir / "answers.json"
    answers_path.write_text(json.dumps({
        f: {"value": a.value, "methods": [
            {"kind": m.kind, "config": m.config, "expected": m.expected}
            for m in a.methods]
        }
        for f, a in result.answers.items()
    }, indent=2, ensure_ascii=False))
    discarded_path = out_dir / "discarded.json"
    discarded_path.write_text(json.dumps([
        {"field": f, "kind": a.kind, "config": a.config,
         "expected": a.expected, "reason": reason}
        for f, a, reason in result.discarded
    ], indent=2, ensure_ascii=False))

    # Report
    print()
    print("=" * 80)
    print(f"# One-shot discovery report — {brand_label}")
    print(f"URL: {url}")
    print(f"Platform hint: {result.platform_hint}")
    print(f"LLM cost: ${result.llm_cost_usd:.4f} ({result.llm_input_tokens} in / {result.llm_output_tokens} out)")
    print()
    print(f"## Field-by-field outcome (one row per field)")
    print()
    print(f"{'field':22s} {'value':40s} {'#methods':10s} cataloged?")
    print(f"{'-'*22} {'-'*40} {'-'*10} {'-'*12}")
    catalog_fields = result.catalog.fields_covered()
    for fname, ans in result.answers.items():
        val = "(null)" if ans.value in (None, "", [], {}) else str(ans.value)
        if len(val) > 38:
            val = val[:35] + "..."
        in_catalog = "✓" if fname in catalog_fields else " "
        print(f"{fname:22s} {val:40s} {len(ans.methods):<10d} {in_catalog}")
    print()
    print(f"## Catalog rows ({len(result.catalog.rows)})")
    for r in result.catalog.rows:
        print(f"  {r.field:22s} -> {r.method.kind}")
    print()
    print(f"## Measured per-method costs (this discovery run)")
    for kind, ms in sorted(result.catalog.site_meta.get("measured_costs_ms", {}).items()):
        print(f"  {kind:30s} {ms:>7.1f} ms")
    print()
    print(f"## Discarded LLM proposals ({len(result.discarded)})")
    for fname, attempt, reason in result.discarded[:20]:
        print(f"  [{fname}] {attempt.kind}: {reason}")
    if len(result.discarded) > 20:
        print(f"  ... +{len(result.discarded) - 20} more (see discarded.json)")
    print()
    print(f"Saved to: {out_dir}/")
    print(f"  catalog:   {catalog_path.name}")
    print(f"  answers:   {answers_path.name}")
    print(f"  discarded: {discarded_path.name}")


if __name__ == "__main__":
    asyncio.run(main())
