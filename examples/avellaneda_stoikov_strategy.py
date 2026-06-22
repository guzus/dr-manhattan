"""
Avellaneda-Stoikov Market Making Strategy

Optimal market making with inventory management based on:
"High-frequency trading in a limit order book" - Avellaneda & Stoikov (2008)
Reference: https://github.com/fedecaccia/avellaneda-stoikov

Computes a reservation price (inventory-adjusted fair value) and optimal
spread to balance profit capture against inventory risk. The reservation
price shifts away from the mid-price proportionally to inventory, encouraging
mean-reversion of the position toward zero.

Key formulas:
    Reservation price: r = s - q * gamma * sigma^2 * (T - t)
    Optimal spread:    spread = (2 / gamma) * ln(1 + gamma / k)
    Ask quote:         r + spread / 2
    Bid quote:         r - spread / 2

Where:
    s     = mid-market price
    q     = current inventory (positive = long)
    gamma = risk aversion (higher = tighter inventory control)
    k     = order arrival sensitivity (higher = tighter spread)
    sigma = price volatility over the trading session
    T - t = remaining time fraction [0, 1]
"""

import argparse
import math
import os
import sys
import time
from collections import deque
from typing import Dict, List, Optional

from dotenv import load_dotenv

from dr_manhattan import Strategy
from dr_manhattan.base import Exchange, create_exchange
from dr_manhattan.models import Market
from dr_manhattan.models.order import OrderSide
from dr_manhattan.utils import prompt_market_selection, setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class AvellanedaStoikovStrategy(Strategy):
    """
    Avellaneda-Stoikov optimal market making strategy.

    Quotes bid and ask prices derived from a reservation price that accounts
    for inventory risk, and an optimal spread that balances profit against
    adverse selection.

    The reservation price shifts away from the mid-price as inventory grows,
    encouraging mean-reversion of the position toward zero. As time remaining
    decreases, the inventory penalty shrinks, allowing tighter quotes near
    the end of the session.

    Parameters:
        gamma: Risk aversion. Higher values penalize inventory more heavily,
               producing more aggressive mean-reversion but potentially
               missing trades. Range: 0.1 - 1.0 for prediction markets.
        k:     Order arrival sensitivity. Controls how much the spread
               widens beyond the minimum. Higher values produce tighter
               spreads. Range: 10 - 100 for prediction markets.
        time_horizon_hours: Trading session length. The inventory penalty
               decays to zero as the session ends.
        volatility_window: Number of ticks used to estimate price volatility.
    """

    def __init__(
        self,
        exchange,
        market_id: str,
        gamma: float = 0.5,
        k: float = 50.0,
        time_horizon_hours: float = 1.0,
        volatility_window: int = 30,
        min_spread: float = 0.0,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,
        check_interval: float = 5.0,
    ):
        super().__init__(
            exchange=exchange,
            market_id=market_id,
            max_position=max_position,
            order_size=order_size,
            max_delta=max_delta,
            check_interval=check_interval,
            track_fills=True,
        )

        self.gamma = gamma
        self.k = k
        self.time_horizon = time_horizon_hours * 3600.0
        self.volatility_window = volatility_window
        self.min_spread = min_spread

        self.price_history: Dict[str, deque] = {}
        self.start_time: float = 0.0

    def setup(self) -> bool:
        if not super().setup():
            return False

        self.start_time = time.time()

        for outcome in self.outcomes:
            self.price_history[outcome] = deque(maxlen=self.volatility_window)

        spread = self._optimal_spread()

        logger.info(
            f"\n{Colors.bold('Avellaneda-Stoikov Config:')}\n"
            f"  gamma: {Colors.yellow(f'{self.gamma:.3f}')} | "
            f"k: {Colors.yellow(f'{self.k:.1f}')} | "
            f"T: {Colors.cyan(f'{self.time_horizon / 3600:.1f}h')}\n"
            f"  Base spread: {Colors.green(f'{spread:.4f}')} | "
            f"Min spread: {Colors.green(f'{self.min_spread:.4f}')} | "
            f"Vol window: {Colors.gray(f'{self.volatility_window} ticks')}"
        )

        return True

    def on_tick(self) -> None:
        self.refresh_state()

        for ot in self.outcome_tokens:
            outcome = ot.outcome
            token_id = ot.token_id

            bid, ask = self.get_best_bid_ask(token_id)
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                continue

            mid_price = (bid + ask) / 2.0
            self.price_history[outcome].append(mid_price)

            sigma = self._estimate_volatility(outcome)
            if sigma is None:
                continue

            elapsed = time.time() - self.start_time
            remaining = max(0.0, 1.0 - elapsed / self.time_horizon)

            q = self._positions.get(outcome, 0.0)

            # Reservation price: mid adjusted for inventory risk
            reservation = mid_price - q * self.gamma * sigma**2 * remaining

            # Optimal spread with floor
            spread = max(self._optimal_spread(), self.min_spread)

            ask_price = reservation + spread / 2.0
            bid_price = reservation - spread / 2.0

            # Clamp to valid prediction market range
            ask_price = self.round_price(max(self.tick_size, min(1.0 - self.tick_size, ask_price)))
            bid_price = self.round_price(max(self.tick_size, min(1.0 - self.tick_size, bid_price)))

            if bid_price >= ask_price:
                continue

            self._update_quotes(outcome, token_id, bid_price, ask_price, q)

        self.log_status()

    def _estimate_volatility(self, outcome: str) -> Optional[float]:
        """
        Estimate price volatility from recent absolute price changes,
        scaled to the full trading session.
        """
        history = self.price_history.get(outcome)
        if not history or len(history) < 2:
            return None

        prices = list(history)
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        if not changes:
            return None

        mean = sum(changes) / len(changes)
        variance = sum((c - mean) ** 2 for c in changes) / len(changes)
        sigma_per_tick = math.sqrt(variance) if variance > 0 else 0.0

        # Scale tick volatility to full-period volatility
        ticks_per_period = self.time_horizon / self.check_interval
        sigma = sigma_per_tick * math.sqrt(ticks_per_period)

        return max(sigma, 0.001)

    def _optimal_spread(self) -> float:
        """Compute optimal spread: (2 / gamma) * ln(1 + gamma / k)"""
        return (2.0 / self.gamma) * math.log(1.0 + self.gamma / self.k)

    def _update_quotes(
        self,
        outcome: str,
        token_id: str,
        bid_price: float,
        ask_price: float,
        position: float,
    ) -> None:
        """Cancel stale orders and place new bid/ask at computed prices."""
        buy_orders, sell_orders = self.get_orders_for_outcome(outcome)

        self.cancel_stale_orders(buy_orders, bid_price)
        self.cancel_stale_orders(sell_orders, ask_price)

        if not self.has_order_at_price(buy_orders, bid_price):
            if position + self.order_size <= self.max_position and self.cash >= self.order_size:
                try:
                    self.create_order(outcome, OrderSide.BUY, bid_price, self.order_size, token_id)
                    self.log_order(OrderSide.BUY, self.order_size, outcome, bid_price)
                except Exception as e:
                    logger.error(f"    BUY failed: {e}")

        if not self.has_order_at_price(sell_orders, ask_price):
            if position >= self.order_size:
                try:
                    self.create_order(outcome, OrderSide.SELL, ask_price, self.order_size, token_id)
                    self.log_order(OrderSide.SELL, self.order_size, outcome, ask_price)
                except Exception as e:
                    logger.error(f"    SELL failed: {e}")


def find_market_id(
    exchange: Exchange,
    slug: str,
    market_index: Optional[int] = None,
) -> Optional[str]:
    """Find market ID by slug/keyword search with optional selection."""
    logger.info(f"Searching for market: {slug}")

    markets: List[Market] = []

    if hasattr(exchange, "fetch_markets_by_slug"):
        markets = exchange.fetch_markets_by_slug(slug)

    if not markets:
        keywords = slug.replace("-", " ").lower()
        keyword_parts = [k for k in keywords.split() if len(k) > 2]

        all_markets: List[Market] = []
        for page in range(1, 6):
            try:
                page_markets = exchange.fetch_markets({"page": page, "limit": 20})
                if not page_markets:
                    break
                all_markets.extend(page_markets)
            except Exception:
                break

        markets = [m for m in all_markets if all(k in m.question.lower() for k in keyword_parts)]

    if not markets:
        logger.error(f"No markets found for: {slug}")
        return None

    if len(markets) == 1:
        logger.info(f"Found: {markets[0].question}")
        return markets[0].id

    if market_index is not None:
        if 0 <= market_index < len(markets):
            logger.info(f"Selected [{market_index}]: {markets[market_index].question}")
            return markets[market_index].id
        else:
            logger.error(f"Index {market_index} out of range (0-{len(markets) - 1})")
            return None

    return prompt_market_selection(markets)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Avellaneda-Stoikov Market Making Strategy")
    parser.add_argument(
        "-e",
        "--exchange",
        default=os.getenv("EXCHANGE", "polymarket"),
        help="Exchange name (default: polymarket)",
    )
    parser.add_argument("-m", "--market-id", default=os.getenv("MARKET_ID", ""), help="Market ID")
    parser.add_argument("-s", "--slug", default=os.getenv("MARKET_SLUG", ""), help="Market slug")
    parser.add_argument(
        "--market", type=int, default=None, dest="market_index", help="Market index"
    )
    parser.add_argument(
        "--gamma",
        type=float,
        default=0.5,
        help="Risk aversion parameter (default: 0.5)",
    )
    parser.add_argument(
        "--k",
        type=float,
        default=50.0,
        help="Order arrival sensitivity (default: 50.0)",
    )
    parser.add_argument(
        "--time-horizon",
        type=float,
        default=1.0,
        help="Trading session length in hours (default: 1.0)",
    )
    parser.add_argument(
        "--vol-window",
        type=int,
        default=30,
        help="Volatility estimation window in ticks (default: 30)",
    )
    parser.add_argument(
        "--min-spread",
        type=float,
        default=0.0,
        help="Minimum spread floor (default: 0.0)",
    )
    parser.add_argument(
        "--max-position",
        type=float,
        default=float(os.getenv("MAX_POSITION", "100")),
        help="Maximum position size (default: 100)",
    )
    parser.add_argument(
        "--order-size",
        type=float,
        default=float(os.getenv("ORDER_SIZE", "5")),
        help="Order size (default: 5)",
    )
    parser.add_argument(
        "--max-delta",
        type=float,
        default=float(os.getenv("MAX_DELTA", "20")),
        help="Maximum delta (default: 20)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("CHECK_INTERVAL", "5")),
        help="Check interval in seconds (default: 5)",
    )
    parser.add_argument("--duration", type=int, default=None, help="Duration in minutes")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    if not args.market_id and not args.slug:
        logger.error("Provide --market-id or --slug")
        return 1

    try:
        exchange = create_exchange(args.exchange)
    except ValueError as e:
        logger.error(str(e))
        return 1

    logger.info(f"\n{Colors.bold('Exchange:')} {Colors.cyan(args.exchange.upper())}")

    market_id: Optional[str] = args.market_id
    if not market_id and args.slug:
        market_id = find_market_id(exchange, args.slug, args.market_index)
        if not market_id:
            return 1

    strategy = AvellanedaStoikovStrategy(
        exchange=exchange,
        market_id=market_id,
        gamma=args.gamma,
        k=args.k,
        time_horizon_hours=args.time_horizon,
        volatility_window=args.vol_window,
        min_spread=args.min_spread,
        max_position=args.max_position,
        order_size=args.order_size,
        max_delta=args.max_delta,
        check_interval=args.interval,
    )

    try:
        strategy.run(duration_minutes=args.duration)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
