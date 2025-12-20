# Opinion

## Overview

- **Exchange ID**: `opinion`
- **Exchange Name**: Opinion
- **Type**: Prediction Market
- **Base Class**: [Exchange](../../dr_manhattan/base/exchange.py)
- **REST API**: `https://proxy.opinion.trade:8443`
- **Chain**: BNB Chain (Chain ID: 56)
- **Documentation**: https://docs.opinion.trade/developer-guide/opinion-open-api/overview

Opinion is a prediction market platform built on BNB Chain. It supports both binary and categorical (multi-outcome) markets.

### Key Features

- **RESTful API**: OpenAPI 3.0 specification with low latency
- **CLOB Trading**: Central Limit Order Book via SDK
- **Binary and Categorical Markets**: Support for both market types
- **Conditional Token Framework**: Split, merge, and redeem operations
- **Multi-Sig Support**: Safe wallet integration for trading

## Table of Contents

- [Features](#features)
- [API Structure](#api-structure)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Market Data](#market-data)
- [Trading](#trading)
- [Account](#account)
- [Conditional Tokens](#conditional-tokens)
- [Examples](#examples)

## Features

### Supported Methods

| Method | REST | Description |
|--------|------|-------------|
| `fetch_markets()` | Y | Fetch all available markets |
| `fetch_market()` | Y | Fetch a specific market by ID |
| `fetch_token_ids()` | Y | Fetch token IDs for a market |
| `get_orderbook()` | Y | Get orderbook for a token |
| `fetch_price_history()` | Y | Get historical price data |
| `search_markets()` | Y | Search markets with filters |
| `create_order()` | Y | Create a new order |
| `cancel_order()` | Y | Cancel an existing order |
| `cancel_all_orders()` | Y | Cancel all open orders |
| `fetch_order()` | Y | Fetch order details |
| `fetch_open_orders()` | Y | Fetch all open orders |
| `fetch_positions()` | Y | Fetch current positions |
| `fetch_balance()` | Y | Fetch account balance |
| `calculate_nav()` | Y | Calculate Net Asset Value |
| `enable_trading()` | Y | Enable trading approvals |
| `split()` | Y | Split collateral into tokens |
| `merge()` | Y | Merge tokens into collateral |
| `redeem()` | Y | Redeem winning tokens |

### Exchange Capabilities

```python
exchange.describe()
# Returns:
{
    'id': 'opinion',
    'name': 'Opinion',
    'chain_id': 56,
    'host': 'https://proxy.opinion.trade:8443',
    'has': {
        'fetch_markets': True,
        'fetch_market': True,
        'fetch_market_by_id': True,
        'create_order': True,
        'cancel_order': True,
        'cancel_all_orders': True,
        'fetch_order': True,
        'fetch_open_orders': True,
        'fetch_positions': True,
        'fetch_positions_for_market': True,
        'fetch_balance': True,
        'get_orderbook': True,
        'fetch_token_ids': True,
        'fetch_price_history': True,
        'search_markets': True,
        'fetch_public_trades': False,
        'get_websocket': False,
        'get_user_websocket': False,
        'enable_trading': True,
        'split': True,
        'merge': True,
        'redeem': True,
    }
}
```

## API Structure

### Open API (REST)

The Opinion OpenAPI provides read-only access to market data:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/openapi/market` | GET | List all markets with filters |
| `/openapi/market/{marketId}` | GET | Get binary market details |
| `/openapi/market/categorical/{marketId}` | GET | Get categorical market details |
| `/openapi/token/latest-price` | GET | Get current trade price |
| `/openapi/token/orderbook` | GET | Get order book depth |
| `/openapi/token/price-history` | GET | Get historical price data |
| `/openapi/quoteToken` | GET | List available currencies |

### CLOB SDK

Trading operations use the `opinion_clob_sdk` Python package:

```python
from opinion_clob_sdk import Client as OpinionClient
```

## Authentication

### 1. Public API (Read-Only)

API key required for all endpoints. Include in HTTP header:

```
apikey: your_api_key
```

### 2. Trading Authentication

For trading operations, you need:

- API key
- Private key (Ethereum-compatible)
- Multi-sig wallet address

```python
from dr_manhattan.exchanges.opinion import Opinion

exchange = Opinion({
    'api_key': 'your_api_key',
    'private_key': 'your_private_key',
    'multi_sig_addr': 'your_multisig_address',
    'rpc_url': 'https://bsc-dataseed.binance.org',  # optional
    'chain_id': 56  # optional, defaults to BSC mainnet
})
```

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `api_key` | str | Yes* | API key for Opinion |
| `private_key` | str | Yes* | Private key for signing |
| `multi_sig_addr` | str | Yes* | Multi-signature wallet address |
| `rpc_url` | str | No | RPC endpoint (default: BSC public RPC) |
| `chain_id` | int | No | Chain ID (default: 56 for BSC) |
| `host` | str | No | API host URL |
| `verbose` | bool | No | Enable verbose logging |

*Required for trading operations

## Rate Limiting

- **Rate Limit**: 15 requests per second per API key
- **Page Size**: Maximum 20 items per page
- **Error Response**: HTTP 429 when exceeded

### Configuration

```python
exchange = Opinion({
    'api_key': 'your_api_key',
    'rate_limit': 15,
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
from opinion_clob_sdk import TopicType, TopicStatusFilter

markets = exchange.fetch_markets({
    'topic_type': TopicType.ALL,       # ALL, BINARY, CATEGORICAL
    'status': TopicStatusFilter.ACTIVATED,  # ALL, ACTIVATED, RESOLVED
    'page': 1,
    'limit': 20,
    'active': True  # Only active markets
})
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic_type` | TopicType | No | Market type filter |
| `status` | TopicStatusFilter | No | Status filter |
| `page` | int | No | Page number (default: 1) |
| `limit` | int | No | Items per page (1-20, default: 20) |
| `active` | bool | No | Only active markets |
| `closed` | bool | No | Include closed markets |

**Returns:** `list[Market]`

### fetch_market()

Fetch a specific market by ID.

```python
market = exchange.fetch_market('12345')
```

Works for both binary and categorical markets. The method automatically tries:
1. Binary market endpoint
2. Categorical market endpoint (if binary fails)

**Returns:** `Market`

### get_orderbook()

Fetch orderbook for a specific token.

```python
orderbook = exchange.get_orderbook('token_id')
# Returns:
{
    'bids': [{'price': '0.55', 'size': '100'}],
    'asks': [{'price': '0.56', 'size': '150'}]
}
```

### fetch_price_history()

Get historical price data.

```python
from datetime import datetime

history = exchange.fetch_price_history(
    market='12345',  # Market object or ID
    outcome=0,       # Outcome index or name
    interval='1h',   # 1m, 1h, 1d, 1w, max
    start_at=1700000000,  # Unix timestamp
    end_at=1700100000,
    as_dataframe=False  # Set True for pandas DataFrame
)
```

**Supported Intervals:**
- `1m` - 1 minute
- `1h` - 1 hour
- `1d` - 1 day
- `1w` - 1 week
- `max` - All available data

**Returns:** `list[PricePoint]` or `pandas.DataFrame`

### search_markets()

Search markets with various filters.

```python
markets = exchange.search_markets(
    limit=200,
    page=1,
    topic_type=TopicType.ALL,
    status=TopicStatusFilter.ACTIVATED,
    query='bitcoin',           # Text search
    keywords=['crypto'],       # Required keywords
    binary=True,               # Only binary markets
    min_liquidity=1000.0,      # Minimum liquidity
    categories=['crypto'],     # Category filter
    outcomes=['Yes', 'No'],    # Required outcomes
    predicate=lambda m: m.volume > 10000  # Custom filter
)
```

## Trading

### create_order()

Create a new order.

```python
from dr_manhattan.models.order import OrderSide

order = exchange.create_order(
    market_id='12345',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.55,
    size=100.0,
    params={
        'token_id': 'token_id_here',  # Required
        'order_type': 'limit',         # 'limit' or 'market'
        'check_approval': False
    }
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
| `params.token_id` | str | Yes | Token ID for the outcome |
| `params.order_type` | str | No | 'limit' or 'market' |
| `params.check_approval` | bool | No | Check approvals first |

**Price Validation:**
- Price must be between 0 and 1
- Price must align to market's tick size

**Returns:** `Order`

### cancel_order()

Cancel an existing order.

```python
order = exchange.cancel_order(
    order_id='order_id',
    market_id='12345'  # optional
)
```

**Returns:** `Order`

### cancel_all_orders()

Cancel all open orders.

```python
result = exchange.cancel_all_orders(
    market_id='12345',    # optional
    side=OrderSide.BUY    # optional
)
```

### fetch_open_orders()

Fetch all open orders.

```python
orders = exchange.fetch_open_orders(
    market_id='12345',
    params={'page': 1, 'limit': 10}
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

**Returns:** `Dict[str, float]`

### fetch_positions()

Fetch current positions.

```python
positions = exchange.fetch_positions(
    market_id='12345',
    params={'page': 1, 'limit': 10}
)
```

**Returns:** `list[Position]`

### calculate_nav()

Calculate Net Asset Value for a market.

```python
market = exchange.fetch_market('12345')
nav = exchange.calculate_nav(market)
# Returns:
# NAV(
#     nav=1500.0,
#     cash=1000.0,
#     positions_value=500.0,
#     positions=[{'outcome': 'Yes', 'size': 100, 'current_price': 0.5, 'value': 50}]
# )
```

## Conditional Tokens

Opinion uses the Conditional Token Framework for market settlement.

### enable_trading()

Enable trading by approving necessary tokens.

```python
success = exchange.enable_trading()
```

### split()

Split collateral into outcome tokens.

```python
result = exchange.split(
    market_id='12345',
    amount=1000000000000000000,  # Amount in wei
    check_approval=True
)
# Returns: {'tx_hash': '0x...', 'safe_tx_hash': '0x...'}
```

### merge()

Merge outcome tokens back into collateral.

```python
result = exchange.merge(
    market_id='12345',
    amount=1000000000000000000,
    check_approval=True
)
```

### redeem()

Redeem winning tokens after market resolution.

```python
result = exchange.redeem(
    market_id='12345',
    check_approval=True
)
```

## Examples

### Basic Usage

```python
from dr_manhattan.exchanges.opinion import Opinion

# Read-only access
exchange = Opinion({'api_key': 'your_api_key'})

# Fetch markets
markets = exchange.fetch_markets({'limit': 10})
for market in markets:
    print(f"{market.id}: {market.question}")
    print(f"  Outcomes: {market.outcomes}")
    print(f"  Volume: {market.volume}")
```

### Trading Example

```python
from dr_manhattan.exchanges.opinion import Opinion
from dr_manhattan.models.order import OrderSide

exchange = Opinion({
    'api_key': 'your_api_key',
    'private_key': 'your_private_key',
    'multi_sig_addr': 'your_multisig_address'
})

# Get market and token IDs
market = exchange.fetch_market('12345')
token_ids = market.metadata.get('clobTokenIds', [])
yes_token_id = token_ids[0]

# Create order
order = exchange.create_order(
    market_id='12345',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.55,
    size=100.0,
    params={'token_id': yes_token_id}
)

print(f"Order created: {order.id}")
```

### Error Handling

```python
from dr_manhattan.exchanges.opinion import Opinion
from dr_manhattan.base.errors import (
    NetworkError,
    RateLimitError,
    MarketNotFound,
    InvalidOrder,
    AuthenticationError
)

exchange = Opinion({'api_key': 'your_api_key'})

try:
    market = exchange.fetch_market('invalid_id')
except MarketNotFound as e:
    print(f"Market not found: {e}")
except NetworkError as e:
    print(f"Network error: {e}")
except RateLimitError as e:
    print(f"Rate limited: {e}")
except AuthenticationError as e:
    print(f"Authentication failed: {e}")
except InvalidOrder as e:
    print(f"Invalid order: {e}")
```

### Price History Analysis

```python
import pandas as pd

exchange = Opinion({'api_key': 'your_api_key'})

# Get price history as DataFrame
df = exchange.fetch_price_history(
    market='12345',
    outcome='Yes',
    interval='1h',
    as_dataframe=True
)

# Analyze
print(df.describe())
print(f"Price range: {df['price'].min()} - {df['price'].max()}")
```

## API Response Format

Opinion API returns standardized JSON responses:

```json
{
    "code": 0,
    "message": "success",
    "result": {
        "data": { ... }
    }
}
```

**Error Codes:**

| Code | Description |
|------|-------------|
| 0 | Success |
| 400 | Bad request |
| 401 | Unauthorized |
| 404 | Not found |
| 429 | Rate limit exceeded |
| 500 | Server error |

## Market Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `market_id` | int | Unique market identifier |
| `market_title` | str | Market question/title |
| `status` | str | activated, resolved |
| `yes_token_id` | str | Token ID for Yes outcome |
| `no_token_id` | str | Token ID for No outcome |
| `yes_label` | str | Label for Yes outcome |
| `no_label` | str | Label for No outcome |
| `volume` | str | Total trading volume |
| `cutoff_at` | int | Market close timestamp |
| `chain_id` | int | Blockchain chain ID |
| `quote_token` | str | Quote token address |
| `tickSize` | float | Minimum price increment |

## Important Notes

- **Chain**: Opinion operates on BNB Chain (BSC Mainnet, Chain ID: 56)
- **Quote Token**: USDT on BSC
- **Tick Size**: Required for order price validation
- **Multi-Sig**: Trading requires a multi-signature wallet address
- **WebSocket**: Not yet available (polling recommended for real-time data)
- **Public Trades**: Endpoint not yet available in Opinion API

## Contract Addresses

| Contract | Address |
|----------|---------|
| Conditional Token | `0xAD1a38cEc043e70E83a3eC30443dB285ED10D774` |
| MultiSend | `0x998739BFdAAdde7C933B942a68053933098f9EDa` |

## References

- [Opinion Documentation](https://docs.opinion.trade/developer-guide/opinion-open-api/overview)
- [Opinion CLOB SDK](https://pypi.org/project/opinion-clob-sdk/)
- [Base Exchange Class](../../dr_manhattan/base/exchange.py)
- [Examples](../../examples/)

## See Also

- [Polymarket](polymarket.md) - Similar prediction market on Polygon
- [Template](TEMPLATE.md) - Documentation template
