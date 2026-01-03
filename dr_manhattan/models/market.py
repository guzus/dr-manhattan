from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

# Readable market ID as a path-like list:
# - ["61"] for simple ID (Opinion)
# - ["fed-decision-in-january", "No change"] for hierarchical (Polymarket)
ReadableMarketId = List[str]


@dataclass
class OutcomeRef:
    """Reference to locate an outcome (market_id + outcome name)."""

    market_id: str
    outcome: str


@dataclass
class OutcomeToken(OutcomeRef):
    """Tradeable outcome with token ID (extends OutcomeRef)."""

    token_id: str


@dataclass
class ExchangeOutcomeRef:
    """Full cross-exchange reference: exchange + market + outcome.

    market_id is a path-like list:
    - ["61"] for simple ID
    - ["event-slug", "match-id"] for hierarchical
    """

    exchange_id: str
    market_id: ReadableMarketId
    outcome: str

    def to_outcome_ref(self) -> OutcomeRef:
        return OutcomeRef(market_id=self.market_id[0], outcome=self.outcome)


@dataclass
class Market:
    """Represents a prediction market"""

    id: str
    question: str
    outcomes: list[str]
    close_time: Optional[datetime]
    volume: float
    liquidity: float
    prices: Dict[str, float]  # outcome -> price (0-1)
    metadata: Dict[str, Any]
    tick_size: float
    description: str = ""  # Resolution criteria

    def __post_init__(self):
        for outcome, price in self.prices.items():
            if not (0 <= price <= 1):
                raise ValueError(f"Price for '{outcome}' must be between 0 and 1, got {price}")

    @property
    def readable_id(self) -> ReadableMarketId:
        """Get readable market ID as a path-like list.

        Returns metadata["readable_id"] if set by exchange,
        otherwise falls back to [self.id].
        """
        return self.metadata.get("readable_id", [self.id])

    @property
    def is_binary(self) -> bool:
        """Check if market is binary (Yes/No)"""
        return len(self.outcomes) == 2

    @property
    def is_open(self) -> bool:
        """Check if market is still open for trading"""
        # Check metadata for explicit closed status (e.g., Polymarket)
        if "closed" in self.metadata:
            return not self.metadata["closed"]

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

    def get_outcome_ref(self, outcome: str) -> OutcomeRef:
        """Get reference to a specific outcome."""
        return OutcomeRef(market_id=self.id, outcome=outcome)

    def get_outcome_refs(self) -> List[OutcomeRef]:
        """Get references for all outcomes."""
        return [OutcomeRef(market_id=self.id, outcome=o) for o in self.outcomes]

    def get_outcome_tokens(self) -> List[OutcomeToken]:
        """Get all tradeable outcomes with their token IDs."""
        tokens = self.metadata.get("tokens", {})
        return [
            OutcomeToken(market_id=self.id, outcome=o, token_id=tokens.get(o, ""))
            for o in self.outcomes
            if o in tokens
        ]
