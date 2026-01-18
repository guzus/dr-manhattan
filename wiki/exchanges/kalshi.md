# Kalshi

## Overview

- **Exchange ID**: `kalshi`
- **Exchange Name**: Kalshi
- **Type**: Prediction Market (CFTC-regulated)
- **Base Class**: [Exchange](../../dr_manhattan/base/exchange.py)
- **REST API**: `https://api.elections.kalshi.com/trade-api/v2`
- **Demo API**: `https://demo-api.kalshi.co/trade-api/v2`
- **WebSocket API**: `wss://api.elections.kalshi.com`
- **Documentation**: https://docs.kalshi.com/

Kalshi is the first CFTC-regulated prediction market exchange in the United States. It offers binary event contracts on various topics including politics, economics, and current events. Prices are quoted in cents (1-99) and converted to decimals (0.01-0.99) in the SDK.

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
| `fetch_markets()` | Yes | No | Fetch all available markets |
| `fetch_market()` | Yes | No | Fetch a specific market by ticker |
| `fetch_markets_by_slug()` | Yes | No | Fetch markets by event ticker |
| `create_order()` | Yes | No | Create a new order |
| `cancel_order()` | Yes | No | Cancel an existing order |
| `fetch_order()` | Yes | No | Fetch order details |
| `fetch_open_orders()` | Yes | No | Fetch all open orders |
| `fetch_positions()` | Yes | No | Fetch current positions |
| `fetch_balance()` | Yes | No | Fetch account balance |
| `get_orderbook()` | Yes | No | Fetch orderbook for a market |
| `watch_orderbook()` | No | No | Real-time orderbook updates (not implemented) |

### Order Types

Kalshi supports three time-in-force options:

| Type | API Value | Description |
|------|-----------|-------------|
| GTC | `good_till_canceled` | Remains active until filled or cancelled |
| FOK | `fill_or_kill` | Must be completely filled immediately or cancelled |
| IOC | `immediate_or_cancel` | Fills what it can immediately, cancels rest |

### Exchange Capabilities

```python
exchange.describe()
# Returns:
{
    'id': 'kalshi',
    'name': 'Kalshi',
    'demo': False,
    'api_url': 'https://api.elections.kalshi.com/trade-api/v2',
    'has': {
        'fetch_markets': True,
        'fetch_market': True,
        'fetch_markets_by_slug': True,
        'create_order': True,
        'cancel_order': True,
        'fetch_order': True,
        'fetch_open_orders': True,
        'fetch_positions': True,
        'fetch_balance': True,
        'get_orderbook': True,
        'get_websocket': False,
        'get_user_websocket': False,
    }
}
```

## Authentication

Kalshi uses RSA-PSS with SHA256 signature authentication. You need an API key ID and a private key.

### 1. Public API (Read-Only)

```python
from dr_manhattan.exchanges.kalshi import Kalshi

exchange = Kalshi()
markets = exchange.fetch_markets()
```

### 2. API Key Authentication

```python
exchange = Kalshi({
    'api_key_id': 'your_api_key_id',
    'private_key_path': '/path/to/private_key.pem',
    # OR
    'private_key_pem': '-----BEGIN RSA PRIVATE KEY-----\n...',
    'demo': False,  # Set to True for demo environment
})
```

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `api_key_id` | str | Yes* | API key identifier |
| `private_key_path` | str | Yes* | Path to RSA private key PEM file |
| `private_key_pem` | str | Yes* | RSA private key as PEM string (alternative to path) |
| `demo` | bool | No | Use demo environment (default: False) |
| `api_url` | str | No | Override API URL |
| `verbose` | bool | No | Enable verbose logging |

*Required for private endpoints only. Either `private_key_path` or `private_key_pem` is required.

### Generating API Keys

1. Log into Kalshi and navigate to Settings > API Keys
2. Generate a new RSA key pair
3. Download the private key and save it securely
4. Note the API Key ID provided

## Rate Limiting

- **Default Rate Limit**: Varies by endpoint
- **Automatic Retry**: Yes
- **Max Retries**: Configurable

### Configuration

```python
exchange = Kalshi({
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
markets = exchange.fetch_markets(params={'limit': 100, 'active': True})
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `params.limit` | int | No | Maximum markets to return (max 200) |
| `params.active` | bool | No | Only fetch active/open markets (default: True) |

**Returns:** `list[Market]`

### fetch_market()

Fetch a specific market by ticker.

```python
market = exchange.fetch_market('KXBTC-24DEC31-T100000')
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market ticker |

**Returns:** `Market`

### fetch_markets_by_slug()

Fetch markets by event ticker.

```python
markets = exchange.fetch_markets_by_slug('KXPRESIDENTIAL')
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `slug_or_url` | str | Yes | Event ticker |

**Returns:** `list[Market]`

### get_orderbook()

Fetch orderbook for a market.

```python
orderbook = exchange.get_orderbook('KXBTC-24DEC31-T100000')
# Returns: {'bids': [{'price': '0.45', 'size': '100'}], 'asks': [...]}
```

**Returns:** `dict` with `bids` and `asks` lists

### fetch_orderbook()

Fetch orderbook as Orderbook model.

```python
from dr_manhattan.models.orderbook import Orderbook

orderbook = exchange.fetch_orderbook('KXBTC-24DEC31-T100000')
# Returns: Orderbook(market_id=..., bids=[(0.45, 100), ...], asks=[...])
```

**Returns:** `Orderbook`

## Trading

### create_order()

Create a new order.

```python
from dr_manhattan.models.order import OrderSide, OrderTimeInForce

order = exchange.create_order(
    market_id='KXBTC-24DEC31-T100000',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.45,
    size=100,
    time_in_force=OrderTimeInForce.GTC
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market ticker |
| `outcome` | str | Yes | 'Yes' or 'No' |
| `side` | OrderSide | Yes | BUY or SELL |
| `price` | float | Yes | Price per contract (0-1) |
| `size` | float | Yes | Number of contracts |
| `time_in_force` | OrderTimeInForce | No | GTC, FOK, or IOC (default: GTC) |
| `params` | dict | No | Additional parameters |

**Returns:** `Order`

### cancel_order()

Cancel an existing order.

```python
order = exchange.cancel_order(order_id='order_id_123')
```

**Returns:** `Order`

### fetch_order()

Fetch order details.

```python
order = exchange.fetch_order(order_id='order_id_123')
```

**Returns:** `Order`

### fetch_open_orders()

Fetch all open orders.

```python
orders = exchange.fetch_open_orders(market_id='KXBTC-24DEC31-T100000')
```

**Returns:** `list[Order]`

## Account

### fetch_balance()

Fetch account balance.

```python
balance = exchange.fetch_balance()
# Returns: {'USD': 1234.56}
```

**Returns:** `Dict[str, float]`

Note: Balance is returned in dollars. The API returns cents which are converted.

### fetch_positions()

Fetch current positions.

```python
positions = exchange.fetch_positions(market_id='KXBTC-24DEC31-T100000')
```

**Returns:** `list[Position]`

## WebSocket

Kalshi provides WebSocket connections for real-time data.

### WebSocket URL

- Production: `wss://api.elections.kalshi.com`
- Demo: `wss://demo-api.kalshi.co`

### Authentication

API key authentication is required during the WebSocket handshake.

### Available Channels

| Channel | Description |
|---------|-------------|
| `orderbook_delta` | Orderbook updates with full refresh + deltas |
| `ticker` | Market ticker updates (price, volume) |
| `trade` | Recent trades |
| `fill` | User's order fills (authenticated) |
| `market_positions` | User's position updates (authenticated) |
| `market_lifecycle_v2` | Market status changes |
| `multivariate` | Multi-outcome market updates |
| `communications` | System announcements |

### Commands

**Subscribe:**
```json
{
  "id": 1,
  "cmd": "subscribe",
  "params": {
    "channels": ["orderbook_delta"],
    "market_ticker": "CPI-22DEC-TN0.1"
  }
}
```

**Unsubscribe:**
```json
{
  "id": 124,
  "cmd": "unsubscribe",
  "params": {
    "sids": [1, 2]
  }
}
```

Note: WebSocket is not yet implemented in dr_manhattan for Kalshi. Use the REST API for now.

## Examples

### Basic Usage

```python
from dr_manhattan.exchanges.kalshi import Kalshi

exchange = Kalshi({'verbose': True})

# Fetch markets
markets = exchange.fetch_markets()
for market in markets[:5]:
    print(f"{market.id}: {market.question}")
    print(f"  Prices: Yes={market.prices.get('Yes'):.2f}, No={market.prices.get('No'):.2f}")
```

### Trading Example

```python
from dr_manhattan.exchanges.kalshi import Kalshi
from dr_manhattan.models.order import OrderSide, OrderTimeInForce

exchange = Kalshi({
    'api_key_id': 'your_api_key_id',
    'private_key_path': '/path/to/private_key.pem'
})

# Check balance
balance = exchange.fetch_balance()
print(f"Balance: ${balance['USD']:.2f}")

# Create order
order = exchange.create_order(
    market_id='KXBTC-24DEC31-T100000',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.45,
    size=10,
    time_in_force=OrderTimeInForce.GTC
)

print(f"Order created: {order.id}")

# Check positions
positions = exchange.fetch_positions()
for pos in positions:
    print(f"{pos.market_id}: {pos.outcome} x {pos.size}")
```

### Error Handling

```python
from dr_manhattan.exchanges.kalshi import Kalshi
from dr_manhattan.base.errors import (
    AuthenticationError,
    InvalidOrder,
    MarketNotFound,
    NetworkError,
    RateLimitError
)

exchange = Kalshi({
    'api_key_id': 'your_api_key_id',
    'private_key_path': '/path/to/private_key.pem'
})

try:
    market = exchange.fetch_market('INVALID-TICKER')
except MarketNotFound as e:
    print(f"Market not found: {e}")
except AuthenticationError as e:
    print(f"Authentication failed: {e}")
except NetworkError as e:
    print(f"Network error: {e}")
except RateLimitError as e:
    print(f"Rate limited: {e}")
```

### Demo Environment

```python
# Use demo environment for testing
exchange = Kalshi({
    'demo': True,
    'api_key_id': 'demo_api_key_id',
    'private_key_path': '/path/to/demo_private_key.pem'
})
```

## Important Notes

- Kalshi is only available to US residents and requires identity verification
- Prices are internally in cents (1-99) but the SDK converts to decimals (0.01-0.99)
- Market tickers follow format: `KXEVENT-YYMMMDD-TPRICE` (e.g., `KXBTC-24DEC31-T100000`)
- Maximum 200,000 open orders per user
- Batch operations support max 20 orders per request
- The `cryptography` package is required for authentication

## References

- [Kalshi API Documentation](https://docs.kalshi.com/api-reference)
- [WebSocket Documentation](https://docs.kalshi.com/websockets/websocket-connection)
- [Base Exchange Class](../../dr_manhattan/base/exchange.py)
- [Examples](../../examples/)
