"""
Weather Bot Strategy Example

Demonstrates the London temperature range trading strategy that
identifies bucket mispricing across adjacent temperature markets.

This strategy:
- Searches for London daily temperature range markets
- Identifies underpriced temperature buckets (20-30 cents)
- Spreads exposure across multiple adjacent ranges
- Profits from probability mispricing across buckets

Based on the successful Polymarket bot that turned $204 into $24,000
with 1,300+ trades and a 73% win rate.

Usage:
    uv run examples/weather_bot_strategy.py

Environment Variables:
    POLYMARKET_PRIVATE_KEY: Your Polymarket private key (required for trading)
    POLYMARKET_FUNDER: Funder address (optional)
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from dr_manhattan.base import create_exchange
from dr_manhattan.strategies import WeatherBotStrategy
from dr_manhattan.utils import setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Weather bot strategy for London temperature markets"
    )
    parser.add_argument(
        "--target-price-min",
        type=float,
        default=0.15,
        help="Minimum price to buy buckets (default: 0.15)",
    )
    parser.add_argument(
        "--target-price-max",
        type=float,
        default=0.35,
        help="Maximum price to buy buckets (default: 0.35)",
    )
    parser.add_argument(
        "--max-markets",
        type=int,
        default=5,
        help="Maximum markets to trade per day (default: 5)",
    )
    parser.add_argument(
        "--max-position",
        type=float,
        default=50.0,
        help="Maximum position per market (default: 50)",
    )
    parser.add_argument(
        "--order-size",
        type=float,
        default=10.0,
        help="Order size (default: 10)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Check interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Run duration in minutes (default: unlimited)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode - analyze opportunities without placing orders",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point for the weather bot strategy."""
    load_dotenv()
    args = parse_args()

    logger.info(f"\n{Colors.bold('Weather Bot Strategy')}")
    logger.info("=" * 80)

    # Check for private key
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not private_key and not args.dry_run:
        logger.error("POLYMARKET_PRIVATE_KEY environment variable required for trading")
        logger.info("Set --dry-run to analyze opportunities without trading")
        return 1

    # Create Polymarket exchange
    try:
        config = {}
        if private_key:
            config["private_key"] = private_key
            config["funder"] = os.getenv("POLYMARKET_FUNDER")

        exchange = create_exchange("polymarket", config)
    except ValueError as e:
        logger.error(str(e))
        return 1

    logger.info(f"{Colors.bold('Exchange:')} {Colors.cyan('POLYMARKET')}")
    logger.info(
        f"{Colors.bold('Target Price Range:')} "
        f"{Colors.yellow(f'{args.target_price_min:.2f}')} - "
        f"{Colors.yellow(f'{args.target_price_max:.2f}')}"
    )
    logger.info(f"{Colors.bold('Max Markets/Day:')} {Colors.cyan(str(args.max_markets))}")
    logger.info(
        f"{Colors.bold('Max Position/Market:')} {Colors.cyan(f'{args.max_position:.0f}')}"
    )

    if args.dry_run:
        logger.info(f"{Colors.bold('Mode:')} {Colors.magenta('DRY RUN (Analysis Only)')}")
    else:
        logger.info(f"{Colors.bold('Mode:')} {Colors.green('LIVE TRADING')}")

    logger.info("=" * 80 + "\n")

    # Create and run strategy
    strategy = WeatherBotStrategy(
        exchange=exchange,
        target_price_min=args.target_price_min,
        target_price_max=args.target_price_max,
        max_markets_per_day=args.max_markets,
        max_position_per_market=args.max_position,
        order_size=args.order_size,
        check_interval=args.interval,
    )

    try:
        strategy.run(duration_minutes=args.duration)
    except KeyboardInterrupt:
        logger.info("\nStrategy interrupted by user")

    return 0


if __name__ == "__main__":
    sys.exit(main())
