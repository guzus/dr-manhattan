"""
Insider verification tool for analyzing wallet trading patterns.

Usage:
    uv run python examples/verify_insider.py 0xWALLET_ADDRESS
    uv run python examples/verify_insider.py 0xWALLET_ADDRESS --analyze
    uv run python examples/verify_insider.py 0xWALLET_ADDRESS --detect-signals
    uv run python examples/verify_insider.py --compare 0xWALLET1 0xWALLET2

Examples:
    # Fetch recent trades for a wallet
    uv run python examples/verify_insider.py 0x1234...

    # Analyze trading performance
    uv run python examples/verify_insider.py 0x1234... --analyze

    # Detect insider trading signals
    uv run python examples/verify_insider.py 0x1234... --detect-signals

    # Compare multiple wallets
    uv run python examples/verify_insider.py --compare 0x1234... 0x5678...
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime

from dotenv import load_dotenv

from dr_manhattan import create_exchange

load_dotenv()


def format_currency(value: float) -> str:
    """Format currency with commas and 2 decimal places."""
    return f"${value:,.2f}"


def format_timestamp(ts: datetime) -> str:
    """Format timestamp for display."""
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(ts)


def fetch_trades(exchange, wallet_address: str, limit: int = 500, market_id: str = None):
    """Fetch and display trades for a wallet."""
    print(f"\nFetching trades for wallet: {wallet_address}")
    print("=" * 80)

    trades = exchange.fetch_public_trades(
        market=market_id,
        user=wallet_address,
        limit=limit,
        taker_only=False,
    )

    if not trades:
        print("No trades found for this wallet.")
        return

    # Summary stats
    total_volume = sum(t.size * t.price for t in trades)
    buy_count = sum(1 for t in trades if t.side.upper() == "BUY")
    sell_count = len(trades) - buy_count
    unique_markets = len(set(t.condition_id for t in trades if t.condition_id))

    print(f"\nSummary:")
    print(f"  Total Trades: {len(trades)}")
    print(f"  Buy/Sell: {buy_count}/{sell_count}")
    print(f"  Total Volume: {format_currency(total_volume)}")
    print(f"  Unique Markets: {unique_markets}")

    # Recent trades
    print(f"\nRecent Trades (showing last {min(10, len(trades))}):")
    print("-" * 80)

    for trade in trades[:10]:
        ts = format_timestamp(trade.timestamp)
        side = trade.side.upper()
        size = trade.size
        price = trade.price
        value = size * price
        title = (trade.title or "Unknown")[:40]

        print(f"  [{ts}] {side:4} {size:>10.2f} @ {price:.4f} = {format_currency(value):>12}")
        print(f"       Market: {title}")

    if len(trades) > 10:
        print(f"\n  ... and {len(trades) - 10} more trades")

    return trades


def analyze_performance(exchange, wallet_address: str, limit: int = 500):
    """Analyze and display trading performance."""
    print(f"\nAnalyzing trading performance for: {wallet_address}")
    print("=" * 80)

    trades = exchange.fetch_public_trades(
        user=wallet_address,
        limit=limit,
        taker_only=False,
    )

    if len(trades) < 5:
        print(f"Insufficient trades for analysis. Found {len(trades)}, need at least 5.")
        return

    # Calculate metrics
    buy_count = sum(1 for t in trades if t.side.upper() == "BUY")
    sell_count = len(trades) - buy_count
    total_volume = sum(t.size * t.price for t in trades)
    avg_trade_size = total_volume / len(trades)

    # Market exposure
    market_exposure = {}
    for trade in trades:
        cid = trade.condition_id or "unknown"
        if cid not in market_exposure:
            market_exposure[cid] = {
                "trades": 0,
                "volume": 0.0,
                "title": trade.title,
            }
        market_exposure[cid]["trades"] += 1
        market_exposure[cid]["volume"] += trade.size * trade.price

    # Sort by volume
    top_markets = sorted(market_exposure.items(), key=lambda x: x[1]["volume"], reverse=True)[:5]

    # Timing analysis
    trades_by_hour = {h: 0 for h in range(24)}
    for trade in trades:
        if trade.timestamp:
            trades_by_hour[trade.timestamp.hour] += 1

    most_active_hours = sorted(trades_by_hour.items(), key=lambda x: x[1], reverse=True)[:3]

    print("\nPerformance Metrics:")
    print("-" * 40)
    print(f"  Total Trades: {len(trades)}")
    print(f"  Buy/Sell: {buy_count}/{sell_count} ({buy_count/len(trades)*100:.1f}% buys)")
    print(f"  Average Trade Size: {format_currency(avg_trade_size)}")
    print(f"  Total Volume: {format_currency(total_volume)}")

    print("\nTop Markets by Volume:")
    print("-" * 40)
    for cid, data in top_markets:
        title = (data["title"] or cid)[:50]
        print(f"  {title}")
        print(f"    Trades: {data['trades']}, Volume: {format_currency(data['volume'])}")

    print("\nMost Active Trading Hours (UTC):")
    print("-" * 40)
    for hour, count in most_active_hours:
        bar = "#" * (count * 2)
        print(f"  {hour:02d}:00 - {count:3d} trades {bar}")


def detect_signals(exchange, wallet_address: str, limit: int = 500, market_id: str = None):
    """Detect and display insider trading signals."""
    print(f"\nDetecting insider signals for: {wallet_address}")
    print("=" * 80)

    trades = exchange.fetch_public_trades(
        market=market_id,
        user=wallet_address,
        limit=limit,
        taker_only=False,
    )

    if len(trades) < 5:
        print(f"Insufficient trades for analysis. Found {len(trades)}, need at least 5.")
        return

    signals = []
    risk_score = 0

    # Signal 1: Market concentration
    market_trades = {}
    for trade in trades:
        cid = trade.condition_id or "unknown"
        market_trades[cid] = market_trades.get(cid, 0) + 1

    if market_trades:
        max_concentration = max(market_trades.values()) / len(trades)
        if max_concentration > 0.5:
            signals.append({
                "type": "HIGH_MARKET_CONCENTRATION",
                "severity": "MEDIUM",
                "details": f"Over {max_concentration*100:.1f}% of trades in single market",
            })
            risk_score += 2

    # Signal 2: Large trade sizes
    trade_sizes = [t.size * t.price for t in trades]
    avg_size = sum(trade_sizes) / len(trade_sizes)
    large_trades = [s for s in trade_sizes if s > avg_size * 3]
    if len(large_trades) > len(trades) * 0.1:
        signals.append({
            "type": "FREQUENT_LARGE_TRADES",
            "severity": "MEDIUM",
            "details": f"{len(large_trades)} trades exceed 3x average size ({format_currency(avg_size)})",
        })
        risk_score += 2

    # Signal 3: High volume
    total_volume = sum(trade_sizes)
    if total_volume > 100000:
        severity = "HIGH" if total_volume > 500000 else "MEDIUM"
        signals.append({
            "type": "HIGH_TOTAL_VOLUME",
            "severity": severity,
            "details": f"Total trading volume: {format_currency(total_volume)}",
        })
        risk_score += 3 if total_volume > 500000 else 2

    # Signal 4: One-sided trading
    buy_count = sum(1 for t in trades if t.side.upper() == "BUY")
    buy_ratio = buy_count / len(trades)
    if buy_ratio > 0.85 or buy_ratio < 0.15:
        signals.append({
            "type": "ONE_SIDED_TRADING",
            "severity": "MEDIUM",
            "details": f"Trading heavily skewed: {buy_ratio*100:.1f}% buys",
        })
        risk_score += 2

    # Signal 5: Burst trading
    timestamps = sorted([t.timestamp for t in trades if t.timestamp])
    burst_count = 0
    for i in range(len(timestamps) - 1):
        if (timestamps[i + 1] - timestamps[i]).total_seconds() < 60:
            burst_count += 1

    if len(timestamps) >= 10 and burst_count > len(timestamps) * 0.2:
        signals.append({
            "type": "BURST_TRADING",
            "severity": "LOW",
            "details": f"{burst_count} trades within 1 minute of each other",
        })
        risk_score += 1

    # Determine risk level
    if risk_score >= 7:
        risk_level = "HIGH"
    elif risk_score >= 4:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Display results
    print(f"\nRisk Assessment:")
    print("-" * 40)
    print(f"  Risk Level: {risk_level}")
    print(f"  Risk Score: {risk_score}/10")
    print(f"  Trades Analyzed: {len(trades)}")

    if signals:
        print(f"\nSignals Detected ({len(signals)}):")
        print("-" * 40)
        for signal in signals:
            severity = signal["severity"]
            marker = "[!]" if severity == "HIGH" else "[*]" if severity == "MEDIUM" else "[-]"
            print(f"  {marker} {signal['type']}")
            print(f"      Severity: {severity}")
            print(f"      {signal['details']}")
    else:
        print("\n  No significant insider trading signals detected.")

    return {"risk_level": risk_level, "signals": signals, "risk_score": risk_score}


def compare_wallets(exchange, wallet_addresses: list, limit_per_wallet: int = 200):
    """Compare trading patterns across wallets."""
    print(f"\nComparing {len(wallet_addresses)} wallets")
    print("=" * 80)

    wallet_data = {}
    market_sets = []

    for wallet in wallet_addresses:
        print(f"\n  Fetching data for {wallet[:10]}...")
        try:
            trades = exchange.fetch_public_trades(
                user=wallet,
                limit=limit_per_wallet,
                taker_only=False,
            )

            markets = set()
            volume = 0.0
            for t in trades:
                if t.condition_id:
                    markets.add(t.condition_id)
                volume += t.size * t.price

            wallet_data[wallet] = {
                "trades": len(trades),
                "volume": volume,
                "markets": len(markets),
            }
            market_sets.append(markets)
        except Exception as e:
            wallet_data[wallet] = {"error": str(e)}

    # Find common markets
    common_markets = []
    if len(market_sets) >= 2:
        common = market_sets[0]
        for s in market_sets[1:]:
            common = common.intersection(s)
        common_markets = list(common)

    print("\nWallet Comparison:")
    print("-" * 60)
    print(f"{'Wallet':<14} {'Trades':>8} {'Volume':>14} {'Markets':>8}")
    print("-" * 60)

    for wallet, data in wallet_data.items():
        if "error" in data:
            print(f"{wallet[:12]}.. {'Error':>8}")
        else:
            print(
                f"{wallet[:12]}.. {data['trades']:>8} {format_currency(data['volume']):>14} {data['markets']:>8}"
            )

    print(f"\nCommon Markets: {len(common_markets)}")

    if common_markets:
        overlap_ratio = len(common_markets) / min(len(s) for s in market_sets if s)
        if overlap_ratio > 0.5:
            print(f"\n  [!] HIGH OVERLAP: {overlap_ratio*100:.1f}% market overlap detected")
            print("      This may indicate coordinated trading")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze wallet trading patterns for insider signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "wallet_address",
        nargs="?",
        help="Wallet address to analyze",
    )
    parser.add_argument(
        "--exchange",
        default="polymarket",
        help="Exchange name (default: polymarket)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum trades to fetch (default: 500)",
    )
    parser.add_argument(
        "--market",
        help="Filter by market/condition ID",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze trading performance",
    )
    parser.add_argument(
        "--detect-signals",
        action="store_true",
        help="Detect insider trading signals",
    )
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="WALLET",
        help="Compare multiple wallets",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.wallet_address and not args.compare:
        parser.error("Either wallet_address or --compare is required")

    # Create exchange (read-only, no credentials needed)
    exchange = create_exchange(args.exchange, verbose=False, validate=False)

    try:
        if args.compare:
            if len(args.compare) < 2:
                parser.error("--compare requires at least 2 wallet addresses")
            compare_wallets(exchange, args.compare, args.limit)
        elif args.detect_signals:
            result = detect_signals(exchange, args.wallet_address, args.limit, args.market)
            if args.json and result:
                print("\n" + json.dumps(result, indent=2))
        elif args.analyze:
            analyze_performance(exchange, args.wallet_address, args.limit)
        else:
            fetch_trades(exchange, args.wallet_address, args.limit, args.market)

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
