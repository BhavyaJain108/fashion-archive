"""
Adaptive Rate Limiter v2 - Finds and maintains exact rate limit.

THE PROBLEM WITH v1:
    - Each worker learned independently (wasted 429s)
    - Used arbitrary exponential backoff (guessing)
    - Didn't calculate actual rate limit

THE SOLUTION (v2):
    - Shared state: ONE 429 pauses ALL workers immediately
    - Calculates exact rate from successes/time
    - Maintains rate with token bucket algorithm
    - Respects Retry-After headers

ARCHITECTURE:
    ┌─────────────────────────────────────────────────────────────────┐
    │                 AdaptiveRateLimiter (shared)                    │
    │                                                                 │
    │   State:                                                        │
    │   • tokens: float         (available request slots)             │
    │   • last_refill: time     (when we last added tokens)           │
    │   • rate: float           (tokens per second = requests/sec)    │
    │   • paused_until: time    (if set, all workers wait)           │
    │                                                                 │
    │   On each request:                                              │
    │   1. Check if paused → wait until pause ends                   │
    │   2. Wait for token (refills at `rate` per second)             │
    │   3. Make request                                               │
    │   4. On 429 → calculate rate, pause all, set new rate          │
    │                                                                 │
    └─────────────────────────────────────────────────────────────────┘

TOKEN BUCKET ALGORITHM:
    Imagine a bucket that:
    - Holds up to `max_tokens` tokens
    - Refills at `rate` tokens per second
    - Each request takes 1 token
    - If empty, you wait for refill

    This naturally enforces the rate limit without explicit timing.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Callable, Any
from collections import deque
from enum import Enum


def _ts() -> str:
    """Timestamp prefix for log messages."""
    return datetime.now().strftime("%H:%M:%S")


class RateLimitState(Enum):
    """Current state of the rate limiter."""
    CALIBRATING = "calibrating"  # Still learning the rate limit
    RUNNING = "running"          # Operating at known rate
    PAUSED = "paused"            # Hit limit, waiting to resume


@dataclass
class RequestOutcome:
    """Record of a single request outcome."""
    timestamp: float
    success: bool
    status_code: int
    latency: float = 0.0
    retry_after: Optional[float] = None  # From Retry-After header


class AdaptiveRateLimiter:
    """
    Rate limiter that finds and maintains the exact rate limit.

    KEY CONCEPTS:

    1. TOKEN BUCKET
       Instead of counting concurrent requests, we use tokens:
       - Bucket refills at `rate` tokens/second
       - Each request consumes 1 token
       - If no tokens, wait for refill

       This automatically enforces requests/second regardless of latency.

    2. SHARED PAUSE
       When ANY request gets 429:
       - ALL workers pause immediately
       - We calculate the actual rate from recent successes
       - We wait for Retry-After (or calculated time)
       - ALL workers resume at new rate

    3. RATE CALCULATION
       rate = successful_requests / time_window

       Example: 15 successes in 1.5 seconds = 10 req/s limit

    Args:
        initial_rate: Starting rate in requests/second (default: 10)
        max_rate: Maximum rate to ever attempt (default: 100)
        min_rate: Minimum rate (default: 1)
    """

    def __init__(
        self,
        initial_rate: float = 10.0,
        max_rate: float = 100.0,
        min_rate: float = 1.0,
        burst_size: int = 5,  # Allow small bursts
        quiet: bool = False,  # Suppress print output (for dashboard mode)
    ):
        self.initial_rate = initial_rate
        self.max_rate = max_rate
        self.min_rate = min_rate
        self.quiet = quiet
        self.burst_size = burst_size

        # Token bucket state
        self._rate = initial_rate  # Current rate (tokens/second)
        self._tokens = float(burst_size)  # Start with burst allowance
        self._max_tokens = float(max(burst_size, initial_rate))  # Allow burst up to rate
        self._last_refill = time.time()

        # Pause state (shared across all workers)
        self._paused_until: Optional[float] = None
        self._state = RateLimitState.CALIBRATING

        # Tracking for rate calculation
        self._window_start = time.time()
        self._window_successes = 0
        self._window_failures = 0
        self._recent_outcomes: deque = deque(maxlen=100)

        # Ramp-up state
        self._last_ramp_time = time.time()  # When we last increased rate
        self._last_429_time: Optional[float] = None  # When we last got blocked
        self._ramp_interval = 10.0  # Try ramping every 10 seconds
        self._ramp_factor = 1.20  # Increase by 20% each ramp
        self._ramp_cooldown = 30.0  # Wait 30s after a 429 before ramping again

        # Lock for thread-safe updates
        self._lock = asyncio.Lock()

        # Stats
        self._total_requests = 0
        self._total_rate_limited = 0
        self._rate_adjustments: List[Dict] = []  # History of rate changes

    def _log(self, msg: str):
        """Print unless in quiet mode (dashboard active)."""
        if not self.quiet:
            print(msg)

    @property
    def rate(self) -> float:
        """Current rate in requests/second."""
        return self._rate

    @property
    def state(self) -> RateLimitState:
        """Current state of the limiter."""
        return self._state

    @property
    def stats(self) -> Dict:
        """Current statistics."""
        return {
            "rate": self._rate,
            "state": self._state.value,
            "tokens_available": self._tokens,
            "total_requests": self._total_requests,
            "total_rate_limited": self._total_rate_limited,
            "window_successes": self._window_successes,
            "window_failures": self._window_failures,
            "rate_adjustments": len(self._rate_adjustments),
        }

    async def acquire(self) -> 'RateLimitToken':
        """
        Acquire permission to make a request.

        This will:
        1. Wait if system is paused (hit rate limit)
        2. Wait for token from bucket (maintains rate)

        Usage:
            async with limiter.acquire() as token:
                response = await make_request()
                await token.record(response.status, response.headers)

        Returns:
            RateLimitToken context manager
        """
        return RateLimitToken(self)

    async def _wait_for_token(self, timeout: float = 60.0):
        """
        Wait until a token is available.

        TOKEN BUCKET MECHANICS:
            - Tokens refill at `self._rate` per second
            - We calculate how many tokens have been added since last check
            - If tokens available, take one and proceed
            - If not, calculate wait time and sleep

        Args:
            timeout: Maximum time to wait for a token (prevents infinite waits)
        """
        start_wait = time.time()

        while True:
            # Timeout check - prevent infinite waits
            elapsed_wait = time.time() - start_wait
            if elapsed_wait > timeout:
                self._log(f"[{_ts()}] [RateLimiter] WARNING: Token wait timeout ({timeout}s), forcing through")
                self._log(f"    State: rate={self._rate:.2f}/s, tokens={self._tokens:.2f}, paused={self._paused_until is not None}")
                self._total_requests += 1
                return

            # Periodic warning for long waits
            if elapsed_wait > 30 and int(elapsed_wait) % 10 == 0:
                self._log(f"[{_ts()}] [RateLimiter] Long wait: {elapsed_wait:.0f}s, rate={self._rate:.2f}/s, tokens={self._tokens:.2f}")

            async with self._lock:
                # First check: are we paused?
                if self._paused_until:
                    wait_time = self._paused_until - time.time()
                    if wait_time > 0:
                        # Release lock while waiting
                        pass
                    else:
                        # Pause is over
                        self._paused_until = None
                        self._state = RateLimitState.RUNNING
                        wait_time = 0
                else:
                    wait_time = 0

            if wait_time > 0:
                await asyncio.sleep(min(wait_time, 5.0))  # Cap individual waits at 5s
                continue

            async with self._lock:
                # Refill tokens based on elapsed time
                now = time.time()
                elapsed = now - self._last_refill
                tokens_to_add = elapsed * self._rate
                self._tokens = min(self._max_tokens, self._tokens + tokens_to_add)
                self._last_refill = now

                # Try to take a token
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_requests += 1
                    return  # Got a token!

                # No token available - calculate wait time
                tokens_needed = 1.0 - self._tokens
                wait_time = tokens_needed / self._rate

            # Wait outside the lock (cap at 5s to allow timeout checks)
            await asyncio.sleep(min(wait_time, 5.0))

    async def record_outcome(
        self,
        status_code: int,
        latency: float = 0.0,
        retry_after: Optional[float] = None
    ):
        """
        Record the outcome of a request.

        This is where the magic happens:
        - On success (2xx): increment success counter
        - On rate limit (429): PAUSE ALL, calculate rate, adjust

        Args:
            status_code: HTTP status code
            latency: Request duration in seconds
            retry_after: Value from Retry-After header (if present)
        """
        outcome = RequestOutcome(
            timestamp=time.time(),
            success=200 <= status_code < 400,
            status_code=status_code,
            latency=latency,
            retry_after=retry_after
        )

        async with self._lock:
            self._recent_outcomes.append(outcome)

            if outcome.success:
                self._window_successes += 1
                self._try_ramp_up()
            else:
                self._window_failures += 1

                if status_code == 429:
                    self._total_rate_limited += 1
                    await self._handle_rate_limit(outcome)

    async def _handle_rate_limit(self, outcome: RequestOutcome):
        """
        Handle a 429 rate limit response.

        This is called while holding the lock.

        STEPS:
        1. Calculate actual rate from recent successes
        2. Pause all workers
        3. Set new rate
        4. Reset tracking window
        """
        # Calculate the rate we were achieving before hitting limit
        window_duration = time.time() - self._window_start

        if window_duration > 0 and self._window_successes > 0:
            # Actual rate = successes / time
            measured_rate = self._window_successes / window_duration

            # The limit is slightly below what we achieved
            # Use 90% of measured rate as safe rate
            new_rate = measured_rate * 0.90
            new_rate = max(self.min_rate, min(self.max_rate, new_rate))

            # Log the adjustment
            self._rate_adjustments.append({
                "time": time.time(),
                "old_rate": self._rate,
                "new_rate": new_rate,
                "measured_rate": measured_rate,
                "window_successes": self._window_successes,
                "window_duration": window_duration,
                "retry_after": outcome.retry_after
            })

            self._log(f"\n[{_ts()}] [RateLimiter] 429 detected!")
            self._log(f"    Measured rate: {measured_rate:.1f} req/s")
            self._log(f"    New safe rate: {new_rate:.1f} req/s")

            self._rate = new_rate
        else:
            # Not enough data - reduce by 50%
            new_rate = max(self.min_rate, self._rate * 0.5)
            self._log(f"\n[{_ts()}] [RateLimiter] 429 detected! Reducing rate {self._rate:.1f} → {new_rate:.1f}")
            self._rate = new_rate

        # Determine pause duration
        if outcome.retry_after:
            # Server told us exactly how long to wait
            pause_duration = outcome.retry_after
            self._log(f"    Retry-After: {pause_duration}s")
        else:
            # Default: pause for 1 second
            pause_duration = 1.0

        # Pause all workers
        self._paused_until = time.time() + pause_duration
        self._state = RateLimitState.PAUSED
        self._last_429_time = time.time()  # Track for ramp-up cooldown

        # Reset tracking window
        self._window_start = time.time()
        self._window_successes = 0
        self._window_failures = 0

        # Reset tokens - give a small burst allowance after pause
        # Note: _last_refill should be NOW, not future (else elapsed becomes negative!)
        self._tokens = min(3, self.burst_size)  # Small burst to get going
        self._last_refill = time.time()

    def _try_ramp_up(self):
        """
        Try to increase rate if things have been smooth.

        Called on every success (while holding lock).
        Only ramps if:
        - Enough time since last ramp attempt
        - Enough time since last 429
        - We have enough successes to be confident
        - We haven't hit max rate
        """
        now = time.time()

        # Don't ramp too frequently
        if now - self._last_ramp_time < self._ramp_interval:
            return

        # Don't ramp if we recently got blocked
        if self._last_429_time and now - self._last_429_time < self._ramp_cooldown:
            return

        # Need at least 10 successes to be confident
        if self._window_successes < 10:
            return

        # Already at max
        if self._rate >= self.max_rate:
            return

        # Ramp up!
        old_rate = self._rate
        successes_at_ramp = self._window_successes
        self._rate = min(self.max_rate, self._rate * self._ramp_factor)
        self._max_tokens = max(self._max_tokens, self._rate)  # Grow bucket with rate
        self._last_ramp_time = now

        self._log(f"[{_ts()}] [RateLimiter] Ramping up: {old_rate:.1f} → {self._rate:.1f} req/s "
                 f"({successes_at_ramp} successes, 0 rejections)")

        # Reset window to measure at new rate
        self._window_start = now
        self._window_successes = 0
        self._window_failures = 0


class RateLimitToken:
    """
    Context manager for rate-limited requests.

    Usage:
        async with limiter.acquire() as token:
            response = await fetch(url)
            await token.record(response.status)
    """

    def __init__(self, limiter: AdaptiveRateLimiter):
        self.limiter = limiter
        self.start_time: Optional[float] = None

    async def __aenter__(self):
        # Wait for token (respects rate limit and pauses)
        await self.limiter._wait_for_token()
        self.start_time = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Nothing to do on exit - recording is explicit
        return False

    async def record(
        self,
        status_code: int,
        headers: Dict[str, str] = None
    ):
        """
        Record the outcome of this request.

        Args:
            status_code: HTTP status code
            headers: Response headers (to extract Retry-After)
        """
        headers = headers or {}
        latency = time.time() - self.start_time if self.start_time else 0

        # Extract Retry-After if present
        retry_after = None
        if 'Retry-After' in headers:
            try:
                retry_after = float(headers['Retry-After'])
            except ValueError:
                pass

        await self.limiter.record_outcome(
            status_code=status_code,
            latency=latency,
            retry_after=retry_after
        )
