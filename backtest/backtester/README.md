# Backtest Guide

Binary token backtester for Polymarket crypto markets.

Buy UP or DOWN tokens when a condition is met, hold until the window settles, and collect (or lose) based on the outcome.

## How It Works

```
15-min window lifecycle:

 t=0            t=14           t=15 (settlement)
  |--- window ---|               |
  K (strike)     S (spot)        resolved = UP if S > K, else DOWN
                 ^
                 buy token here
                 hold until settlement
```

Each 15-minute window is a binary market. If BTC price at settlement is above the opening price, the UP token pays $1. Otherwise, the DOWN token pays $1. The losing side pays $0.

**PnL per trade:** `qty * settlement - cost`
- Buy UP at $0.70, settles UP: `1.0 - 0.70 = +$0.30`
- Buy UP at $0.70, settles DOWN: `0.0 - 0.70 = -$0.70`

## Structure

```
backtester/
├── data_manager.py       # BinanceManager (klines) + PolymarketManager (S3 orderbook)
├── backtest.py           # backtest(), backtest_fixed(), backtest_summary()
├── 15min_backtest.ipynb  # Runnable example notebook
├── data/                 # Auto-generated on first run (gitignored)
└── README.md
```

## Step 1: Collect Data

`data_manager.py` provides two data loaders. Both cache locally to `./data/` so subsequent runs only fetch new data.

### Binance USDM Klines

Polymarket crypto markets settle via Chainlink oracle, but we pull price data from Binance USDM perpetual futures instead. Binance has longer history, finer granularity, and is easier to fetch. The price difference between Chainlink and Binance USDM is negligible for backtesting purposes.

```python
from data_manager import BinanceManager

binance = BinanceManager(base_dir='./data')
btc_klines = binance.fetch_klines('usdm', 'BTCUSDT', '1m', start='2026-01-01')
```

Returns 1-minute OHLCV candles from Binance USDM perpetual futures. Used as the price reference (S) and for realized volatility features.

### Polymarket Orderbook

```python
from data_manager import PolymarketManager

pm = PolymarketManager(base_dir='./data')
book_df = pm.load_book_df(
    asset='BTC', freq='15M',
    start_date='2026-01-01', end_date='2026-03-31',
    log=True
)
```

Downloads UP-token orderbook snapshots from a private S3 bucket (set via `PM_S3_BUCKET` env var). Each row is a 1-minute snapshot within a 15-minute window.

**`book_df` columns:**

| Column | Description |
|---|---|
| `start_time` / `end_time` | 15-min window boundaries |
| `up_best_bid` / `up_best_ask` | Best level-1 quotes for UP token |
| `down_best_bid` / `down_best_ask` | Best level-1 quotes for DOWN token |
| `up_mid` / `down_mid` | Mid prices `(bid + ask) / 2` |
| `resolved` | Settlement outcome: `UP`, `DOWN`, or `UNKNOWN` |

## Step 2: Define Signal

A signal is a boolean Series aligned to `book_df.index`. When `True`, the backtester buys the corresponding token at the best ask.

```python
# Example: buy when market is already confident (mid > 0.7) near expiry (T < 4 min)
up_cond   = (book_df['up_mid']   > 0.7) & (features['T'] < 4)
down_cond = (book_df['down_mid'] > 0.7) & (features['T'] < 4)

up_cond   = up_cond.reindex(book_df.index)
down_cond = down_cond.reindex(book_df.index)
```

You can use any features (volatility, momentum, external signals) to construct `up_cond` and `down_cond`. The only requirement is that they share the same index as `book_df`.

## Step 3: Run Backtest

### Proportional Sizing

```python
from backtest import backtest, backtest_summary

trades = backtest(
    book_df,
    up_condition=up_cond,
    down_condition=down_cond,
    initial_balance=1000,  # starting capital ($)
    bet_pct=0.01,          # risk 1% of balance per window
    fee=True,              # Polymarket variable fee: 0.25 * (p*(1-p))^2
    slippage_bps=5,        # 0.05% execution slippage
)
```

### Fixed Sizing

```python
from backtest import backtest_fixed, backtest_summary

trades = backtest_fixed(
    book_df,
    up_condition=up_cond,
    down_condition=down_cond,
    bet_size=100,          # flat $100 per signal
    fee=True,
    slippage_bps=5,
)
```

### Summary

```python
metrics = backtest_summary(trades)
```

Returns per-window aggregates: `resolved`, `total_pnl`, `cum_pnl`, `drawdown`, `win_rate`.

## Step 4: Evaluate

The notebook (`15min_backtest.ipynb`) includes a 4-panel dashboard:

| Panel | What it shows |
|---|---|
| Cumulative PnL | Equity curve over time |
| Drawdown | Peak-to-trough decline ($) |
| PnL Distribution | Win/loss histogram per market |
| Win Rate | Expanding cumulative win rate |

Flat regions in the equity curve indicate gaps in S3 snapshot data.

## Quick Start

```bash
cd backtest/backtester
jupyter notebook 15min_backtest.ipynb
# Run all cells -- data/ directory is created automatically on first run
```
