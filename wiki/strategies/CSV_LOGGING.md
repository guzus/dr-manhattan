# CSV Logging & Dashboard

Strategy execution logging and visualization dashboard.

## Features

- Automatic CSV logging of strategy execution
- Track NAV, positions, delta, and orders over time
- Web dashboard with interactive charts
- Real-time PnL and performance metrics

## Usage

### 1. Enable CSV Logging

Add `enable_csv_logging=True` when creating your strategy:

```python
from dr_manhattan import Strategy

strategy = SpreadStrategy(
    exchange=exchange,
    market_id=market_id,
    max_position=100,
    order_size=5,
    enable_csv_logging=True,  # Enable logging
)
strategy.run()
```

Or use the command line flag with example scripts:

```bash
uv run python examples/spread_strategy.py \
    --exchange polymarket \
    --slug "trump" \
    --enable-logging
```

### 2. CSV Output

Log files are saved to `logs/` directory with format:
```
logs/{StrategyName}_{MarketID}_{Timestamp}.csv
```

Example CSV structure:
```csv
timestamp,nav,cash,positions_value,delta,num_open_orders,yes_qty,yes_value,no_qty,no_value
2024-01-21T10:00:00,1050.25,500.00,550.25,5.2,2,100.0,52.0,95.0,45.6
2024-01-21T10:00:05,1051.30,498.50,552.80,5.5,2,102.0,54.6,97.0,47.04
```

### 3. View Dashboard

Start the dashboard server:

```bash
uv run dr-manhattan-dashboard
```

Open your browser to: http://localhost:8000

The dashboard shows:
- NAV, cash, and positions value over time
- Position quantities per outcome
- Delta tracking
- Performance statistics (PnL, max/min NAV, avg delta)

## Configuration

### Strategy Parameters

- `enable_csv_logging`: Enable/disable CSV logging (default: False)
- `log_dir`: Directory for log files (default: "logs")
- `check_interval`: Logging frequency in seconds (default: 5.0)

### Environment Variables

```bash
# Enable logging via environment
export ENABLE_CSV_LOGGING=true

# Run strategy
uv run python examples/spread_strategy.py --slug "market-name"
```

## Dashboard Features

### Charts

1. **NAV Chart**: Track total NAV, cash, and positions value
2. **Positions Chart**: Monitor position quantities for each outcome
3. **Delta Chart**: Track position imbalance over time

### Statistics

- Current NAV
- Total PnL and PnL %
- Max/Min NAV
- Average Delta
- Total ticks executed

## Example

```python
from dr_manhattan import Strategy, create_exchange

# Create exchange
exchange = create_exchange("polymarket")

# Create strategy with logging
class MyStrategy(Strategy):
    def on_tick(self):
        self.log_status()
        self.place_bbo_orders()

strategy = MyStrategy(
    exchange=exchange,
    market_id="0x...",
    max_position=100,
    order_size=5,
    check_interval=5.0,
    enable_csv_logging=True,
)

# Run strategy (logs every 5 seconds)
strategy.run()
```

Then view the dashboard:
```bash
uv run dr-manhattan-dashboard
```
