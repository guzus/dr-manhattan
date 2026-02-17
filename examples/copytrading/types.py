"""
Type definitions for the copytrading bot.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class TradeAction(str, Enum):
    """Trade action type"""

    DETECTED = "detected"
    COPIED = "copied"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class CopyStats:
    """Statistics for a copytrading session"""

    trades_detected: int = 0
    trades_copied: int = 0
    trades_skipped: int = 0
    trades_failed: int = 0
    total_volume: float = 0.0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "detected": self.trades_detected,
            "copied": self.trades_copied,
            "skipped": self.trades_skipped,
            "failed": self.trades_failed,
            "volume": self.total_volume,
        }


@dataclass
class BotConfig:
    """Configuration for the copytrading bot"""

    target_wallet: str
    scale_factor: float = 1.0
    poll_interval: float = 5.0
    max_position: float = 100.0
    min_trade_size: float = 1.0
    market_filter: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if not self.target_wallet:
            raise ValueError("target_wallet is required")
        if self.scale_factor <= 0:
            raise ValueError("scale_factor must be positive")
        if self.poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if self.max_position <= 0:
            raise ValueError("max_position must be positive")


@dataclass
class TradeInfo:
    """Information about a trade"""

    trade_id: str
    side: str
    size: float
    outcome: str
    price: float
    market_slug: str
    condition_id: str
    timestamp: datetime

    @property
    def side_upper(self) -> str:
        """Get uppercase side"""
        return self.side.upper()

    @property
    def is_buy(self) -> bool:
        """Check if this is a buy trade"""
        return self.side_upper == "BUY"
