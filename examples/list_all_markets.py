"""
List all markets from any exchange.

Usage:
    uv run python examples/list_all_markets.py polymarket
    uv run python examples/list_all_markets.py opinion
    uv run python examples/list_all_markets.py limitless
"""

import argparse

from dotenv import load_dotenv

from dr_manhattan import create_exchange, list_exchanges

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="List markets from any exchange")
    parser.add_argument(
        "exchange",
        choices=list_exchanges(),
        help="Exchange name",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of markets to fetch (default: 20)",
    )
    parser.add_argument(
        "--binary-only",
        action="store_true",
        help="Only show binary markets",
    )
    parser.add_argument(
        "--open-only",
        action="store_true",
        help="Only show open markets",
    )
    args = parser.parse_args()

    exchange = create_exchange(args.exchange, verbose=False, validate=False)
    markets = exchange.fetch_markets({"limit": args.limit})

    if args.binary_only:
        markets = [m for m in markets if m.is_binary]
    if args.open_only:
        markets = [m for m in markets if m.is_open]

    print(f"\n{exchange.name} Markets ({len(markets)} found)")
    print("=" * 80)

    for market in markets:
        status = "OPEN" if market.is_open else "CLOSED"
        market_type = "Binary" if market.is_binary else f"{len(market.outcomes)} outcomes"

        print(f"\n[{status}] {market.question[:70]}")
        print(f"  ID: {market.id}")
        print(f"  Type: {market_type}")
        print(f"  Outcomes: {', '.join(market.outcomes[:5])}")

        if market.prices:
            prices_str = " | ".join(f"{k}={v:.2f}" for k, v in list(market.prices.items())[:4])
            print(f"  Prices: {prices_str}")

        if market.liquidity > 0:
            print(f"  Liquidity: ${market.liquidity:,.2f}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
