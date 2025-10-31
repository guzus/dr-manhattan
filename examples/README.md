# Two-Face Examples

This directory contains example scripts demonstrating how to use the Two-Face library.

## Spread Strategy Example

A simple spread trading strategy that exploits arbitrage opportunities in binary prediction markets.

### Strategy Overview

The spread strategy identifies markets where the sum of Yes and No prices is less than 1, indicating a potential arbitrage opportunity. When found, it buys both outcomes to guarantee profit when the market resolves.

**Strategy Features:**
- **Arbitrage Detection**: Identifies markets where Yes + No prices < 1
- **Risk Management**: Configurable position sizing and exposure limits
- **Automated Trading**: Places orders for both outcomes to capture spread
- **Real-time Monitoring**: Tracks positions and logs performance
- **Error Handling**: Built-in retry logic and rate limiting

### Running the Strategy

```bash
uv run python examples/spread_strategy.py
```

### Configuration

Edit `spread_strategy.py` to configure:

```python
strategy = SpreadStrategy(
    exchange_config={'dry_run': True},
    min_spread=0.03,      # 3% minimum spread required
    max_exposure=500.0    # Maximum $500 exposure per trade
)

strategy.run_strategy(
    duration_minutes=10,         # Run for 10 minutes
    check_interval_seconds=60    # Check markets every 60 seconds
)
```

### How It Works

1. **Fetch Markets**: Retrieves active binary markets from Polymarket
2. **Filter Opportunities**: Finds markets where price sum < 1
3. **Calculate Position Size**: Based on spread size and liquidity
4. **Execute Trades**: Buys both Yes and No outcomes
5. **Track Positions**: Monitors expected profit and positions

### Example Output

```
2025-10-31 12:41:06 - INFO - Starting spread strategy for 10 minutes
2025-10-31 12:41:06 - INFO - Fetched 20 markets
2025-10-31 12:41:06 - INFO - Found opportunity: Will Bitcoin reach $100k in 2025? - Spread: 3.50%
2025-10-31 12:41:06 - INFO - Placed order: BUY 250 @ 0.48 for Yes
2025-10-31 12:41:06 - INFO - Placed order: BUY 250 @ 0.485 for No
2025-10-31 12:41:06 - INFO - Spread trade executed for Will Bitcoin reach $100k...
```

### Notes

- The strategy runs in dry-run mode by default (no real orders)
- Set `dry_run: False` and provide `private_key` for live trading
- Polymarket markets are typically very efficient (spreads ~0%)
- Real arbitrage opportunities are rare and quickly exploited

## Other Examples

### simple_test.py
Basic test showing how to fetch markets and display market data.

### test_strategy.py
Additional strategy testing framework.

## Market Data Streaming Example

Real-time market data streaming:

```python
import time
import two_face
from two_face.models import Market

def market_update_callback(market_id: str, market: Market):
    """Called when market data is updated"""
    print(f"Market {market_id[:8]}... updated:")
    print(f"  Question: {market.question[:50]}...")
    print(f"  Prices: {market.prices}")
    print(f"  Spread: {market.spread:.2%}")

# Initialize exchange
exchange = two_face.Polymarket({'verbose': True})

# Fetch markets to watch
markets = exchange.fetch_markets()
target_markets = [m.id for m in markets[:3] if m.is_binary]

# Start streaming
stream_thread = exchange.stream_market_data(target_markets, market_update_callback)

# Keep running
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nStopping streams...")
```

**Streaming Features:**
- Real-time market data polling
- Price change detection with callbacks
- Multi-market support
- Error resilience with automatic retry
- Non-blocking thread-based operation
