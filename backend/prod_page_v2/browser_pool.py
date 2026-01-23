"""
Browser Pool - Memory-efficient browser instance management.

THE PROBLEM:
    Without pooling, each concurrent extraction launches a new browser:
    - 50 concurrent extractions = 50 Chromium processes
    - Each Chromium process uses 100-200MB RAM
    - Total: 5-10GB RAM just for browsers
    - Plus: 1-3 second startup time per browser (wasted)

THE SOLUTION:
    Keep a fixed pool of browser instances that get reused:
    - 10 browsers in pool = ~1.5GB RAM (fixed)
    - Pages are created/destroyed per request (cheap: 10-50ms)
    - Browsers recycled every N pages (resets memory leaks)

ARCHITECTURE:
    ┌─────────────────────────────────────────────────────────────┐
    │                    BrowserPool(size=10)                     │
    │                                                             │
    │   ┌─────────┐ ┌─────────┐ ┌─────────┐       ┌─────────┐   │
    │   │Browser 1│ │Browser 2│ │Browser 3│  ...  │Browser N│   │
    │   │ pages:3 │ │ pages:47│ │ pages:12│       │ pages:0 │   │
    │   │ [busy]  │ │ [avail] │ │ [busy]  │       │ [avail] │   │
    │   └─────────┘ └─────────┘ └─────────┘       └─────────┘   │
    │                                                             │
    │   Available Queue: [Browser 2, Browser N, ...]             │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘

USAGE:
    # Create pool once at pipeline start
    pool = BrowserPool(size=10, pages_per_recycle=50)
    await pool.start()

    # For each extraction (can be called concurrently)
    async with pool.acquire() as page:
        await page.goto(url)
        html = await page.content()
    # Page automatically returned and closed

    # At pipeline end
    await pool.shutdown()

WHY RECYCLE BROWSERS?
    Even with page closing, browsers accumulate garbage over time:
    - JavaScript heap fragmentation
    - Cached resources not fully freed
    - Internal Chromium state

    Recycling (closing and relaunching) every N pages resets this.
    The "sawtooth" memory pattern keeps RAM bounded.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


@dataclass
class BrowserInstance:
    """
    Wrapper around a single browser instance.

    Tracks usage for recycling decisions.
    """
    browser: Browser
    context: BrowserContext
    pages_served: int = 0          # How many pages this browser has served
    is_available: bool = True      # Whether this browser is free for use
    id: int = 0                    # For logging/debugging

    async def close(self):
        """Clean shutdown of browser and context."""
        try:
            await self.context.close()
        except Exception:
            pass
        try:
            await self.browser.close()
        except Exception:
            pass


class BrowserPool:
    """
    Pool of reusable Playwright browser instances.

    Key concepts:

    1. FIXED SIZE
       - Pool has exactly `size` browser instances
       - This caps memory usage regardless of workload
       - If all browsers busy, callers wait (backpressure)

    2. PAGE LIFECYCLE
       - Each acquire() creates a NEW page on an available browser
       - Each release() CLOSES the page (frees page memory)
       - Browser stays alive (avoids startup cost)

    3. BROWSER RECYCLING
       - After `pages_per_recycle` pages, browser is restarted
       - This resets any accumulated memory leaks
       - Happens transparently during release()

    4. CONCURRENCY CONTROL
       - Uses asyncio.Semaphore to limit concurrent acquisitions
       - Uses asyncio.Queue for fair ordering (FIFO)

    Args:
        size: Number of browser instances in pool (default: 10)
        pages_per_recycle: Restart browser after this many pages (default: 50)
        headless: Run browsers in headless mode (default: True)
    """

    def __init__(
        self,
        size: int = 10,
        pages_per_recycle: int = 50,
        headless: bool = True
    ):
        self.size = size
        self.pages_per_recycle = pages_per_recycle
        self.headless = headless

        # State
        self._playwright: Optional[Playwright] = None
        self._browsers: Dict[int, BrowserInstance] = {}  # id -> instance
        self._available: asyncio.Queue = asyncio.Queue()  # Queue of available browser IDs
        self._lock = asyncio.Lock()  # Protects state modifications

        # Stats (for monitoring)
        self._total_pages_served = 0
        self._total_recycles = 0
        self._started = False

    async def start(self):
        """
        Initialize the pool by launching all browsers.

        This is separate from __init__ because:
        1. Browser launch is async (can't do in __init__)
        2. Allows explicit control over when the expensive
           browser launches happen
        3. Makes error handling clearer

        Call this once before using the pool.
        """
        if self._started:
            return

        print(f"[BrowserPool] Starting pool with {self.size} browsers...")

        # Start Playwright
        # We keep ONE Playwright instance for the whole pool
        # (Playwright manages the connection to browser processes)
        self._playwright = await async_playwright().start()

        # Launch all browsers in parallel for faster startup
        launch_tasks = [
            self._create_browser(i)
            for i in range(self.size)
        ]
        browsers = await asyncio.gather(*launch_tasks)

        # Store browsers and mark all as available
        for browser in browsers:
            self._browsers[browser.id] = browser
            await self._available.put(browser.id)

        self._started = True
        print(f"[BrowserPool] Pool ready. {self.size} browsers available.")

    async def _create_browser(self, browser_id: int) -> BrowserInstance:
        """
        Create a single browser instance with stealth settings.

        Why these specific settings?

        - headless: No GUI = less memory, faster
        - args: Chromium flags for performance/stealth
            --disable-blink-features=AutomationControlled: Hide automation
            --no-sandbox: Required in some environments (Docker)
            --disable-dev-shm-usage: Prevent /dev/shm issues in containers

        Returns a BrowserInstance ready for use.
        """
        # Launch browser with optimized settings
        browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',  # Prevents crashes in memory-constrained environments
                '--no-first-run',
                '--no-default-browser-check',
            ]
        )

        # Create a context (isolated session - cookies, storage, etc.)
        # Each browser has ONE context in our model
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        return BrowserInstance(
            browser=browser,
            context=context,
            pages_served=0,
            is_available=True,
            id=browser_id
        )

    @asynccontextmanager
    async def acquire(self):
        """
        Acquire a page from the pool.

        This is an async context manager, used like:

            async with pool.acquire() as page:
                await page.goto(url)
                html = await page.content()
            # Page automatically released here

        BLOCKING BEHAVIOR:
            If all browsers are busy, this will WAIT until one
            becomes available. This provides natural backpressure -
            if extraction is slower than URL production, the system
            automatically slows down rather than consuming infinite memory.

        WHAT HAPPENS:
            1. Wait for available browser (blocks if none free)
            2. Mark browser as busy
            3. Create NEW page on that browser
            4. Yield page to caller
            5. On exit: close page, maybe recycle browser, mark available

        Yields:
            Page: A fresh Playwright page ready for navigation
        """
        browser_id = None
        page = None

        try:
            # Step 1: Wait for an available browser
            # This is where backpressure happens - if all browsers busy,
            # we wait here until one is released
            browser_id = await self._available.get()

            # Step 2: Get the browser instance and mark it busy
            async with self._lock:
                instance = self._browsers[browser_id]
                instance.is_available = False

            # Step 3: Create a fresh page
            # Pages are cheap to create (~10-50ms)
            # We create fresh ones to avoid state leakage between extractions
            page = await instance.context.new_page()

            # Yield the page for the caller to use
            yield page

        finally:
            # Step 4: Cleanup - always runs, even if extraction raised exception

            # Close the page (frees page memory)
            if page:
                try:
                    await page.close()
                except Exception:
                    pass  # Page might already be closed

            # Return browser to pool
            if browser_id is not None:
                await self._release_browser(browser_id)

    async def _release_browser(self, browser_id: int):
        """
        Return a browser to the available pool.

        Also handles recycling if the browser has served too many pages.

        RECYCLING LOGIC:
            After `pages_per_recycle` pages, we restart the browser.
            This is because browsers accumulate garbage over time:
            - JavaScript heap fragmentation
            - Cached resources
            - Internal state

            Restarting periodically keeps memory bounded.
        """
        async with self._lock:
            instance = self._browsers[browser_id]
            instance.pages_served += 1
            self._total_pages_served += 1

            # Check if browser needs recycling
            if instance.pages_served >= self.pages_per_recycle:
                # Recycle: close old browser, create new one
                print(f"[BrowserPool] Recycling browser {browser_id} after {instance.pages_served} pages")

                await instance.close()

                # Create fresh browser with same ID
                new_instance = await self._create_browser(browser_id)
                self._browsers[browser_id] = new_instance
                self._total_recycles += 1
            else:
                # Just mark as available
                instance.is_available = True

        # Put browser ID back in available queue
        # This wakes up any callers waiting in acquire()
        await self._available.put(browser_id)

    async def shutdown(self):
        """
        Gracefully shut down the pool.

        Closes all browsers and the Playwright instance.
        Call this when you're done with the pool.
        """
        if not self._started:
            return

        print(f"[BrowserPool] Shutting down...")
        print(f"[BrowserPool] Stats: {self._total_pages_served} pages served, {self._total_recycles} recycles")

        # Close all browsers
        for instance in self._browsers.values():
            await instance.close()

        self._browsers.clear()

        # Stop Playwright
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self._started = False
        print(f"[BrowserPool] Shutdown complete.")

    @property
    def stats(self) -> Dict:
        """
        Get current pool statistics.

        Useful for monitoring memory usage and pool health.
        """
        available_count = self._available.qsize()
        busy_count = self.size - available_count

        return {
            "size": self.size,
            "available": available_count,
            "busy": busy_count,
            "total_pages_served": self._total_pages_served,
            "total_recycles": self._total_recycles,
            "pages_per_recycle": self.pages_per_recycle,
        }

    async def __aenter__(self):
        """Support async context manager usage."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Support async context manager usage."""
        await self.shutdown()
        return False
