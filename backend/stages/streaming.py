"""
Streaming Pipeline Orchestrator

Bridges URL extraction (ThreadPoolExecutor) with Product extraction (asyncio)
for streaming pipeline execution. Products start extracting as soon as URLs
become available, rather than waiting for all URL extraction to complete.
"""

import asyncio
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))  # stages/
sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))
sys.path.insert(0, str(Path(__file__).parent.parent / "prod_page_v2"))


@dataclass
class URLBatch:
    """A batch of URLs from a completed category."""
    urls: List[str]
    category_path: str      # For save location (e.g., "women/tops")
    category_name: str      # Human readable
    category_url: str       # Source category URL
    is_sentinel: bool = False  # True = end of stream


@dataclass
class StreamingResult:
    """Result of streaming pipeline execution."""
    success: bool
    urls_extracted: int
    products_extracted: int
    products_successful: int
    duration: float
    errors: List[str] = field(default_factory=list)


class StreamingOrchestrator:
    """
    Orchestrates streaming between URL and Product extraction stages.

    Usage:
        orchestrator = StreamingOrchestrator(domain, nav_tree)
        result = orchestrator.run()
    """

    def __init__(
        self,
        domain: str,
        nav_tree: dict,
        max_url_workers: int = 4,
        product_concurrency: int = 10
    ):
        """
        Initialize streaming orchestrator.

        Args:
            domain: Domain name (e.g., "eckhauslatta_com")
            nav_tree: Navigation tree from Stage 1 (nav.json content)
            max_url_workers: Max parallel URL extraction workers
            product_concurrency: Max concurrent product extractions
        """
        self.domain = domain
        self.nav_tree = nav_tree
        self.max_url_workers = max_url_workers
        self.product_concurrency = product_concurrency

        # Shared queue (thread-safe)
        self.url_queue: queue.Queue[URLBatch] = queue.Queue()

        # Discovery state
        self.discovery_urls: List[Tuple[str, str]] = []  # [(url, category_path), ...]
        self.discovery_complete = threading.Event()
        self.config = None  # MultiStrategyConfig after discovery

        # Stats (thread-safe via queue, final tally at end)
        self.urls_produced = 0
        self.products_extracted = 0
        self.products_successful = 0
        self.products_retried = 0  # Count of retry attempts
        self.errors: List[str] = []

        # URL tracking for urls.json (category -> list of URLs)
        self.category_urls: Dict[str, Dict] = {}  # path -> {name, url, products}

        # Lock for stats updates
        self._stats_lock = threading.Lock()

    def run(self) -> StreamingResult:
        """
        Execute streaming pipeline.

        Returns:
            StreamingResult with stats and status
        """
        start_time = time.time()

        print(f"\n{'='*60}")
        print(f"STREAMING PIPELINE")
        print(f"{'='*60}")
        print(f"Domain: {self.domain}")
        print(f"URL workers: {self.max_url_workers}")
        print(f"Product concurrency: {self.product_concurrency}")
        print(f"{'='*60}\n")

        # Start consumer thread (will wait for discovery)
        consumer_thread = threading.Thread(
            target=self._product_consumer_thread,
            daemon=True,
            name="ProductConsumer"
        )
        consumer_thread.start()

        # Run producer (blocks until all URLs extracted)
        try:
            self._url_producer()
        except Exception as e:
            with self._stats_lock:
                self.errors.append(f"URL producer error: {e}")
            import traceback
            traceback.print_exc()

        # Wait for consumer to finish
        consumer_thread.join(timeout=600)  # 10 min timeout

        if consumer_thread.is_alive():
            with self._stats_lock:
                self.errors.append("Product consumer timed out")

        duration = time.time() - start_time

        print(f"\n{'='*60}")
        print(f"STREAMING COMPLETE")
        print(f"{'='*60}")
        print(f"URLs extracted: {self.urls_produced}")
        print(f"Products extracted: {self.products_extracted}")
        print(f"Products successful: {self.products_successful}")
        print(f"Duration: {duration:.1f}s")
        if self.errors:
            print(f"Errors: {len(self.errors)}")
            for err in self.errors[:5]:
                print(f"  - {err}")
        print(f"{'='*60}\n")

        return StreamingResult(
            success=self.products_successful > 0 or self.urls_produced == 0,
            urls_extracted=self.urls_produced,
            products_extracted=self.products_extracted,
            products_successful=self.products_successful,
            duration=duration,
            errors=self.errors
        )

    def _url_producer(self):
        """
        Extract URLs from categories and feed them to the queue.

        Runs in main thread with ThreadPoolExecutor for parallel category extraction.
        """
        from stages.urls import get_leaf_categories_with_stats, extract_urls_from_category, clean_redundant_parent_urls, dedupe_urls_by_path
        from stages.storage import ensure_domain_dir
        from brand import Brand

        # Clean redundant parent URLs (where parent URL = child URL)
        tree = self.nav_tree.get("category_tree", [])
        removed_parents = clean_redundant_parent_urls(tree)
        if removed_parents:
            print(f"[URL Producer] Removed {len(removed_parents)} redundant parent URLs:")
            for path in removed_parents:
                print(f"  - {path}")

        # Get leaf categories from nav tree (skipping "View All" type with 2+ siblings)
        leaves, skipped_count, _ = get_leaf_categories_with_stats(tree)

        if not leaves:
            print("No leaf categories found in navigation tree")
            self.url_queue.put(URLBatch(
                urls=[], category_path="", category_name="",
                category_url="", is_sentinel=True
            ))
            return

        if skipped_count > 0:
            print(f"[URL Producer] Starting extraction of {len(leaves)} categories ({skipped_count} 'All' categories skipped)")
        else:
            print(f"[URL Producer] Starting extraction of {len(leaves)} categories")

        # Create brand instance for shared state (lineage caching)
        domain_with_dots = self.domain.replace('_', '.')
        brand = Brand(url=f"https://{domain_with_dots}/")

        # Track dedup stats and raw URLs
        all_raw_urls = []
        dedup_stats = {"total_raw": 0, "total_deduped": 0, "total_removed": 0}

        # Track discovery phase
        discovery_needed = 2
        discovery_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=self.max_url_workers) as executor:
            futures = {
                executor.submit(
                    extract_urls_from_category,
                    leaf["url"],
                    leaf["name"],
                    brand
                ): leaf
                for leaf in leaves
            }

            completed = 0
            for future in as_completed(futures):
                leaf = futures[future]
                completed += 1

                try:
                    result = future.result()
                    raw_urls = result.get("urls", [])

                    if not raw_urls:
                        print(f"  [{completed}/{len(leaves)}] {leaf['name']}: 0 URLs")
                        continue

                    # Track raw URLs for full_urls.txt
                    all_raw_urls.extend(raw_urls)

                    # Dedupe URLs by path (removes color variants, etc.)
                    urls, raw_count, removed_count = dedupe_urls_by_path(raw_urls)
                    dedup_stats["total_raw"] += raw_count
                    dedup_stats["total_deduped"] += len(urls)
                    dedup_stats["total_removed"] += removed_count

                    dedup_note = f" (deduped from {raw_count})" if removed_count > 0 else ""
                    print(f"  [{completed}/{len(leaves)}] {leaf['name']}: {len(urls)} URLs{dedup_note}")

                    # Convert path to filesystem-safe format
                    category_path = leaf["path"].lower().replace(" ", "-")
                    category_path = ''.join(c for c in category_path if c.isalnum() or c in '-/')

                    # Discovery phase: collect first 2 URLs
                    with discovery_lock:
                        if len(self.discovery_urls) < discovery_needed:
                            for url in urls:
                                if len(self.discovery_urls) < discovery_needed:
                                    self.discovery_urls.append((url, category_path))

                            if len(self.discovery_urls) >= discovery_needed:
                                print(f"\n[Discovery] Got {len(self.discovery_urls)} URLs for discovery")
                                self.discovery_complete.set()

                    # Put batch in queue
                    batch = URLBatch(
                        urls=urls,
                        category_path=category_path,
                        category_name=leaf["name"],
                        category_url=leaf["url"]
                    )
                    self.url_queue.put(batch)

                    with self._stats_lock:
                        self.urls_produced += len(urls)
                        # Track URLs for urls.json
                        self.category_urls[category_path] = {
                            "name": leaf["name"],
                            "url": leaf["url"],
                            "path": leaf["path"],
                            "products": urls
                        }

                except Exception as e:
                    print(f"  [{completed}/{len(leaves)}] {leaf['name']}: ERROR - {e}")
                    with self._stats_lock:
                        self.errors.append(f"Category {leaf['name']}: {e}")

        # Save full_urls.txt (all raw URLs before dedup)
        domain_dir = ensure_domain_dir(self.domain)
        full_urls_path = domain_dir / "full_urls.txt"
        with open(full_urls_path, 'w') as f:
            for url in all_raw_urls:
                f.write(f"{url}\n")
        print(f"\n[URL Producer] Saved raw URLs: {full_urls_path}")

        # Save urls.json (deduped URLs organized by category)
        self._save_urls_json()

        # Dedup warning if >70% removed
        if dedup_stats["total_raw"] > 0:
            removal_pct = (dedup_stats["total_removed"] / dedup_stats["total_raw"]) * 100
            if removal_pct > 70:
                print(f"\n  ⚠️  WARNING: {removal_pct:.1f}% of URLs removed by dedup ({dedup_stats['total_removed']}/{dedup_stats['total_raw']})")
                print(f"     This may indicate an issue with URL structure or excessive variants.")

        # Signal completion
        print(f"\n[URL Producer] Complete. Raw: {dedup_stats['total_raw']}, After dedup: {self.urls_produced}")
        self.url_queue.put(URLBatch(
            urls=[], category_path="", category_name="",
            category_url="", is_sentinel=True
        ))

        # Ensure discovery is signaled even if we have < 2 URLs
        self.discovery_complete.set()

    def _product_consumer_thread(self):
        """
        Consume URLs from queue and extract products.

        Runs in a separate thread with its own asyncio event loop.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._async_product_consumer())
        except Exception as e:
            with self._stats_lock:
                self.errors.append(f"Product consumer error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            loop.close()

    async def _async_product_consumer(self):
        """
        Async consumer that extracts products from queued URLs.

        Uses:
        - BrowserPool: Memory-efficient browser reuse (fixed RAM regardless of queue size)
        - AdaptiveRateLimiter: Adjusts concurrency to avoid rate limits

        ARCHITECTURE:
            ┌─────────────────────────────────────────────────────────────────┐
            │                     Product Consumer                            │
            │                                                                 │
            │   URL Queue ──▶ Rate Limiter ──▶ Browser Pool ──▶ Extractor   │
            │                 (controls       (provides        (extracts     │
            │                  speed)          pages)           product)     │
            └─────────────────────────────────────────────────────────────────┘

        The two layers of control serve different purposes:
        - Rate limiter: Prevents HTTP 429 errors from the target site
        - Browser pool: Caps memory usage (10 browsers = ~1.5GB max)
        """
        from prod_page_v2.extractor import ProductExtractor
        from prod_page_v2.browser_pool import BrowserPool
        from stages.storage import save_product
        from stages.rate_limiter import AdaptiveRateLimiter

        print("[Product Consumer] Waiting for discovery URLs...")

        # Wait for discovery phase (first 2 URLs)
        while not self.discovery_complete.is_set():
            await asyncio.sleep(0.1)

        if len(self.discovery_urls) < 2:
            print("[Product Consumer] Not enough URLs for discovery, exiting")
            return

        # Run discovery
        print(f"[Product Consumer] Running discovery with {len(self.discovery_urls)} URLs...")
        extractor = ProductExtractor()
        domain_with_dots = self.domain.replace('_', '.')

        discovery_url_list = [url for url, _ in self.discovery_urls]
        self.config = await extractor.discover_and_verify(domain_with_dots, discovery_url_list)

        if not self.config:
            print("[Product Consumer] Discovery failed, exiting")
            with self._stats_lock:
                self.errors.append("Discovery failed")
            return

        print(f"[Product Consumer] Discovery complete. Setting up extraction pipeline...")

        # Track which URLs we've already processed
        processed_urls: Set[str] = set()

        # =================================================================
        # BROWSER POOL SETUP
        # =================================================================
        # The browser pool provides memory-efficient browser reuse:
        # - Fixed number of browsers (caps RAM usage)
        # - Pages created/destroyed per request (prevents memory leaks)
        # - Browsers recycled every N pages (resets accumulated garbage)
        #
        # Pool size should be >= rate limiter's max concurrency
        # (otherwise pool becomes the bottleneck, not rate limiting)
        # =================================================================
        pool_size = min(15, self.product_concurrency)  # Don't need more browsers than concurrency
        browser_pool = BrowserPool(
            size=pool_size,
            pages_per_recycle=50,  # Restart browser every 50 pages to prevent memory leaks
            headless=True
        )

        # =================================================================
        # RATE LIMITER SETUP (v2 - Token Bucket with Shared Pause)
        # =================================================================
        # The new rate limiter:
        # - Uses token bucket to enforce exact requests/second
        # - On ANY 429: pauses ALL workers, calculates actual rate
        # - Resumes at calculated safe rate
        # - No wasted 429s from independent learning
        # =================================================================
        rate_limiter = AdaptiveRateLimiter(
            initial_rate=float(self.product_concurrency),  # Start at N req/s
            max_rate=50.0,
            min_rate=2.0,  # Don't go below 2 req/s (prevents worker starvation)
            burst_size=pool_size  # Allow all workers to start after pause
        )

        print(f"[Product Consumer] Browser pool: {pool_size} browsers")
        print(f"[Product Consumer] Rate limiter: starting at {rate_limiter.rate:.1f} req/s")

        # Start browser pool
        await browser_pool.start()

        try:
            # Extract and save discovery products (not using pool yet - these were already loaded)
            for url, category_path in self.discovery_urls:
                result = await extractor.extract_single(url, self.config)
                with self._stats_lock:
                    self.products_extracted += 1
                if result.success and result.product:
                    product_dict = self._product_to_dict(result.product, url)
                    save_product(self.domain, product_dict, category_path, source_url=url)
                    with self._stats_lock:
                        self.products_successful += 1
                processed_urls.add(url)

            print(f"[Product Consumer] Discovery products saved. Processing queue...")

            pending_tasks: Set[asyncio.Task] = set()
            MAX_RETRIES = 3  # Retry configuration

            # Progress tracking
            progress = {
                "total_queued": 0,
                "completed": 0,
                "successful": 0,
                "failed": 0,
                "in_flight": 0,
                "last_log_time": time.time(),
                "categories_received": 0,
            }
            PROGRESS_INTERVAL = 3  # Log progress every 3 seconds

            def log_progress(force: bool = False):
                """Log progress if enough time has passed."""
                now = time.time()
                if force or (now - progress["last_log_time"]) >= PROGRESS_INTERVAL:
                    progress["last_log_time"] = now
                    pct = (progress["completed"] / progress["total_queued"] * 100) if progress["total_queued"] > 0 else 0
                    print(f"[Progress] {progress['completed']}/{progress['total_queued']} ({pct:.0f}%) | "
                          f"✓{progress['successful']} ✗{progress['failed']} | "
                          f"in-flight: {progress['in_flight']} | "
                          f"rate: {rate_limiter.rate:.1f}/s")

            async def extract_and_save(url: str, category_path: str, max_retries: int = MAX_RETRIES):
                """
                Extract a single product with retry logic.

                RETRY STRATEGY:
                    ┌─────────────────────────────────────────────────────┐
                    │  Attempt 1: Try extraction                         │
                    │      ↓ fail                                        │
                    │  Wait 1 second (backoff)                           │
                    │      ↓                                             │
                    │  Attempt 2: Try extraction                         │
                    │      ↓ fail                                        │
                    │  Wait 2 seconds (backoff)                          │
                    │      ↓                                             │
                    │  Attempt 3: Try extraction                         │
                    │      ↓ fail                                        │
                    │  Give up, log error                                │
                    └─────────────────────────────────────────────────────┘

                Each attempt:
                1. Acquires rate limiter slot (respects concurrency limits)
                2. Acquires fresh page from browser pool
                3. Attempts extraction
                4. On failure: releases resources, waits, retries
                5. On success: saves product, done
                """
                last_error = None

                progress["in_flight"] += 1

                for attempt in range(max_retries):
                    # Backoff before retry (not on first attempt)
                    if attempt > 0:
                        backoff = 2 ** (attempt - 1)  # 1s, 2s for attempts 2, 3
                        await asyncio.sleep(backoff)
                        with self._stats_lock:
                            self.products_retried += 1

                    # New rate limiter API: acquire() returns token context manager
                    # token.record() reports outcome (triggers shared pause on 429)
                    async with await rate_limiter.acquire() as token:
                        try:
                            # Acquire fresh page from pool for each attempt
                            # (previous page might be in bad state after failure)
                            async with browser_pool.acquire() as page:
                                result = await extractor.extract_single_pooled(url, page, self.config)

                            # Check if extraction succeeded
                            if result.success and result.product:
                                # SUCCESS - record good outcome, save product
                                await token.record(200)

                                with self._stats_lock:
                                    self.products_extracted += 1
                                    self.products_successful += 1

                                progress["completed"] += 1
                                progress["successful"] += 1
                                progress["in_flight"] -= 1
                                log_progress()

                                product_dict = self._product_to_dict(result.product, url)
                                save_product(self.domain, product_dict, category_path, source_url=url)
                                return  # Done!

                            else:
                                # Extraction ran but didn't get product - might be transient
                                last_error = result.error or "No product extracted"
                                await token.record(500)
                                # Continue to retry

                        except Exception as e:
                            # Exception during extraction - definitely retry
                            last_error = str(e)
                            await token.record(500)
                            # Continue to retry

                # All retries exhausted
                progress["completed"] += 1
                progress["failed"] += 1
                progress["in_flight"] -= 1
                log_progress()

                with self._stats_lock:
                    self.products_extracted += 1  # We tried
                    self.errors.append(f"Product {url}: {last_error} (after {max_retries} attempts)")

            # Process queue with TRUE async (non-blocking queue access)
            # The key fix: use run_in_executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()

            async def get_batch_async():
                """Non-blocking queue get using executor."""
                try:
                    return await loop.run_in_executor(
                        None,  # Default executor
                        lambda: self.url_queue.get(timeout=0.5)
                    )
                except queue.Empty:
                    return None

            print(f"[Product Consumer] Starting extraction (streaming mode)...")

            queue_exhausted = False
            while not queue_exhausted or pending_tasks:
                # Check for new batches (non-blocking)
                if not queue_exhausted:
                    batch = await get_batch_async()

                    if batch is None:
                        # No batch ready - let tasks run
                        pass
                    elif batch.is_sentinel:
                        # URL producer is done
                        queue_exhausted = True
                        print(f"[Product Consumer] All URLs received. {progress['total_queued']} products to extract.")
                        log_progress(force=True)
                    else:
                        # New batch arrived - queue up extractions
                        progress["categories_received"] += 1
                        new_urls = 0
                        for url in batch.urls:
                            if url not in processed_urls:
                                processed_urls.add(url)
                                progress["total_queued"] += 1
                                new_urls += 1

                                task = asyncio.create_task(
                                    extract_and_save(url, batch.category_path)
                                )
                                pending_tasks.add(task)

                        print(f"[Category] {batch.category_name}: +{new_urls} products (total queued: {progress['total_queued']})")

                # Clean up completed tasks
                done_tasks = {t for t in pending_tasks if t.done()}
                pending_tasks -= done_tasks

                # Let other tasks run
                if pending_tasks or not queue_exhausted:
                    await asyncio.sleep(0.1)

            # Final progress
            log_progress(force=True)
            print(f"[Product Consumer] All extractions complete.")

        finally:
            # =================================================================
            # CLEANUP
            # =================================================================
            # Always shut down browser pool, even if extraction failed.
            # This closes all browser processes and frees memory.
            # =================================================================
            await browser_pool.shutdown()

        # Print final stats
        rate_stats = rate_limiter.stats
        pool_stats = browser_pool.stats
        failed_count = self.products_extracted - self.products_successful

        print(f"\n[Product Consumer] Complete!")
        print(f"    Products: {self.products_successful}/{self.products_extracted} succeeded")
        if failed_count > 0:
            print(f"    Failed: {failed_count} products (after {MAX_RETRIES} retries each)")
        if self.products_retried > 0:
            print(f"    Retries: {self.products_retried} total retry attempts")
        print(f"    Rate limiter: final rate {rate_stats['rate']:.1f} req/s, {rate_stats['total_rate_limited']} rate limited")
        print(f"    Browser pool: {pool_stats['total_pages_served']} pages, {pool_stats['total_recycles']} browser recycles")

    def _product_to_dict(self, product, source_url: str) -> dict:
        """Convert Product object to dictionary for saving."""
        return {
            "name": product.name,
            "price": product.price,
            "currency": product.currency,
            "images": product.images,
            "description": product.description,
            "url": product.url,
            "source_url": source_url,
            "brand": product.brand,
            "sku": product.sku,
            "category": product.category,
            "variants": [
                {
                    "size": v.size,
                    "color": v.color,
                    "sku": v.sku,
                    "price": v.price,
                    "available": v.available,
                }
                for v in product.variants
            ],
        }

    def _save_urls_json(self):
        """
        Save urls.json with category structure and deduped product URLs.

        Format matches standard urls.json:
        {
            "category_tree": [
                {"name": "...", "url": "...", "products": [...], "children": [...]},
                ...
            ],
            "total_products": N,
            "unique_products": M
        }
        """
        from stages.storage import save_urls

        # Build flat category list (we don't have tree hierarchy in streaming mode)
        category_tree = []
        all_urls = set()

        for path, data in self.category_urls.items():
            category_tree.append({
                "name": data["name"],
                "url": data["url"],
                "path": data.get("path", path),
                "products": data["products"],
                "product_count": len(data["products"]),
                "children": []
            })
            all_urls.update(data["products"])

        urls_tree = {
            "category_tree": category_tree,
            "total_products": sum(len(d["products"]) for d in self.category_urls.values()),
            "unique_products": len(all_urls)
        }

        json_path, txt_path = save_urls(self.domain, urls_tree)
        print(f"[URL Producer] Saved urls.json: {json_path}")
