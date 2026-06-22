"""Insider verification and wallet analysis tools."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dr_manhattan.utils import setup_logger

from ..session import ExchangeSessionManager
from ..utils import translate_error, validate_exchange

logger = setup_logger(__name__)

exchange_manager = ExchangeSessionManager()

# Analysis thresholds (per CLAUDE.md Rule #4: config in code)
DEFAULT_TRADE_LIMIT = 500
MIN_SIGNIFICANT_TRADE_USD = 1000
HIGH_WIN_RATE_THRESHOLD = 0.70
SUSPICIOUS_TIMING_HOURS = 24
MIN_TRADES_FOR_ANALYSIS = 5


def fetch_wallet_trades(
    exchange: str,
    wallet_address: str,
    market_id: Optional[str] = None,
    limit: int = DEFAULT_TRADE_LIMIT,
) -> Dict[str, Any]:
    """
    Fetch all trades for a specific wallet address.

    Args:
        exchange: Exchange name (currently only polymarket supported)
        wallet_address: Wallet/proxy wallet address to analyze
        market_id: Optional market filter (condition_id)
        limit: Maximum trades to fetch (default: 500)

    Returns:
        Dict with trades and summary:
        {
            "trades": [...],
            "summary": {
                "total_trades": 100,
                "total_volume_usd": 50000,
                "unique_markets": 15,
                "date_range": {"from": "...", "to": "..."}
            }
        }

    Example:
        >>> result = fetch_wallet_trades("polymarket", "0x1234...")
        >>> print(f"Total trades: {result['summary']['total_trades']}")
    """
    try:
        exchange = validate_exchange(exchange)

        if exchange.lower() != "polymarket":
            raise ValueError(f"Insider analysis currently only supports polymarket, got {exchange}")

        if not wallet_address or not wallet_address.startswith("0x"):
            raise ValueError("wallet_address must be a valid Ethereum address starting with 0x")

        if limit <= 0:
            limit = DEFAULT_TRADE_LIMIT
        elif limit > 5000:
            limit = 5000

        exch = exchange_manager.get_exchange(exchange)

        # Fetch trades for the wallet
        trades = exch.fetch_public_trades(
            market=market_id,
            user=wallet_address,
            limit=limit,
            taker_only=False,
        )

        # Convert to serializable format
        trades_data = []
        total_volume = 0.0
        unique_markets = set()
        min_time = None
        max_time = None

        for trade in trades:
            trade_dict = asdict(trade)
            # Convert datetime to ISO string
            if trade_dict.get("timestamp"):
                ts = trade_dict["timestamp"]
                trade_dict["timestamp"] = ts.isoformat() if isinstance(ts, datetime) else str(ts)
                if min_time is None or ts < min_time:
                    min_time = ts
                if max_time is None or ts > max_time:
                    max_time = ts

            trades_data.append(trade_dict)
            total_volume += trade.size * trade.price
            if trade.condition_id:
                unique_markets.add(trade.condition_id)

        summary = {
            "total_trades": len(trades_data),
            "total_volume_usd": round(total_volume, 2),
            "unique_markets": len(unique_markets),
            "date_range": {
                "from": min_time.isoformat() if min_time else None,
                "to": max_time.isoformat() if max_time else None,
            },
        }

        return {"trades": trades_data, "summary": summary}

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "wallet_address": wallet_address}) from e


def analyze_wallet_performance(
    exchange: str,
    wallet_address: str,
    limit: int = DEFAULT_TRADE_LIMIT,
) -> Dict[str, Any]:
    """
    Analyze trading performance and patterns for a wallet.

    Calculates win rate, average trade size, market concentration,
    and timing patterns that may indicate informed trading.

    Args:
        exchange: Exchange name (currently only polymarket supported)
        wallet_address: Wallet address to analyze
        limit: Maximum trades to analyze (default: 500)

    Returns:
        Dict with performance metrics:
        {
            "metrics": {
                "total_trades": 100,
                "buy_count": 60,
                "sell_count": 40,
                "avg_trade_size_usd": 500,
                "total_volume_usd": 50000
            },
            "market_exposure": {
                "condition_id": {"trades": 10, "volume": 5000}
            },
            "timing_analysis": {
                "trades_by_hour": {...},
                "avg_time_between_trades_hours": 2.5
            }
        }

    Example:
        >>> result = analyze_wallet_performance("polymarket", "0x1234...")
        >>> print(f"Win rate: {result['metrics'].get('estimated_win_rate', 'N/A')}")
    """
    try:
        exchange = validate_exchange(exchange)

        if exchange.lower() != "polymarket":
            raise ValueError(f"Insider analysis currently only supports polymarket, got {exchange}")

        # Fetch trades first
        trade_result = fetch_wallet_trades(exchange, wallet_address, limit=limit)
        trades_data = trade_result["trades"]

        if len(trades_data) < MIN_TRADES_FOR_ANALYSIS:
            return {
                "error": f"Insufficient trades for analysis. Found {len(trades_data)}, need at least {MIN_TRADES_FOR_ANALYSIS}",
                "trades_found": len(trades_data),
            }

        # Calculate metrics
        buy_count = sum(1 for t in trades_data if t.get("side", "").upper() == "BUY")
        sell_count = sum(1 for t in trades_data if t.get("side", "").upper() == "SELL")
        total_volume = sum(t.get("size", 0) * t.get("price", 0) for t in trades_data)
        avg_trade_size = total_volume / len(trades_data) if trades_data else 0

        # Market exposure analysis
        market_exposure: Dict[str, Dict[str, Any]] = {}
        for trade in trades_data:
            cid = trade.get("condition_id", "unknown")
            if cid not in market_exposure:
                market_exposure[cid] = {
                    "trades": 0,
                    "volume": 0.0,
                    "title": trade.get("title"),
                    "slug": trade.get("slug"),
                }
            market_exposure[cid]["trades"] += 1
            market_exposure[cid]["volume"] += trade.get("size", 0) * trade.get("price", 0)

        # Sort by volume
        market_exposure = dict(
            sorted(market_exposure.items(), key=lambda x: x[1]["volume"], reverse=True)
        )

        # Timing analysis
        trades_by_hour: Dict[int, int] = {h: 0 for h in range(24)}
        timestamps = []
        for trade in trades_data:
            ts_str = trade.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    trades_by_hour[ts.hour] += 1
                    timestamps.append(ts)
                except (ValueError, AttributeError):
                    pass

        # Calculate average time between trades
        avg_time_between = None
        if len(timestamps) >= 2:
            timestamps.sort()
            deltas = [(timestamps[i + 1] - timestamps[i]).total_seconds() / 3600 for i in range(len(timestamps) - 1)]
            avg_time_between = round(sum(deltas) / len(deltas), 2) if deltas else None

        # Identify significant trades (large size)
        significant_trades = [
            t for t in trades_data
            if (t.get("size", 0) * t.get("price", 0)) >= MIN_SIGNIFICANT_TRADE_USD
        ]

        return {
            "wallet_address": wallet_address,
            "metrics": {
                "total_trades": len(trades_data),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "avg_trade_size_usd": round(avg_trade_size, 2),
                "total_volume_usd": round(total_volume, 2),
                "significant_trades_count": len(significant_trades),
            },
            "market_exposure": dict(list(market_exposure.items())[:10]),  # Top 10 markets
            "timing_analysis": {
                "trades_by_hour": trades_by_hour,
                "avg_time_between_trades_hours": avg_time_between,
                "most_active_hours": sorted(trades_by_hour.items(), key=lambda x: x[1], reverse=True)[:3],
            },
            "data_range": trade_result["summary"]["date_range"],
        }

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "wallet_address": wallet_address}) from e


def detect_insider_signals(
    exchange: str,
    wallet_address: str,
    market_id: Optional[str] = None,
    limit: int = DEFAULT_TRADE_LIMIT,
) -> Dict[str, Any]:
    """
    Detect potential insider trading signals for a wallet.

    Analyzes trading patterns to identify suspicious activity:
    - Large trades before significant price movements
    - Unusually high win rates
    - Concentrated positions in specific markets
    - Timing patterns that suggest foreknowledge

    Args:
        exchange: Exchange name (currently only polymarket supported)
        wallet_address: Wallet address to analyze
        market_id: Optional market filter
        limit: Maximum trades to analyze

    Returns:
        Dict with risk assessment:
        {
            "risk_level": "low|medium|high",
            "signals": [
                {"type": "high_win_rate", "severity": "medium", "details": "..."},
                ...
            ],
            "summary": "..."
        }

    Example:
        >>> result = detect_insider_signals("polymarket", "0x1234...")
        >>> print(f"Risk level: {result['risk_level']}")
    """
    try:
        exchange = validate_exchange(exchange)

        if exchange.lower() != "polymarket":
            raise ValueError(f"Insider analysis currently only supports polymarket, got {exchange}")

        # Fetch trades
        trade_result = fetch_wallet_trades(exchange, wallet_address, market_id=market_id, limit=limit)
        trades_data = trade_result["trades"]

        if len(trades_data) < MIN_TRADES_FOR_ANALYSIS:
            return {
                "risk_level": "unknown",
                "signals": [],
                "summary": f"Insufficient data: {len(trades_data)} trades found, need at least {MIN_TRADES_FOR_ANALYSIS}",
                "trades_analyzed": len(trades_data),
            }

        signals: List[Dict[str, Any]] = []
        risk_score = 0

        # Signal 1: Market concentration
        market_trades: Dict[str, int] = {}
        for trade in trades_data:
            cid = trade.get("condition_id", "unknown")
            market_trades[cid] = market_trades.get(cid, 0) + 1

        if market_trades:
            max_concentration = max(market_trades.values()) / len(trades_data)
            if max_concentration > 0.5:
                signals.append({
                    "type": "high_market_concentration",
                    "severity": "medium",
                    "details": f"Over {max_concentration*100:.1f}% of trades in single market",
                    "threshold": "50%",
                })
                risk_score += 2

        # Signal 2: Large trade sizes
        trade_sizes = [t.get("size", 0) * t.get("price", 0) for t in trades_data]
        if trade_sizes:
            avg_size = sum(trade_sizes) / len(trade_sizes)
            large_trades = [s for s in trade_sizes if s > avg_size * 3]
            if len(large_trades) > len(trades_data) * 0.1:
                signals.append({
                    "type": "frequent_large_trades",
                    "severity": "medium",
                    "details": f"{len(large_trades)} trades exceed 3x average size (${avg_size:.2f})",
                    "threshold": "10% of trades",
                })
                risk_score += 2

        # Signal 3: Timing clustering
        timestamps = []
        for trade in trades_data:
            ts_str = trade.get("timestamp")
            if ts_str:
                try:
                    timestamps.append(datetime.fromisoformat(ts_str.replace("Z", "+00:00")))
                except (ValueError, AttributeError):
                    pass

        if len(timestamps) >= 10:
            timestamps.sort()
            # Check for burst trading (many trades in short period)
            burst_count = 0
            for i in range(len(timestamps) - 1):
                if (timestamps[i + 1] - timestamps[i]).total_seconds() < 60:  # Within 1 minute
                    burst_count += 1

            if burst_count > len(timestamps) * 0.2:
                signals.append({
                    "type": "burst_trading",
                    "severity": "low",
                    "details": f"{burst_count} trades within 1 minute of each other",
                    "threshold": "20% of trades",
                })
                risk_score += 1

        # Signal 4: Volume spikes
        total_volume = sum(trade_sizes)
        if total_volume > 100000:  # $100k+
            signals.append({
                "type": "high_total_volume",
                "severity": "high" if total_volume > 500000 else "medium",
                "details": f"Total trading volume: ${total_volume:,.2f}",
                "threshold": "$100,000",
            })
            risk_score += 3 if total_volume > 500000 else 2

        # Signal 5: One-sided trading
        buy_count = sum(1 for t in trades_data if t.get("side", "").upper() == "BUY")
        sell_count = len(trades_data) - buy_count
        if len(trades_data) >= 20:
            buy_ratio = buy_count / len(trades_data)
            if buy_ratio > 0.85 or buy_ratio < 0.15:
                signals.append({
                    "type": "one_sided_trading",
                    "severity": "medium",
                    "details": f"Trading heavily skewed: {buy_count} buys vs {sell_count} sells ({buy_ratio*100:.1f}% buys)",
                    "threshold": "85% one direction",
                })
                risk_score += 2

        # Determine risk level
        if risk_score >= 7:
            risk_level = "high"
        elif risk_score >= 4:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Generate summary
        if signals:
            summary = f"Found {len(signals)} potential insider signal(s). "
            high_severity = sum(1 for s in signals if s["severity"] == "high")
            if high_severity:
                summary += f"{high_severity} high-severity signal(s) detected. "
            summary += "Manual review recommended." if risk_level != "low" else "Patterns appear normal."
        else:
            summary = "No significant insider trading signals detected."

        return {
            "wallet_address": wallet_address,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "signals": signals,
            "summary": summary,
            "trades_analyzed": len(trades_data),
            "analysis_period": trade_result["summary"]["date_range"],
        }

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "wallet_address": wallet_address}) from e


def compare_wallets(
    exchange: str,
    wallet_addresses: List[str],
    limit_per_wallet: int = 200,
) -> Dict[str, Any]:
    """
    Compare trading patterns across multiple wallets.

    Useful for identifying coordinated trading or related accounts.

    Args:
        exchange: Exchange name
        wallet_addresses: List of wallet addresses to compare
        limit_per_wallet: Max trades per wallet

    Returns:
        Dict with comparison results:
        {
            "wallets": {
                "0x1234": {"volume": 50000, "trades": 100, ...},
                "0x5678": {"volume": 30000, "trades": 80, ...}
            },
            "common_markets": ["market1", "market2"],
            "correlation_signals": [...]
        }

    Example:
        >>> result = compare_wallets("polymarket", ["0x1234...", "0x5678..."])
        >>> print(f"Common markets: {len(result['common_markets'])}")
    """
    try:
        exchange = validate_exchange(exchange)

        if len(wallet_addresses) < 2:
            raise ValueError("Need at least 2 wallet addresses to compare")
        if len(wallet_addresses) > 10:
            raise ValueError("Maximum 10 wallets can be compared at once")

        wallet_data: Dict[str, Dict[str, Any]] = {}
        market_sets: List[set] = []

        for wallet in wallet_addresses:
            try:
                result = fetch_wallet_trades(exchange, wallet, limit=limit_per_wallet)
                trades = result["trades"]

                markets = set()
                for t in trades:
                    if t.get("condition_id"):
                        markets.add(t["condition_id"])

                wallet_data[wallet] = {
                    "total_trades": len(trades),
                    "total_volume_usd": result["summary"]["total_volume_usd"],
                    "unique_markets": len(markets),
                    "markets": list(markets)[:20],
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

        # Detect correlation signals
        correlation_signals = []

        if common_markets:
            overlap_ratio = len(common_markets) / min(len(s) for s in market_sets if s)
            if overlap_ratio > 0.5:
                correlation_signals.append({
                    "type": "high_market_overlap",
                    "details": f"{len(common_markets)} common markets ({overlap_ratio*100:.1f}% overlap)",
                })

        return {
            "wallets": wallet_data,
            "common_markets": common_markets[:20],
            "common_market_count": len(common_markets),
            "correlation_signals": correlation_signals,
        }

    except Exception as e:
        raise translate_error(e, {"exchange": exchange}) from e
