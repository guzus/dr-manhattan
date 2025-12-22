# dr-manhattan

CCXT-style unified API for prediction markets. Simple, scalable, and easy to extend.


<p align="center">
  <img src="assets/polymarket.png" alt="Polymarket" width="50"/>
  <img src="assets/kalshi.jpeg" alt="Kalshi" width="50"/>
  <img src="assets/opinion.jpg" alt="Opinion" width="50"/>
  <img src="assets/limitless.jpg" alt="Limitless" width="50"/>
</p>

## Architecture

`dr-manhattan` provides a unified interface to interact with multiple prediction market platforms, similar to how CCXT works for cryptocurrency exchanges.

### Core Components

```
dr_manhattan/
├── base/               # Core abstractions
│   ├── exchange.py     # Abstract base class for exchanges
│   ├── exchange_client.py  # High-level trading client
│   ├── exchange_factory.py # Exchange instantiation
│   ├── strategy.py     # Strategy base class
│   ├── order_tracker.py    # Order event tracking
│   ├── websocket.py    # WebSocket base class
│   └── errors.py       # Exception hierarchy
├── exchanges/          # Exchange implementations
│   ├── polymarket.py
│   ├── polymarket_ws.py
│   ├── opinion.py
│   ├── limitless.py
│   └── limitless_ws.py
├── models/             # Data models
│   ├── market.py
│   ├── order.py
│   ├── orderbook.py
│   └── position.py
├── strategies/         # Strategy implementations
└── utils/              # Utilities
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
- WebSocket support for real-time data
- Strategy base class for building trading strategies
- Order tracking and event logging
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
opinion = dr_manhattan.Opinion({'timeout': 30})
limitless = dr_manhattan.Limitless({'timeout': 30})

# Fetch markets
markets = polymarket.fetch_markets()
for market in markets:
    print(f"{market.question}: {market.prices}")
```

### Advanced Usage (With Authentication)

```python
import dr_manhattan

# Polymarket
polymarket = dr_manhattan.Polymarket({
    'private_key': 'your_private_key',
    'funder': 'your_funder_address',
})

# Opinion (BNB Chain)
opinion = dr_manhattan.Opinion({
    'api_key': 'your_api_key',
    'private_key': 'your_private_key',
    'multi_sig_addr': 'your_multi_sig_addr'
})

# Limitless
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

### Using the Strategy Base Class

```python
from dr_manhattan import Strategy

class MyStrategy(Strategy):
    def on_tick(self):
        self.log_status()
        self.place_bbo_orders()

strategy = MyStrategy(exchange, market_id="123")
strategy.run()
```

### Exchange Factory

```python
from dr_manhattan import create_exchange, list_exchanges

# List available exchanges
print(list_exchanges())  # ['polymarket', 'limitless', 'opinion']

# Create exchange by name
exchange = create_exchange('polymarket', {'timeout': 30})
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
    "opinion": Opinion,
    "limitless": Limitless,
    "newexchange": NewExchange,
}
```

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

### OrderBook
- Bids and asks
- Best bid/ask prices

## Error Handling

All errors inherit from `DrManhattanError`:
- `ExchangeError` - Exchange-specific errors
- `NetworkError` - Connectivity issues
- `RateLimitError` - Rate limit exceeded
- `AuthenticationError` - Auth failures
- `InsufficientFunds` - Not enough balance
- `InvalidOrder` - Invalid order parameters
- `MarketNotFound` - Market doesn't exist

## Examples

Check out the [examples/](examples/) directory for working examples:

- **list_all_markets.py** - List markets from any exchange
- **spread_strategy.py** - Exchange-agnostic BBO market making strategy

Run examples:

```bash
# List markets
uv run python examples/list_all_markets.py polymarket
uv run python examples/list_all_markets.py opinion
uv run python examples/list_all_markets.py limitless

# Run spread strategy
uv run python examples/spread_strategy.py --exchange polymarket --slug fed-decision
uv run python examples/spread_strategy.py --exchange opinion --market-id 813
```

See [examples/README.md](examples/README.md) for detailed documentation.

## Dependencies

- Python >= 3.11
- requests >= 2.31.0
- websockets >= 15.0.1
- python-socketio >= 5.11.0
- eth-account >= 0.11.0
- py-clob-client >= 0.28.0
- opinion-clob-sdk >= 0.4.3
- pandas >= 2.0.0

Development:
- pytest
- black
- ruff
