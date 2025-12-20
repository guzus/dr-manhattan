"""
List all currently active Limitless markets

Usage:
    uv run python examples/limitless/list_markets.py
"""

from datetime import datetime, timezone

import dr_manhattan


def main():
    exchange = dr_manhattan.Limitless({})

    print("\n" + "=" * 80)
    print("LIMITLESS ACTIVE MARKETS")
    print("=" * 80)

    try:
        markets = exchange.fetch_markets({"limit": 20})
    except Exception as e:
        print(f"Failed to fetch markets: {e}")
        return 1

    if not markets:
        print("\nNo active markets found.")
        print("=" * 80 + "\n")
        return 0

    now = datetime.now(timezone.utc)

    for i, market in enumerate(markets, 1):
        print(f"\n[{i}] {market.question}")
        print(f"    Slug: {market.id}")
        print(f"    Outcomes: {market.outcomes}")

        # Display prices
        price_strs = []
        for outcome in market.outcomes:
            price = market.prices.get(outcome, 0)
            price_strs.append(f"{outcome}={price:.4f}")
        print(f"    Prices: {' | '.join(price_strs)}")

        # Display time info
        if market.close_time:
            time_left = (market.close_time - now).total_seconds()
            if time_left > 0:
                hours_left = int(time_left / 3600)
                minutes_left = int((time_left % 3600) / 60)
                print(
                    f"    Closes: {market.close_time.strftime('%Y-%m-%d %H:%M UTC')} ({hours_left}h {minutes_left}m left)"
                )
            else:
                print(f"    Status: CLOSED")

        print(f"    Volume: ${market.volume:,.2f}")
        print(f"    Liquidity: ${market.liquidity:,.2f}")

        # Token IDs
        token_ids = market.metadata.get("clobTokenIds", [])
        if token_ids:
            print(f"    Token IDs: {token_ids}")

    print("\n" + "=" * 80)
    print(f"Total: {len(markets)} markets")
    print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    exit(main())
