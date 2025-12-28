# Examples

Trading strategy examples for Dr. Manhattan library.

## Setup

**1. Create `.env` in project root:**

```env
# Polymarket
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_FUNDER=0x...

# Opinion
OPINION_API_KEY=...
OPINION_PRIVATE_KEY=0x...
OPINION_MULTI_SIG_ADDR=0x...

# Limitless
LIMITLESS_PRIVATE_KEY=0x...
```

**2. Run from project root:**

```bash
uv run python examples/spread_strategy.py --exchange polymarket --slug fed-decision
```

## list_all_markets.py

**List markets from any exchange.**

```bash
uv run python examples/list_all_markets.py polymarket
uv run python examples/list_all_markets.py opinion
uv run python examples/list_all_markets.py limitless
uv run python examples/list_all_markets.py polymarket --limit 50 --open-only
```

## find_common_markets.py

**Find markets that exist on both Polymarket and Opinion exchanges.**

```bash
uv run python examples/find_common_markets.py
```

## spread_strategy.py

**Exchange-agnostic BBO market making strategy.**

Works with Polymarket, Opinion, Limitless, or any exchange implementing the standard interface.

**Usage:**
```bash
# Polymarket
uv run python examples/spread_strategy.py --exchange polymarket --slug fed-decision
uv run python examples/spread_strategy.py -e polymarket -m 12345

# Opinion
uv run python examples/spread_strategy.py --exchange opinion --market-id 813
uv run python examples/spread_strategy.py -e opinion --slug bitcoin

# Environment variables
EXCHANGE=polymarket MARKET_SLUG=fed-decision uv run python examples/spread_strategy.py
```

**Options:**
- `--exchange, -e`: Exchange name (polymarket, opinion, limitless)
- `--market-id, -m`: Market ID
- `--slug, -s`: Market slug/keyword for search
- `--max-position`: Max position per outcome (default: 100)
- `--order-size`: Order size (default: 5)

**Warning:** This places REAL orders with REAL money.

## elon_tweets_strategy.py

**Statistical arbitrage strategy for Elon Musk tweet count markets.**

Based on the strategy from @noovd (source: https://x.com/0xMovez/status/2005002806722203657)

Calculates expected tweet count and identifies profitable ranges to buy on Polymarket.

**Strategy Logic:**
1. Calculate average daily tweets from historical data
2. Get current tweet count for the period
3. Project final count: `current_tweets + (avg_daily * days_remaining)`
4. Identify profitable ranges around the projection
5. Buy ranges with positive expected value (>70% probability coverage)

**Usage:**
```bash
# Auto-discover Elon tweets market
uv run python examples/elon_tweets_strategy.py --current 221 --avg-daily 48 --days-remaining 3

# Specify market ID directly
uv run python examples/elon_tweets_strategy.py \
  --market-id 0x... \
  --current 221 \
  --avg-daily 48 \
  --days-remaining 3 \
  --order-size 10 \
  --min-prob 0.70
```

**Required Parameters:**
- `--current`: Current tweet count for the period
- `--avg-daily`: Average tweets per day (from historical data)
- `--days-remaining`: Days remaining in the period

**Optional Parameters:**
- `--market-id, -m`: Market ID (auto-discovers if not provided)
- `--min-prob`: Minimum probability to target (default: 0.70)
- `--order-size`: Order size in USDC (default: 10)
- `--max-delta`: Maximum position imbalance (default: 100)
- `--interval`: Check interval in seconds (default: 300)

**Example Calculation:**
```
Current tweets: 221
Average daily: 48
Days remaining: 3
Projected: 221 + (48 × 3) = 365 tweets

Strategy buys ranges: 320-339, 340-359, 360-379, 380-399
Total probability: 79% (17% + 23% + 24% + 15%)
Expected value: ~20% premium
```

**Data Sources:**
- Manual input (parameters from your analysis)
- Twitter/X API (via @elontweets_live or similar)
- Historical average calculated from past periods

**Warning:** This places REAL orders with REAL money.

## Creating Custom Strategies

Inherit from `Strategy` base class:

```python
from dr_manhattan import Strategy

class MyStrategy(Strategy):
    def on_tick(self):
        self.log_status()
        self.place_bbo_orders()

strategy = MyStrategy(exchange, market_id="123")
strategy.run()
```

## Resources

- [Polymarket Setup Guide](../wiki/exchanges/polymarket_setup.md)
