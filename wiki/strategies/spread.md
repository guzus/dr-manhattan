# Spread Strategy (BBO Market Making)

Exchange-agnostic BBO (Best Bid/Offer) spread strategy.

## Overview

Spread Strategy places orders at the best bid and best ask prices, capturing the bid-ask spread as profit.

- **Strategy Type**: Market Making
- **Direction**: Bidirectional (BUY + SELL)
- **Profit Source**: Bid-Ask spread capture
- **Supported Exchanges**: Polymarket, Opinion, Limitless, etc.

## How It Works

```
┌─────────────────────────────────────────────────┐
│                  Orderbook                       │
├─────────────────────────────────────────────────┤
│  Best Ask: 0.55  ← SELL order placed here        │
│  ...                                             │
│  Best Bid: 0.45  ← BUY order placed here         │
└─────────────────────────────────────────────────┘
```

1. **Check BBO each tick**: Poll REST API for best bid/ask
2. **Manage existing orders**: Cancel stale orders if price changed
3. **Place new orders**: Place at BBO if no order exists
4. **Delta management**: Skip entry if position imbalance exceeds max_delta

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--exchange` | polymarket | Exchange (polymarket, opinion, limitless) |
| `--market-id` | - | Market ID (direct) |
| `--slug` | - | Market search keyword |
| `--market` | - | Index to select from search results |
| `--max-position` | 100 | Max position per outcome |
| `--order-size` | 5 | Order size |
| `--max-delta` | 20 | Max position imbalance |
| `--interval` | 5 | Check interval (seconds) |

## Usage

```bash
# Run with market ID
uv run python examples/spread_strategy.py -e polymarket -m "0x1234..."

# Search market by slug
uv run python examples/spread_strategy.py -s "trump" --market 0

# Custom parameters
uv run python examples/spread_strategy.py \
    -e opinion \
    -s "bitcoin" \
    --max-position 50 \
    --order-size 10 \
    --max-delta 15 \
    --interval 3
```

## Core Logic

```python
class SpreadStrategy(Strategy):
    def on_tick(self) -> None:
        self.log_status()       # Log NAV, positions, delta
        self.place_bbo_orders() # Place orders at BBO
```

`place_bbo_orders()` is implemented in the Strategy base class:
- Fetch best_bid, best_ask for each outcome
- Validate spread (bid < ask)
- Skip entry if delta exceeds limit
- Cancel/replace orders if price changed

## Risk Management

- **max_position**: Limits holdings per outcome
- **max_delta**: Limits YES/NO position imbalance
- **cash check**: Skip BUY if insufficient balance

## File Location

- Strategy: `examples/spread_strategy.py`
- Base Class: `dr_manhattan/base/strategy.py`
