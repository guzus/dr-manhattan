from dataclasses import dataclass, field
from typing import List, Tuple

# Price level: (price, size)
PriceLevel = Tuple[float, float]


@dataclass
class Orderbook:
    """Normalized orderbook data structure."""

    bids: List[PriceLevel] = field(default_factory=list)  # Sorted descending by price
    asks: List[PriceLevel] = field(default_factory=list)  # Sorted ascending by price
    timestamp: int = 0
    asset_id: str = ""
    market_id: str = ""

    @property
    def best_bid(self) -> float | None:
        """Get best bid price."""
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        """Get best ask price."""
        return self.asks[0][0] if self.asks else None

    @property
    def mid_price(self) -> float | None:
        """Get mid price."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float | None:
        """Get bid-ask spread."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @classmethod
    def from_rest_response(cls, data: dict, token_id: str = "") -> "Orderbook":
        """
        Create Orderbook from REST API response.

        REST format: {"bids": [{"price": "0.5", "size": "100"}, ...], "asks": [...]}
        """
        bids: List[PriceLevel] = []
        asks: List[PriceLevel] = []

        for bid in data.get("bids", []):
            try:
                price = float(bid.get("price", 0))
                size = float(bid.get("size", 0))
                if price > 0 and size > 0:
                    bids.append((price, size))
            except (ValueError, TypeError):
                continue

        for ask in data.get("asks", []):
            try:
                price = float(ask.get("price", 0))
                size = float(ask.get("size", 0))
                if price > 0 and size > 0:
                    asks.append((price, size))
            except (ValueError, TypeError):
                continue

        # Sort: bids descending, asks ascending
        bids.sort(reverse=True)
        asks.sort()

        return cls(bids=bids, asks=asks, asset_id=token_id)

    def to_dict(self) -> dict:
        """Convert to dict format for OrderbookManager compatibility."""
        return {
            "bids": self.bids,
            "asks": self.asks,
            "timestamp": self.timestamp,
            "asset_id": self.asset_id,
            "market_id": self.market_id,
        }
