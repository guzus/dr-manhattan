from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from backtester import *

# ============================================
# Fixed Spread Market Making Strategy
# ============================================

@dataclass
class FixedSpreadStrategy:
    """
    Simple market making strategy placing symmetric bid/ask around mid price.

    Parameters
    ----------
    name : str
        Name of the strategy.
    spread : float
        Total spread (e.g. 0.04 -> bid/ask at mid ± 0.02).
    size : float
        Order size for each quote.
    inventory_limit : float
        Maximum long/short inventory allowed.
    state : StrategyState
        Persistent strategy state (inventory, cash, last mid price).
    """
    name: str
    spread: float
    size: float
    inventory_limit: float
    state: StrategyState = field(default_factory=StrategyState)

    def reset(self) -> None:
        """Reset internal state before running a new backtest."""
        self.state = StrategyState()

    def update_quotes(
        self,
        now: datetime,
        last_trade: Optional[Trade],
        state: StrategyState
    ) -> List[Quote]:
        """
        Compute bid/ask quotes based on last traded price or previous mid.

        Rules:
        - Mid price = last_trade.price or previous mid (or 0.5 if none).
        - Bid = mid - spread/2
        - Ask = mid + spread/2
        - Quotes only allowed if inventory is within risk limits.
        """
        # Determine mid price
        if last_trade is None:
            mid = state.last_mid if state.last_mid is not None else 0.5
        else:
            mid = last_trade.price
        state.last_mid = mid

        # Compute bid/ask boundaries
        bid_px = max(0.0, mid - self.spread / 2)
        ask_px = min(1.0, mid + self.spread / 2)

        quotes: List[Quote] = []

        # Place bid if inventory is not too long
        if state.inventory < self.inventory_limit:
            quotes.append(Quote(side="BID", price=bid_px, size=self.size))

        # Place ask if inventory is not too short
        if state.inventory > -self.inventory_limit:
            quotes.append(Quote(side="ASK", price=ask_px, size=self.size))

        return quotes

    def on_fill(self, fill: Fill, state: StrategyState) -> None:
        """
        Update inventory and cash based on fill direction.

        BUY fill  -> we buy from market  -> inventory increases, cash decreases  
        SELL fill -> we sell to market  -> inventory decreases, cash increases
        """
        if fill.side == "BUY":
            state.inventory += fill.size
            state.cash -= fill.price * fill.size
        else:
            state.inventory -= fill.size
            state.cash += fill.price * fill.size


# ============================================
# Inventory-Skewed Market Making Strategy
# ============================================

@dataclass
class InventorySkewStrategy(FixedSpreadStrategy):
    """
    Extends FixedSpreadStrategy by adjusting mid price depending on inventory.

    The skew rule:
        mid_adjusted = base_mid + (-skew_k * inventory)

    Higher inventory pushes mid lower (encourages selling).
    Lower inventory pushes mid higher (encourages buying).

    Parameters
    ----------
    skew_k : float
        Sensitivity of mid price adjustment per unit inventory.
    """
    skew_k: float = 0.1

    def update_quotes(
        self,
        now: datetime,
        last_trade: Optional[Trade],
        state: StrategyState
    ) -> List[Quote]:
        """
        Compute quotes with inventory-based mid skew.

        Steps:
        - Base mid = last_trade.price or previous mid.
        - Adjust mid with skew: mid = base_mid - skew_k * inventory
        - Clip mid to [0, 1]
        - Create bid/ask using fixed spread
        """
        # Determine base mid
        if last_trade is None:
            base_mid = state.last_mid if state.last_mid is not None else 0.5
        else:
            base_mid = last_trade.price

        # Inventory-based mid skew
        skew = -self.skew_k * state.inventory
        mid = min(1.0, max(0.0, base_mid + skew))
        state.last_mid = mid

        # Compute bid/ask
        bid_px = max(0.0, mid - self.spread / 2)
        ask_px = min(1.0, mid + self.spread / 2)

        quotes: List[Quote] = []

        # Post bid only if inventory below upper bound
        if state.inventory < self.inventory_limit:
            quotes.append(Quote(side="BID", price=bid_px, size=self.size))

        # Post ask only if inventory above lower bound
        if state.inventory > -self.inventory_limit:
            quotes.append(Quote(side="ASK", price=ask_px, size=self.size))

        return quotes
