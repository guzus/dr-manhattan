"""
Dr. Manhattan: CCXT-style unified API for prediction markets
"""

from .base.exchange import Exchange
from .base.errors import (
    DrManhattanError,
    ExchangeError,
    NetworkError,
    RateLimitError,
    AuthenticationError,
    InsufficientFunds,
    InvalidOrder,
    MarketNotFound
)
from .base.order_tracker import OrderTracker, OrderEvent, create_fill_logger

from .models.market import Market
from .models.order import Order, OrderSide, OrderStatus
from .models.position import Position

from .exchanges.polymarket import Polymarket
from .exchanges.limitless import Limitless


__version__ = "0.1.0"

__all__ = [
    "Exchange",
    "DrManhattanError",
    "ExchangeError",
    "NetworkError",
    "RateLimitError",
    "AuthenticationError",
    "InsufficientFunds",
    "InvalidOrder",
    "MarketNotFound",
    "OrderTracker",
    "OrderEvent",
    "create_fill_logger",
    "Market",
    "Order",
    "OrderSide",
    "OrderStatus",
    "Position",
    "Polymarket",
    "Limitless",
]


exchanges = {
    "polymarket": Polymarket,
    "limitless": Limitless,
}
