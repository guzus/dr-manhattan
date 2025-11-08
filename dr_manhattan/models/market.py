from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass
class Market:
    """Represents a prediction market"""
    id: str
    question: str
    outcomes: list[str]
    close_time: Optional[datetime]
    volume: float
    liquidity: float
    prices: Dict[str, float]  # outcome -> price (0-1 or 0-100)
    metadata: Dict[str, Any]

    @property
    def is_binary(self) -> bool:
        """Check if market is binary (Yes/No)"""
        return len(self.outcomes) == 2

    @property
    def is_open(self) -> bool:
        """Check if market is still open for trading"""
        # Check metadata for explicit closed status (e.g., Polymarket)
        if 'closed' in self.metadata:
            return not self.metadata['closed']

        # Fallback to close_time check
        if not self.close_time:
            return True
        return datetime.now() < self.close_time

    @property
    def spread(self) -> Optional[float]:
        """Get bid-ask spread for binary markets"""
        if not self.is_binary or len(self.outcomes) != 2:
            return None

        prices = list(self.prices.values())
        if len(prices) != 2:
            return None

        # For binary markets, spread is typically 1 - sum of probabilities
        # (when prices sum to exactly 1, spread is 0)
        return abs(1.0 - sum(prices))
