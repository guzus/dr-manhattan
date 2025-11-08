# Exchange Name

## Overview

- **Exchange ID**: `exchange_id`
- **Exchange Name**: Exchange Name
- **Type**: Prediction Market / Derivatives / Spot
- **Base Class**: [Exchange](../../dr_manhattan/base/exchange.py)
- **REST API**: `https://api.example.com`
- **WebSocket API**: `wss://ws.example.com` (if supported)
- **Documentation**: https://docs.example.com/

Brief description of the exchange and what it specializes in.

## Table of Contents

- [Features](#features)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Market Data](#market-data)
- [Trading](#trading)
- [Account](#account)
- [WebSocket](#websocket) (if supported)
- [Examples](#examples)

## Features

### Supported Methods

| Method | REST | WebSocket | Description |
|--------|------|-----------|-------------|
| `fetch_markets()` | ✅/❌ | ❌ | Fetch all available markets |
| `fetch_market()` | ✅/❌ | ❌ | Fetch a specific market by ID |
| `create_order()` | ✅/❌ | ❌ | Create a new order |
| `cancel_order()` | ✅/❌ | ❌ | Cancel an existing order |
| `fetch_order()` | ✅/❌ | ❌ | Fetch order details |
| `fetch_open_orders()` | ✅/❌ | ❌ | Fetch all open orders |
| `fetch_positions()` | ✅/❌ | ❌ | Fetch current positions |
| `fetch_balance()` | ✅/❌ | ❌ | Fetch account balance |
| `watch_orderbook()` | ❌ | ✅/❌ | Real-time orderbook updates |

### Exchange Capabilities

```python
exchange.describe()
# Returns:
{
    'id': 'exchange_id',
    'name': 'Exchange Name',
    'has': {
        'fetch_markets': True/False,
        'fetch_market': True/False,
        'create_order': True/False,
        'cancel_order': True/False,
        'fetch_order': True/False,
        'fetch_open_orders': True/False,
        'fetch_positions': True/False,
        'fetch_balance': True/False,
        'rate_limit': True/False,
        'retry_logic': True/False,
    }
}
```

## Authentication

Describe authentication methods supported by the exchange.

### 1. Public API (Read-Only)

```python
from dr_manhattan.exchanges.exchange_name import ExchangeName

exchange = ExchangeName()
markets = exchange.fetch_markets()
```

### 2. API Key Authentication

```python
exchange = ExchangeName({
    'api_key': 'your_api_key',
    'api_secret': 'your_api_secret',
    # Other auth parameters
})
```

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `api_key` | str | Yes* | API key |
| `api_secret` | str | Yes* | API secret |
| `verbose` | bool | No | Enable verbose logging |

*Required for private endpoints only

## Rate Limiting

Describe rate limiting policies.

- **Default Rate Limit**: X requests per second
- **Automatic Retry**: Yes/No
- **Max Retries**: X attempts

### Configuration

```python
exchange = ExchangeName({
    'rate_limit': 10,
    'max_retries': 3,
    'retry_delay': 1.0,
    'retry_backoff': 2.0,
    'timeout': 30
})
```

## Market Data

### fetch_markets()

Fetch all available markets.

```python
markets = exchange.fetch_markets(params={})
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `params` | dict | No | Exchange-specific parameters |

**Returns:** `list[Market]`

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

## Trading

### create_order()

Create a new order.

```python
from dr_manhattan.models.order import OrderSide

order = exchange.create_order(
    market_id='market_id',
    outcome='outcome',
    side=OrderSide.BUY,
    price=1.0,
    size=100.0,
    params={}
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market identifier |
| `outcome` | str | Yes | Outcome to bet on |
| `side` | OrderSide | Yes | BUY or SELL |
| `price` | float | Yes | Price per share |
| `size` | float | Yes | Number of shares |
| `params` | dict | No | Additional parameters |

**Returns:** `Order`

### cancel_order()

Cancel an existing order.

```python
order = exchange.cancel_order(
    order_id='order_id',
    market_id='market_id'
)
```

**Returns:** `Order`

### fetch_open_orders()

Fetch all open orders.

```python
orders = exchange.fetch_open_orders(
    market_id='market_id',
    params={}
)
```

**Returns:** `list[Order]`

## Account

### fetch_balance()

Fetch account balance.

```python
balance = exchange.fetch_balance()
```

**Returns:** `Dict[str, float]`

### fetch_positions()

Fetch current positions.

```python
positions = exchange.fetch_positions(
    market_id='market_id',
    params={}
)
```

**Returns:** `list[Position]`

## WebSocket

(Include this section only if WebSocket is supported)

### Getting Started

```python
import asyncio
from dr_manhattan.exchanges.exchange_name import ExchangeName

async def main():
    exchange = ExchangeName({'verbose': True})
    ws = exchange.get_websocket()

    def on_update(market_id, orderbook):
        print(f"Update: {market_id}")

    await ws.watch_orderbook('market_id', on_update)
    await ws._receive_loop()

asyncio.run(main())
```

### WebSocket Configuration

```python
ws = exchange.get_websocket()
```

### Orderbook Message Format

```python
{
    'market_id': str,
    'bids': [(price, size)],
    'asks': [(price, size)],
    'timestamp': int
}
```

## Examples

### Basic Usage

```python
from dr_manhattan.exchanges.exchange_name import ExchangeName

exchange = ExchangeName({'verbose': True})

# Fetch markets
markets = exchange.fetch_markets()
for market in markets:
    print(market.question)
```

### Trading Example

```python
from dr_manhattan.exchanges.exchange_name import ExchangeName
from dr_manhattan.models.order import OrderSide

exchange = ExchangeName({
    'api_key': 'your_api_key',
    'api_secret': 'your_api_secret'
})

# Create order
order = exchange.create_order(
    market_id='market_id',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.5,
    size=100.0
)

print(f"Order created: {order.id}")
```

### Error Handling

```python
from dr_manhattan.exchanges.exchange_name import ExchangeName
from dr_manhattan.base.errors import NetworkError, RateLimitError, MarketNotFound

exchange = ExchangeName()

try:
    market = exchange.fetch_market('market_id')
except MarketNotFound as e:
    print(f"Market not found: {e}")
except NetworkError as e:
    print(f"Network error: {e}")
except RateLimitError as e:
    print(f"Rate limited: {e}")
```

## Important Notes

- Add any exchange-specific notes
- Special requirements
- Known limitations
- Tips and best practices

## References

- [Exchange Documentation](https://docs.example.com/)
- [API Reference](https://docs.example.com/api)
- [Base Exchange Class](../../dr_manhattan/base/exchange.py)
- [Examples](../../examples/)

## See Also

- Other related exchanges
- Related documentation
- Helper utilities
