"""
One-page count detection probe.
================================

Run the real count-detection pipeline against ONE real URL with the real
LLM. No mocks. Use this to verify count detection is actually working
before committing to a full pipeline run.

Usage:
    python scraper/tests/test_count_on_url.py <URL>
    python scraper/tests/test_count_on_url.py https://namedcollective.com/collections/hoodies
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from playwright.sync_api import sync_playwright

from brand import Brand
from count_detection import (
    detect_collection_count,
    _detect_count_from_jsonld,
    _detect_count_from_cached_selector,
    _detect_count_from_vision,
)


def probe(url: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"COUNT DETECTION PROBE")
    print(f"{'=' * 70}")
    print(f"URL: {url}")
    print()

    brand = Brand(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=os.environ.get("PROBE_HEADLESS", "0") == "1")
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )
        page = context.new_page()

        try:
            print(f"→ Loading page...")
            t0 = time.time()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            print(f"  loaded in {time.time() - t0:.1f}s")

            # Dismiss popups before any detection (mirrors what the real
            # pipeline does in _scroll_and_extract_links).
            try:
                from url_extractor import _dismiss_popups_sync
                dismissed = _dismiss_popups_sync(page)
                page.wait_for_timeout(800)
                _dismiss_popups_sync(page)
                if dismissed:
                    print(f"  dismissed {dismissed} popup(s)")
            except Exception as e:
                print(f"  popup dismissal skipped: {e}")

            # Scroll to bottom and back — matches the pipeline's actual
            # state at the moment count detection runs.
            print(f"→ Scrolling page to load lazy content...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

            # ── Stage 1: JSON-LD ────────────────────────────────────────
            print(f"\n--- Stage 1: JSON-LD ---")
            t0 = time.time()
            n = _detect_count_from_jsonld(page)
            print(f"  result: {n}    ({time.time() - t0:.2f}s)")

            # ── Stage 2: cached selector (will be None on first run) ───
            print(f"\n--- Stage 2: cached selector ---")
            print(f"  cached selector: {brand.collection_count_selector}")
            t0 = time.time()
            n = _detect_count_from_cached_selector(page, brand)
            print(f"  result: {n}    ({time.time() - t0:.2f}s)")

            # ── Stage 3: vision LLM ────────────────────────────────────
            print(f"\n--- Stage 3: vision LLM ---")
            t0 = time.time()
            n = _detect_count_from_vision(page, "this collection", brand, brand.llm_handler)
            elapsed = time.time() - t0
            print(f"  result: {n}    ({elapsed:.2f}s)")
            print(f"  selector cached after vision: {brand.collection_count_selector}")

            # ── Full orchestrator (re-run, should hit Stage 1 again or
            #     Stage 2 if vision cached a selector) ─────────────────
            print(f"\n--- Full orchestrator ---")
            # Reset miss count just in case
            brand._count_selector_miss_count = 0
            t0 = time.time()
            result = detect_collection_count(
                page, "this collection", brand, brand.llm_handler
            )
            elapsed = time.time() - t0
            if result:
                print(f"  count: {result.count}")
                print(f"  source: {result.source}")
            else:
                print(f"  count: None (no count detectable)")
            print(f"  ({elapsed:.2f}s)")

            # Verbatim what's at the top of the page (for debugging when
            # the LLM says 'no count visible'):
            print(f"\n--- Top of page innerText (first 800 chars) ---")
            top_text = page.evaluate("document.body.innerText.slice(0, 800)")
            print(top_text)

        finally:
            browser.close()

    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scraper/tests/test_count_on_url.py <URL>")
        print("Example: python scraper/tests/test_count_on_url.py https://namedcollective.com/collections/hoodies")
        sys.exit(1)
    probe(sys.argv[1])
