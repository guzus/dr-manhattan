# Two-Face

CCXT-style unified API for prediction markets. Simple, scalable, and easy to extend.

## Architecture

Two-Face provides a unified interface to interact with multiple prediction market platforms, similar to how CCXT works for cryptocurrency exchanges.

### Core Components

```
two_face/
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

Symbolic Links:
├── poly-mm/        -> /path/to/poly-mm
└── limitless-mm/   -> /path/to/limitless-mm
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
import two_face

# Initialize exchange without authentication
polymarket = two_face.Polymarket({'timeout': 30})
limitless = two_face.Limitless({'timeout': 30})

# Fetch markets
markets = polymarket.fetch_markets()
for market in markets:
    print(f"{market.question}: {market.prices}")
```

### Advanced Usage (With Authentication)

The implementations use symbolic links to integrate with existing market maker implementations:

```python
import two_face

# Polymarket with poly-mm integration
polymarket = two_face.Polymarket({
    'private_key': 'your_private_key',
    'condition_id': 'condition_id',
    'yes_token_id': 'yes_token',
    'no_token_id': 'no_token',
    'dry_run': False
})

# Limitless with limitless-mm integration
limitless = two_face.Limitless({
    'private_key': 'your_private_key',
    'timeout': 30
})

# Create order
order = polymarket.create_order(
    market_id="market_123",
    outcome="Yes",
    side=two_face.OrderSide.BUY,
    price=0.65,
    size=100,
    params={'token_id': 'token_id'}
)

# Fetch balance
balance = polymarket.fetch_balance()
print(f"USDC: {balance['USDC']}")
```

### Builder Profile (Order Attribution)

Polymarket's Builder Profile allows you to attribute orders to your builder account for tracking and analytics:

```python
import two_face

# Initialize with builder credentials
polymarket = two_face.Polymarket({
    'private_key': 'your_private_key',
    'builder_api_key': 'your_builder_api_key',
    'builder_secret': 'your_builder_secret',
    'builder_passphrase': 'your_builder_passphrase',
    'timeout': 30
})

# All orders will now be attributed to your builder profile
order = polymarket.create_order(
    market_id="market_123",
    outcome="Yes",
    side=two_face.OrderSide.BUY,
    price=0.65,
    size=100,
    params={'token_id': 'token_id'}
)
```

To get your builder credentials:
1. Visit the Polymarket Builder Portal
2. Create a builder profile
3. Generate API keys (key, secret, passphrase)

### Unified API Pattern

```python
import two_face

# Works with any exchange
for exchange_id in two_face.exchanges:
    exchange = two_face.exchanges[exchange_id]()
    print(f"{exchange.name}: {exchange.id}")
```

## Adding New Exchanges

To add a new exchange, create a class that inherits from `Exchange`:

```python
from two_face.base import Exchange

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

Register in `two_face/__init__.py`:

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

All errors inherit from `TwoFaceError`:
- `ExchangeError` - Exchange-specific errors
- `NetworkError` - Connectivity issues
- `AuthenticationError` - Auth failures
- `InvalidOrder` - Invalid order parameters
- `MarketNotFound` - Market doesn't exist

## Example

Run the included example:

```bash
uv run python example.py
```

The example demonstrates:
- Connecting to both Polymarket and Limitless
- Fetching market data
- Unified API pattern
- Exchange capabilities

## Dependencies

- Python >= 3.10
- requests >= 2.31.0

Development:
- pytest
- black
- ruff
