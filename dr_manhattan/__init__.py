"""
Dr. Manhattan: CCXT-style unified API for prediction markets
"""

from .base.errors import (
    AuthenticationError,
    DrManhattanError,
    ExchangeError,
    InsufficientFunds,
    InvalidOrder,
    MarketNotFound,
    NetworkError,
    RateLimitError,
)
from .base.exchange import Exchange
from .base.order_tracker import OrderEvent, OrderTracker, create_fill_logger
from .exchanges.limitless import Limitless
from .exchanges.opinion import Opinion
from .exchanges.polymarket import Polymarket
from .models.market import Market
from .models.order import Order, OrderSide, OrderStatus
from .models.position import Position

__version__ = "0.0.1"

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
    "Opinion",
]


exchanges = {
    "polymarket": Polymarket,
    "limitless": Limitless,
    "opinion": Opinion,
}
