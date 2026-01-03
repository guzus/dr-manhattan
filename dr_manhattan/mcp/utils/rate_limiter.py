"""Rate limiter for MCP tool calls."""

import random
import threading
import time
from typing import Optional

from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)

# Rate limiter configuration (per CLAUDE.md Rule #4: config in code)
# 10 calls/sec is a reasonable default that balances responsiveness with API protection.
# Higher rates risk hitting exchange rate limits; lower rates feel sluggish.
DEFAULT_CALLS_PER_SECOND = 10.0
# Burst size of 20 allows quick initial queries (e.g., loading dashboard data)
# while still enforcing the sustained rate limit over time.
DEFAULT_BURST_SIZE = 20


class RateLimiter:
    """
    Token bucket rate limiter for MCP tool calls.

    Features:
    - Token bucket algorithm for smooth rate limiting
    - Thread-safe for concurrent calls
    - Configurable rate and burst size
    - Non-blocking check available
    """

    def __init__(
        self,
        calls_per_second: float = DEFAULT_CALLS_PER_SECOND,
        burst_size: Optional[int] = None,
    ):
        """
        Initialize rate limiter.

        Args:
            calls_per_second: Maximum sustained rate
            burst_size: Maximum burst size (defaults to 2x rate)
        """
        self.rate = calls_per_second
        self.burst_size = burst_size or int(calls_per_second * 2)
        self.tokens = float(self.burst_size)  # Start with full bucket
        self.last_update = time.time()
        self._lock = threading.Lock()

        logger.info(f"RateLimiter initialized: rate={calls_per_second}/s, burst={self.burst_size}")

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.burst_size, self.tokens + elapsed * self.rate)
        self.last_update = now

    def acquire(self, blocking: bool = True, timeout: float = 1.0) -> bool:
        """
        Acquire a token for one request.

        Args:
            blocking: If True, wait for a token. If False, return immediately.
            timeout: Maximum time to wait (only if blocking=True)

        Returns:
            True if token acquired, False if rate limited
        """
        deadline = time.time() + timeout if blocking else time.time()

        while True:
            with self._lock:
                self._refill()

                if self.tokens >= 1:
                    self.tokens -= 1
                    return True

                if not blocking or time.time() >= deadline:
                    return False

                # Calculate exact wait time for next token (avoids busy-wait)
                tokens_needed = 1 - self.tokens
                wait_time = tokens_needed / self.rate
                # Clamp to remaining time until deadline
                remaining = deadline - time.time()
                wait_time = min(wait_time, max(0, remaining))

            # Sleep for calculated duration (outside lock)
            # Add small random jitter (0-10ms) to prevent thundering herd
            if wait_time > 0:
                jitter = random.uniform(0, 0.01)
                time.sleep(wait_time + jitter)

    def try_acquire(self) -> bool:
        """
        Try to acquire a token without blocking.

        Returns:
            True if token acquired, False if rate limited
        """
        return self.acquire(blocking=False)

    def get_wait_time(self) -> float:
        """
        Get estimated wait time for next available token.

        Returns:
            Seconds until a token is available (0 if available now)
        """
        with self._lock:
            self._refill()
            if self.tokens >= 1:
                return 0.0
            return (1 - self.tokens) / self.rate

    def get_status(self) -> dict:
        """
        Get current rate limiter status.

        Returns:
            Status dict with tokens, rate, etc.
        """
        with self._lock:
            self._refill()
            # Calculate wait_time inline to avoid acquiring lock twice
            wait_time = 0.0 if self.tokens >= 1 else (1 - self.tokens) / self.rate
            return {
                "tokens_available": self.tokens,
                "rate_per_second": self.rate,
                "burst_size": self.burst_size,
                "wait_time": wait_time,
            }


# Global rate limiter instance (thread-safe initialization)
_rate_limiter: Optional[RateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """
    Get or create global rate limiter instance.

    Thread-safe: uses double-checked locking pattern.
    """
    global _rate_limiter
    # First check without lock (fast path for already-initialized case)
    if _rate_limiter is None:
        with _rate_limiter_lock:
            # Re-check inside lock (another thread may have initialized)
            if _rate_limiter is None:
                _rate_limiter = RateLimiter()
    return _rate_limiter


def check_rate_limit() -> bool:
    """
    Check rate limit for a tool call.

    Returns:
        True if allowed, raises exception if rate limited
    """
    limiter = get_rate_limiter()
    if not limiter.try_acquire():
        wait_time = limiter.get_wait_time()
        logger.warning(f"Rate limit exceeded. Wait time: {wait_time:.2f}s")
        return False
    return True
