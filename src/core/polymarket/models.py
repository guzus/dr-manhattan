from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Literal
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OutcomeSide(str, Enum):
    YES = "YES"
    NO = "NO"


class OrderType(str, Enum):
    GTC = "GTC"  # Good Till Cancelled
    GTD = "GTD"  # Good Till Date
    FOK = "FOK"  # Fill Or Kill
    IOC = "IOC"  # Immediate Or Cancel


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class OrderBookEntry:
    price: float
    size: float


@dataclass
class OrderBook:
    bids: List[OrderBookEntry]  # Buy orders
    asks: List[OrderBookEntry]  # Sell orders
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def midpoint(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None


@dataclass
class MarketData:
    """Polymarket 시장 데이터"""

    id: str
    condition_id: str
    question: str
    description: Optional[str] = None
    category: Optional[str] = None

    # Event relationship (for submarket structure)
    event_id: Optional[str] = None
    event_title: Optional[str] = None

    # Token IDs
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None

    # Prices
    yes_price: float = 0.5
    no_price: float = 0.5

    # Order Books
    yes_order_book: Optional[OrderBook] = None
    no_order_book: Optional[OrderBook] = None

    # Volume & Liquidity
    liquidity: float = 0.0
    volume_24h: float = 0.0
    volume_total: float = 0.0

    # Timeline
    end_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    # Status
    is_active: bool = True
    is_resolved: bool = False
    resolution: Optional[str] = None

    # Additional data
    tags: List[str] = field(default_factory=list)
    outcomes: List[str] = field(default_factory=lambda: ["Yes", "No"])

    @property
    def spread(self) -> float:
        """YES/NO 스프레드"""
        return abs(self.yes_price + self.no_price - 1.0)

    @property
    def implied_probability_yes(self) -> float:
        """YES 암시 확률"""
        return self.yes_price

    @property
    def implied_probability_no(self) -> float:
        """NO 암시 확률"""
        return self.no_price

    def get_price(self, side: OutcomeSide) -> float:
        return self.yes_price if side == OutcomeSide.YES else self.no_price


@dataclass
class Order:
    """주문 정보"""

    market_id: str
    token_id: str
    side: Side
    outcome_side: OutcomeSide
    price: float
    size: float
    order_type: OrderType = OrderType.GTC

    # Optional
    expiration: Optional[datetime] = None


@dataclass
class OrderResult:
    """주문 결과"""

    success: bool
    order_id: Optional[str] = None
    status: Optional[OrderStatus] = None
    filled_size: float = 0.0
    average_price: float = 0.0
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TradeResult:
    """체결 결과"""

    trade_id: str
    order_id: str
    market_id: str
    side: Side
    outcome_side: OutcomeSide
    size: float
    price: float
    fee: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PositionData:
    """포지션 데이터"""

    market_id: str
    token_id: str
    outcome_side: OutcomeSide
    size: float
    average_price: float
    current_price: float

    @property
    def value(self) -> float:
        """현재 가치"""
        return self.size * self.current_price

    @property
    def cost_basis(self) -> float:
        """취득 원가"""
        return self.size * self.average_price

    @property
    def unrealized_pnl(self) -> float:
        """미실현 손익"""
        return self.value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        """미실현 손익률"""
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100
