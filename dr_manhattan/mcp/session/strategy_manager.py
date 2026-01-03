"""Strategy session manager."""

import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from dr_manhattan.base import Exchange, Strategy
from dr_manhattan.utils import setup_logger

from .models import SessionStatus, StrategySession

logger = setup_logger(__name__)

# Thread cleanup configuration (per CLAUDE.md Rule #4: config in code)
THREAD_GRACE_PERIOD = 10.0  # seconds - initial wait before force-kill
THREAD_FORCE_KILL_TIMEOUT = 5.0  # seconds - timeout for force-kill attempt
THREAD_CLEANUP_TIMEOUT = 5.0  # seconds - timeout during cleanup()

# Status caching configuration (reduces refresh_state() calls)
STATUS_CACHE_TTL = 1.0  # seconds - cache lifetime for get_status()
STATUS_CACHE_MAX_SIZE = 100  # Maximum cache entries (prevents memory leak)


class StrategySessionManager:
    """
    Manages background strategy executions.

    Maintains active strategy sessions and provides monitoring/control.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Ensure singleton instance with thread-safe initialization."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # Initialize within the lock to prevent race condition
                cls._instance._sessions: Dict[str, StrategySession] = {}
                cls._instance._instance_lock = threading.Lock()
                # Orphaned sessions that failed to terminate
                cls._instance._orphaned_sessions: Dict[str, str] = {}
                # Status cache: session_id -> (timestamp, status_dict)
                cls._instance._status_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
                logger.info("StrategySessionManager initialized")
        return cls._instance

    def __init__(self):
        """No-op: initialization done in __new__ to prevent race conditions."""
        pass

    def create_session(
        self,
        strategy_class: type,
        exchange: Exchange,
        exchange_name: str,
        market_id: str,
        **params,
    ) -> str:
        """
        Create and start strategy in background thread.

        Args:
            strategy_class: Strategy class to instantiate
            exchange: Exchange instance
            exchange_name: Exchange name
            market_id: Market ID to trade
            **params: Strategy parameters (max_position, order_size, etc.)

        Returns:
            session_id for monitoring/control
        """
        session_id = str(uuid.uuid4())

        try:
            # Create strategy instance
            strategy = strategy_class(exchange=exchange, market_id=market_id, **params)

            # Create session
            session = StrategySession(
                id=session_id,
                strategy_type=strategy_class.__name__,
                exchange_name=exchange_name,
                market_id=market_id,
                strategy=strategy,
                status=SessionStatus.RUNNING,
            )

            # Start in background thread (daemon=True allows clean shutdown)
            thread = threading.Thread(
                target=self._run_strategy,
                args=(session_id, strategy, params.get("duration_minutes")),
                daemon=True,
            )
            thread.start()
            session.thread = thread

            with self._instance_lock:
                self._sessions[session_id] = session

            logger.info(
                f"Strategy session created: {session_id} "
                f"({strategy_class.__name__} on {exchange_name})"
            )

            return session_id

        except Exception as e:
            logger.error(f"Failed to create strategy session: {e}")
            raise

    def _run_strategy(self, session_id: str, strategy: Strategy, duration_minutes: Optional[int]):
        """Run strategy in background thread."""
        try:
            logger.info(f"Starting strategy execution: {session_id}")
            strategy.run(duration_minutes=duration_minutes)

            # Update status when done and clear cache
            with self._instance_lock:
                if session_id in self._sessions:
                    self._sessions[session_id].status = SessionStatus.STOPPED
                # Clear cache for completed session (prevents memory leak)
                if session_id in self._status_cache:
                    del self._status_cache[session_id]

        except Exception as e:
            logger.error(f"Strategy execution failed: {e}")
            with self._instance_lock:
                if session_id in self._sessions:
                    self._sessions[session_id].status = SessionStatus.ERROR
                    self._sessions[session_id].error = str(e)
                # Clear cache for failed session (prevents memory leak)
                if session_id in self._status_cache:
                    del self._status_cache[session_id]

    def get_session(self, session_id: str) -> StrategySession:
        """
        Get strategy session by ID.

        Args:
            session_id: Session ID

        Returns:
            StrategySession

        Raises:
            ValueError: If session not found
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return session

    def _evict_stale_cache_entries(self, now: float) -> None:
        """
        Remove stale cache entries to prevent memory leak.

        Must be called while holding _instance_lock.
        Removes entries older than TTL or exceeding max size.
        """
        # Remove expired entries first
        expired = [
            sid for sid, (cached_time, _) in self._status_cache.items()
            if now - cached_time >= STATUS_CACHE_TTL
        ]
        for sid in expired:
            del self._status_cache[sid]

        # If still over limit, remove oldest entries
        if len(self._status_cache) > STATUS_CACHE_MAX_SIZE:
            # Sort by timestamp and remove oldest
            sorted_entries = sorted(
                self._status_cache.items(),
                key=lambda x: x[1][0]  # Sort by cached_time
            )
            entries_to_remove = len(self._status_cache) - STATUS_CACHE_MAX_SIZE
            for sid, _ in sorted_entries[:entries_to_remove]:
                del self._status_cache[sid]

    def get_status(self, session_id: str) -> Dict[str, Any]:
        """
        Get real-time strategy status with caching.

        Uses TTL-based caching to reduce expensive refresh_state() calls.
        Cache TTL is configured by STATUS_CACHE_TTL constant.
        Thread-safe: cache access protected by _instance_lock.

        Args:
            session_id: Session ID

        Returns:
            Status dictionary with NAV, positions, orders, etc.
        """
        now = time.time()

        # Check cache first (thread-safe read)
        with self._instance_lock:
            if session_id in self._status_cache:
                cached_time, cached_status = self._status_cache[session_id]
                if now - cached_time < STATUS_CACHE_TTL:
                    return cached_status

        # Cache miss - compute fresh status (outside lock to avoid blocking)
        status = self._compute_status(session_id)

        # Update cache (thread-safe write) with eviction
        with self._instance_lock:
            self._status_cache[session_id] = (now, status)
            # Periodic eviction to prevent memory leak
            self._evict_stale_cache_entries(now)

        return status

    def _compute_status(self, session_id: str) -> Dict[str, Any]:
        """
        Compute fresh strategy status (internal, uncached).

        Args:
            session_id: Session ID

        Returns:
            Status dictionary
        """
        session = self.get_session(session_id)
        strategy = session.strategy

        # Refresh state
        try:
            strategy.refresh_state()
        except Exception as e:
            logger.warning(f"Failed to refresh strategy state: {e}")

        # Calculate uptime
        uptime = (datetime.now() - session.created_at).total_seconds()

        # Check if session is orphaned
        is_orphaned = session_id in self._orphaned_sessions

        return {
            "session_id": session_id,
            "status": session.status.value,
            "strategy_type": session.strategy_type,
            "exchange": session.exchange_name,
            "market_id": session.market_id,
            "uptime_seconds": uptime,
            "is_running": strategy.is_running,
            "thread_alive": session.is_alive(),
            "is_orphaned": is_orphaned,
            "nav": strategy.nav,
            "cash": strategy.cash,
            "positions": strategy.positions,
            "delta": strategy.delta,
            "open_orders_count": len(strategy.open_orders),
            "error": session.error,
        }

    def pause_strategy(self, session_id: str) -> bool:
        """
        Pause strategy execution.

        Args:
            session_id: Session ID

        Returns:
            True if paused successfully
        """
        session = self.get_session(session_id)
        session.strategy.is_running = False
        session.status = SessionStatus.PAUSED
        logger.info(f"Strategy paused: {session_id}")
        return True

    def resume_strategy(self, session_id: str) -> bool:
        """
        Resume paused strategy.

        Args:
            session_id: Session ID

        Returns:
            True if resumed successfully
        """
        session = self.get_session(session_id)
        if session.status != SessionStatus.PAUSED:
            raise ValueError(f"Strategy not paused: {session_id}")

        session.strategy.is_running = True
        session.status = SessionStatus.RUNNING
        logger.info(f"Strategy resumed: {session_id}")
        return True

    def _force_stop_thread(self, session_id: str, session: StrategySession) -> bool:
        """
        Attempt to force-stop a thread that didn't respond to graceful stop.

        Args:
            session_id: Session ID
            session: Strategy session

        Returns:
            True if thread stopped, False if still running (orphaned)
        """
        strategy = session.strategy

        # Second attempt: force is_running = False and wait again
        strategy.is_running = False

        if session.thread and session.thread.is_alive():
            logger.warning(f"Force-stopping strategy thread: {session_id}")
            session.thread.join(timeout=THREAD_FORCE_KILL_TIMEOUT)

            if session.thread.is_alive():
                # Thread is orphaned - mark it and log
                total_timeout = THREAD_GRACE_PERIOD + THREAD_FORCE_KILL_TIMEOUT
                self._orphaned_sessions[session_id] = (
                    f"Thread did not terminate after {total_timeout}s"
                )
                logger.error(
                    f"Strategy thread {session_id} is orphaned. "
                    "Thread may still be running in background. "
                    "Consider restarting the MCP server if this persists."
                )
                return False

        return True

    def stop_strategy(self, session_id: str, cleanup: bool = True) -> Dict[str, Any]:
        """
        Stop strategy with force-kill capability.

        Implements a two-phase shutdown:
        1. Graceful stop with THREAD_GRACE_PERIOD timeout
        2. Force-kill with THREAD_FORCE_KILL_TIMEOUT if graceful fails

        Args:
            session_id: Session ID
            cleanup: If True, cancel orders and liquidate positions

        Returns:
            Final status and metrics
        """
        session = self.get_session(session_id)
        strategy = session.strategy

        logger.info(f"Stopping strategy: {session_id} (cleanup={cleanup})")

        # Phase 1: Graceful stop
        strategy.stop()

        # Wait for thread to finish (with grace period)
        thread_stopped = True
        if session.thread and session.thread.is_alive():
            session.thread.join(timeout=THREAD_GRACE_PERIOD)

            # Check if thread is still alive after grace period
            if session.thread.is_alive():
                logger.warning(
                    f"Strategy thread {session_id} did not stop within grace period "
                    f"({THREAD_GRACE_PERIOD}s). Attempting force-stop..."
                )
                # Phase 2: Force-kill
                thread_stopped = self._force_stop_thread(session_id, session)

        # Clear status cache for this session (thread-safe)
        with self._instance_lock:
            if session_id in self._status_cache:
                del self._status_cache[session_id]

        # Get final status
        final_status = self._compute_status(session_id)

        # Update session status
        session.status = SessionStatus.STOPPED

        # Add thread status to response
        final_status["thread_stopped"] = thread_stopped
        if not thread_stopped:
            final_status["warning"] = "Thread is orphaned and may still be running"

        logger.info(f"Strategy stopped: {session_id} (thread_stopped={thread_stopped})")

        return final_status

    def get_metrics(self, session_id: str) -> Dict[str, Any]:
        """
        Get strategy performance metrics.

        Args:
            session_id: Session ID

        Returns:
            Performance metrics
        """
        session = self.get_session(session_id)
        strategy = session.strategy

        # Refresh state
        strategy.refresh_state()

        uptime = (datetime.now() - session.created_at).total_seconds()

        return {
            "session_id": session_id,
            "uptime_seconds": uptime,
            "current_nav": strategy.nav,
            "cash": strategy.cash,
            "positions_value": strategy.nav - strategy.cash,
            "current_delta": strategy.delta,
            "open_orders": len(strategy.open_orders),
        }

    def list_sessions(self) -> Dict[str, Any]:
        """
        List all active sessions.

        Returns:
            Dictionary of session_id -> session info
        """
        with self._instance_lock:
            return {
                sid: {
                    "session_id": sid,
                    "strategy_type": session.strategy_type,
                    "exchange": session.exchange_name,
                    "market_id": session.market_id,
                    "status": session.status.value,
                    "created_at": session.created_at.isoformat(),
                    "is_alive": session.is_alive(),
                    "is_orphaned": sid in self._orphaned_sessions,
                }
                for sid, session in self._sessions.items()
            }

    def get_orphaned_sessions(self) -> Dict[str, str]:
        """
        Get list of orphaned sessions that failed to terminate.

        Returns:
            Dictionary of session_id -> reason for orphan status
        """
        return dict(self._orphaned_sessions)

    def cleanup(self):
        """
        Stop all strategies with force-kill capability.

        Implements two-phase shutdown for each session:
        1. Graceful stop with THREAD_CLEANUP_TIMEOUT
        2. Force-stop for threads that don't respond
        """
        logger.info("Cleaning up strategy sessions...")
        with self._instance_lock:
            failed_sessions = []
            for session_id, session in list(self._sessions.items()):
                try:
                    logger.info(f"Stopping strategy: {session_id}")
                    session.strategy.stop()

                    # Phase 1: Graceful stop with timeout
                    if session.thread and session.thread.is_alive():
                        session.thread.join(timeout=THREAD_CLEANUP_TIMEOUT)

                        # Phase 2: Force-stop if still alive
                        if session.thread.is_alive():
                            logger.warning(
                                f"Strategy thread {session_id} did not stop "
                                "within cleanup timeout. Attempting force-stop..."
                            )
                            session.strategy.is_running = False
                            session.thread.join(timeout=THREAD_FORCE_KILL_TIMEOUT)

                            if session.thread.is_alive():
                                # Mark as orphaned
                                self._orphaned_sessions[session_id] = (
                                    "Failed to terminate during cleanup"
                                )
                                logger.error(
                                    f"Strategy thread {session_id} is orphaned during cleanup"
                                )
                                failed_sessions.append(session_id)

                except Exception as e:
                    logger.error(f"Error stopping strategy {session_id}: {e}")
                    failed_sessions.append(session_id)

            # Only remove successfully cleaned sessions
            for session_id in list(self._sessions.keys()):
                if session_id not in failed_sessions:
                    del self._sessions[session_id]
                    # Clear from cache
                    if session_id in self._status_cache:
                        del self._status_cache[session_id]

        logger.info(f"Strategy sessions cleaned up. Orphaned: {len(self._orphaned_sessions)}")
