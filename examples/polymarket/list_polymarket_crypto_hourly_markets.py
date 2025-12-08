"""
List all currently active crypto hourly markets
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
import dr_manhattan

load_dotenv()

def find_all_active_crypto_hourly_markets(exchange, limit=200):
    """
    Find all currently active crypto hourly markets.

    Returns a list of (Market, CryptoHourlyMarket) tuples.
    """
    import re
    from dr_manhattan.models import CryptoHourlyMarket

    # Fetch markets with 1H tag
    import requests
    url = f"{exchange.BASE_URL}/markets"
    params = {
        "active": "true",
        "closed": "false",
        "tag_id": exchange.TAG_1H,
        "limit": limit,
        "order": "volume",
        "ascending": "false",
    }

    response = requests.get(url, params=params, timeout=10)
    data = response.json()

    all_markets = []
    for market_data in data:
        market = exchange._parse_market(market_data)
        if market:
            all_markets.append(market)

    # Pattern for "Up or Down" markets
    up_down_pattern = re.compile(
        r'(?P<token>Bitcoin|Ethereum|Solana|BTC|ETH|SOL|XRP)\s+Up or Down',
        re.IGNORECASE
    )

    active_crypto_markets = []

    for market in all_markets:
        # Must be binary and open
        if not market.is_binary or not market.is_open:
            continue

        # Check if currently active (expiring within 1 hour)
        if market.close_time:
            if market.close_time.tzinfo is not None:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()

            time_until_expiry = (market.close_time - now).total_seconds()

            # Skip if expired or more than 1 hour away
            if time_until_expiry <= 0 or time_until_expiry > 3600:
                continue

        # Try to parse as crypto market
        match = up_down_pattern.search(market.question)
        if match:
            parsed_token = exchange.normalize_token(match.group('token'))

            expiry = market.close_time if market.close_time else datetime.now(timezone.utc)

            crypto_market = CryptoHourlyMarket(
                token_symbol=parsed_token,
                expiry_time=expiry,
                strike_price=None,
                market_type="up_down"
            )

            active_crypto_markets.append((market, crypto_market))

    return active_crypto_markets


def main():
    # Initialize Polymarket exchange
    exchange = dr_manhattan.Polymarket({
        'private_key': os.getenv('POLYMARKET_PRIVATE_KEY'),
        'funder': os.getenv('POLYMARKET_FUNDER'),
    })

    print("\n" + "="*80)
    print("CURRENTLY ACTIVE CRYPTO HOURLY MARKETS")
    print("="*80)

    # Find all active markets
    active_markets = find_all_active_crypto_hourly_markets(exchange, limit=200)

    if not active_markets:
        print("\nNo currently active crypto hourly markets found.")
        print("\n" + "="*80 + "\n")
        return

    # Group by token
    by_token = {}
    for market, crypto_info in active_markets:
        token = crypto_info.token_symbol
        if token not in by_token:
            by_token[token] = []
        by_token[token].append((market, crypto_info))

    # Display grouped by token
    now = datetime.now(timezone.utc)

    for token in sorted(by_token.keys()):
        markets = by_token[token]
        print(f"\n{token} Markets ({len(markets)} active):")
        print("-" * 80)

        for market, crypto_info in markets:
            time_left = (crypto_info.expiry_time - now).total_seconds()
            minutes_left = int(time_left / 60)

            price_up = market.prices.get("Up", 0)
            price_down = market.prices.get("Down", 0)

            print(f"  {market.question}")
            print(f"    Expiry: {crypto_info.expiry_time.strftime('%Y-%m-%d %H:%M UTC')} ({minutes_left}m left)")
            print(f"    Prices: UP={price_up:.4f} | DOWN={price_down:.4f}")
            print(f"    Liquidity: ${market.liquidity:,.2f}")
            print()

    print("="*80)
    print(f"Total: {len(active_markets)} active crypto hourly markets")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
