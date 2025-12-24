# Spike Bot Strategy

A momentum trading strategy that exploits short-term price spikes on prediction markets.

## Overview

The Spike Bot monitors price movements in real-time and takes advantage of sharp price movements (spikes) that typically mean-revert. This is based on the observation that when news hits or markets panic, prices can spike 1-4% in seconds before settling back down.

**Concept Source**: https://x.com/gusik4ever/status/2003103062546657636

## How It Works

1. **Price Monitoring**: Polls the market every second via WebSocket or REST API
2. **Spike Detection**: Identifies sharp price movements (1.5%+ by default)
3. **Entry Logic**: Takes counter-trend positions to capture the bounce/reversion
   - **Upward spike**: Sells into the spike (expects price to come down)
   - **Downward spike**: Buys the dip (expects price to recover)
4. **Exit Logic**: Closes positions with tight risk management
   - **Profit Target**: 3% gain (configurable)
   - **Stop Loss**: 2% loss (configurable)

## Configuration

### Basic Parameters

```python
SpikeBot(
    exchange=exchange,
    market_id="market_id",
    spike_threshold=0.015,    # 1.5% movement triggers detection
    profit_target=0.03,       # 3% profit target
    stop_loss=0.02,          # 2% stop loss
    position_size=5.0,       # $5 per trade
    max_position=20.0,       # Max $20 per outcome
    history_size=60,         # 60 seconds of price history
    check_interval=1.0,      # Check every 1 second
)
```

### Parameter Guide

- **spike_threshold**: Minimum price change to trigger (0.015 = 1.5%)
  - Lower = more trades, higher noise
  - Higher = fewer trades, stronger signals

- **profit_target**: Exit when this profit is reached (0.03 = 3%)
  - Recommended: 2-4% for quick exits

- **stop_loss**: Exit when loss exceeds this (0.02 = 2%)
  - Protects against trend continuation

- **position_size**: Dollar amount per trade
  - Start small ($1-5) while testing

- **max_position**: Maximum exposure per outcome
  - Prevents over-concentration

- **history_size**: Price history window in seconds
  - 60s = 1 minute of history for spike detection

- **check_interval**: Polling frequency in seconds
  - 1s recommended for spike detection

## Usage

### Setup

1. Install dependencies:
```bash
uv sync
```

2. Set environment variables:
```bash
export POLYMARKET_PRIVATE_KEY="your_private_key"
export POLYMARKET_FUNDER="your_funder_address"  # optional
```

### Running the Bot

Basic usage:
```bash
uv run python examples/spike_bot.py --slug will-btc-hit-100k-by-2024
```

With custom parameters:
```bash
uv run python examples/spike_bot.py \
  --slug btc-above-100k \
  --spike-threshold 0.02 \
  --profit-target 0.04 \
  --stop-loss 0.02 \
  --position-size 10 \
  --max-position 50
```

Run for specific duration:
```bash
uv run python examples/spike_bot.py \
  --slug fed-decision \
  --duration 60  # Run for 60 minutes
```

### Programmatic Usage

```python
import dr_manhattan
from dr_manhattan.strategies import SpikeBot

# Initialize exchange
exchange = dr_manhattan.Polymarket({
    'private_key': 'your_private_key',
    'funder': 'your_funder_address',
})

# Fetch market
markets = exchange.fetch_markets_by_slug('btc-above-100k')
market = markets[0]

# Create and run bot
bot = SpikeBot(
    exchange=exchange,
    market_id=market.id,
    spike_threshold=0.015,
    profit_target=0.03,
    stop_loss=0.02,
    position_size=5.0,
)

# Run indefinitely (or set duration_minutes)
bot.run()
```

## Strategy Logic

### Spike Detection Algorithm

```python
def detect_spike(current_price, price_history, threshold=0.015):
    """
    Compare current price to recent 10-second average.
    If change exceeds threshold, spike is detected.
    """
    recent_avg = average(price_history[-10:])
    price_change = (current_price - recent_avg) / recent_avg

    if abs(price_change) >= threshold:
        return 'up' if price_change > 0 else 'down'
    return None
```

### Entry Logic

- **Upward Spike** (price jumped up):
  - SELL at best bid
  - Rationale: Price likely to revert down

- **Downward Spike** (price dropped):
  - BUY at best ask
  - Rationale: Price likely to bounce back

### Exit Logic

Active position management on every tick:

```python
pnl_pct = (current_price - entry_price) / entry_price

if pnl_pct >= profit_target:
    exit_position(reason="PROFIT TARGET")

elif pnl_pct <= -stop_loss:
    exit_position(reason="STOP LOSS")
```

## Risk Management

### Position Sizing

- Start with small positions ($1-5) while learning
- Never risk more than you can afford to lose
- Max position limits prevent overexposure

### Market Selection

Best markets for spike trading:
- High volume (>$100k recommended)
- High volatility (news-driven markets)
- Liquid orderbooks (tight spreads)
- Binary markets (simpler dynamics)

Good examples:
- Crypto price markets (hourly, daily)
- Fed decision markets
- Election markets during key events
- Sports markets during games

### Timing

- Most active during:
  - Major news events
  - Market open/close
  - Event deadlines
  - High volatility periods

### Filters and Safety

The bot includes basic safety features:
- Cash balance checks before trades
- Position limits per outcome
- Automatic cleanup on shutdown
- Error handling and logging

## Performance Tips

1. **Monitor Initially**: Watch the bot for the first hour to understand behavior
2. **Test with Small Size**: Use $1-2 positions initially
3. **Choose Volatile Markets**: More spikes = more opportunities
4. **Adjust Thresholds**: Tune based on market volatility
5. **Watch Spreads**: Wide spreads can eat into profits

## Logging

The bot provides detailed logging:

```
[09:15:23] NAV: $1,234.56 | Cash: $1,200.00 | Pos: 10 Yes | Delta: 10.0 | Orders: 0

  ↑ SPIKE UP detected on Yes: 0.6543 - Selling into spike at 0.6500
    SPIKE -> SELL 5 Yes @ 0.6500

  Positions: Yes: +2.3%

  EXIT Yes @ 0.6650 - PROFIT TARGET (2.3%)
```

## Limitations

- Requires active internet connection
- Latency matters (faster = better)
- Spreads can reduce profitability
- Not all spikes mean-revert
- Needs sufficient liquidity

## Deployment

### VPS Deployment

For 24/7 operation, deploy on a VPS:

```bash
# Install dependencies
uv sync

# Run in background with nohup
nohup uv run python examples/spike_bot.py \
  --slug your-market \
  > spike_bot.log 2>&1 &

# Check logs
tail -f spike_bot.log
```

### Using tmux/screen

```bash
# Start tmux session
tmux new -s spikebot

# Run bot
uv run python examples/spike_bot.py --slug your-market

# Detach: Ctrl+B then D
# Reattach: tmux attach -t spikebot
```

## Advanced Customization

### Custom Exit Logic

Extend `SpikeBot` and override `manage_position`:

```python
from dr_manhattan.strategies import SpikeBot

class MyCustomBot(SpikeBot):
    def manage_position(self, outcome, current_price, position):
        # Your custom exit logic
        # e.g., trailing stops, time-based exits, etc.
        pass
```

### Multiple Markets

Run multiple bots on different markets:

```python
markets = ['btc-100k', 'eth-5k', 'fed-decision']

for slug in markets:
    market = exchange.fetch_markets_by_slug(slug)[0]
    bot = SpikeBot(exchange, market.id)
    # Run each in separate thread/process
```

## Troubleshooting

**Bot not detecting spikes**:
- Lower spike_threshold
- Check if market is active
- Verify price data is updating

**Too many trades**:
- Increase spike_threshold
- Add cooldown between trades

**Exits too early**:
- Increase profit_target
- Adjust stop_loss

**Connection errors**:
- Check internet connection
- Verify API credentials
- Check Polymarket API status

## Legal and Disclaimer

- Trading carries risk. Only trade with funds you can afford to lose
- This is educational software. Use at your own risk
- Not financial advice
- Ensure compliance with local regulations
- Polymarket may have geographic restrictions

## See Also

- [Polymarket Setup Guide](../exchanges/polymarket_setup.md)
- [Strategy Base Class](../../dr_manhattan/base/strategy.py)
- [Spread Strategy Example](../../examples/spread_strategy.py)
