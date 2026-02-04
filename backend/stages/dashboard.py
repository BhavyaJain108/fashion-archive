"""
Live terminal dashboard for extraction pipeline.

Replaces noisy scroll/load/schema logs with a clean, in-place updating view
showing rate, browsers, progress bar, and recent product outcomes.
"""

import asyncio
import io
import os
import sys
import time
from collections import deque
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import urlparse


class Dashboard:
    """
    Live-updating terminal dashboard for product extraction.

    Usage:
        dashboard = Dashboard("kuurth.com", progress, rate_limiter, browser_pool)
        task = asyncio.create_task(dashboard.run())
        # ... extraction happens ...
        dashboard.stop()
        await task
    """

    WIDTH = 62

    def __init__(self, domain: str, progress: Dict, rate_limiter, browser_pool):
        self.domain = domain
        self.progress = progress
        self.rate_limiter = rate_limiter
        self.browser_pool = browser_pool

        self._running = False
        self._recent: deque = deque(maxlen=8)  # (slug, success, error)
        self._skipped = 0
        self._start_time = time.time()

        # Rate direction tracking
        self._last_rate = rate_limiter.rate
        self._rate_direction = "stable"  # "up", "down", "stable"

    def record_outcome(self, url: str, success: bool, error: str = None):
        slug = self._slug(url)
        self._recent.append((slug, success, error))

    def record_skip(self, url: str):
        self._skipped += 1

    def stop(self):
        self._running = False

    async def run(self):
        self._running = True
        # Suppress other modules' stdout — dashboard writes directly to terminal fd
        self._real_stdout = sys.stdout
        try:
            self._tty = open("/dev/tty", "w") if os.path.exists("/dev/tty") else sys.stdout
        except OSError:
            self._tty = sys.stdout
        sys.stdout = io.StringIO()  # Swallow all other prints

        # Clear screen once at start
        self._tty.write("\033[2J\033[H")
        self._tty.flush()

        while self._running:
            self._update_rate_direction()
            output = self.render()
            # Move cursor to top-left, then draw
            self._tty.write("\033[H" + output)
            self._tty.flush()
            # Discard anything other modules printed
            sys.stdout = io.StringIO()
            await asyncio.sleep(0.5)

        # Restore stdout
        sys.stdout = self._real_stdout

        # Final render + clear screen artifacts
        self._update_rate_direction()
        print(self.render())
        if self._tty is not self._real_stdout:
            self._tty.close()

    def render(self) -> str:
        p = self.progress
        now = time.time()
        elapsed = now - self._start_time

        # Header
        elapsed_str = self._fmt_duration(elapsed)
        header = f"  Fashion Archive -- {self.domain}"
        header = header.ljust(self.WIDTH - len(elapsed_str) - 4) + elapsed_str + "  "

        # Progress bar
        total = max(p.get("total_queued", 0), 1)
        completed = p.get("completed", 0)
        pct = completed / total
        bar_width = 30
        filled = int(bar_width * pct)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        progress_line = f"  Progress  [{bar}]  {completed}/{total} ({pct*100:.0f}%)"

        # Counts
        ok = p.get("successful", 0)
        fail = p.get("failed", 0)
        counts = f"  \u2713 {ok}  \u2717 {fail}"
        if self._skipped:
            counts += f"  \u2298 {self._skipped} skipped"

        # Rate
        rate = self.rate_limiter.rate
        arrow = {"up": "\u25b2", "down": "\u25bc", "stable": "\u2192"}[self._rate_direction]
        label = {"up": "(ramping)", "down": "(throttled)", "stable": ""}[self._rate_direction]
        rate_line = f"  Rate       {rate:.1f} req/s  {arrow} {label}"

        # Browsers
        try:
            free = self.browser_pool._available.qsize()
            total_b = self.browser_pool.size
            busy = total_b - free
            browser_line = f"  Browsers   {busy}/{total_b} busy"
        except Exception:
            browser_line = "  Browsers   --"

        # Throughput
        if elapsed > 0:
            overall = completed / elapsed
        else:
            overall = 0
        dt = now - p.get("last_log_time", now)
        recent_done = completed - p.get("last_log_completed", 0)
        recent_rate = recent_done / dt if dt > 2 else overall
        tp_line = f"  Throughput {recent_rate:.1f}/s recent | {overall:.1f}/s avg"

        # ETA
        remaining = total - completed
        eta = remaining / overall if overall > 0 else 0
        eta_line = f"  ETA        {self._fmt_duration(eta)}"

        # Recent products (2 columns, up to 8)
        recent_lines = []
        items = list(self._recent)
        for i in range(0, len(items), 2):
            left = self._fmt_outcome(items[i])
            right = self._fmt_outcome(items[i + 1]) if i + 1 < len(items) else ""
            recent_lines.append(f"    {left:<28} {right}")

        # Build frame
        W = self.WIDTH
        top = "\u2554" + "\u2550" * W + "\u2557"
        mid = "\u2560" + "\u2550" * W + "\u2563"
        bot = "\u255a" + "\u2550" * W + "\u255d"
        v = "\u2551"

        lines = [
            top,
            v + header.ljust(W) + v,
            mid,
            v + "".ljust(W) + v,
            v + progress_line.ljust(W) + v,
            v + counts.ljust(W) + v,
            v + "".ljust(W) + v,
            v + rate_line.ljust(W) + v,
            v + browser_line.ljust(W) + v,
            v + tp_line.ljust(W) + v,
            v + eta_line.ljust(W) + v,
            v + "".ljust(W) + v,
            v + "  Recent:".ljust(W) + v,
        ]
        for rl in recent_lines:
            lines.append(v + rl.ljust(W) + v)
        if not recent_lines:
            lines.append(v + "    (waiting...)".ljust(W) + v)
        lines.append(v + "".ljust(W) + v)
        lines.append(bot)

        # Clear each line to prevent artifacts from previous longer renders
        return "\n".join(f"\033[K{line}" for line in lines) + "\n"

    def _update_rate_direction(self):
        current = self.rate_limiter.rate
        if current > self._last_rate * 1.05:
            self._rate_direction = "up"
        elif current < self._last_rate * 0.95:
            self._rate_direction = "down"
        else:
            self._rate_direction = "stable"
        self._last_rate = current

    @staticmethod
    def _slug(url: str) -> str:
        path = urlparse(url).path
        if "/products/" in path:
            return path.split("/products/")[-1].rstrip("/")
        parts = path.rstrip("/").split("/")
        return parts[-1] if parts else url

    @staticmethod
    def _fmt_outcome(item: tuple) -> str:
        slug, success, error = item
        slug = slug[:22]
        if success:
            return f"\u2713 {slug}"
        else:
            short_err = ""
            if error:
                short_err = f" ({error[:15]})"
            return f"\u2717 {slug}{short_err}"

    @staticmethod
    def _fmt_duration(secs: float) -> str:
        secs = max(0, secs)
        if secs < 60:
            return f"{secs:.0f}s"
        m, s = divmod(int(secs), 60)
        if m < 60:
            return f"{m}m {s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m"
