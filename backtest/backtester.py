from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Protocol, Optional, Dict, Any


# ===============================
# Core data structures
# ===============================

@dataclass
class Trade:
    """
    External market trade (taker order) hitting the book.
    side: "BUY"  -> taker buys, hits resting asks
          "SELL" -> taker sells, hits resting bids
    """
    timestamp: datetime
    side: str
    price: float
    size: float


@dataclass
class Quote:
    """
    Our resting limit order (quote).
    side: "BID" or "ASK"
    """
    side: str
    price: float
    size: float


@dataclass
class Fill:
    """
    Execution of our quote.
    side: "BUY"  -> we bought from the market
          "SELL" -> we sold to the market
    """
    timestamp: datetime
    side: str
    price: float
    size: float


@dataclass
class StrategyState:
    """
    Shared state object used by all strategies.
    PnL is marked to the last known mid price.
    """
    inventory: float = 0.0
    cash: float = 0.0
    last_mid: Optional[float] = None

    @property
    def pnl(self) -> float:
        """Mark-to-market PnL using last_mid as reference price."""
        if self.last_mid is None:
            return self.cash
        return self.cash + self.inventory * self.last_mid


class Strategy(Protocol):
    """
    Strategy interface.

    Any strategy that implements:
      - name (str)
      - state (StrategyState)
      - reset()
      - update_quotes(...)
      - on_fill(...)
    can be plugged into the backtest engine.
    """
    name: str
    state: StrategyState

    def reset(self) -> None:
        """Reset internal/position state before running a new backtest."""
        ...

    def update_quotes(
        self,
        now: datetime,
        last_trade: Optional[Trade],
        state: StrategyState,
    ) -> List[Quote]:
        """
        Return a list of quotes (bids/asks) the strategy wants to place
        at the current time.

        Parameters
        ----------
        now : datetime
            Current timestamp.
        last_trade : Optional[Trade]
            Most recent external trade (can be None at the beginning).
        state : StrategyState
            Current state (inventory, cash, last_mid, ...).

        Returns
        -------
        List[Quote]
            Quotes to be considered active at this time.
        """
        ...

    def on_fill(self, fill: Fill, state: StrategyState) -> None:
        """
        Update state when one of our quotes is filled.

        Parameters
        ----------
        fill : Fill
            Execution information.
        state : StrategyState
            Current state that should be updated in-place.
        """
        ...


# ===============================
# Matching & backtest engine
# ===============================

def match_trades_with_strategy(
    trades: List[Trade],
    strategy: Strategy,
    fee_bps: float = 0.0,
):
    """
    Run a backtest for a single strategy on a sequence of external trades.

    The logic is:
      - Sort trades by time.
      - For each trade:
          * Ask the strategy for current quotes.
          * Match the external trade against our quotes if prices are compatible.
          * Apply transaction fees (if any).
          * Update strategy state via on_fill.

    Parameters
    ----------
    trades : List[Trade]
        External trades ordered arbitrarily (will be sorted by timestamp).
    strategy : Strategy
        Strategy implementing the Strategy protocol.
    fee_bps : float, optional
        Fee in basis points (1 bps = 0.01%), taken on notional of each fill.

    Returns
    -------
    fills : List[Fill]
        All fills generated for this strategy.
    state : StrategyState
        Final state after processing all trades.
    """
    strategy.reset()
    state = strategy.state
    fills: List[Fill] = []

    # Sort trades by time ascending
    for t in sorted(trades, key=lambda x: x.timestamp):
        quotes = strategy.update_quotes(t.timestamp, t, state)
        bid = next((q for q in quotes if q.side == "BID"), None)
        ask = next((q for q in quotes if q.side == "ASK"), None)

        remaining = t.size

        # External taker is SELL -> can hit our bid
        if t.side == "SELL" and bid is not None:
            # Taker sells at price <= our bid: we are willing to buy
            if bid.price >= t.price and remaining > 0:
                traded = min(remaining, bid.size)
                fee = fee_bps * 1e-4 * bid.price * traded

                fill = Fill(
                    timestamp=t.timestamp,
                    side="BUY",
                    price=bid.price,
                    size=traded,
                )
                strategy.on_fill(fill, state)
                # Fee is paid out of cash
                state.cash -= fee
                fills.append(fill)
                remaining -= traded

        # External taker is BUY -> can hit our ask
        elif t.side == "BUY" and ask is not None:
            # Taker buys at price >= our ask: we are willing to sell
            if ask.price <= t.price and remaining > 0:
                traded = min(remaining, ask.size)
                fee = fee_bps * 1e-4 * ask.price * traded

                fill = Fill(
                    timestamp=t.timestamp,
                    side="SELL",
                    price=ask.price,
                    size=traded,
                )
                strategy.on_fill(fill, state)
                # Fee is paid out of cash
                state.cash -= fee
                fills.append(fill)
                remaining -= traded

    return fills, state


def run_backtest_for_strategies(
    trades: List[Trade],
    strategies: List[Strategy],
    fee_bps: float = 0.0,
) -> Dict[str, Dict[str, Any]]:
    """
    Run the same trade stream against multiple strategies.

    Parameters
    ----------
    trades : List[Trade]
        External trades.
    strategies : List[Strategy]
        List of strategy instances.
    fee_bps : float, optional
        Fee in basis points applied to all strategies.

    Returns
    -------
    Dict[str, Dict[str, Any]]
        Mapping from strategy name to a result dictionary containing:
          - "fills": List[Fill]
          - "final_inventory": float
          - "final_cash": float
          - "final_pnl": float
    """
    results: Dict[str, Dict[str, Any]] = {}

    for strat in strategies:
        fills, state = match_trades_with_strategy(trades, strat, fee_bps=fee_bps)
        results[strat.name] = {
            "fills": fills,
            "final_inventory": state.inventory,
            "final_cash": state.cash,
            "final_pnl": state.pnl,
        }

    return results


# ===============================
# Helper to pretty-print results
# ===============================

def print_backtest_results(results: Dict[str, Dict[str, Any]]) -> None:
    """
    Pretty-print backtest results produced by run_backtest_for_strategies.

    Parameters
    ----------
    results : Dict[str, Dict[str, Any]]
        Result dictionary returned by run_backtest_for_strategies.
    """
    for name, r in results.items():
        fills: List[Fill] = r["fills"]
        final_inventory = r["final_inventory"]
        final_cash = r["final_cash"]
        final_pnl = r["final_pnl"]

        print(f"Strategy: {name}")
        print(f"  Final PnL      : {final_pnl:.6f}")
        print(f"  Final Inventory: {final_inventory:.6f}")
        print(f"  Final Cash     : {final_cash:.6f}")
        print(f"  Number of Fills: {len(fills)}")
        print("-" * 40)
