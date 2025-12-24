"""
Spike Bot Example

Run a spike detection bot on a Polymarket market.

Usage:
    # Run with default settings
    uv run python examples/spike_bot.py --slug will-btc-hit-100k-by-2024

    # Custom configuration
    uv run python examples/spike_bot.py --slug btc-above-100k \\
        --spike-threshold 0.02 \\
        --profit-target 0.04 \\
        --stop-loss 0.02 \\
        --position-size 10

Environment variables:
    POLYMARKET_PRIVATE_KEY: Your Ethereum private key
    POLYMARKET_FUNDER: Your funder address (optional)
"""

import argparse
import os
import sys

import dr_manhattan
from dr_manhattan.strategies.spike_bot import SpikeBot


def main():
    parser = argparse.ArgumentParser(description="Run Polymarket Spike Bot")

    parser.add_argument("--slug", required=True, help="Market slug or URL")
    parser.add_argument(
        "--spike-threshold",
        type=float,
        default=0.015,
        help="Spike detection threshold (default: 0.015 = 1.5%%)",
    )
    parser.add_argument(
        "--profit-target",
        type=float,
        default=0.03,
        help="Profit target (default: 0.03 = 3%%)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=0.02,
        help="Stop loss (default: 0.02 = 2%%)",
    )
    parser.add_argument(
        "--position-size",
        type=float,
        default=5.0,
        help="Position size in USDC (default: 5)",
    )
    parser.add_argument(
        "--max-position",
        type=float,
        default=20.0,
        help="Maximum position size (default: 20)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Run duration in minutes (default: run indefinitely)",
    )

    args = parser.parse_args()

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not private_key:
        print("Error: POLYMARKET_PRIVATE_KEY environment variable not set")
        print("\nTo set it:")
        print("  export POLYMARKET_PRIVATE_KEY='your_private_key_here'")
        sys.exit(1)

    funder = os.getenv("POLYMARKET_FUNDER")

    print("Initializing Polymarket exchange...")
    config = {
        "private_key": private_key,
        "funder": funder,
        "timeout": 30,
        "verbose": True,
    }

    exchange = dr_manhattan.Polymarket(config)

    print(f"Fetching market: {args.slug}")
    markets = exchange.fetch_markets_by_slug(args.slug)

    if not markets:
        print(f"Error: Market not found: {args.slug}")
        sys.exit(1)

    market = markets[0]
    market_id = market.id

    print(f"\nMarket: {market.question}")
    print(f"Outcomes: {market.outcomes}")
    print(f"Volume: ${market.volume:,.0f}")

    bot = SpikeBot(
        exchange=exchange,
        market_id=market_id,
        spike_threshold=args.spike_threshold,
        profit_target=args.profit_target,
        stop_loss=args.stop_loss,
        position_size=args.position_size,
        max_position=args.max_position,
        history_size=60,
        check_interval=1.0,
    )

    print("\nStarting Spike Bot...")
    print("Press Ctrl+C to stop\n")

    try:
        bot.run(duration_minutes=args.duration)
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
