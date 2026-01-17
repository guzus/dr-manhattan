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

# Kalshi (get API keys from https://kalshi.com/api)
KALSHI_API_KEY_ID=your-api-key-id
KALSHI_PRIVATE_KEY_PEM="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
# Or use a file path instead:
# KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi-private-key.pem
KALSHI_DEMO=false
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
uv run python examples/list_all_markets.py kalshi
uv run python examples/list_all_markets.py polymarket --limit 50 --open-only
```

## find_common_markets.py

**Find markets that exist on both Polymarket and Opinion exchanges.**

```bash
uv run python examples/find_common_markets.py
```

## spread_strategy.py

**Exchange-agnostic BBO market making strategy.**

Works with Polymarket, Opinion, Limitless, Kalshi, or any exchange implementing the standard interface.

**Usage:**
```bash
# Polymarket
uv run python examples/spread_strategy.py --exchange polymarket --slug fed-decision
uv run python examples/spread_strategy.py -e polymarket -m 12345

# Opinion
uv run python examples/spread_strategy.py --exchange opinion --market-id 813
uv run python examples/spread_strategy.py -e opinion --slug bitcoin

# Kalshi (market ID from URL: kalshi.com/markets/.../MARKET-ID)
uv run python examples/spread_strategy.py -e kalshi -m "KXNBABLK-26JAN15MEMORL-ORLPBANCHERO5-1"
uv run python examples/spread_strategy.py -e kalshi -m "KXATPMATCH-26JAN16DAVHUM-HUM" --order-size 1

# Environment variables
EXCHANGE=polymarket MARKET_SLUG=fed-decision uv run python examples/spread_strategy.py
```

**Options:**
- `--exchange, -e`: Exchange name (polymarket, opinion, limitless, kalshi)
- `--market-id, -m`: Market ID
- `--slug, -s`: Market slug/keyword for search
- `--max-position`: Max position per outcome (default: 100)
- `--order-size`: Order size (default: 5)

**Warning:** This places REAL orders with REAL money.

## spike_strategy.py

**Mean reversion strategy that buys price dips.**

Detects when price drops below EMA baseline and enters expecting bounce back.

**Usage:**
```bash
uv run python examples/spike_strategy.py --exchange polymarket --slug fed-decision
uv run python examples/spike_strategy.py -e polymarket -m 12345 --spike-threshold 0.02
```

**Options:**
- `--exchange, -e`: Exchange name (polymarket, opinion, limitless, kalshi)
- `--market-id, -m`: Market ID
- `--slug, -s`: Market slug/keyword for search
- `--spike-threshold`: Entry threshold (default: 1.5%)
- `--profit-target`: Take profit (default: 3%)
- `--stop-loss`: Stop loss (default: 2%)

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
