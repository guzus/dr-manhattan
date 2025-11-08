# Dr. Manhattan Wiki

Documentation for the Dr. Manhattan prediction market trading library.

## Exchanges

Exchange-specific documentation:

- [Polymarket](exchanges/polymarket.md) - Decentralized prediction market on Polygon
- [Template](exchanges/TEMPLATE.md) - Template for creating new exchange documentation

## Core Concepts

### Exchange

The base `Exchange` class provides a unified API for interacting with different prediction market platforms, following the CCXT-style pattern.

#### Common Methods

All exchanges implement these core methods:

| Method | Description |
|--------|-------------|
| `fetch_markets()` | Retrieve all available markets |
| `fetch_market(id)` | Get details for a specific market |
| `create_order()` | Place a new order |
| `cancel_order()` | Cancel an existing order |
| `fetch_order()` | Get order status |
| `fetch_open_orders()` | List all open orders |
| `fetch_positions()` | Get current positions |
| `fetch_balance()` | Check account balance |

### Models

#### Market

Represents a prediction market:

```python
Market(
    id: str,                    # Unique identifier
    question: str,              # Market question
    outcomes: list[str],        # Possible outcomes
    close_time: datetime,       # Market close time
    volume: float,              # Trading volume
    liquidity: float,           # Available liquidity
    prices: Dict[str, float],   # Current prices by outcome
    metadata: dict              # Exchange-specific data
)
```

#### Order

Represents a trading order:

```python
Order(
    id: str,                    # Order ID
    market_id: str,             # Market identifier
    outcome: str,               # Outcome being traded
    side: OrderSide,            # BUY or SELL
    price: float,               # Price per share
    size: float,                # Number of shares
    filled: float,              # Filled amount
    status: OrderStatus,        # Order status
    created_at: datetime,       # Creation time
    updated_at: datetime        # Last update time
)
```

#### Position

Represents a market position:

```python
Position(
    market_id: str,             # Market identifier
    outcome: str,               # Outcome held
    size: float,                # Position size
    average_price: float,       # Average entry price
    current_price: float        # Current market price
)
```

## WebSocket Streaming

Real-time orderbook updates via WebSocket:

### Base WebSocket Class

`OrderBookWebSocket` provides interrupt-driven orderbook streaming:

- Auto-reconnection with exponential backoff
- Multi-market subscriptions
- State management
- Async/sync callback support

### Usage Pattern

```python
import asyncio

async def main():
    exchange = SomeExchange({'verbose': True})
    ws = exchange.get_websocket()

    def on_update(market_id, orderbook):
        bids = orderbook['bids']
        asks = orderbook['asks']
        print(f"Best bid: {bids[0][0]}, Best ask: {asks[0][0]}")

    await ws.watch_orderbook('market_id', on_update)
    await ws._receive_loop()

asyncio.run(main())
```

## Configuration

### Exchange Configuration

All exchanges accept a configuration dictionary:

```python
exchange = Exchange({
    # Authentication
    'api_key': 'your_api_key',
    'api_secret': 'your_api_secret',
    'private_key': 'ethereum_private_key',  # For blockchain-based exchanges

    # Rate Limiting
    'rate_limit': 10,           # Requests per second
    'max_retries': 3,           # Retry attempts
    'retry_delay': 1.0,         # Base retry delay (seconds)
    'retry_backoff': 2.0,       # Exponential backoff multiplier

    # Other
    'timeout': 30,              # Request timeout (seconds)
    'verbose': False,           # Enable debug logging
    'dry_run': False            # Dry-run mode (no real trades)
})
```

### WebSocket Configuration

```python
ws = exchange.get_websocket()
# Or with custom settings:
ws = OrderBookWebSocket({
    'verbose': True,
    'auto_reconnect': True,
    'max_reconnect_attempts': 10,
    'reconnect_delay': 5.0
})
```

## Error Handling

The library defines several exception types:

| Exception | Description |
|-----------|-------------|
| `ExchangeError` | Base exchange error |
| `NetworkError` | Network-related errors |
| `RateLimitError` | Rate limit exceeded |
| `MarketNotFound` | Market does not exist |

Example:

```python
from dr_manhattan.base.errors import MarketNotFound, RateLimitError

try:
    market = exchange.fetch_market('invalid_id')
except MarketNotFound:
    print("Market not found")
except RateLimitError:
    print("Rate limited - wait and retry")
```

## Examples

Check the [examples/](../examples/) directory for:

- Basic market fetching
- Order placement and management
- WebSocket streaming
- Position tracking
- Multi-exchange usage

## Architecture

```
dr_manhattan/
├── base/
│   ├── exchange.py         # Base exchange class
│   ├── websocket.py        # Base WebSocket class
│   └── errors.py           # Exception definitions
├── exchanges/
│   ├── polymarket.py       # Polymarket implementation
│   └── polymarket_ws.py    # Polymarket WebSocket
├── models/
│   ├── market.py           # Market model
│   ├── order.py            # Order model
│   └── position.py         # Position model
└── strategies/             # Trading strategies
```

## Development

### Adding a New Exchange

1. Create `dr_manhattan/exchanges/your_exchange.py`
2. Inherit from `Exchange` base class
3. Implement required methods
4. Add WebSocket support (optional)
5. Create documentation in `wiki/exchanges/your_exchange.md`
6. Add examples in `examples/`

Use [TEMPLATE.md](exchanges/TEMPLATE.md) as a guide.

### Testing

```bash
# Run all tests
uv run pytest

# Test specific exchange
uv run pytest tests/test_polymarket.py

# Test WebSocket
uv run python examples/test_polymarket_ws.py
```

## Resources

- [GitHub Repository](https://github.com/guzus/dr-manhattan)
- [Polymarket Docs](https://docs.polymarket.com/)

## Contributing

Contributions welcome! Please:

1. Follow the existing code style
2. Add tests for new features
3. Update documentation
4. Follow the template for new exchanges

## License

See [LICENSE](../LICENSE) for details.
