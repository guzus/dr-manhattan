"""
Exchange-Agnostic BBO Spread Strategy

Works with any exchange (Polymarket, Opinion, Limitless, etc.)
"""

import argparse
import os
import sys
from typing import List, Optional

from dotenv import load_dotenv

from dr_manhattan import Strategy
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
            logger.error(f"Market index {market_index} out of range (0-{len(markets) - 1})")
            return None

    # Interactive selection using TUI utility
    return prompt_market_selection(markets)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Exchange-agnostic BBO spread strategy")
    parser.add_argument(
        "-e",
        "--exchange",
        default=os.getenv("EXCHANGE", "polymarket"),
        help="Exchange name (default: polymarket)",
    )
    parser.add_argument(
        "-m",
        "--market-id",
        default=os.getenv("MARKET_ID", ""),
        help="Market ID to trade",
    )
    parser.add_argument(
        "-s",
        "--slug",
        default=os.getenv("MARKET_SLUG", ""),
        help="Market slug for search",
    )
    parser.add_argument(
        "--market",
        type=int,
        default=None,
        dest="market_index",
        help="Select specific market index from search results",
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
    return parser.parse_args()


def main() -> int:
    """Entry point for the spread strategy."""
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

    # Find market_id from slug if needed
    market_id: Optional[str] = args.market_id
    if not market_id and args.slug:
        market_id = find_market_id(exchange, args.slug, args.market_index)
        if not market_id:
            return 1

    strategy = SpreadStrategy(
        exchange=exchange,
        market_id=market_id,
        max_position=args.max_position,
        order_size=args.order_size,
        max_delta=args.max_delta,
        check_interval=args.interval,
    )
    strategy.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
