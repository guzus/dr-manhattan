from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal


@dataclass
class CryptoHourlyMarket:
    """
    Represents a crypto hourly price market.

    These are markets that predict whether a token's price will be above/below
    a certain threshold, or whether it will go up/down from the open price.
    """
    token_symbol: str  # e.g., "BTC", "ETH", "SOL"
    expiry_time: datetime  # When the market expires/settles
    strike_price: Optional[float] = None  # The price threshold (if applicable)
    market_type: Literal["strike_price", "up_down"] = "strike_price"  # Type of market

    def __str__(self) -> str:
        if self.market_type == "up_down":
            return (
                f"{self.token_symbol} Up or Down "
                f"at {self.expiry_time.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        else:
            price_str = f"${self.strike_price:,.2f}" if self.strike_price else "TBD"
            return (
                f"{self.token_symbol} at {price_str} "
                f"by {self.expiry_time.strftime('%Y-%m-%d %H:%M UTC')}"
            )
