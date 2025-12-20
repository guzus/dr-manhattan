# Limitless

## Overview

- **Exchange ID**: `limitless`
- **Exchange Name**: Limitless
- **Type**: Prediction Market
- **Base Class**: [Exchange](../../dr_manhattan/base/exchange.py)
- **REST API**: `https://api.limitless.exchange`
- **WebSocket API**: `wss://ws.limitless.exchange` (not yet implemented)
- **Documentation**: https://api.limitless.exchange/api-v1
- **Chain**: Base (Chain ID: 8453)

Limitless is a prediction market platform built on Base chain with CLOB-style orderbook. It uses EIP-712 message signing for authentication and order placement.

### Key Features

- **CLOB Trading**: Central Limit Order Book for efficient price discovery
- **EIP-712 Signing**: Secure order signing using Ethereum standards
- **Base Chain**: Low gas fees on Base L2
- **Market Groups**: Support for grouped/categorical markets (NegRisk)
- **Real-time Data**: Historical price data and market events

### Quick Links

- [API Documentation](https://api.limitless.exchange/api-v1)
- [Limitless Website](https://limitless.exchange)

## Table of Contents

- [Features](#features)
- [API Structure](#api-structure)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Market Data](#market-data)
- [Trading](#trading)
- [Account](#account)
- [Examples](#examples)

## Features

### Supported Methods

| Method | REST | WebSocket | Description |
|--------|------|-----------|-------------|
| `fetch_markets()` | ✅ | ❌ | Fetch all available markets |
| `fetch_market()` | ✅ | ❌ | Fetch a specific market by slug |
| `fetch_token_ids()` | ✅ | ❌ | Fetch token IDs for a market |
| `create_order()` | ✅ | ❌ | Create a new order |
| `cancel_order()` | ✅ | ❌ | Cancel an existing order |
| `cancel_all_orders()` | ✅ | ❌ | Cancel all orders in a market |
| `fetch_order()` | ✅ | ❌ | Fetch order details |
| `fetch_open_orders()` | ✅ | ❌ | Fetch all open orders |
| `fetch_positions()` | ✅ | ❌ | Fetch current positions |
| `fetch_balance()` | ✅ | ❌ | Fetch USDC balance |
| `get_orderbook()` | ✅ | ❌ | Fetch orderbook for a market |
| `fetch_price_history()` | ✅ | ❌ | Fetch historical price data |
| `search_markets()` | ✅ | ❌ | Search markets by query |
| `fetch_feed_events()` | ✅ | ❌ | Fetch market feed events |
| `watch_orderbook()` | ❌ | ❌ | Real-time orderbook (not implemented) |

### Exchange Capabilities

```python
exchange.describe()
# Returns:
{
    'id': 'limitless',
    'name': 'Limitless',
    'chain_id': 8453,
    'host': 'https://api.limitless.exchange',
    'has': {
        'fetch_markets': True,
        'fetch_market': True,
        'fetch_markets_by_slug': True,
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
        'fetch_feed_events': True,
        'fetch_market_events': True,
        'get_websocket': False,
        'get_user_websocket': False,
    }
}
```

## API Structure

Limitless provides a unified REST API for all operations:

### Authentication Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/signing-message` | GET | Get signing message with nonce |
| `/auth/login` | POST | Authenticate with signed message |
| `/auth/verify-auth` | GET | Verify authentication status |
| `/auth/logout` | POST | Logout and clear session |

### Market Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/markets/active` | GET | Get active markets with pagination |
| `/markets/active/{categoryId}` | GET | Get active markets by category |
| `/markets/categories/count` | GET | Get market count per category |
| `/markets/active/slugs` | GET | Get all active market slugs |
| `/markets/{addressOrSlug}` | GET | Get market by address or slug |
| `/markets/{slug}/orderbook` | GET | Get market orderbook |
| `/markets/{slug}/historical-price` | GET | Get historical price data |
| `/markets/{slug}/get-feed-events` | GET | Get market feed events |
| `/markets/{slug}/events` | GET | Get market events (trades, orders) |
| `/markets/search` | GET | Search markets semantically |

### Trading Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/orders` | POST | Create a new order |
| `/orders/{orderId}` | DELETE | Cancel an order |
| `/orders/cancel-batch` | POST | Cancel multiple orders |
| `/orders/all/{slug}` | DELETE | Cancel all orders in market |
| `/markets/{slug}/user-orders` | GET | Get user orders for market |
| `/markets/{slug}/locked-balance` | GET | Get locked balance in orders |

### Portfolio Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio/positions` | GET | Get all positions |
| `/portfolio/trades` | GET | Get trade history |
| `/portfolio/history` | GET | Get paginated history |
| `/portfolio/points` | GET | Get points breakdown |
| `/portfolio/trading/allowance` | GET | Check USDC allowance |
| `/portfolio/{account}/positions` | GET | Get positions for address (public) |
| `/portfolio/{account}/traded-volume` | GET | Get traded volume for address |

## Authentication

Limitless uses EIP-712 message signing for authentication. The library handles this automatically when a private key is provided.

### 1. Public API (Read-Only)

```python
from dr_manhattan.exchanges.limitless import Limitless

exchange = Limitless()
markets = exchange.fetch_markets()
```

### 2. Authenticated API (Trading)

```python
exchange = Limitless({
    'private_key': 'your_private_key',
})

# Authentication happens automatically
positions = exchange.fetch_positions()
```

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `private_key` | str | Yes* | Private key for signing (hex string) |
| `host` | str | No | API host URL (default: `https://api.limitless.exchange`) |
| `chain_id` | int | No | Chain ID (default: 8453 for Base) |
| `verbose` | bool | No | Enable verbose logging |
| `timeout` | int | No | Request timeout in seconds |
| `rate_limit` | int | No | Requests per second limit |
| `max_retries` | int | No | Maximum retry attempts |

*Required for trading operations only

### Authentication Flow

1. **Get Signing Message**: Fetch a random nonce from `/auth/signing-message`
2. **Sign Message**: Sign the message with your private key
3. **Login**: POST to `/auth/login` with:
   - `x-account`: Your checksummed Ethereum address
   - `x-signing-message`: Hex-encoded signing message
   - `x-signature`: Wallet signature
4. **Session Cookie**: A `limitless_session` cookie is set for subsequent requests

## Rate Limiting

- **Default Rate Limit**: 10 requests per second
- **Automatic Retry**: Yes
- **Max Retries**: 3 attempts

### Configuration

```python
exchange = Limitless({
    'rate_limit': 10,
    'max_retries': 3,
    'retry_delay': 1.0,
    'retry_backoff': 2.0,
    'timeout': 30
})
```

## Market Data

### fetch_markets()

Fetch all active markets with pagination.

```python
markets = exchange.fetch_markets(params={
    'page': 1,
    'limit': 10,
    'sortBy': 'newest',
    'categoryId': 'politics'
})
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page` | int | No | Page number (default: 1) |
| `limit` | int | No | Items per page (default: 10) |
| `sortBy` | str | No | Sort parameter (e.g., "newest") |
| `categoryId` | str | No | Filter by category |

**Returns:** `list[Market]`

### fetch_market()

Fetch a specific market by slug or address.

```python
market = exchange.fetch_market('will-trump-win-2024')
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market slug or address |

**Returns:** `Market`

### get_orderbook()

Fetch the current orderbook for a market.

```python
orderbook = exchange.get_orderbook('will-trump-win-2024')
# Returns:
# {
#     'bids': [{'price': '0.65', 'size': '1000'}],
#     'asks': [{'price': '0.67', 'size': '500'}],
#     'adjustedMidpoint': 0.66,
#     'lastTradePrice': 0.65,
#     'maxSpread': 0.02,
#     'minSize': 1
# }
```

**Returns:** `Dict[str, Any]`

### fetch_price_history()

Fetch historical price data for a market.

```python
from dr_manhattan.exchanges.limitless import PricePoint

history = exchange.fetch_price_history(
    market='will-trump-win-2024',
    outcome=0,  # 0 for Yes, 1 for No
    interval='1h',
    start_at=1700000000,
    end_at=1700086400
)

# Returns list of PricePoint objects
for point in history:
    print(f"{point.timestamp}: {point.price}")

# Or as DataFrame
df = exchange.fetch_price_history(
    market='will-trump-win-2024',
    interval='1d',
    as_dataframe=True
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market` | Market/str | Yes | Market object or slug |
| `outcome` | int/str | No | Outcome index or name (default: 0) |
| `interval` | str | No | Time interval: "1m", "1h", "1d", "1w" (default: "1h") |
| `start_at` | int | No | Start timestamp (Unix) |
| `end_at` | int | No | End timestamp (Unix) |
| `as_dataframe` | bool | No | Return as pandas DataFrame |

**Returns:** `list[PricePoint]` or `DataFrame`

### search_markets()

Search markets using semantic similarity.

```python
markets = exchange.search_markets(
    query='trump election',
    limit=10,
    min_liquidity=1000.0,
    binary=True
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | str | No | Search text |
| `limit` | int | No | Maximum results (default: 200) |
| `min_liquidity` | float | No | Minimum liquidity filter |
| `binary` | bool | No | Only binary markets |
| `categories` | list | No | Filter by categories |
| `predicate` | callable | No | Custom filter function |

**Returns:** `list[Market]`

## Trading

### create_order()

Create a new order using EIP-712 signed order data.

```python
from dr_manhattan.models.order import OrderSide

order = exchange.create_order(
    market_id='will-trump-win-2024',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.65,
    size=100.0,
    params={
        'token_id': '0x...',  # Required: token ID for the outcome
    }
)

print(f"Order created: {order.id}")
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market slug |
| `outcome` | str | Yes | Outcome to bet on (e.g., "Yes", "No") |
| `side` | OrderSide | Yes | BUY or SELL |
| `price` | float | Yes | Price per share (0-1) |
| `size` | float | Yes | Number of shares |
| `params.token_id` | str | Yes | Token ID for the outcome |

**Returns:** `Order`

**Important Notes:**
- Price must be between 0 and 1 (exclusive)
- Price must be aligned to market tick_size
- Token approvals required before trading:
  - BUY orders: Approve USDC to venue exchange
  - SELL orders: Approve conditional tokens to venue exchange

### cancel_order()

Cancel an existing order.

```python
order = exchange.cancel_order(
    order_id='uuid-order-id',
    market_id='will-trump-win-2024'
)
```

**Returns:** `Order` with status CANCELLED

### cancel_all_orders()

Cancel all orders in a specific market.

```python
result = exchange.cancel_all_orders(market_id='will-trump-win-2024')
```

**Returns:** `Dict[str, Any]` with cancellation results

### fetch_open_orders()

Fetch all open orders for a market.

```python
orders = exchange.fetch_open_orders(
    market_id='will-trump-win-2024',
    params={
        'statuses': 'LIVE',  # or 'MATCHED'
        'limit': 100
    }
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | No | Filter by market |
| `params.statuses` | str | No | Filter by status: "LIVE" or "MATCHED" |
| `params.limit` | int | No | Maximum orders to return |

**Returns:** `list[Order]`

## Account

### fetch_balance()

Fetch USDC balance from on-chain contract.

```python
balance = exchange.fetch_balance()
# Returns: {'USDC': 1000.0}
```

**Returns:** `Dict[str, float]`

### fetch_positions()

Fetch current positions with P&L calculations.

```python
positions = exchange.fetch_positions(market_id='will-trump-win-2024')

for pos in positions:
    print(f"{pos.outcome}: {pos.size} @ {pos.average_price}")
```

**Returns:** `list[Position]`

### calculate_nav()

Calculate Net Asset Value for a market.

```python
from dr_manhattan.exchanges.limitless import NAV

nav = exchange.calculate_nav(market)

print(f"NAV: {nav.nav}")
print(f"Cash: {nav.cash}")
print(f"Positions Value: {nav.positions_value}")
```

**Returns:** `NAV` object

## Examples

### Basic Usage

```python
from dr_manhattan.exchanges.limitless import Limitless

# Public API - no authentication needed
exchange = Limitless({'verbose': True})

# Fetch active markets
markets = exchange.fetch_markets({'limit': 5})
for market in markets:
    print(f"{market.question}")
    print(f"  Prices: {market.prices}")
    print(f"  Volume: ${market.volume:,.2f}")

# Fetch specific market
market = exchange.fetch_market('will-trump-win-2024')
print(f"Outcomes: {market.outcomes}")
print(f"Tick size: {market.tick_size}")

# Get orderbook
orderbook = exchange.get_orderbook(market.id)
print(f"Best bid: {orderbook['bids'][0] if orderbook['bids'] else 'None'}")
print(f"Best ask: {orderbook['asks'][0] if orderbook['asks'] else 'None'}")
```

### Trading Example

```python
from dr_manhattan.exchanges.limitless import Limitless
from dr_manhattan.models.order import OrderSide

exchange = Limitless({
    'private_key': 'your_private_key',
    'verbose': True
})

# Fetch market and token IDs
market = exchange.fetch_market('will-trump-win-2024')
token_ids = exchange.fetch_token_ids(market.id)

# Get Yes token ID
yes_token_id = token_ids[0]

# Create buy order for Yes outcome
order = exchange.create_order(
    market_id=market.id,
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.65,
    size=100.0,
    params={'token_id': yes_token_id}
)

print(f"Order created: {order.id}")
print(f"Status: {order.status}")

# Check open orders
open_orders = exchange.fetch_open_orders(market_id=market.id)
print(f"Open orders: {len(open_orders)}")

# Cancel order
cancelled = exchange.cancel_order(order.id, market.id)
print(f"Order cancelled: {cancelled.status}")
```

### Error Handling

```python
from dr_manhattan.exchanges.limitless import Limitless
from dr_manhattan.base.errors import (
    NetworkError,
    RateLimitError,
    MarketNotFound,
    InvalidOrder,
    AuthenticationError,
    ExchangeError
)

exchange = Limitless()

try:
    market = exchange.fetch_market('nonexistent-market')
except MarketNotFound as e:
    print(f"Market not found: {e}")
except NetworkError as e:
    print(f"Network error: {e}")
except RateLimitError as e:
    print(f"Rate limited: {e}")
except ExchangeError as e:
    print(f"Exchange error: {e}")

# Trading errors
try:
    order = exchange.create_order(
        market_id='some-market',
        outcome='Yes',
        side=OrderSide.BUY,
        price=1.5,  # Invalid: must be 0-1
        size=100.0,
        params={'token_id': 'token123'}
    )
except InvalidOrder as e:
    print(f"Invalid order: {e}")
except AuthenticationError as e:
    print(f"Authentication required: {e}")
```

### Price History Analysis

```python
from dr_manhattan.exchanges.limitless import Limitless

exchange = Limitless()

# Get price history as DataFrame
df = exchange.fetch_price_history(
    market='will-trump-win-2024',
    interval='1d',
    as_dataframe=True
)

# Calculate basic statistics
print(f"Average price: {df['price'].mean():.3f}")
print(f"Min price: {df['price'].min():.3f}")
print(f"Max price: {df['price'].max():.3f}")
print(f"Volatility: {df['price'].std():.3f}")
```

## Important Notes

### Address Format
All Ethereum addresses must use EIP-55 checksummed format, particularly in the `x-account` header and order fields.

### Venue System
CLOB markets require fetching venue data. The response includes:
- `venue.exchange`: Used as EIP-712 `verifyingContract`
- `venue.adapter`: Optional adapter for NegRisk/grouped markets

### Token Approvals
Required before trading:
- **BUY orders**: Approve USDC to `venue.exchange`
- **SELL (simple CLOB)**: Approve conditional tokens to `venue.exchange`
- **SELL (NegRisk/grouped)**: Approve to both `venue.exchange` and `venue.adapter`

### Market Types
- **Simple CLOB**: Standard binary markets
- **NegRisk Groups**: Grouped/categorical markets with multiple outcomes

### Tick Size
Each market has a specific tick_size (minimum price increment). The tick_size is fetched from the API and must not use fallback defaults.

## References

- [Limitless API Documentation](https://api.limitless.exchange/api-v1)
- [Limitless Website](https://limitless.exchange)
- [Base Exchange Class](../../dr_manhattan/base/exchange.py)
- [Examples](../../examples/)

## See Also

- [Polymarket](./polymarket.md)
- [Opinion](./opinion.md)
