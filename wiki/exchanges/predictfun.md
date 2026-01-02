# Predict.fun

## Overview

- **Exchange ID**: `predictfun`
- **Exchange Name**: Predict.fun
- **Type**: Prediction Market
- **Chain**: BNB Chain (BSC)
- **Base Class**: [Exchange](../../dr_manhattan/base/exchange.py)
- **REST API**: `https://api.predict.fun/v1`
- **Testnet API**: `https://api-testnet.predict.fun/v1`
- **Documentation**: https://dev.predict.fun/

Predict.fun is a prediction market on BNB Chain with a CLOB-style orderbook. It supports both yield-bearing and non-yield-bearing markets with EIP-712 signed orders.

## Table of Contents

- [Features](#features)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Market Data](#market-data)
- [Trading](#trading)
- [Account](#account)
- [Examples](#examples)

## Features

### Supported Methods

| Method | REST | Description |
|--------|------|-------------|
| `fetch_markets()` | Yes | Fetch all available markets |
| `fetch_market()` | Yes | Fetch a specific market by ID |
| `get_orderbook()` | Yes | Fetch orderbook for a market |
| `fetch_token_ids()` | Yes | Fetch token IDs for a market |
| `create_order()` | Yes | Create a new order |
| `cancel_order()` | Yes | Cancel an existing order |
| `fetch_order()` | Yes | Fetch order details |
| `fetch_open_orders()` | Yes | Fetch all open orders |
| `fetch_positions()` | Yes | Fetch current positions |
| `fetch_balance()` | Yes | Fetch account balance |

### Exchange Capabilities

```python
exchange.describe()
# Returns:
{
    'id': 'predictfun',
    'name': 'Predict.fun',
    'chain_id': 56,  # BNB Mainnet
    'host': 'https://api.predict.fun',
    'testnet': False,
    'has': {
        'fetch_markets': True,
        'fetch_market': True,
        'create_order': True,
        'cancel_order': True,
        'fetch_order': True,
        'fetch_open_orders': True,
        'fetch_positions': True,
        'fetch_balance': True,
        'get_orderbook': True,
        'fetch_token_ids': True,
    }
}
```

## Authentication

Predict.fun uses a two-step authentication process:

1. **API Key**: Required for all API calls (header: `x-api-key`)
2. **JWT Token**: Required for private endpoints, obtained by signing a message with your wallet

### 1. Public API (Read-Only with API Key)

```python
from dr_manhattan import PredictFun

# API key required even for public endpoints
exchange = PredictFun({
    'api_key': 'your_api_key',
})

markets = exchange.fetch_markets()
```

### 2. Full Authentication (Trading)

```python
exchange = PredictFun({
    'api_key': 'your_api_key',
    'private_key': 'your_private_key',
})

# JWT token is automatically obtained when needed
order = exchange.create_order(...)
```

### 3. Testnet

```python
exchange = PredictFun({
    'api_key': 'your_testnet_api_key',
    'private_key': 'your_private_key',
    'testnet': True,
})
```

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `api_key` | str | Yes | API key from Predict.fun |
| `private_key` | str | Yes* | Private key for signing |
| `testnet` | bool | No | Use testnet (default: False) |
| `verbose` | bool | No | Enable verbose logging |
| `timeout` | int | No | Request timeout (default: 30) |

*Required for trading operations

### Environment Variables

```bash
export PREDICTFUN_API_KEY="your_api_key"
export PREDICTFUN_PRIVATE_KEY="your_private_key"
export PREDICTFUN_TESTNET="false"
```

## Rate Limiting

- **Default Rate Limit**: 10 requests per second
- **Automatic Retry**: Yes
- **Max Retries**: 3 attempts

### Configuration

```python
exchange = PredictFun({
    'api_key': 'your_api_key',
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
markets = exchange.fetch_markets(params={
    'first': 100,  # Number of markets
    'after': 'cursor',  # Pagination cursor
})
```

**Returns:** `list[Market]`

### fetch_market()

Fetch a specific market by ID.

```python
market = exchange.fetch_market('123')
```

**Returns:** `Market`

### get_orderbook()

Fetch the orderbook for a market.

Note: The orderbook stores prices based on the Yes outcome. For No outcome, use: `No price = 1 - Yes price`

```python
orderbook = exchange.get_orderbook('123')
# Returns:
{
    'bids': [{'price': '0.65', 'size': '100'}],
    'asks': [{'price': '0.67', 'size': '50'}]
}
```

## Trading

### create_order()

Create a new order. Orders are signed using EIP-712.

```python
from dr_manhattan import OrderSide

order = exchange.create_order(
    market_id='123',
    outcome='Yes',  # or 'No'
    side=OrderSide.BUY,
    price=0.65,  # Price between 0 and 1
    size=100.0,  # Size in USDT
    params={
        'strategy': 'LIMIT',  # or 'MARKET'
    }
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market ID |
| `outcome` | str | Yes | Outcome name (e.g., "Yes", "No") |
| `side` | OrderSide | Yes | BUY or SELL |
| `price` | float | Yes | Price per share (0-1) |
| `size` | float | Yes | Size in USDT |
| `params.strategy` | str | No | LIMIT or MARKET (default: LIMIT) |
| `params.token_id` | str | No | Token ID (auto-resolved from outcome) |

**Returns:** `Order`

### cancel_order()

Cancel an existing order.

```python
order = exchange.cancel_order(
    order_id='0x...',  # Order hash
)
```

**Returns:** `Order`

### fetch_open_orders()

Fetch all open orders.

```python
orders = exchange.fetch_open_orders(market_id='123')
```

**Returns:** `list[Order]`

## Account

### fetch_balance()

Fetch account balance.

```python
balance = exchange.fetch_balance()
# Returns: {'USDT': 1000.0}
```

**Returns:** `Dict[str, float]`

### fetch_positions()

Fetch current positions.

```python
positions = exchange.fetch_positions(market_id='123')
```

**Returns:** `list[Position]`

## Examples

### Basic Usage

```python
from dr_manhattan import PredictFun

exchange = PredictFun({
    'api_key': 'your_api_key',
    'verbose': True
})

# Fetch markets
markets = exchange.fetch_markets()
for market in markets[:5]:
    print(f"{market.id}: {market.question}")

# Get orderbook
orderbook = exchange.get_orderbook(markets[0].id)
print(f"Best bid: {orderbook['bids'][0] if orderbook['bids'] else 'N/A'}")
print(f"Best ask: {orderbook['asks'][0] if orderbook['asks'] else 'N/A'}")
```

### Trading Example

```python
from dr_manhattan import PredictFun, OrderSide

exchange = PredictFun({
    'api_key': 'your_api_key',
    'private_key': 'your_private_key'
})

# Create a limit order
order = exchange.create_order(
    market_id='123',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.55,
    size=10.0
)

print(f"Order created: {order.id}")

# Cancel the order
cancelled = exchange.cancel_order(order.id)
print(f"Order cancelled: {cancelled.status}")
```

### Error Handling

```python
from dr_manhattan import PredictFun
from dr_manhattan.base.errors import (
    NetworkError,
    RateLimitError,
    MarketNotFound,
    AuthenticationError,
    InvalidOrder
)

exchange = PredictFun({'api_key': 'your_api_key'})

try:
    market = exchange.fetch_market('invalid_id')
except MarketNotFound as e:
    print(f"Market not found: {e}")
except AuthenticationError as e:
    print(f"Auth error: {e}")
except NetworkError as e:
    print(f"Network error: {e}")
except RateLimitError as e:
    print(f"Rate limited: {e}")
```

## Important Notes

- **Orderbook Pricing**: The orderbook stores prices based on the Yes outcome. Calculate No price as `1 - Yes price`.
- **NegRisk Markets**: Some markets use the yield-bearing NegRisk CTF Exchange contract. This is handled automatically.
- **Yield Bearing**: Some markets support yield bearing. Check `market.metadata['isYieldBearing']`.
- **Decimal Precision**: Markets can have 2 or 3 decimal places. Check `market.tick_size`.
- **Token IDs**: Each outcome has a unique `onChainId` used as the token ID for orders.

## Deployed Contracts (BNB Mainnet)

| Contract (yield-bearing) | Address |
|--------------------------|---------|
| Yield-Bearing CTFExchange | `0x6bEb5a40C032AFc305961162d8204CDA16DECFa5` |
| Yield-Bearing NegRiskCtfExchange | `0x8A289d458f5a134bA40015085A8F50Ffb681B41d` |
| Vault | `0x09F683d8a144c4ac296D770F839098c3377410c5` |

> Note: The protocol also defines non-yield-bearing variants of the CTFExchange and NegRiskCtfExchange contracts. Those non-yield-bearing contract addresses are not listed here.

## References

- [Predict.fun Developer Documentation](https://dev.predict.fun/)
- [API Reference](https://dev.predict.fun/get-markets-25326905e0.md)
- [Understanding the Orderbook](https://dev.predict.fun/understanding-the-orderbook-685654m0.md)
- [How to Authenticate (Python)](https://dev.predict.fun/py-how-to-authenticate-your-api-requests-1868364m0.md)
- [Base Exchange Class](../../dr_manhattan/base/exchange.py)

## See Also

- [Opinion Exchange](./opinion.md) - Another BNB Chain prediction market
- [Polymarket Exchange](./polymarket.md) - Polygon prediction market
- [Limitless Exchange](./limitless.md) - Base chain prediction market
