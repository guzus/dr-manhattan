"""Trading operation tools."""

from typing import Any, Dict, List, Optional

from dr_manhattan.models.order import OrderSide

from ..session import ExchangeSessionManager
from ..utils import (
    serialize_model,
    translate_error,
    validate_exchange,
    validate_market_id,
    validate_optional_market_id,
    validate_order_id,
    validate_outcome,
    validate_side,
)

exchange_manager = ExchangeSessionManager()


def create_order(
    exchange: str,
    market_id: str,
    outcome: str,
    side: str,
    price: float,
    size: float,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a new order.

    Mirrors: Exchange.create_order()

    Args:
        exchange: Exchange name
        market_id: Market identifier
        outcome: Outcome to bet on ("Yes", "No", etc.)
        side: "buy" or "sell"
        price: Price per share (0-1 range)
        size: Number of shares
        params: Additional exchange-specific parameters

    Returns:
        Order object as dict

    Example:
        >>> order = create_order(
        ...     "polymarket",
        ...     market_id="0x123...",
        ...     outcome="Yes",
        ...     side="buy",
        ...     price=0.55,
        ...     size=10
        ... )
    """
    try:
        # Validate all inputs
        exchange = validate_exchange(exchange)
        market_id = validate_market_id(market_id)
        outcome = validate_outcome(outcome)
        side = validate_side(side)

        # Validate price range (prediction markets use 0-1, exclusive)
        # Note: 0.0 (0%) and 1.0 (100%) are not valid because no outcome is certain
        # and the counterparty would pay nothing (or receive shares for free)
        if not isinstance(price, (int, float)):
            raise ValueError("Price must be a number")
        if not 0 < price < 1:
            raise ValueError(
                f"Price must be between 0 and 1 (exclusive), got {price}. "
                "Prediction market prices represent probabilities (0% < p < 100%)."
            )

        # Validate size
        if not isinstance(size, (int, float)):
            raise ValueError("Size must be a number")
        if size <= 0:
            raise ValueError(f"Size must be positive, got {size}")

        client = exchange_manager.get_client(exchange)

        # Convert side string to OrderSide enum
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

        order = client.create_order(
            market_id=market_id,
            outcome=outcome,
            side=order_side,
            price=price,
            size=size,
            params=params or {},
        )

        return serialize_model(order)

    except Exception as e:
        raise translate_error(
            e, {"exchange": exchange, "market_id": market_id, "side": side}
        ) from e


def cancel_order(exchange: str, order_id: str, market_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Cancel an existing order.

    Mirrors: Exchange.cancel_order()

    Args:
        exchange: Exchange name
        order_id: Order identifier
        market_id: Market identifier (required by some exchanges)

    Returns:
        Updated Order object
    """
    try:
        exchange = validate_exchange(exchange)
        order_id = validate_order_id(order_id)
        market_id = validate_optional_market_id(market_id)

        client = exchange_manager.get_client(exchange)
        order = client.cancel_order(order_id, market_id=market_id)
        return serialize_model(order)

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "order_id": order_id}) from e


def cancel_all_orders(exchange: str, market_id: Optional[str] = None) -> int:
    """
    Cancel all open orders.

    Mirrors: ExchangeClient.cancel_all_orders()

    Args:
        exchange: Exchange name
        market_id: Optional market filter

    Returns:
        Number of orders cancelled
    """
    try:
        exchange = validate_exchange(exchange)
        market_id = validate_optional_market_id(market_id)

        client = exchange_manager.get_client(exchange)
        count = client.cancel_all_orders(market_id=market_id)
        return count

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id}) from e


def fetch_order(exchange: str, order_id: str, market_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch order details.

    Mirrors: Exchange.fetch_order()

    Args:
        exchange: Exchange name
        order_id: Order identifier
        market_id: Market identifier (required by some exchanges)

    Returns:
        Order object with fill status
    """
    try:
        exchange = validate_exchange(exchange)
        order_id = validate_order_id(order_id)
        market_id = validate_optional_market_id(market_id)

        exch = exchange_manager.get_exchange(exchange)
        order = exch.fetch_order(order_id, market_id=market_id)
        return serialize_model(order)

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "order_id": order_id}) from e


def fetch_open_orders(exchange: str, market_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch all open orders.

    Mirrors: Exchange.fetch_open_orders()

    Args:
        exchange: Exchange name
        market_id: Optional market filter

    Returns:
        List of Order objects
    """
    try:
        exchange = validate_exchange(exchange)
        market_id = validate_optional_market_id(market_id)

        client = exchange_manager.get_client(exchange)
        orders = client.fetch_open_orders(market_id=market_id)
        return [serialize_model(o) for o in orders]

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id}) from e
