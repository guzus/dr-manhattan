"""Strategy session manager."""

import threading
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from dr_manhattan.base import Exchange, Strategy
from dr_manhattan.utils import setup_logger

from .models import SessionStatus, StrategySession

logger = setup_logger(__name__)


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
                cls._instance._initialized = True
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

    def _run_strategy(
        self, session_id: str, strategy: Strategy, duration_minutes: Optional[int]
    ):
        """Run strategy in background thread."""
        try:
            logger.info(f"Starting strategy execution: {session_id}")
            strategy.run(duration_minutes=duration_minutes)

            # Update status when done
            with self._instance_lock:
                if session_id in self._sessions:
                    self._sessions[session_id].status = SessionStatus.STOPPED

        except Exception as e:
            logger.error(f"Strategy execution failed: {e}")
            with self._instance_lock:
                if session_id in self._sessions:
                    self._sessions[session_id].status = SessionStatus.ERROR
                    self._sessions[session_id].error = str(e)

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

    def get_status(self, session_id: str) -> Dict[str, Any]:
        """
        Get real-time strategy status.

        Args:
            session_id: Session ID

        Returns:
            Status dictionary with NAV, positions, orders, etc.
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

        return {
            "session_id": session_id,
            "status": session.status.value,
            "strategy_type": session.strategy_type,
            "exchange": session.exchange_name,
            "market_id": session.market_id,
            "uptime_seconds": uptime,
            "is_running": strategy.is_running,
            "thread_alive": session.is_alive(),
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

    def stop_strategy(self, session_id: str, cleanup: bool = True) -> Dict[str, Any]:
        """
        Stop strategy and optionally cleanup.

        Args:
            session_id: Session ID
            cleanup: If True, cancel orders and liquidate positions

        Returns:
            Final status and metrics
        """
        session = self.get_session(session_id)
        strategy = session.strategy

        logger.info(f"Stopping strategy: {session_id} (cleanup={cleanup})")

        # Stop strategy execution
        strategy.stop()

        # Wait for thread to finish (with timeout)
        if session.thread and session.thread.is_alive():
            session.thread.join(timeout=10.0)

        # Get final status
        final_status = self.get_status(session_id)

        # Update session status
        session.status = SessionStatus.STOPPED

        logger.info(f"Strategy stopped: {session_id}")

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
                }
                for sid, session in self._sessions.items()
            }

    def cleanup(self):
        """Stop all strategies and cleanup."""
        logger.info("Cleaning up strategy sessions...")
        with self._instance_lock:
            for session_id, session in list(self._sessions.items()):
                try:
                    logger.info(f"Stopping strategy: {session_id}")
                    session.strategy.stop()

                    # Wait for thread with timeout
                    if session.thread and session.thread.is_alive():
                        session.thread.join(timeout=5.0)

                except Exception as e:
                    logger.error(f"Error stopping strategy {session_id}: {e}")

            self._sessions.clear()

        logger.info("Strategy sessions cleaned up")
