# dr-manhattan

CCXT-style unified API for prediction markets. Simple, scalable, and easy to extend.

## Architecture

`dr-manhattan` provides a unified interface to interact with multiple prediction market platforms, similar to how CCXT works for cryptocurrency exchanges.

### Core Components

```
dr_manhattan/
├── base/           # Core abstractions
│   ├── exchange.py # Abstract base class
│   └── errors.py   # Exception hierarchy
├── exchanges/      # Exchange implementations
│   ├── polymarket.py
│   └── limitless.py
├── models/         # Data models
│   ├── market.py
│   ├── order.py
│   └── position.py
└── utils/          # Utilities (future)
```

### Design Principles

1. **Unified Interface**: All exchanges implement the same `Exchange` base class
2. **Scalability**: Adding new exchanges is straightforward - just implement the abstract methods
3. **Simplicity**: Clean abstractions with minimal dependencies
4. **Type Safety**: Full type hints throughout

### Key Features

- Fetch markets and market data
- Create and cancel orders
- Query positions and balances
- Standardized error handling
- Exchange-agnostic code

## Installation

```bash
uv venv
uv pip install -e .
```

## Usage

### Basic Usage (Public API)

```python
import dr_manhattan

# Initialize exchange without authentication
polymarket = dr_manhattan.Polymarket({'timeout': 30})
limitless = dr_manhattan.Limitless({'timeout': 30})

# Fetch markets
markets = polymarket.fetch_markets()
for market in markets:
    print(f"{market.question}: {market.prices}")
```

### Advanced Usage (With Authentication)

The implementations use symbolic links to integrate with existing market maker implementations:

```python
import dr_manhattan

# Polymarket with poly-mm integration
polymarket = dr_manhattan.Polymarket({
    'private_key': 'your_private_key',
    'condition_id': 'condition_id',
    'yes_token_id': 'yes_token',
    'no_token_id': 'no_token',
    'dry_run': False
})

# Limitless with limitless-mm integration
limitless = dr_manhattan.Limitless({
    'private_key': 'your_private_key',
    'timeout': 30
})

# Create order
order = polymarket.create_order(
    market_id="market_123",
    outcome="Yes",
    side=dr_manhattan.OrderSide.BUY,
    price=0.65,
    size=100,
    params={'token_id': 'token_id'}
)

# Fetch balance
balance = polymarket.fetch_balance()
print(f"USDC: {balance['USDC']}")
```

### Unified API Pattern

```python
import dr_manhattan

# Works with any exchange
for exchange_id in dr_manhattan.exchanges:
    exchange = dr_manhattan.exchanges[exchange_id]()
    print(f"{exchange.name}: {exchange.id}")
```

## Adding New Exchanges

To add a new exchange, create a class that inherits from `Exchange`:

```python
from dr_manhattan.base import Exchange

class NewExchange(Exchange):
    @property
    def id(self) -> str:
        return "newexchange"

    @property
    def name(self) -> str:
        return "New Exchange"

    def fetch_markets(self, params=None):
        # Implement API call
        pass

    # Implement other abstract methods...
```

Register in `dr_manhattan/__init__.py`:

```python
from .exchanges.newexchange import NewExchange

exchanges = {
    "polymarket": Polymarket,
    "limitless": Limitless,
    "newexchange": NewExchange,
}
```

### Using Symbolic Links

The implementations leverage existing market maker codebases through symbolic links:

1. **poly-mm**: Full Polymarket market maker implementation
2. **limitless-mm**: Full Limitless market maker implementation

When initialized with authentication credentials, the exchange classes use these implementations directly, providing access to production-ready trading functionality.

## Data Models

### Market
- Question and outcomes
- Prices and volume
- Close time and status

### Order
- Market and outcome
- Side (buy/sell), price, size
- Status tracking

### Position
- Current holdings
- PnL calculation
- Average entry price

## Error Handling

All errors inherit from `DrManhattanError`:
- `ExchangeError` - Exchange-specific errors
- `NetworkError` - Connectivity issues
- `AuthenticationError` - Auth failures
- `InvalidOrder` - Invalid order parameters
- `MarketNotFound` - Market doesn't exist

## Examples

Check out the [examples/](examples/) directory for working examples:

- **spread_strategy.py** - Arbitrage trading strategy for binary markets
- **simple_test.py** - Basic market data fetching
- **test_strategy.py** - Strategy testing framework

Run an example:

```bash
uv run python examples/spread_strategy.py
```

See [examples/README.md](examples/README.md) for detailed documentation.

## Dependencies

- Python >= 3.10
- requests >= 2.31.0

Development:
- pytest
- black
- ruff
