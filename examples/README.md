# Examples

Trading strategy examples for Dr. Manhattan library.

## Setup

**1. Create `.env` in project root:**

```env
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_FUNDER=0x...
```

**2. Run from project root:**

```bash
uv run examples/spread_strategy.py
```

## Available Examples

### spread_strategy.py

**Live market making strategy for Polymarket.**

Places bid and ask orders inside the spread to provide liquidity.

**Features:**
- Automatic market selection
- Dynamic spread calculation
- Real-time orderbook monitoring
- Live order placement

**Usage:**
```bash
# From project root
uv run examples/spread_strategy.py
```

**⚠️ Warning:** This places REAL orders with REAL money!

**Configuration:**
- Duration: 2 minutes (configurable)
- Check interval: 30 seconds
- Max exposure: $500

## Adding More Examples

Create new strategy files following this structure:

```python
from dotenv import load_dotenv
import dr_manhattan

load_dotenv()  # Loads .env from project root

exchange = dr_manhattan.Polymarket({
    'private_key': os.getenv('POLYMARKET_PRIVATE_KEY'),
    'funder': os.getenv('POLYMARKET_FUNDER'),
})

# Your strategy here...
```

## Resources

- [Polymarket Setup Guide](../wiki/exchanges/polymarket_setup.md)
- [Check Wallet Balance](../scripts/polymarket/check_approval.py)
