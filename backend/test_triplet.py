"""
Triplet test harness for cost-optimization experiments.

Runs N category URLs SEQUENTIALLY on a single shared Brand instance — this
mirrors what happens inside the pipeline once the seeded cache is warm, and
lets us measure the cost contribution of each optimization (Haiku swap,
heuristic count detection, persistent brand cache, etc.) on a small, fast
test set instead of the full 34-category brand run.

Usage:
    python test_triplet.py <url1> <target1> <url2> <target2> <url3> <target3>
                          [--headless] [--label "baseline"]

Output: per-category cost breakdown + a summary table at the end.
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scraper'))

from url_extractor import extract_urls_from_category
from brand import Brand
from llm_handler import LLMHandler, LLMUsageTracker as _Tracker, calculate_cost
# alias to keep call sites readable
MetricsTracker = _Tracker
from urllib.parse import urlparse


def _print_op_table(operations, indent="  "):
    if not operations:
        print(f"{indent}(no LLM calls)")
        return
    print(f"{indent}{'Operation':<32}{'Calls':>6}{'Input':>9}{'Output':>9}{'Cost':>10}")
    print(f"{indent}{'-'*32}{'-'*6}{'-'*9}{'-'*9}{'-'*10}")
    for op in operations:
        print(
            f"{indent}{op['name'][:32]:<32}{op['calls']:>6}"
            f"{op['input_tokens']:>9}{op['output_tokens']:>9}"
            f"  ${op['cost']:>7.4f}"
        )


def run_triplet(urls_and_targets, headless=True, label=""):
    if label:
        print(f"\n{'#'*70}")
        print(f"# TRIPLET TEST — {label}")
        print(f"{'#'*70}")

    os.environ['EXTRACTOR_HEADLESS'] = '1' if headless else '0'

    # Single Brand instance shared across all three categories so the brand
    # cache (lineage memory, count selector, etc.) accumulates exactly like
    # it does mid-pipeline once the seed has run.
    domain = urlparse(urls_and_targets[0][0]).netloc
    brand = Brand(url=f"https://{domain}/")

    # Fresh metrics for this test run.
    MetricsTracker.reset_all()
    MetricsTracker.set_stage("triplet")

    results = []

    for idx, (url, target) in enumerate(urls_and_targets, start=1):
        # Snapshot before so we can diff per-category.
        before = MetricsTracker.get_stage_summary("triplet")["summary"]

        print(f"\n{'='*70}")
        print(f"[{idx}/{len(urls_and_targets)}] {url}")
        print(f"          target={target}")
        print(f"{'='*70}")

        result = extract_urls_from_category(url, brand_instance=brand, quiet=False)

        after = MetricsTracker.get_stage_summary("triplet")["summary"]
        per_cat = {
            "calls": after["calls"] - before["calls"],
            "input": after["input_tokens"] - before["input_tokens"],
            "output": after["output_tokens"] - before["output_tokens"],
            "cost": after["cost"] - before["cost"],
        }

        # Per-category op breakdown (diff vs. before)
        ops_after = MetricsTracker.get_stage_summary("triplet")["operations"]

        got = len(result.product_urls)
        diff = got - target
        status = "✅" if diff == 0 else ("📈" if diff > 0 else "❌")

        print(f"\n  Result: {got}/{target} {status}  (diff={diff:+d})")
        print(f"  Per-category LLM:")
        print(f"    calls={per_cat['calls']}  input={per_cat['input']}  "
              f"output={per_cat['output']}  cost=${per_cat['cost']:.4f}")

        results.append({
            "url": url,
            "target": target,
            "got": got,
            "diff": diff,
            "calls": per_cat['calls'],
            "input": per_cat['input'],
            "output": per_cat['output'],
            "cost": per_cat['cost'],
        })

    # Final summary
    total = MetricsTracker.get_stage_summary("triplet")["summary"]
    ops = MetricsTracker.get_stage_summary("triplet")["operations"]

    print(f"\n{'='*70}")
    print(f"TRIPLET SUMMARY{' — ' + label if label else ''}")
    print(f"{'='*70}")
    print(f"\n  Per-category results:")
    print(f"    {'#':>2} {'URL':<55} {'Target':>7} {'Got':>5} {'Cost':>10}")
    for i, r in enumerate(results, 1):
        u = r["url"].replace("https://namedcollective.com/collections/", "…/")[:55]
        status_char = "✓" if r["diff"] == 0 else ("+" if r["diff"] > 0 else "✗")
        print(
            f"    {i:>2} {u:<55} {r['target']:>7} "
            f"{r['got']:>4}{status_char} ${r['cost']:>7.4f}"
        )

    print(f"\n  Operations across the triplet:")
    _print_op_table(ops, indent="    ")

    print(f"\n  TOTAL:")
    print(f"    Calls:  {total['calls']}")
    print(f"    Tokens: {total['input_tokens']} in / {total['output_tokens']} out")
    print(f"    Cost:   ${total['cost']:.4f}")

    # Persist the brand cache so a second run can load it (tests OPT #4).
    try:
        brand.save_persisted_cache()
    except Exception as e:
        print(f"   ⚠️  Could not save cache: {e}")

    return {"results": results, "operations": ops, "total": total, "label": label}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run 3 categories sequentially on one Brand")
    parser.add_argument("args", nargs="+",
                        help="alternating url target url target url target ...")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--label", default="")
    a = parser.parse_args()

    if len(a.args) % 2 != 0:
        print("Need pairs of (url, target)")
        sys.exit(1)

    triples = []
    for i in range(0, len(a.args), 2):
        triples.append((a.args[i], int(a.args[i+1])))

    run_triplet(triples, headless=a.headless, label=a.label)
