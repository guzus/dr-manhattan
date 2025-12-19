from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderTimeInForce(Enum):
    GTC = "gtc"  # Good-Til-Cancel: remains active until filled or cancelled
    FOK = "fok"  # Fill-Or-Kill: must be filled immediately and completely or cancelled
    IOC = "ioc"  # Immediate-Or-Cancel: fill what's available immediately, cancel rest


@dataclass
class Order:
    """Represents an order on a prediction market"""

    id: str
    market_id: str
    outcome: str
    side: OrderSide
    price: float
    size: float
    filled: float
    status: OrderStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    time_in_force: OrderTimeInForce = OrderTimeInForce.GTC

    @property
    def remaining(self) -> float:
        """Amount remaining to be filled"""
        return self.size - self.filled

    @property
    def is_active(self) -> bool:
        """Check if order is still active"""
        return self.status in [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]

    @property
    def is_open(self) -> bool:
        """Check if order is open"""
        return self.status in [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]

    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled"""
        return self.status == OrderStatus.FILLED or self.filled >= self.size

    @property
    def fill_percentage(self) -> float:
        """Get fill percentage (0-1)"""
        if self.size == 0:
            return 0.0
        return self.filled / self.size
