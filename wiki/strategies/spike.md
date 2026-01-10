# Spike Strategy (Mean Reversion)

Price spike detection strategy for binary prediction markets.

## Overview

Spike Strategy detects sudden price drops (spike down) and buys expecting mean reversion.

- **Strategy Type**: Mean Reversion
- **Direction**: BUY-only
- **Profit Source**: Short-term price overshoot recovery
- **Best For**: Volatile event markets

## How It Works

```
Price
  │
  │    ┌─── EMA (Moving Average)
  │    │
0.50 ──┼────────────────────────
  │    │         ╲
  │    │          ╲ Spike Down (< threshold)
  │    │           ╲
0.45 ──┼────────────●──────────  ← BUY signal
  │    │             ╲
  │    │              └─── Mean Reversion Expected
  │
  └────┴───────────────────────► Time
```

### Binary Market Logic

Since YES + NO = 1.0:
- **YES dip → BUY YES**: Buy YES when YES price drops
- **NO dip → BUY NO**: Buy NO when NO price drops (effectively shorting YES)

This covers both directions with BUY-only logic.

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--exchange` | polymarket | Exchange |
| `--market-id` | - | Market ID |
| `--slug` | - | Market search keyword |
| `--spike-threshold` | 0.015 | Spike detection threshold (1.5%) |
| `--profit-target` | 0.03 | Take profit target (3%) |
| `--stop-loss` | 0.02 | Stop loss limit (2%) |
| `--position-size` | 5.0 | Position size ($) |
| `--max-position` | 20.0 | Max position ($) |
| `--ema-period` | 30 | EMA period (seconds) |
| `--cooldown` | 30.0 | Re-entry cooldown (seconds) |
| `--duration` | - | Run duration (minutes) |

## Usage

```bash
# Basic run
uv run python examples/spike_strategy.py -s "trump"

# Aggressive settings (low threshold, fast TP)
uv run python examples/spike_strategy.py \
    -s "bitcoin" \
    --spike-threshold 0.01 \
    --profit-target 0.02 \
    --stop-loss 0.015 \
    --position-size 10

# Conservative settings (high threshold, large TP)
uv run python examples/spike_strategy.py \
    -s "election" \
    --spike-threshold 0.025 \
    --profit-target 0.05 \
    --stop-loss 0.03 \
    --ema-period 60

# Time-limited run (30 minutes)
uv run python examples/spike_strategy.py -s "fed" --duration 30
```

## Core Logic

### 1. EMA Calculation

```python
def _update_ema(self, outcome: str, price: float):
    alpha = 2.0 / (ema_period + 1)
    ema = price * alpha + prev_ema * (1 - alpha)
```

### 2. Spike Detection

```python
def _detect_spike_down(self, outcome: str, price: float) -> bool:
    deviation = (price - ema) / ema
    return deviation <= -spike_threshold
```

### 3. Position Management

```python
# Entry
if spike_down and not in_cooldown and has_cash:
    BUY at ask price

# Exit
pnl = (current_price - entry_price) / entry_price
if pnl >= profit_target:  # Take Profit
    SELL at bid price
if pnl <= -stop_loss:     # Stop Loss
    SELL at bid price
```

## State Tracking

| State | Description |
|-------|-------------|
| `ema_prices` | EMA price per outcome |
| `price_history` | Last 60 price records |
| `entries` | Current positions (entry_price, size, entry_time) |
| `last_exit_time` | Last exit time (for cooldown) |

## Risk Management

- **Stop Loss**: Auto-exit when loss limit reached
- **Take Profit**: Auto-exit when profit target reached
- **Cooldown**: Wait period before re-entry after exit
- **Position Limit**: Cap total exposure with max_position
- **Dust Filter**: Ignore positions < 1

## Cleanup

On shutdown:
1. Cancel all open orders
2. Attempt to liquidate positions
3. Close WebSocket connection

## File Location

- Strategy: `examples/spike_strategy.py`
- Base Class: `dr_manhattan/base/strategy.py`
