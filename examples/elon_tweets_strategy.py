"""
Elon Tweets Volume Betting Strategy

Statistical arbitrage strategy for Elon Musk tweet count markets on Polymarket.

Strategy Logic:
1. Calculate average daily tweets from historical data
2. Get current tweet count for the period
3. Project final count: current_tweets + (avg_daily * days_remaining)
4. Identify profitable ranges around the projection
5. Buy ranges with positive expected value (>70% probability coverage with discount)

Based on analysis from: https://x.com/0xMovez/status/2005002806722203657
"""

import argparse
import sys
from datetime import datetime
from typing import List, Optional, Tuple

from dotenv import load_dotenv

from dr_manhattan import Strategy, create_exchange
from dr_manhattan.models import Market, OrderSide
from dr_manhattan.utils import prompt_market_selection, setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class ElonTweetsStrategy(Strategy):
    """
    Statistical arbitrage strategy for Elon tweet count markets.

    Calculates expected tweet count and identifies profitable ranges to buy.
    """

    def __init__(
        self,
        exchange,
        market_id: str,
        current_tweets: int,
        avg_daily_tweets: float,
        days_remaining: int,
        min_probability: float = 0.70,
        max_delta: float = 100.0,
        order_size: float = 10.0,
        check_interval: float = 300.0,
    ):
        """
        Initialize Elon tweets strategy.

        Args:
            exchange: Exchange instance
            market_id: Market ID to trade
            current_tweets: Current tweet count for the period
            avg_daily_tweets: Average tweets per day (calculated from historical data)
            days_remaining: Days remaining in the period
            min_probability: Minimum total probability to target (default: 0.70)
            max_delta: Maximum position imbalance
            order_size: Size per order
            check_interval: Seconds between checks (default: 5 minutes)
        """
        super().__init__(
            exchange=exchange,
            market_id=market_id,
            max_position=1000.0,
            order_size=order_size,
            max_delta=max_delta,
            check_interval=check_interval,
            track_fills=True,
        )

        self.current_tweets = current_tweets
        self.avg_daily_tweets = avg_daily_tweets
        self.days_remaining = days_remaining
        self.min_probability = min_probability

        # Calculate projection
        self.projected_tweets = current_tweets + (avg_daily_tweets * days_remaining)
        self.target_ranges: List[str] = []

    def setup(self) -> bool:
        """Setup and identify target ranges"""
        if not super().setup():
            return False

        self._log_strategy_params()
        self._identify_target_ranges()
        return True

    def _log_strategy_params(self):
        """Log strategy parameters and projection"""
        logger.info(f"\n{Colors.bold('Strategy Parameters:')}")
        logger.info(f"Current Tweets: {Colors.cyan(str(self.current_tweets))}")
        logger.info(f"Avg Daily Tweets: {Colors.yellow(f'{self.avg_daily_tweets:.1f}')}")
        logger.info(f"Days Remaining: {Colors.magenta(str(self.days_remaining))}")
        logger.info(
            f"Projected Total: {Colors.green(f'{self.projected_tweets:.0f}')} tweets"
        )
        logger.info(f"Min Probability Target: {Colors.yellow(f'{self.min_probability:.0%}')}")

    def _identify_target_ranges(self):
        """
        Identify target ranges to buy.

        Strategy: Find ranges around the projection that cover min_probability
        of the outcome space at a discount.
        """
        if not self.market or not self.outcomes:
            logger.error("Market not loaded")
            return

        projection = self.projected_tweets
        logger.info(f"\n{Colors.bold('Identifying Target Ranges:')}")

        # Parse ranges from outcomes
        ranges = []
        for outcome in self.outcomes:
            range_tuple = self._parse_range(outcome)
            if range_tuple:
                low, high = range_tuple
                price = self.market.prices.get(outcome, 0)
                ranges.append((outcome, low, high, price))

        if not ranges:
            logger.warning("No valid ranges found in market outcomes")
            return

        # Sort by distance from projection
        ranges.sort(key=lambda r: abs((r[1] + r[2]) / 2 - projection))

        # Select ranges around projection
        total_prob = 0.0
        selected = []

        for outcome, low, high, price in ranges:
            # Check if range overlaps with projection +/- 50 tweets
            if low <= projection + 50 and high >= projection - 50:
                selected.append((outcome, price))
                total_prob += price
                logger.info(
                    f"  {Colors.green('+')} {Colors.magenta(outcome)}: "
                    f"{Colors.yellow(f'{price:.1%}')}"
                )

                # Stop if we have enough probability coverage
                if total_prob >= self.min_probability:
                    break

        if not selected:
            logger.warning("No ranges selected around projection")
            return

        self.target_ranges = [outcome for outcome, _ in selected]

        logger.info(
            f"\n{Colors.bold('Selected:')} {Colors.cyan(str(len(self.target_ranges)))} ranges "
            f"covering {Colors.green(f'{total_prob:.1%}')} probability"
        )

        # Calculate expected value
        cost = sum(price for _, price in selected)
        expected_value = (total_prob - cost) * 100
        if expected_value > 0:
            logger.info(
                f"{Colors.bold('Expected Value:')} {Colors.green(f'+{expected_value:.1f}%')}"
            )
        else:
            logger.warning(
                f"{Colors.bold('Expected Value:')} {Colors.red(f'{expected_value:.1f}%')} "
                f"(negative EV)"
            )

    def _parse_range(self, outcome: str) -> Optional[Tuple[int, int]]:
        """
        Parse tweet count range from outcome string.

        Examples: "320-339", "340-359", "360-379"

        Args:
            outcome: Outcome string

        Returns:
            Tuple of (low, high) or None if invalid
        """
        try:
            # Look for pattern like "320-339" or "320 to 339"
            parts = outcome.replace(" to ", "-").replace("–", "-").split("-")
            if len(parts) == 2:
                low = int(parts[0].strip())
                high = int(parts[1].strip())
                if low < high:
                    return (low, high)
        except (ValueError, AttributeError):
            pass
        return None

    def on_tick(self):
        """Main trading logic"""
        self.log_status()

        if not self.target_ranges:
            logger.warning("No target ranges - strategy inactive")
            return

        # Check and place orders on target ranges
        for outcome in self.target_ranges:
            self._manage_range_position(outcome)

    def _manage_range_position(self, outcome: str):
        """
        Manage position for a target range.

        Strategy: Buy if we don't have a position and price is attractive.
        """
        position = self._positions.get(outcome, 0)
        token_id = self.get_token_id(outcome)

        if not token_id:
            return

        # Get current market price
        best_bid, best_ask = self.get_best_bid_ask(token_id)
        if best_ask is None:
            return

        # Check if we should buy more
        if position < self.max_position:
            # Only buy if we have open orders or need to establish position
            buy_orders, _ = self.get_orders_for_outcome(outcome)

            if not buy_orders and self.cash >= self.order_size:
                # Place buy order at best ask (take liquidity)
                try:
                    self.create_order(
                        outcome, OrderSide.BUY, best_ask, self.order_size, token_id
                    )
                    self.log_order(OrderSide.BUY, self.order_size, outcome, best_ask)
                except Exception as e:
                    logger.error(f"    BUY failed: {e}")


def find_elon_tweets_market(exchange) -> Optional[str]:
    """Find active Elon tweets market on Polymarket"""
    logger.info("Searching for Elon tweets markets...")

    # Search for markets with keywords
    keywords = ["elon", "musk", "tweet", "tweets"]

    all_markets: List[Market] = []
    for page in range(1, 10):
        try:
            page_markets = exchange.fetch_markets({"page": page, "limit": 20})
            if not page_markets:
                break
            all_markets.extend(page_markets)
        except Exception:
            break

    # Filter for tweet count markets
    candidates = []
    for market in all_markets:
        question_lower = market.question.lower()
        # Must contain "elon" or "musk" and "tweet"
        if any(k in question_lower for k in ["elon", "musk"]) and "tweet" in question_lower:
            # Prefer markets with numeric ranges in outcomes
            if market.outcomes and any(
                any(c.isdigit() for c in outcome) for outcome in market.outcomes
            ):
                candidates.append(market)

    if not candidates:
        logger.error("No Elon tweets markets found")
        return None

    if len(candidates) == 1:
        logger.info(f"Found: {candidates[0].question}")
        return candidates[0].id

    # Interactive selection
    return prompt_market_selection(candidates)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Elon tweets volume betting strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  # Manual market selection with auto-discovery
  uv run examples/elon_tweets_strategy.py --current 221 --avg-daily 48 --days-remaining 3

  # Specify market ID directly
  uv run examples/elon_tweets_strategy.py \\
    --market-id 0x... \\
    --current 221 \\
    --avg-daily 48 \\
    --days-remaining 3

Strategy calculates: projected = current + (avg_daily * days_remaining)
Then buys ranges around the projection with positive expected value.
        """,
    )

    parser.add_argument(
        "-m",
        "--market-id",
        default=None,
        help="Market ID (if not provided, will search for Elon tweets market)",
    )
    parser.add_argument(
        "--current",
        type=int,
        required=True,
        help="Current tweet count for the period",
    )
    parser.add_argument(
        "--avg-daily",
        type=float,
        required=True,
        help="Average tweets per day (from historical data)",
    )
    parser.add_argument(
        "--days-remaining",
        type=int,
        required=True,
        help="Days remaining in the period",
    )
    parser.add_argument(
        "--min-prob",
        type=float,
        default=0.70,
        help="Minimum probability to target (default: 0.70)",
    )
    parser.add_argument(
        "--order-size",
        type=float,
        default=10.0,
        help="Order size in USDC (default: 10)",
    )
    parser.add_argument(
        "--max-delta",
        type=float,
        default=100.0,
        help="Maximum position imbalance (default: 100)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=300.0,
        help="Check interval in seconds (default: 300 = 5 minutes)",
    )

    return parser.parse_args()


def main() -> int:
    """Entry point"""
    load_dotenv()
    args = parse_args()

    try:
        exchange = create_exchange("polymarket")
    except ValueError as e:
        logger.error(str(e))
        return 1

    logger.info(f"\n{Colors.bold('Exchange:')} {Colors.cyan('POLYMARKET')}")

    # Find market if not provided
    market_id = args.market_id
    if not market_id:
        market_id = find_elon_tweets_market(exchange)
        if not market_id:
            return 1

    # Create and run strategy
    strategy = ElonTweetsStrategy(
        exchange=exchange,
        market_id=market_id,
        current_tweets=args.current,
        avg_daily_tweets=args.avg_daily,
        days_remaining=args.days_remaining,
        min_probability=args.min_prob,
        max_delta=args.max_delta,
        order_size=args.order_size,
        check_interval=args.interval,
    )

    strategy.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
