"""Strategy management tools."""

from typing import Any, Dict, Optional  # noqa: F401

from ..session import ExchangeSessionManager, StrategySessionManager
from ..utils import (
    serialize_model,
    translate_error,
    validate_exchange,
    validate_market_id,
    validate_positive_float,
    validate_session_id,
)

exchange_manager = ExchangeSessionManager()
strategy_manager = StrategySessionManager()


def create_strategy_session(
    strategy_type: str,
    exchange: str,
    market_id: Optional[str] = None,
    max_position: float = 100.0,
    order_size: float = 5.0,
    max_delta: float = 20.0,
    check_interval: float = 5.0,
    duration_minutes: Optional[int] = None,
    # btc_scalp parameters
    entry_price: float = 0.30,
    profit_target: float = 0.33,
    order_size_usd: float = 10.0,
    order_lifetime: float = 72.0,
    cancel_before_expiry: float = 90.0,
) -> str:
    """
    Start strategy in background thread.

    Based on: dr_manhattan.Strategy class

    Args:
        strategy_type: "market_making" or "btc_scalp"
        exchange: Exchange name
        market_id: Market ID to trade (not required for btc_scalp — auto-discovered)
        max_position: Maximum position size per outcome
        order_size: Default order size
        max_delta: Maximum position imbalance
        check_interval: Seconds between strategy ticks
        duration_minutes: Run duration (None = indefinite)
        entry_price: (btc_scalp) Limit buy price for YES and NO (default 0.30)
        profit_target: (btc_scalp) Limit sell price after fill (default 0.33)
        order_size_usd: (btc_scalp) USD per side per entry (default 10.0)
        order_lifetime: (btc_scalp) Seconds before cancelling unfilled buys (default 72)
        cancel_before_expiry: (btc_scalp) Cancel everything N seconds before window close (default 90)

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
        >>> session_id = create_strategy_session(
        ...     strategy_type="btc_scalp",
        ...     exchange="polymarket",
        ...     order_size_usd=10.0,
        ...     entry_price=0.30,
        ...     profit_target=0.33,
        ... )
    """
    try:
        # Validate inputs
        exchange = validate_exchange(exchange)

        # Validate strategy_type
        if not strategy_type or not isinstance(strategy_type, str):
            raise ValueError("strategy_type is required")
        strategy_type = strategy_type.strip().lower()

        # btc_scalp auto-discovers its market — market_id is optional
        if strategy_type == "btc_scalp":
            resolved_market_id = market_id or "btc-5min-auto"
        else:
            if not market_id:
                raise ValueError("market_id is required for strategy_type='market_making'")
            resolved_market_id = validate_market_id(market_id)

        # Validate numeric parameters
        max_position = validate_positive_float(max_position, "max_position")
        order_size = validate_positive_float(order_size, "order_size")
        max_delta = validate_positive_float(max_delta, "max_delta")
        check_interval = validate_positive_float(check_interval, "check_interval")

        if duration_minutes is not None:
            if not isinstance(duration_minutes, int) or duration_minutes <= 0:
                raise ValueError("duration_minutes must be a positive integer")

        # Get exchange instance
        exch = exchange_manager.get_exchange(exchange)

        # Determine strategy class and params
        if strategy_type == "market_making":
            from dr_manhattan.base.strategy import Strategy as BaseStrategy

            class MarketMakingStrategy(BaseStrategy):
                def on_tick(self):
                    self.log_status()
                    self.place_bbo_orders()

            strategy_class = MarketMakingStrategy
            extra_params: Dict[str, Any] = {}

        elif strategy_type == "btc_scalp":
            from dr_manhattan.strategies.btc_scalp import BTCScalpStrategy

            strategy_class = BTCScalpStrategy
            extra_params = {
                "entry_price": entry_price,
                "profit_target": profit_target,
                "order_size_usd": order_size_usd,
                "order_lifetime": order_lifetime,
                "cancel_before_expiry": cancel_before_expiry,
            }

        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}. Supported: market_making, btc_scalp")

        # Create session
        session_id = strategy_manager.create_session(
            strategy_class=strategy_class,
            exchange=exch,
            exchange_name=exchange,
            market_id=resolved_market_id,
            max_position=max_position,
            order_size=order_size,
            max_delta=max_delta,
            check_interval=check_interval,
            duration_minutes=duration_minutes,
            **extra_params,
        )

        return session_id

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id}) from e


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
        session_id = validate_session_id(session_id)
        status = strategy_manager.get_status(session_id)
        return serialize_model(status)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id}) from e


def pause_strategy(session_id: str) -> bool:
    """
    Pause strategy execution.

    Args:
        session_id: Strategy session ID

    Returns:
        True if paused successfully
    """
    try:
        session_id = validate_session_id(session_id)
        return strategy_manager.pause_strategy(session_id)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id}) from e


def resume_strategy(session_id: str) -> bool:
    """
    Resume paused strategy.

    Args:
        session_id: Strategy session ID

    Returns:
        True if resumed successfully
    """
    try:
        session_id = validate_session_id(session_id)
        return strategy_manager.resume_strategy(session_id)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id}) from e


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
        session_id = validate_session_id(session_id)
        final_status = strategy_manager.stop_strategy(session_id, cleanup=cleanup)
        return serialize_model(final_status)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id}) from e


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
        session_id = validate_session_id(session_id)
        metrics = strategy_manager.get_metrics(session_id)
        return serialize_model(metrics)

    except Exception as e:
        raise translate_error(e, {"session_id": session_id}) from e


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
        raise translate_error(e) from e
