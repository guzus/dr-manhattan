"""Strategy management tools."""

from typing import Any, Dict, Optional

from ..session import ExchangeSessionManager, StrategySessionManager
from ..utils import serialize_model, translate_error

exchange_manager = ExchangeSessionManager()
strategy_manager = StrategySessionManager()


def create_strategy_session(
    strategy_type: str,
    exchange: str,
    market_id: str,
    max_position: float = 100.0,
    order_size: float = 5.0,
    max_delta: float = 20.0,
    check_interval: float = 5.0,
    duration_minutes: Optional[int] = None,
) -> str:
    """
    Start strategy in background thread.

    Based on: dr_manhattan.Strategy class

    Args:
        strategy_type: "market_making" or custom strategy name
        exchange: Exchange name
        market_id: Market ID to trade
        max_position: Maximum position size per outcome
        order_size: Default order size
        max_delta: Maximum position imbalance
        check_interval: Seconds between strategy ticks
        duration_minutes: Run duration (None = indefinite)

    Returns:
        session_id for monitoring/control

    Example:
        >>> session_id = create_strategy_session(
        ...     strategy_type="market_making",
        ...     exchange="polymarket",
        ...     market_id="0x123...",
        ...     max_position=100,
        ...     order_size=5
        ... )
    """
    try:
        # Get exchange instance
        exch = exchange_manager.get_exchange(exchange)

        # Determine strategy class
        if strategy_type == "market_making":
            # Use base Strategy class (user must implement on_tick)
            # For now, create a simple market making strategy
            from dr_manhattan.base.strategy import Strategy as BaseStrategy

            # Create anonymous strategy class with on_tick
            class MarketMakingStrategy(BaseStrategy):
                def on_tick(self):
                    self.log_status()
                    self.place_bbo_orders()

            strategy_class = MarketMakingStrategy
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

        # Create session
        session_id = strategy_manager.create_session(
            strategy_class=strategy_class,
            exchange=exch,
            exchange_name=exchange,
            market_id=market_id,
            max_position=max_position,
            order_size=order_size,
            max_delta=max_delta,
            check_interval=check_interval,
            duration_minutes=duration_minutes,
        )

        return session_id

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id})


def get_strategy_status(session_id: str) -> Dict[str, Any]:
    """
    Get real-time strategy status.

    Args:
        session_id: Strategy session ID

    Returns:
        Status dictionary with NAV, positions, orders, etc.

    Example:
        >>> status = get_strategy_status(session_id)
        >>> print(f"NAV: ${status['nav']:.2f}")
        >>> print(f"Delta: {status['delta']:.1f}")
    """
    try:
        status = strategy_manager.get_status(session_id)
        return serialize_model(status)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id})


def pause_strategy(session_id: str) -> bool:
    """
    Pause strategy execution.

    Args:
        session_id: Strategy session ID

    Returns:
        True if paused successfully
    """
    try:
        return strategy_manager.pause_strategy(session_id)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id})


def resume_strategy(session_id: str) -> bool:
    """
    Resume paused strategy.

    Args:
        session_id: Strategy session ID

    Returns:
        True if resumed successfully
    """
    try:
        return strategy_manager.resume_strategy(session_id)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id})


def stop_strategy(session_id: str, cleanup: bool = True) -> Dict[str, Any]:
    """
    Stop strategy and optionally cleanup.

    Args:
        session_id: Strategy session ID
        cleanup: If True, cancel orders and liquidate positions

    Returns:
        Final status and metrics
    """
    try:
        final_status = strategy_manager.stop_strategy(session_id, cleanup=cleanup)
        return serialize_model(final_status)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id})


def get_strategy_metrics(session_id: str) -> Dict[str, Any]:
    """
    Get strategy performance metrics.

    Args:
        session_id: Strategy session ID

    Returns:
        Performance metrics dictionary

    Example:
        >>> metrics = get_strategy_metrics(session_id)
        >>> print(f"Uptime: {metrics['uptime_seconds']:.0f}s")
        >>> print(f"Current NAV: ${metrics['current_nav']:.2f}")
    """
    try:
        metrics = strategy_manager.get_metrics(session_id)
        return serialize_model(metrics)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id})


def list_strategy_sessions() -> Dict[str, Any]:
    """
    List all active strategy sessions.

    Returns:
        Dictionary of session_id -> session info

    Example:
        >>> sessions = list_strategy_sessions()
        >>> for sid, info in sessions.items():
        ...     print(f"{sid}: {info['status']} on {info['exchange']}")
    """
    try:
        sessions = strategy_manager.list_sessions()
        return serialize_model(sessions)

    except Exception as e:
        raise translate_error(e)
