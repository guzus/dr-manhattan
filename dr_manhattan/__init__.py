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
from .base.exchange_client import (
    DeltaInfo,
    ExchangeClient,
    StrategyState,
    calculate_delta,
    format_delta_side,
    format_positions_compact,
)
from .base.exchange_factory import create_exchange, list_exchanges
from .base.order_tracker import OrderEvent, OrderTracker, create_fill_logger
from .base.strategy import Strategy
from .exchanges.limitless import Limitless
from .exchanges.opinion import Opinion
from .exchanges.polymarket import Polymarket
from .models.market import Market
from .models.order import Order, OrderSide, OrderStatus
from .models.position import Position

__version__ = "0.0.1"

__all__ = [
    "create_exchange",
    "list_exchanges",
    "Exchange",
    "ExchangeClient",
    "Strategy",
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
    "StrategyState",
    "DeltaInfo",
    "calculate_delta",
    "format_positions_compact",
    "format_delta_side",
]


exchanges = {
    "polymarket": Polymarket,
    "limitless": Limitless,
    "opinion": Opinion,
}
