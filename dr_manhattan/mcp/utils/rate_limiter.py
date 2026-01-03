"""Rate limiter for MCP tool calls."""

import threading
import time
from typing import Optional

from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)

# Rate limiter configuration (per CLAUDE.md Rule #4: config in code)
DEFAULT_CALLS_PER_SECOND = 10.0  # Default rate limit
DEFAULT_BURST_SIZE = 20  # Allow burst of this many calls


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

            # Wait a bit before retrying (outside lock)
            time.sleep(0.01)

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
            return {
                "tokens_available": self.tokens,
                "rate_per_second": self.rate,
                "burst_size": self.burst_size,
                "wait_time": self.get_wait_time() if self.tokens < 1 else 0.0,
            }


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance."""
    global _rate_limiter
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
