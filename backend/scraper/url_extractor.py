"""
URL-Only Product Extractor
==========================

Extracts product URLs from category pages without full product details.
Preserves all pagination/scroll/load-more discovery logic.
Uses LLM classification to filter product links from navigation/recommendations.
"""

import os
import time
import json
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm_handler import LLMHandler
from prompts import url_classification

# Thread-local storage for quiet mode
_thread_local = threading.local()

# Import shared popup selectors from navigation module
from navigation.popup_selectors import (
    POPUP_CLOSE_SELECTORS,
    POPUP_IFRAME_SELECTORS,
    OVERLAY_REMOVAL_SELECTORS,
)


def _dismiss_popups_sync(page) -> int:
    """
    Dismiss popups using direct selectors (sync version).
    Uses same selectors as navigation/llm_popup_dismiss.py for consistency.
    """
    dismissed = 0

    # Click popup close buttons
    for sel in POPUP_CLOSE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=2000)
                page.wait_for_timeout(300)
                _log(f"   [POPUP] Clicked: {sel}")
                dismissed += 1
        except:
            continue

    # Remove popup iframes
    for sel in POPUP_IFRAME_SELECTORS:
        try:
            iframe = page.locator(sel)
            if iframe.count() > 0 and iframe.is_visible():
                page.evaluate(f"document.querySelector('{sel}')?.parentElement?.remove()")
                _log(f"   [POPUP] Removed iframe: {sel}")
                dismissed += 1
        except:
            continue

    # Remove overlay elements from DOM entirely
    for selector in OVERLAY_REMOVAL_SELECTORS:
        try:
            removed = page.evaluate(f"""
                (() => {{
                    const els = document.querySelectorAll('{selector}');
                    const count = els.length;
                    els.forEach(el => el.remove());
                    return count;
                }})()
            """)
            if removed > 0:
                _log(f"   [POPUP] Removed {removed} overlay elements: {selector}")
                dismissed += removed
        except:
            continue

    return dismissed


def _log(message: str):
    """Print message unless quiet mode is enabled."""
    if not getattr(_thread_local, 'quiet', False):
        print(message)

# Import reusable functions from page_extractor
from page_extractor import (
    extract_category_name,
    _detect_pagination_element,
    _detect_post_scroll_pagination,
    _extract_bottom_page_links,
    _filter_links_by_category,
    _generate_page_urls,
    _handle_load_more_button,
    _scroll_using_pagination_element,
    escape_css_selector_for_playwright,
)

# Import modal bypass (same pattern as page_extractor)
try:
    from backend.scraper.modal_bypass_engine import bypass_blocking_modals_only
except ImportError:
    try:
        from .modal_bypass_engine import bypass_blocking_modals_only
    except ImportError:
        def bypass_blocking_modals_only(page, url):
            return {"modals_detected": 0, "modals_bypassed": 0, "success": True}


@dataclass
class ProductURL:
    """A discovered product URL with debugging metadata"""
    url: str                      # The product URL
    source_page: str              # "page_1", "page_2", etc.
    category_url: str             # Category it was found in
    category_name: str            # Human-readable name
    lineage: str                  # DOM lineage for debugging
    discovery_method: str         # "initial_load" | "scroll" | "load_more" | "pagination"
    link_text: str                # Anchor text
    position_index: int           # Position on page

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class URLExtractionResult:
    """Result of URL extraction for a single category"""
    category_url: str
    category_name: str
    product_urls: List[ProductURL] = field(default_factory=list)
    pages_processed: int = 1
    extraction_time: float = 0.0
    llm_filtering_stats: Dict = field(default_factory=dict)
    llm_usage: Dict = field(default_factory=lambda: {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0
    })
    errors: List[str] = field(default_factory=list)
    discovery_info: Dict = field(default_factory=dict)  # Scroll/extraction stats

    def to_dict(self) -> Dict:
        return {
            "category_url": self.category_url,
            "category_name": self.category_name,
            "product_urls": [url.to_dict() for url in self.product_urls],
            "pages_processed": self.pages_processed,
            "extraction_time": self.extraction_time,
            "llm_filtering_stats": self.llm_filtering_stats,
            "llm_usage": self.llm_usage,
            "errors": self.errors
        }

    def add_llm_usage(self, usage: Dict):
        """Accumulate LLM usage from a call."""
        if usage:
            self.llm_usage["calls"] += 1
            self.llm_usage["input_tokens"] += usage.get("input_tokens", 0)
            self.llm_usage["output_tokens"] += usage.get("output_tokens", 0)


def _extract_links_from_current_state(page, page_url: str) -> List[Dict]:
    """
    Extract all links from current page state (after scrolling).

    Returns:
        List of dicts with: url, lineage, link_text, position_index, in_carousel
    """
    try:
        # JavaScript to extract all links with their metadata
        links_data = page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href]'));

                // Patterns that indicate carousel/slider containers
                const carouselPatterns = [
                    'slider', 'carousel', 'swiper', 'slick', 'glide', 'splide',
                    'slideshow', 'marquee', 'ticker'
                ];

                // Check if element has a carousel ancestor (walk up to 15 levels)
                function isInCarousel(element) {
                    let current = element;
                    for (let i = 0; i < 15 && current && current !== document.body; i++) {
                        const tagName = (current.tagName || '').toLowerCase();
                        const className = (typeof current.className === 'string' ? current.className : '').toLowerCase();

                        for (const pattern of carouselPatterns) {
                            if (tagName.includes(pattern) || className.includes(pattern)) {
                                return true;
                            }
                        }
                        current = current.parentElement;
                    }
                    return false;
                }

                // Function to get DOM lineage (3 generations)
                function getLineage(element) {
                    const parts = [];
                    let current = element;

                    for (let i = 0; i < 3 && current && current !== document.body; i++) {
                        let identifier = current.tagName.toLowerCase();

                        // Add classes (limit to 3 most relevant)
                        if (current.className && typeof current.className === 'string') {
                            const classes = current.className.split(' ')
                                .filter(c => c && !c.includes(':'))  // Skip Tailwind responsive
                                .slice(0, 3);
                            if (classes.length > 0) {
                                identifier += '.' + classes.join('.');
                            }
                        }

                        parts.push(identifier);
                        current = current.parentElement;
                    }

                    return parts.join(' > ');
                }

                const results = [];

                links.forEach((link, index) => {
                    const href = link.href;

                    // Skip invalid links
                    if (!href || href.startsWith('javascript:') || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('tel:')) {
                        return;
                    }

                    results.push({
                        url: href,
                        lineage: getLineage(link),
                        link_text: (link.textContent || '').trim().substring(0, 100),
                        position_index: index,
                        in_carousel: isInCarousel(link)
                    });
                });

                return results;
            }
        """)

        return links_data

    except Exception as e:
        _log(f"   ❌ Error extracting links: {e}")
        return []


def _detect_pagination_with_cached_pattern(page, page_url: str, cached_pattern: Dict) -> Dict[str, Any]:
    """
    Fast pagination detection using a known URL pattern from the brand cache.

    Skips the LLM call entirely. Extracts bottom links, filters by category,
    then uses the known url_pattern to find max_page from the link URLs.

    Returns same structure as _detect_post_scroll_pagination.
    """
    import re
    url_pattern = cached_pattern.get("url_pattern")
    if not url_pattern:
        return {"pagination_found": False, "url_pattern": None, "max_page_detected": None,
                "next_page_url": None, "reasoning": "No cached url_pattern"}

    result = {
        "pagination_found": False,
        "url_pattern": url_pattern,
        "pagination_type": cached_pattern.get("pagination_type", "page_links"),
        "max_page_detected": None,
        "next_page_url": None,
        "reasoning": "Fast detection using cached pattern"
    }

    try:
        bottom_links = _extract_bottom_page_links(page, page_url)
        if not bottom_links:
            return result

        category_links = _filter_links_by_category(bottom_links, page_url)
        if not category_links:
            return result

        # Extract page numbers from links using the known pattern
        page_numbers = []
        for link in category_links:
            if "?page=" in url_pattern or "?page=X" in url_pattern:
                match = re.search(r'[?&]page=(\d+)', link)
            elif "?p=" in url_pattern or "?p=X" in url_pattern:
                match = re.search(r'[?&]p=(\d+)', link)
            elif "/page/" in url_pattern:
                match = re.search(r'/page/(\d+)', link)
            else:
                match = None
            if match:
                page_numbers.append(int(match.group(1)))

        if page_numbers:
            max_page = max(page_numbers)
            result["pagination_found"] = True
            result["max_page_detected"] = max_page
            result["reasoning"] = f"Fast detection: found pages {sorted(set(page_numbers))}, max={max_page} (cached pattern: {url_pattern})"
            _log(f"   ⚡ Fast pagination: max page {max_page} (cached pattern: {url_pattern})")
        else:
            _log(f"   📄 No page numbers found with cached pattern {url_pattern}")

    except Exception as e:
        result["reasoning"] = f"Fast detection failed: {e}"
        _log(f"   ❌ Fast pagination detection failed: {e}")

    return result


def _scroll_and_extract_links(page_url: str, brand_instance=None, skip_pagination_detection: bool = False) -> Dict[str, Any]:
    """
    Scroll page fully and extract all links.

    Reuses pagination detection, height-based scrolling, and load-more logic
    from page_extractor but extracts links instead of products.

    Returns:
        Dict with: links, pagination_detected, discovery_info
    """
    all_links = []
    discovery_info = {
        "initial_load_count": 0,
        "after_scroll_count": 0,
        "after_load_more_count": 0,
        "pagination_detected": None
    }

    with sync_playwright() as p:
        # Use EXTRACTOR_HEADLESS env var (default True for pipeline, False for test_category.py)
        headless = os.environ.get('EXTRACTOR_HEADLESS', '1') == '1'
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()

        try:
            # Navigate to page
            _log(f"   🌐 Loading: {page_url}")
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)  # 60s timeout for slow connections
            page.wait_for_timeout(3000)  # Wait for async popups to load

            # Dismiss popups that might block interactions
            _dismiss_popups_sync(page)
            page.wait_for_timeout(1000)  # Let popup animation complete
            _dismiss_popups_sync(page)  # Try again in case more popups appeared

            # Extract initial links
            initial_links = _extract_links_from_current_state(page, page_url)
            discovery_info["initial_load_count"] = len(initial_links)
            _log(f"   📊 Initial load: {len(initial_links)} links found")

            # Detect pagination elements
            pagination_element = _detect_pagination_element(page)
            if pagination_element:
                _log(f"   🎯 Pagination element detected: {pagination_element}")

            # Scrolling phase
            scroll_count = 0
            no_change_count = 0
            max_no_change = 2

            if brand_instance and brand_instance.load_more_loading_mechanism:
                max_no_change = 1

            _log(f"   🔄 Scrolling to load all content...")

            # If pagination element found, use proper pagination-based scrolling
            if pagination_element:
                _log(f"   📍 Using pagination element for scroll targeting")
                _scroll_using_pagination_element(page, pagination_element, [])

            # Height-based scrolling (fallback or additional)
            while True:
                current_height = page.evaluate("document.body.scrollHeight")
                scroll_count += 1

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                new_height = page.evaluate("document.body.scrollHeight")

                if new_height == current_height:
                    no_change_count += 1
                    if no_change_count >= max_no_change:
                        break
                    page.wait_for_timeout(3000)
                else:
                    no_change_count = 0

            # Extract links after scrolling
            after_scroll_links = _extract_links_from_current_state(page, page_url)
            discovery_info["after_scroll_count"] = len(after_scroll_links)
            _log(f"   📊 After scrolling: {len(after_scroll_links)} links found")

            # Load more button handling
            _log(f"   🔍 Checking for load more buttons...")
            load_more_clicked = _handle_load_more_button(page, page_url, brand_instance)

            if load_more_clicked:
                _log(f"   🎯 Load more button found, chasing until exhausted...")
                click_count = 1
                no_click_attempts = 0
                no_height_change = 0

                while click_count < 20:
                    current_height = page.evaluate("document.body.scrollHeight")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(3000)

                    new_height = page.evaluate("document.body.scrollHeight")

                    if new_height == current_height:
                        no_height_change += 1
                        if no_height_change >= 2:
                            break
                    else:
                        no_height_change = 0

                    additional_click = _handle_load_more_button(page, page_url, brand_instance)
                    if additional_click:
                        click_count += 1
                        no_click_attempts = 0
                    else:
                        no_click_attempts += 1
                        if no_click_attempts >= 2:
                            break
                        page.wait_for_timeout(3000)

            # Extract final links after all loading
            final_links = _extract_links_from_current_state(page, page_url)
            discovery_info["after_load_more_count"] = len(final_links)
            _log(f"   📊 After load more: {len(final_links)} links found")

            all_links = final_links

            # Detect pagination for multi-page extraction (skip on pages 2+ where we already know the pattern)
            if not skip_pagination_detection:
                # If brand has a cached pagination pattern, use fast detection (no LLM)
                cached = brand_instance.pagination_pattern if brand_instance and getattr(brand_instance, 'pagination_pattern', None) else None
                if cached:
                    _log(f"   ⚡ Using cached pagination pattern from brand: {cached.get('url_pattern')}")
                    pagination_result = _detect_pagination_with_cached_pattern(page, page_url, cached)
                else:
                    pagination_result = _detect_post_scroll_pagination(page, page_url)
                discovery_info["pagination_detected"] = pagination_result

        finally:
            browser.close()

    return {
        "links": all_links,
        "discovery_info": discovery_info
    }


def classify_product_links(
    links: List[Dict],
    page_url: str,
    category_name: str,
    brand_instance=None
) -> Dict[str, Any]:
    """
    Use LLM to classify links as products vs navigation/recommendations.

    Uses lineage memory from brand_instance for incremental learning.

    Returns:
        Dict with: product_links (List[Dict]), stats (Dict)
    """
    if not links:
        return {"product_links": [], "stats": {"total": 0, "approved": 0, "rejected": 0}}

    # Group links by lineage pattern for efficient classification
    lineage_groups: Dict[str, List[Dict]] = {}
    for link in links:
        lineage = link.get("lineage", "unknown")
        if lineage not in lineage_groups:
            lineage_groups[lineage] = []
        lineage_groups[lineage].append(link)

    _log(f"   📊 Found {len(lineage_groups)} unique lineage patterns across {len(links)} links")

    # Check for pre-approved/rejected lineages from brand instance
    approved_lineages: Set[str] = set()
    rejected_lineages: Set[str] = set()

    if brand_instance:
        approved_lineages = getattr(brand_instance, 'approved_url_lineages', set()) or set()
        rejected_lineages = getattr(brand_instance, 'rejected_url_lineages', set()) or set()

    # Separate known and unknown lineages
    known_approved_links = []
    known_rejected_links = []
    unknown_lineage_links = []

    for lineage, group_links in lineage_groups.items():
        if lineage in approved_lineages:
            known_approved_links.extend(group_links)
        elif lineage in rejected_lineages:
            known_rejected_links.extend(group_links)
        else:
            unknown_lineage_links.extend(group_links)

    _log(f"   ✅ Pre-approved: {len(known_approved_links)} links ({len([l for l in lineage_groups if l in approved_lineages])} lineages)")
    _log(f"   ❌ Pre-rejected: {len(known_rejected_links)} links ({len([l for l in lineage_groups if l in rejected_lineages])} lineages)")
    _log(f"   ❓ Unknown: {len(unknown_lineage_links)} links need classification")

    newly_approved_links = []
    newly_approved_lineages = set()
    newly_rejected_lineages = set()

    # If there are unknown links, use LLM to classify
    if unknown_lineage_links:
        # Limit to a reasonable sample for LLM (take representative links)
        sample_size = min(50, len(unknown_lineage_links))

        # Sample links ensuring each lineage is represented
        sampled_links = []
        lineages_sampled = set()

        for link in unknown_lineage_links:
            lineage = link.get("lineage", "unknown")
            if lineage not in lineages_sampled:
                sampled_links.append(link)
                lineages_sampled.add(lineage)
                if len(sampled_links) >= sample_size:
                    break

        # Add more links if we have room
        if len(sampled_links) < sample_size:
            for link in unknown_lineage_links:
                if link not in sampled_links:
                    sampled_links.append(link)
                    if len(sampled_links) >= sample_size:
                        break

        _log(f"   🧠 Sending {len(sampled_links)} sample links to LLM for classification...")

        # Call LLM
        llm_handler = LLMHandler()
        prompt = url_classification.get_prompt(page_url, category_name, sampled_links)
        response = llm_handler.call(
            prompt,
            expected_format="json",
            response_model=url_classification.get_response_model(),
            operation="url_classification",
        )

        if response.get("success"):
            data = response.get("data", {})
            product_indices = set(data.get("product_link_indices", []))
            confidence = data.get("confidence", "Medium")
            analysis = data.get("analysis", "")

            _log(f"   📋 LLM classified {len(product_indices)} of {len(sampled_links)} as products (confidence: {confidence})")
            _log(f"   📝 Analysis: {analysis[:200]}...")

            # Map indices back to lineages
            for i, link in enumerate(sampled_links):
                lineage = link.get("lineage", "unknown")
                if i in product_indices:
                    newly_approved_lineages.add(lineage)
                else:
                    newly_rejected_lineages.add(lineage)

            # Apply classification to ALL links with matching lineages
            for link in unknown_lineage_links:
                lineage = link.get("lineage", "unknown")
                if lineage in newly_approved_lineages:
                    newly_approved_links.append(link)
        else:
            _log(f"   ❌ LLM classification failed: {response.get('error', 'Unknown error')}")
            # Fallback: use URL heuristics
            _log(f"   🔄 Using URL heuristics as fallback...")
            for link in unknown_lineage_links:
                url = link.get("url", "")
                # Common product URL patterns
                if any(pattern in url.lower() for pattern in ['/products/', '/product/', '/p/', '/item/', '/shop/']):
                    newly_approved_links.append(link)
                    newly_approved_lineages.add(link.get("lineage", "unknown"))

    # Update brand instance with new lineage knowledge
    if brand_instance:
        if not hasattr(brand_instance, 'approved_url_lineages'):
            brand_instance.approved_url_lineages = set()
        if not hasattr(brand_instance, 'rejected_url_lineages'):
            brand_instance.rejected_url_lineages = set()

        brand_instance.approved_url_lineages.update(newly_approved_lineages)
        brand_instance.rejected_url_lineages.update(newly_rejected_lineages)

    # Combine all approved links
    all_product_links = known_approved_links + newly_approved_links

    # Deduplicate by URL
    seen_urls = set()
    unique_product_links = []
    for link in all_product_links:
        url = link.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_product_links.append(link)

    # Build rejected URLs grouped by lineage
    all_rejected_lineages = rejected_lineages | newly_rejected_lineages
    approved_urls = {link.get("url") for link in all_product_links}

    rejected_by_lineage = {}
    for link in links:
        url = link.get("url", "")
        lineage = link.get("lineage", "unknown")

        # If this URL wasn't approved, it was rejected
        if url not in approved_urls:
            if lineage not in rejected_by_lineage:
                rejected_by_lineage[lineage] = []
            rejected_by_lineage[lineage].append({
                "url": url,
                "link_text": link.get("link_text", "")
            })

    stats = {
        "total_links_found": len(links),
        "product_links_approved": len(unique_product_links),
        "links_rejected": len(links) - len(all_product_links),
        "lineages_approved": list(approved_lineages | newly_approved_lineages),
        "lineages_rejected": list(rejected_lineages | newly_rejected_lineages),
        "pre_approved_count": len(known_approved_links),
        "newly_classified_count": len(newly_approved_links),
        "rejected_by_lineage": rejected_by_lineage
    }

    _log(f"   ✅ Classification complete: {len(unique_product_links)} product URLs identified")

    return {
        "product_links": unique_product_links,
        "stats": stats
    }


def _extract_urls_from_single_page(
    page_url: str,
    category_url: str,
    category_name: str,
    page_num: int,
    brand_instance=None,
    skip_pagination_detection: bool = False
) -> Dict[str, Any]:
    """
    Extract product URLs from a single page.

    Returns:
        Dict with: product_urls, pagination_detected, extraction_time
    """
    start_time = time.time()

    try:
        # Scroll and extract all links (skip pagination detection on pages 2+ to avoid wasted LLM calls)
        result = _scroll_and_extract_links(page_url, brand_instance, skip_pagination_detection=skip_pagination_detection)
        links = result.get("links", [])
        discovery_info = result.get("discovery_info", {})

        # Classify links to filter products
        classification = classify_product_links(links, page_url, category_name, brand_instance)
        product_links = classification.get("product_links", [])
        stats = classification.get("stats", {})

        # Convert to ProductURL objects
        source_page = f"page_{page_num}"
        product_urls = []

        for link in product_links:
            product_url = ProductURL(
                url=link.get("url", ""),
                source_page=source_page,
                category_url=category_url,
                category_name=category_name,
                lineage=link.get("lineage", "unknown"),
                discovery_method="scroll" if discovery_info.get("after_scroll_count", 0) > discovery_info.get("initial_load_count", 0) else "initial_load",
                link_text=link.get("link_text", ""),
                position_index=link.get("position_index", 0)
            )
            product_urls.append(product_url)

        extraction_time = time.time() - start_time

        return {
            "product_urls": product_urls,
            "pagination_detected": discovery_info.get("pagination_detected") if not skip_pagination_detection else None,
            "extraction_time": extraction_time,
            "stats": stats,
            "discovery_info": discovery_info
        }

    except Exception as e:
        _log(f"   ❌ Error extracting URLs from {page_url}: {e}")
        return {
            "product_urls": [],
            "pagination_detected": None,
            "extraction_time": time.time() - start_time,
            "error": str(e)
        }


def extract_multi_page_urls(
    base_url: str,
    category_name: str,
    brand_instance=None,
    pagination_result: Dict = None
) -> Dict[str, Any]:
    """
    Extract URLs from multiple pages (parallel extraction).

    Returns:
        Dict with: product_urls, pages_extracted, stats
    """
    if not pagination_result or not pagination_result.get("pagination_found"):
        return {
            "product_urls": [],
            "pages_extracted": 0,
            "stats": {}
        }

    _log(f"\n🔗 Multi-Page URL Extraction Starting...")

    # Generate page URLs
    page_urls = _generate_page_urls(base_url, pagination_result)
    if not page_urls:
        _log(f"   📄 No additional pages to extract")
        return {
            "product_urls": [],
            "pages_extracted": 0,
            "stats": {}
        }

    _log(f"   📊 Extracting URLs from {len(page_urls)} additional pages")

    all_urls = []
    per_page_stats = []

    start_time = time.time()
    max_workers = min(len(page_urls), 8)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_info = {}

        for i, url in enumerate(page_urls):
            future = executor.submit(
                _extract_urls_from_single_page,
                url, base_url, category_name, i + 2, brand_instance, True
            )
            future_to_info[future] = {"url": url, "page_num": i + 2}

        for future in as_completed(future_to_info):
            info = future_to_info[future]

            try:
                result = future.result()
                urls_found = result.get("product_urls", [])

                if urls_found:
                    all_urls.extend(urls_found)
                    _log(f"   ✅ Page {info['page_num']}: {len(urls_found)} product URLs")
                else:
                    _log(f"   📄 Page {info['page_num']}: 0 product URLs")

                per_page_stats.append({
                    "page_num": info["page_num"],
                    "url": info["url"],
                    "urls_found": len(urls_found),
                    "extraction_time": result.get("extraction_time", 0)
                })

            except Exception as e:
                _log(f"   ❌ Page {info['page_num']} failed: {e}")
                per_page_stats.append({
                    "page_num": info["page_num"],
                    "url": info["url"],
                    "urls_found": 0,
                    "error": str(e)
                })

    # Sequential discovery: continue extracting pages beyond what we already processed.
    # This handles:
    # - next_page_url only (no max detected) - classic next/prev button case
    # - pagination_type == "next_button" - LLM explicitly identified next button
    # - max_page_detected <= 2 - likely only seeing adjacent page, not full numbered pagination
    max_page = pagination_result.get("max_page_detected")
    pagination_type = pagination_result.get("pagination_type", "page_links")
    should_continue_sequential = (
        (not max_page and pagination_result.get("next_page_url")) or
        pagination_type == "next_button" or
        (max_page is not None and max_page <= 2)
    )
    if should_continue_sequential and pagination_result.get("url_pattern"):
        url_pattern = pagination_result.get("url_pattern")
        if url_pattern:
            import re
            # Find the highest page number we just processed
            current_page_num = 2  # We started at page 2
            for stat in per_page_stats:
                if stat.get("page_num", 0) > current_page_num:
                    current_page_num = stat["page_num"]

            # Continue sequentially: load next page, extract URLs, check ONLY that page for more pages
            consecutive_empty = 0
            safety_limit = current_page_num + 50
            current_page_num += 1

            while current_page_num <= safety_limit and consecutive_empty < 3:
                # Generate URL for this page
                if "?page=X" in url_pattern or "?page=" in url_pattern:
                    next_url = base_url.split("?")[0] + f"?page={current_page_num}"
                elif "/page/X/" in url_pattern or "/page/" in url_pattern:
                    next_url = base_url.rstrip("/") + f"/page/{current_page_num}/"
                elif "/page/X" in url_pattern:
                    next_url = base_url.rstrip("/") + f"/page/{current_page_num}"
                elif "?p=X" in url_pattern or "?p=" in url_pattern:
                    next_url = base_url.split("?")[0] + f"?p={current_page_num}"
                else:
                    next_url = base_url + url_pattern.replace("X", str(current_page_num))

                _log(f"   🔄 Sequential discovery: page {current_page_num} ({next_url})")

                try:
                    page_result = _extract_urls_from_single_page(
                        next_url, base_url, category_name, current_page_num, brand_instance, True
                    )
                    urls_found = page_result.get("product_urls", [])

                    if urls_found:
                        all_urls.extend(urls_found)
                        consecutive_empty = 0
                        _log(f"   ✅ Page {current_page_num}: {len(urls_found)} product URLs")
                    else:
                        consecutive_empty += 1
                        _log(f"   📄 Page {current_page_num}: 0 product URLs (empty #{consecutive_empty})")

                    per_page_stats.append({
                        "page_num": current_page_num,
                        "url": next_url,
                        "urls_found": len(urls_found),
                        "extraction_time": page_result.get("extraction_time", 0)
                    })

                except Exception as e:
                    consecutive_empty += 1
                    _log(f"   ❌ Page {current_page_num} failed: {e}")
                    per_page_stats.append({
                        "page_num": current_page_num,
                        "url": next_url,
                        "urls_found": 0,
                        "error": str(e)
                    })

                current_page_num += 1

    total_time = time.time() - start_time

    _log(f"   📊 Multi-page extraction complete:")
    _log(f"      • Pages processed: {len(per_page_stats)}")
    _log(f"      • Total URLs: {len(all_urls)}")
    _log(f"      • Time: {total_time:.2f}s")

    return {
        "product_urls": all_urls,
        "pages_extracted": len(per_page_stats),
        "per_page_stats": per_page_stats,
        "total_time": total_time
    }


def extract_urls_from_category(
    category_url: str,
    brand_instance=None,
    quiet: bool = False
) -> URLExtractionResult:
    """
    Extract all product URLs from a single category.

    Main entry point for single category extraction.

    Args:
        category_url: URL of the category page
        brand_instance: Optional brand instance for shared state
        quiet: If True, suppress all log output (for parallel execution)
    """
    # Set thread-local quiet flag
    _thread_local.quiet = quiet

    start_time = time.time()
    category_name = extract_category_name(category_url)

    _log(f"\n{'='*60}")
    _log(f"📁 Extracting URLs from: {category_name}")
    _log(f"   URL: {category_url}")
    _log(f"{'='*60}")

    result = URLExtractionResult(
        category_url=category_url,
        category_name=category_name
    )

    try:
        # Extract page 1
        page1_result = _extract_urls_from_single_page(
            category_url, category_url, category_name, 1, brand_instance
        )

        page1_urls = page1_result.get("product_urls", [])
        pagination_detected = page1_result.get("pagination_detected")

        result.product_urls.extend(page1_urls)
        result.llm_filtering_stats = page1_result.get("stats", {})
        result.discovery_info = page1_result.get("discovery_info", {})

        if page1_result.get("error"):
            result.errors.append(f"Page 1: {page1_result['error']}")

        # Multi-page extraction if pagination detected
        if pagination_detected and pagination_detected.get("pagination_found"):
            _log(f"\n   📖 Pagination detected, extracting additional pages...")

            # Cache pagination pattern on brand for cross-category reuse
            if brand_instance and pagination_detected.get("url_pattern"):
                with brand_instance._pagination_lock:
                    if not brand_instance.pagination_pattern:
                        brand_instance.pagination_pattern = {
                            "url_pattern": pagination_detected["url_pattern"],
                            "pagination_type": pagination_detected.get("pagination_type", "page_links"),
                        }
                        _log(f"   💾 Cached pagination pattern: {brand_instance.pagination_pattern['url_pattern']}")

            multi_result = extract_multi_page_urls(
                category_url, category_name, brand_instance, pagination_detected
            )

            additional_urls = multi_result.get("product_urls", [])
            result.product_urls.extend(additional_urls)
            result.pages_processed = 1 + multi_result.get("pages_extracted", 0)

        # Deduplicate URLs
        seen = set()
        unique_urls = []
        for url in result.product_urls:
            if url.url not in seen:
                seen.add(url.url)
                unique_urls.append(url)
        result.product_urls = unique_urls

        result.extraction_time = time.time() - start_time

        _log(f"\n   ✅ Category complete: {len(result.product_urls)} unique product URLs")
        _log(f"   ⏱️  Time: {result.extraction_time:.2f}s")

    except Exception as e:
        result.errors.append(str(e))
        result.extraction_time = time.time() - start_time
        _log(f"   ❌ Category extraction failed: {e}")

    return result


def extract_urls_from_navigation_tree(
    navigation_tree: Dict,
    brand_instance=None,
    parallel: bool = True,
    max_workers: int = 8
) -> Dict[str, Any]:
    """
    Extract URLs from all categories in navigation tree.

    Main entry point for full extraction pipeline.

    Args:
        navigation_tree: Navigation tree dict with "category_tree" key
        brand_instance: Brand instance for shared state
        parallel: Whether to process categories in parallel
        max_workers: Max parallel workers (default 8)

    Returns:
        Dict with: success, categories (Dict[url, URLExtractionResult]), summary
    """
    from page_extractor import flatten_dict_tree

    start_time = time.time()

    # Extract leaf URLs from navigation tree
    category_tree = navigation_tree.get("category_tree", [])
    leaf_urls = flatten_dict_tree(category_tree)

    _log(f"\n{'='*60}")
    _log(f"🚀 URL EXTRACTION PIPELINE")
    _log(f"{'='*60}")
    _log(f"   Categories to process: {len(leaf_urls)}")
    _log(f"   Parallel: {parallel} (workers: {max_workers})")
    _log(f"{'='*60}\n")

    results: Dict[str, URLExtractionResult] = {}

    if parallel and len(leaf_urls) > 1:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {
                executor.submit(extract_urls_from_category, url, brand_instance): url
                for url in leaf_urls
            }

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    results[url] = result
                except Exception as e:
                    _log(f"   ❌ Category failed: {url} - {e}")
                    results[url] = URLExtractionResult(
                        category_url=url,
                        category_name=extract_category_name(url),
                        errors=[str(e)]
                    )
    else:
        # Sequential processing
        for url in leaf_urls:
            result = extract_urls_from_category(url, brand_instance)
            results[url] = result

    # Calculate summary
    total_urls = sum(len(r.product_urls) for r in results.values())
    all_urls = []
    for r in results.values():
        all_urls.extend([u.url for u in r.product_urls])
    unique_urls = len(set(all_urls))

    total_time = time.time() - start_time

    # Get LLM usage stats
    llm_usage = LLMHandler.get_total_usage()

    summary = {
        "total_categories": len(leaf_urls),
        "successful_categories": sum(1 for r in results.values() if not r.errors),
        "total_urls": total_urls,
        "unique_urls": unique_urls,
        "extraction_time": total_time,
        "llm_calls": llm_usage.get("call_count", 0),
        "estimated_cost_usd": llm_usage.get("estimated_cost_usd", 0)
    }

    _log(f"\n{'='*60}")
    _log(f"📊 EXTRACTION COMPLETE")
    _log(f"{'='*60}")
    _log(f"   Categories: {summary['successful_categories']}/{summary['total_categories']}")
    _log(f"   Total URLs: {summary['total_urls']}")
    _log(f"   Unique URLs: {summary['unique_urls']}")
    _log(f"   Time: {summary['extraction_time']:.2f}s")
    _log(f"   LLM calls: {summary['llm_calls']}")
    _log(f"   Estimated cost: ${summary['estimated_cost_usd']:.4f}")
    _log(f"{'='*60}\n")

    return {
        "success": summary['successful_categories'] > 0,
        "categories": {url: result.to_dict() for url, result in results.items()},
        "summary": summary
    }
