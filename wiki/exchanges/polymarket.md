# Polymarket

## Overview

- **Exchange ID**: `polymarket`
- **Exchange Name**: Polymarket
- **Type**: Prediction Market
- **Base Class**: [Exchange](../../two_face/base/exchange.py)
- **REST API**: `https://gamma-api.polymarket.com`
- **WebSocket API**: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- **Documentation**: https://docs.polymarket.com/

Polymarket is a decentralized prediction market platform built on Polygon. Users can trade on the outcome of real-world events.

## Table of Contents

- [Features](#features)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Market Data](#market-data)
- [Trading](#trading)
- [Account](#account)
- [WebSocket](#websocket)
- [Examples](#examples)

## Features

### Supported Methods

| Method | REST | WebSocket | Description |
|--------|------|-----------|-------------|
| `fetch_markets()` | ✅ | ❌ | Fetch all available markets |
| `fetch_market()` | ✅ | ❌ | Fetch a specific market by ID |
| `create_order()` | ✅ | ❌ | Create a new order |
| `cancel_order()` | ✅ | ❌ | Cancel an existing order |
| `fetch_order()` | ✅ | ❌ | Fetch order details |
| `fetch_open_orders()` | ✅ | ❌ | Fetch all open orders |
| `fetch_positions()` | ✅ | ❌ | Fetch current positions |
| `fetch_balance()` | ✅ | ❌ | Fetch account balance |
| `watch_orderbook()` | ❌ | ✅ | Real-time orderbook updates |

### Exchange Capabilities

```python
exchange.describe()
# Returns:
{
    'id': 'polymarket',
    'name': 'Polymarket',
    'has': {
        'fetch_markets': True,
        'fetch_market': True,
        'create_order': True,
        'cancel_order': True,
        'fetch_order': True,
        'fetch_open_orders': True,
        'fetch_positions': True,
        'fetch_balance': True,
        'rate_limit': True,
        'retry_logic': True,
    }
}
```

## Authentication

Polymarket supports two authentication methods:

### 1. Public API (Read-Only)

No authentication required for market data:

```python
from two_face.exchanges.polymarket import Polymarket

exchange = Polymarket()
markets = exchange.fetch_markets()
```

### 2. Private Key Authentication (Trading)

For trading operations, provide a private key:

```python
exchange = Polymarket({
    'private_key': 'your_private_key_here',
    'condition_id': 'market_condition_id',
    'yes_token_id': 'yes_token_id',
    'no_token_id': 'no_token_id',
    'dry_run': False  # Set True for testing
})
```

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `private_key` | str | Yes* | Ethereum private key for signing transactions |
| `condition_id` | str | No | Market condition ID |
| `yes_token_id` | str | No | YES outcome token ID |
| `no_token_id` | str | No | NO outcome token ID |
| `dry_run` | bool | No | Enable dry-run mode (default: False) |
| `verbose` | bool | No | Enable verbose logging (default: False) |

*Required for trading operations only

## Rate Limiting

Polymarket implements rate limiting to prevent abuse:

- **Default Rate Limit**: 10 requests per second
- **Automatic Retry**: Built-in retry logic with exponential backoff
- **Max Retries**: 3 attempts (configurable)

### Configuration

```python
exchange = Polymarket({
    'rate_limit': 10,        # requests per second
    'max_retries': 3,        # retry attempts
    'retry_delay': 1.0,      # base delay in seconds
    'retry_backoff': 2.0,    # exponential backoff multiplier
    'timeout': 30            # request timeout in seconds
})
```

## Market Data

### fetch_markets()

Fetch all available markets.

```python
markets = exchange.fetch_markets(params={
    'active': True,   # Only active markets
    'closed': False,  # Exclude closed markets
    'limit': 100      # Limit results
})
```

**Returns:** `list[Market]`

**Market Object:**
```python
Market(
    id='market_id',
    question='Will X happen?',
    outcomes=['Yes', 'No'],
    close_time=datetime,
    volume=1000000.0,
    liquidity=500000.0,
    prices={'Yes': 0.52, 'No': 0.48},
    metadata={}
)
```

### fetch_market()

Fetch a specific market by ID.

```python
market = exchange.fetch_market('market_id')
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market identifier |

**Returns:** `Market`

**Raises:**
- `MarketNotFound` - Market does not exist

## Trading

### create_order()

Create a new order.

```python
from two_face.models.order import OrderSide

order = exchange.create_order(
    market_id='market_id',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.52,
    size=100.0,
    params={'token_id': 'token_id'}
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market identifier |
| `outcome` | str | Yes | Outcome to bet on |
| `side` | OrderSide | Yes | BUY or SELL |
| `price` | float | Yes | Price per share (0-1) |
| `size` | float | Yes | Number of shares |
| `params` | dict | No | Additional parameters |

**Returns:** `Order`

### cancel_order()

Cancel an existing order.

```python
order = exchange.cancel_order(
    order_id='order_id',
    market_id='market_id'  # Optional for some exchanges
)
```

**Returns:** `Order`

### fetch_open_orders()

Fetch all open orders.

```python
orders = exchange.fetch_open_orders(
    market_id='market_id',  # Optional: filter by market
    params={}
)
```

**Returns:** `list[Order]`

## Account

### fetch_balance()

Fetch account balance.

```python
balance = exchange.fetch_balance()
# Returns: {'USDC': 1000.0}
```

**Returns:** `Dict[str, float]` - Currency to balance mapping

### fetch_positions()

Fetch current positions.

```python
positions = exchange.fetch_positions(
    market_id='market_id',  # Optional: filter by market
    params={}
)
```

**Returns:** `list[Position]`

**Position Object:**
```python
Position(
    market_id='market_id',
    outcome='Yes',
    size=100.0,
    average_price=0.52,
    current_price=0.55
)
```

## WebSocket

Polymarket supports real-time orderbook updates via WebSocket.

### Getting Started

```python
import asyncio
from two_face.exchanges.polymarket import Polymarket

async def main():
    exchange = Polymarket({'verbose': True})
    ws = exchange.get_websocket()

    def on_update(asset_id, orderbook):
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        if bids and asks:
            print(f"Best Bid: {bids[0][0]:.4f}")
            print(f"Best Ask: {asks[0][0]:.4f}")

    # Subscribe to asset (token ID)
    asset_id = "token_id_here"
    await ws.watch_orderbook(asset_id, on_update)
    await ws._receive_loop()

asyncio.run(main())
```

### WebSocket Configuration

```python
ws = exchange.get_websocket()
# Or with custom config:
from two_face.exchanges.polymarket_ws import PolymarketWebSocket

ws = PolymarketWebSocket({
    'verbose': True,
    'auto_reconnect': True,
    'max_reconnect_attempts': 10,
    'reconnect_delay': 5.0
})
```

### Orderbook Message Format

```python
{
    'market_id': str,           # Market condition ID
    'asset_id': str,            # Token ID
    'bids': [(price, size)],    # Sorted descending
    'asks': [(price, size)],    # Sorted ascending
    'timestamp': int,           # Unix timestamp (ms)
    'hash': str                 # Orderbook hash
}
```

### WebSocket Methods

#### watch_orderbook()

Subscribe to orderbook updates for an asset.

```python
await ws.watch_orderbook(asset_id, callback)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `asset_id` | str | Yes | Token ID to watch |
| `callback` | function | Yes | Callback for updates |

#### watch_orderbook_by_market()

Subscribe to multiple assets in a market.

```python
await ws.watch_orderbook_by_market(
    market_id='condition_id',
    asset_ids=['token_id_1', 'token_id_2'],
    callback=on_update
)
```

### Background Thread Usage

For synchronous code:

```python
exchange = Polymarket({'verbose': True})
ws = exchange.get_websocket()

def on_update(asset_id, orderbook):
    print(f"Update: {asset_id}")

# Start in background
ws.start()

# Subscribe
import asyncio
loop = asyncio.new_event_loop()
loop.run_until_complete(ws.watch_orderbook(asset_id, on_update))

# Keep running
try:
    while True:
        import time
        time.sleep(1)
except KeyboardInterrupt:
    ws.stop()
```

## Examples

### Basic Market Fetching

```python
from two_face.exchanges.polymarket import Polymarket

exchange = Polymarket({'verbose': True})

# Fetch active markets
markets = exchange.fetch_markets({'active': True, 'limit': 10})

for market in markets:
    print(f"{market.question}")
    print(f"  Volume: ${market.volume:,.2f}")
    print(f"  Prices: {market.prices}")
```

### Trading Example

```python
from two_face.exchanges.polymarket import Polymarket
from two_face.models.order import OrderSide

exchange = Polymarket({
    'private_key': 'your_private_key',
    'verbose': True
})

# Create a buy order
order = exchange.create_order(
    market_id='market_id',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.52,
    size=100.0,
    params={'token_id': 'token_id'}
)

print(f"Order created: {order.id}")

# Check open orders
open_orders = exchange.fetch_open_orders()
print(f"Open orders: {len(open_orders)}")

# Cancel order
cancelled = exchange.cancel_order(order.id)
print(f"Order cancelled: {cancelled.status}")
```

### WebSocket Streaming

```python
import asyncio
from two_face.exchanges.polymarket import Polymarket

async def stream_orderbook():
    exchange = Polymarket({'verbose': True})
    ws = exchange.get_websocket()

    update_count = 0

    def on_update(asset_id, orderbook):
        nonlocal update_count
        update_count += 1

        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if bids and asks:
            spread = asks[0][0] - bids[0][0]
            print(f"Update #{update_count}")
            print(f"  Bid: {bids[0][0]:.4f} ({bids[0][1]:.2f})")
            print(f"  Ask: {asks[0][0]:.4f} ({asks[0][1]:.2f})")
            print(f"  Spread: {spread:.4f}")

    asset_id = "your_token_id"

    await ws.connect()
    await ws.watch_orderbook(asset_id, on_update)

    try:
        await ws._receive_loop()
    except KeyboardInterrupt:
        await ws.disconnect()

asyncio.run(stream_orderbook())
```

### Error Handling

```python
from two_face.exchanges.polymarket import Polymarket
from two_face.base.errors import NetworkError, RateLimitError, MarketNotFound

exchange = Polymarket({'verbose': True})

try:
    market = exchange.fetch_market('invalid_id')
except MarketNotFound as e:
    print(f"Market not found: {e}")
except NetworkError as e:
    print(f"Network error: {e}")
except RateLimitError as e:
    print(f"Rate limited: {e}")
```

## Important Notes

### Token IDs for WebSocket

The Gamma API does not provide token IDs needed for WebSocket subscriptions. To get token IDs:

1. Use the CLOB API (`https://clob.polymarket.com`)
2. Calculate from condition_id using CTF utils
3. Extract from market transactions

### Market Types

- **Binary Markets**: Two outcomes (Yes/No)
- **Categorical Markets**: Multiple outcomes
- **Scalar Markets**: Range of outcomes

### Price Format

Prices are represented as decimals between 0 and 1:
- `0.52` = 52% probability
- `1.00` = 100% probability (certain)

### Fees

Polymarket charges fees on trades. Check the platform documentation for current fee structure.

## References

- [Polymarket Documentation](https://docs.polymarket.com/)
- [CLOB API Docs](https://docs.polymarket.com/developers/CLOB/)
- [WebSocket API](https://docs.polymarket.com/developers/CLOB/websocket/)
- [CTF Utils](https://github.com/Polymarket/ctf-utils)
- [Official Python Client](https://github.com/Polymarket/py-clob-client)

## See Also

- [Base Exchange Class](../../two_face/base/exchange.py)
- [WebSocket Implementation](../../two_face/base/websocket.py)
- [Polymarket WebSocket](../../two_face/exchanges/polymarket_ws.py)
- [Examples](../../examples/)
