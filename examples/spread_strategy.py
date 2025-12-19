"""
Exchange-Agnostic BBO Spread Strategy

Works with any exchange (Polymarket, Opinion, Limitless, etc.)

Usage:
    # Polymarket
    EXCHANGE=polymarket MARKET_ID=... uv run python examples/spread_strategy.py

    # Opinion
    EXCHANGE=opinion MARKET_ID=813 uv run python examples/spread_strategy.py

    # With market slug (Polymarket/Opinion)
    EXCHANGE=polymarket MARKET_SLUG=fed-decision uv run python examples/spread_strategy.py

    # Select specific market from multi-market event
    uv run python examples/spread_strategy.py --exchange polymarket --slug fed-decision --market 2

    # Command line
    uv run python examples/spread_strategy.py --exchange polymarket --market-id 123
    uv run python examples/spread_strategy.py --exchange opinion --slug bitcoin
"""

import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from dr_manhattan import OrderSide, Strategy
from dr_manhattan.base import Exchange, create_exchange
from dr_manhattan.models import Market
from dr_manhattan.utils import prompt_market_selection, setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class SpreadStrategy(Strategy):
    """
    Exchange-agnostic BBO (Best Bid/Offer) spread strategy.

    Joins the best bid and ask on each tick using REST API polling.
    Works with any exchange that implements the standard interface.
    """

    def _place_bbo_for_outcome(
        self,
        outcome: str,
        token_id: str,
        get_bbo: Callable[[str], Tuple[Optional[float], Optional[float]]],
    ) -> None:
        """Place BBO orders for the given outcome."""
        best_bid, best_ask = get_bbo(token_id)

        if best_bid is None or best_ask is None:
            return

        our_bid = self.round_price(best_bid)
        our_ask = self.round_price(best_ask)

        # Clamp to valid range (0.001 ~ 0.999 for some exchanges)
        our_bid = max(0.001, min(0.999, our_bid))
        our_ask = max(0.001, min(0.999, our_ask))

        if our_bid >= our_ask:
            return

        position = self._positions.get(outcome, 0)
        buy_orders, sell_orders = self.get_orders_for_outcome(outcome)

        # Delta management
        if self._delta_info and self.delta > self.max_delta:
            if position == self._delta_info.max_position:
                return

        # BUY order
        if not self.has_order_at_price(buy_orders, our_bid):
            self.cancel_stale_orders(buy_orders, our_bid)

            if position + self.order_size <= self.max_position:
                if self.cash >= self.order_size:
                    try:
                        self.client.create_order(
                            market_id=self.market_id,
                            outcome=outcome,
                            side=OrderSide.BUY,
                            price=our_bid,
                            size=self.order_size,
                            params={"token_id": token_id},
                        )
                        self.log_order(OrderSide.BUY, self.order_size, outcome, our_bid)
                    except Exception as e:
                        logger.error(f"    BUY failed: {e}")

        # SELL order
        if not self.has_order_at_price(sell_orders, our_ask):
            self.cancel_stale_orders(sell_orders, our_ask)

            if position >= self.order_size:
                try:
                    self.client.create_order(
                        market_id=self.market_id,
                        outcome=outcome,
                        side=OrderSide.SELL,
                        price=our_ask,
                        size=self.order_size,
                        params={"token_id": token_id},
                    )
                    self.log_order(OrderSide.SELL, self.order_size, outcome, our_ask)
                except Exception as e:
                    logger.error(f"    SELL failed: {e}")

    def on_tick(self) -> None:
        """Main trading logic."""
        self.log_status()
        self.place_bbo_orders()


def find_market_id(
    exchange: Exchange,
    slug: str,
    market_index: Optional[int] = None,
) -> Optional[str]:
    """Find market ID by slug/keyword search with optional selection."""
    logger.info(f"Searching for market: {slug}")

    markets: List[Market] = []

    # Try fetch_markets_by_slug if available (Polymarket)
    if hasattr(exchange, "fetch_markets_by_slug"):
        markets = exchange.fetch_markets_by_slug(slug)

    # Fallback: search through paginated markets
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

    # Single market - use it
    if len(markets) == 1:
        logger.info(f"Found: {markets[0].question}")
        return markets[0].id

    # Multiple markets - select one
    if market_index is not None:
        if 0 <= market_index < len(markets):
            logger.info(f"Selected market [{market_index}]: {markets[market_index].question}")
            return markets[market_index].id
        else:
            logger.error(f"Market index {market_index} out of range (0-{len(markets)-1})")
            return None

    # Interactive selection using TUI utility
    return prompt_market_selection(markets)


def parse_args() -> Dict[str, Any]:
    """Parse command line arguments."""
    args: Dict[str, Any] = {
        "exchange": os.getenv("EXCHANGE", "polymarket"),
        "market_id": os.getenv("MARKET_ID", ""),
        "slug": os.getenv("MARKET_SLUG", ""),
        "market_index": None,
        "max_position": float(os.getenv("MAX_POSITION", "100")),
        "order_size": float(os.getenv("ORDER_SIZE", "5")),
        "max_delta": float(os.getenv("MAX_DELTA", "20")),
        "interval": float(os.getenv("CHECK_INTERVAL", "5")),
    }

    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] in ("--exchange", "-e") and i + 1 < len(argv):
            args["exchange"] = argv[i + 1]
            i += 2
        elif argv[i] in ("--market-id", "-m") and i + 1 < len(argv):
            args["market_id"] = argv[i + 1]
            i += 2
        elif argv[i] in ("--slug", "-s") and i + 1 < len(argv):
            args["slug"] = argv[i + 1]
            i += 2
        elif argv[i] in ("--market",) and i + 1 < len(argv):
            args["market_index"] = int(argv[i + 1])
            i += 2
        elif argv[i] in ("--max-position",) and i + 1 < len(argv):
            args["max_position"] = float(argv[i + 1])
            i += 2
        elif argv[i] in ("--order-size",) and i + 1 < len(argv):
            args["order_size"] = float(argv[i + 1])
            i += 2
        elif argv[i] in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        elif not argv[i].startswith("-"):
            # Positional arg: treat as slug or market_id
            if argv[i].isdigit():
                args["market_id"] = argv[i]
            else:
                args["slug"] = argv[i]
            i += 1
        else:
            i += 1

    return args


def main() -> int:
    """Entry point for the spread strategy."""
    load_dotenv()
    args = parse_args()

    if not args["market_id"] and not args["slug"]:
        logger.error("Provide MARKET_ID or MARKET_SLUG")
        logger.error(
            "Usage: uv run python examples/spread_strategy.py --exchange polymarket --slug fed-decision"
        )
        return 1

    try:
        exchange = create_exchange(args["exchange"])
    except ValueError as e:
        logger.error(str(e))
        return 1

    logger.info(f"\n{Colors.bold('Exchange:')} {Colors.cyan(args['exchange'].upper())}")

    # Find market_id from slug if needed
    market_id: Optional[str] = args["market_id"]
    if not market_id and args["slug"]:
        market_id = find_market_id(exchange, args["slug"], args["market_index"])
        if not market_id:
            return 1

    strategy = SpreadStrategy(
        exchange=exchange,
        market_id=market_id,
        max_position=args["max_position"],
        order_size=args["order_size"],
        max_delta=args["max_delta"],
        check_interval=args["interval"],
    )
    strategy.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
