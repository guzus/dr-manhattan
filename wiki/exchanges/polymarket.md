# Polymarket

## Overview

- **Exchange ID**: `polymarket`
- **Exchange Name**: Polymarket
- **Type**: Prediction Market
- **Base Class**: [Exchange](../../dr_manhattan/base/exchange.py)
- **CLOB API**: `https://clob.polymarket.com/`
- **Data API**: `https://data-api.polymarket.com/`
- **Gamma API**: `https://gamma-api.polymarket.com/`
- **WebSocket API**: `wss://ws-subscriptions-clob.polymarket.com/ws/`
- **RTDS WebSocket**: `wss://ws-live-data.polymarket.com`
- **Documentation**: https://docs.polymarket.com/

Polymarket is a decentralized prediction market platform built on Polygon. Users can trade on the outcome of real-world events.

### Key Features

- **Multiple APIs**: CLOB, Gamma, Data API, WebSocket, and GraphQL
- **Real-time Data**: WebSocket support for orderbook and user events
- **Advanced Features**: Conditional tokens, proxy wallets, subgraph queries
- **Open Source**: All code and SDKs are freely available
- **Builder Program**: Developer rewards and support
- **Low Fees**: 0.5-1% trading fees, minimal gas costs on Polygon

### Quick Links

- [Developer Quickstart](https://docs.polymarket.com/quickstart)
- [API Showcase](https://docs.polymarket.com/quickstart/introduction/showcase)
- [Discord Community](https://discord.gg/polymarket)
- [Official Python Client](https://github.com/Polymarket/py-clob-client)

## Table of Contents

- [Features](#features)
- [API Structure](#api-structure)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Market Data](#market-data)
  - [Gamma API](#gamma-api)
  - [Fetching Markets](#fetching-markets)
- [Trading](#trading)
  - [Order Types](#order-types)
  - [CLOB API](#clob-api)
- [Account](#account)
  - [Data API](#data-api)
- [WebSocket](#websocket)
  - [User Channel](#user-channel)
  - [Market Channel](#market-channel)
- [Advanced Features](#advanced-features)
  - [Subgraph API](#subgraph-api)
  - [Conditional Token Framework](#conditional-token-framework)
  - [Proxy Wallets](#proxy-wallets)
  - [Negative Risk](#negative-risk)
- [SDKs and Tools](#sdks-and-tools)
- [Examples](#examples)
- [Community and Support](#community-and-support)

## Features

### Supported Methods

| Method | REST | WebSocket | Description |
|--------|------|-----------|-------------|
| `fetch_markets()` | ✅ | ❌ | Fetch all available markets |
| `fetch_market()` | ✅ | ❌ | Fetch a specific market by ID |
| `fetch_token_ids()` | ✅ | ❌ | Fetch token IDs for a market (for trading) |
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

## API Structure

Polymarket provides multiple specialized APIs for different use cases:

### CLOB API (Central Limit Order Book)
- **Base URL**: `https://clob.polymarket.com/`
- **Purpose**: Order book operations, trading, and order management
- **Key Endpoints**:
  - `/orderbook` - Get orderbook for a token
  - `/prices` - Get current prices
  - `/spreads` - Get bid-ask spreads
  - `/order` - Place/manage orders
  - `/trades` - Get trade history

### Gamma API
- **Base URL**: `https://gamma-api.polymarket.com/`
- **Purpose**: Market discovery and market data
- **Key Endpoints**:
  - `/events` - Get events
  - `/markets` - Get markets
  - `/sports` - Sports betting markets
  - `/tags` - Market categories/tags
  - `/series` - Event series

### Data API
- **Base URL**: `https://data-api.polymarket.com/`
- **Purpose**: User data, holdings, and on-chain activities
- **Key Endpoints**:
  - `/holdings` - User token holdings
  - `/positions` - User positions
  - `/portfolio` - Portfolio summary
  - `/history` - Transaction history

### WebSocket API
- **URL**: `wss://ws-subscriptions-clob.polymarket.com/ws/`
- **Purpose**: Real-time orderbook updates
- **Channels**:
  - User Channel - Account-specific updates
  - Market Channel - Market orderbook updates

### RTDS WebSocket
- **URL**: `wss://ws-live-data.polymarket.com`
- **Purpose**: Real-time data streams
- **Streams**:
  - Crypto prices
  - Comments and discussions

## Authentication

Polymarket supports multiple authentication methods depending on the API being used:

### 1. Public API (Read-Only)

No authentication required for public market data via Gamma API:

```python
from dr_manhattan.exchanges.polymarket import Polymarket

exchange = Polymarket()
markets = exchange.fetch_markets()
```

**Available without authentication:**
- Market discovery (Gamma API)
- Public orderbook data (CLOB API)
- Market prices and spreads
- Event information

### 2. Private Key Authentication (Trading)

For trading operations via CLOB API, wallet authentication is required. There are two initialization patterns:

#### Pattern A: Multi-Market Trading (Recommended)

Initialize once, trade on multiple markets by passing `token_id` per order:

```python
# Initialize with just private key
exchange = Polymarket({
    'private_key': 'your_private_key_here',
    'dry_run': False,
    'verbose': True
})

# Trade on any market by specifying token_id in params
order1 = exchange.create_order(
    market_id='market_1',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.52,
    size=100.0,
    params={'token_id': 'token_id_1'}  # Specify per order
)

order2 = exchange.create_order(
    market_id='market_2',
    outcome='No',
    side=OrderSide.SELL,
    price=0.45,
    size=50.0,
    params={'token_id': 'token_id_2'}  # Different market
)
```

**Use Cases:**
- ✅ Trade across multiple markets simultaneously
- ✅ Market making on different markets
- ✅ Portfolio management and diversification
- ✅ Multi-strategy trading

#### Pattern B: Single Market Trading

Pre-configure market parameters for convenience (locks to one market):

```python
# Initialize with specific market parameters
exchange = Polymarket({
    'private_key': 'your_private_key_here',
    'condition_id': 'market_condition_id',
    'yes_token_id': 'yes_token_id',
    'no_token_id': 'no_token_id',
    'dry_run': False
})

# Trades are limited to this specific market
```

**Use Cases:**
- ✅ Single market focus
- ✅ Simplified configuration
- ✅ Quick prototyping

**Authentication Process:**
1. Sign order messages with your Ethereum private key
2. Submit signed orders to CLOB API
3. Orders are verified on-chain via Polygon network

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `private_key` | str | Yes* | Ethereum private key for signing transactions |
| `funder` | str | No** | Funder address (public key) for proxy wallet trading |
| `condition_id` | str | No | Market condition ID (Pattern B only) |
| `yes_token_id` | str | No | YES outcome token ID (Pattern B only) |
| `no_token_id` | str | No | NO outcome token ID (Pattern B only) |
| `dry_run` | bool | No | Enable dry-run mode (default: False) |
| `verbose` | bool | No | Enable verbose logging (default: False) |
| `chain_id` | int | No | Polygon chain ID (default: 137) |

*Required for trading operations only  
**Required if using proxy wallet for trading

**💡 Tip:** Use Pattern A for maximum flexibility when trading on multiple markets.

#### Proxy Wallet Trading

If you're using a proxy wallet (common for Polymarket trading), you need both:
1. **Private Key** - Your proxy wallet's private key for signing
2. **Funder Address** - Your main wallet's public address that funds the proxy

```python
exchange = Polymarket({
    'private_key': 'proxy_wallet_private_key',
    'funder': '0xYourMainWalletAddress',  # Public address of funder
    'verbose': True
})

# Now trade as normal
order = exchange.create_order(
    market_id='market_id',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.52,
    size=100.0,
    params={'token_id': 'token_id'}
)
```

**Benefits of Proxy Wallets:**
- Lower gas costs
- Faster order execution
- Main wallet retains custody of funds
- Can be revoked at any time

### 3. WebSocket Authentication

WebSocket connections for user-specific data require API key authentication:

```python
ws = exchange.get_websocket()
await ws.authenticate(api_key='your_api_key')
```

**Note:** Public market data via WebSocket does not require authentication.

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

### Gamma API

The Gamma API is Polymarket's primary market data endpoint for discovering events and markets.

**Base URL:** `https://gamma-api.polymarket.com/`

#### Available Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events` | GET | List all events |
| `/markets` | GET | List all markets |
| `/sports` | GET | Sports betting markets |
| `/tags` | GET | Market categories and tags |
| `/series` | GET | Event series |
| `/health` | GET | API health status |
| `/search` | GET | Search markets and events |
| `/comments` | GET | Market comments |

### Fetching Markets

#### fetch_markets()

Fetch all available markets via the Gamma API.

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

### fetch_token_ids()

Fetch token IDs for a specific market from CLOB API. Token IDs are required for placing orders.

```python
# Fetch token IDs for a market
token_ids = exchange.fetch_token_ids('market_condition_id')
# Returns: ['NO_token_id', 'YES_token_id']

# For binary markets:
# token_ids[0] = NO token
# token_ids[1] = YES token
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `condition_id` | str | Yes | Market/condition identifier |

**Returns:** `list[str]` - List of token IDs

**Raises:**
- `ExchangeError` - If token IDs cannot be fetched

**Note:** This method is automatically called by the trading strategy when needed. Token IDs are cached in the market's metadata after first fetch.

## Trading

### Order Types

Polymarket CLOB API supports multiple order types:

| Order Type | Code | Description |
|------------|------|-------------|
| **Good-Til-Cancelled (GTC)** | `GTC` | Order remains active until filled or cancelled |
| **Good-Til-Date (GTD)** | `GTD` | Order expires at specified date/time |
| **Fill-Or-Kill (FOK)** | `FOK` | Order must be filled immediately in full or cancelled |
| **Immediate-Or-Cancel (IOC)** | `IOC` | Fill immediately, cancel remaining |
| **Post-Only** | `POST_ONLY` | Order only adds liquidity (maker only) |

**Default Order Type:** `GTC`

### CLOB API

The CLOB (Central Limit Order Book) API handles all trading operations.

**Base URL:** `https://clob.polymarket.com/`

#### Key Trading Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/order` | POST | Place single order |
| `/orders` | POST | Place multiple orders (batch) |
| `/order` | DELETE | Cancel order |
| `/orders` | GET | Get active orders |
| `/order/{id}` | GET | Get order details |
| `/trades` | GET | Get trade history |
| `/orderbook` | GET | Get orderbook for token |
| `/prices` | GET | Get current prices |
| `/spreads` | GET | Get bid-ask spreads |

### create_order()

Create a new order via the CLOB API.

```python
from dr_manhattan.models.order import OrderSide

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

### Data API

The Data API provides access to user-specific data, holdings, and on-chain activities.

**Base URL:** `https://data-api.polymarket.com/`

#### Available Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/holdings` | GET | Get user token holdings |
| `/positions` | GET | Get user positions |
| `/portfolio` | GET | Get portfolio summary |
| `/history` | GET | Get transaction history |
| `/health` | GET | API health status |

### fetch_balance()

Fetch account balance via the Data API.

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

Polymarket supports real-time data streaming via WebSocket for orderbook updates, user events, and market changes.

**WebSocket URL:** `wss://ws-subscriptions-clob.polymarket.com/ws/`

### WebSocket Channels

#### User Channel

Subscribe to user-specific events (requires authentication):

- Order fills
- Order cancellations
- Position updates
- Balance changes

```python
await ws.subscribe_user(user_address, callback)
```

#### Market Channel

Subscribe to market orderbook updates (no authentication required):

- Real-time orderbook changes
- Price updates
- Liquidity changes

```python
await ws.subscribe_market(asset_id, callback)
```

### Getting Started

```python
import asyncio
from dr_manhattan.exchanges.polymarket import Polymarket

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
from dr_manhattan.exchanges.polymarket_ws import PolymarketWebSocket

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

## Advanced Features

### Subgraph API

Polymarket provides a GraphQL interface for querying on-chain data through The Graph protocol.

**Endpoint:** Hosted by Goldsky (third-party provider)

**Features:**
- Real-time aggregate calculations
- Event indexing
- Volume metrics
- User positions tracking
- Market data queries
- Liquidity analytics

**Example Query:**

```graphql
query GetMarketData {
  market(id: "market_id") {
    id
    question
    outcomes
    volume
    liquidity
    positions {
      user
      outcome
      shares
    }
  }
}
```

**Use Cases:**
- Historical data analysis
- Portfolio tracking
- Market research
- Analytics dashboards

**Note:** The subgraph is open-source and can be self-hosted. See the [official documentation](https://docs.polymarket.com/developers/subgraph/overview) for details.

### Conditional Token Framework

Polymarket uses the Conditional Token Framework (CTF) for managing outcome tokens.

#### Key Operations

**1. Splitting USDC**

Convert USDC into conditional outcome tokens:

```python
# Split 100 USDC into YES and NO tokens
ctf.split(
    condition_id='condition_id',
    amount=100.0
)
# Result: 100 YES tokens + 100 NO tokens
```

**2. Merging Tokens**

Combine outcome tokens back into USDC:

```python
# Merge 100 YES + 100 NO tokens back to 100 USDC
ctf.merge(
    condition_id='condition_id',
    amount=100.0
)
```

**3. Redeeming Tokens**

Claim payouts for resolved markets:

```python
# Redeem winning tokens after market resolution
ctf.redeem(
    condition_id='resolved_condition_id',
    outcome='Yes'
)
```

**Token Properties:**
- Each YES/NO token represents a share in the outcome
- Total supply: YES + NO = Total USDC committed
- Price range: $0.00 - $1.00 per token
- Resolution: Winning tokens redeemable for $1.00 each

**Contract Addresses:**
- CTF Contract: Deployed on Polygon
- Exchange: Polygon PoS Chain (Chain ID: 137)

### Proxy Wallets

Polymarket supports proxy wallets for trading without direct on-chain transactions.

**Benefits:**
- Reduced gas costs
- Faster order execution
- Simplified UX
- No direct wallet interaction needed

**How It Works:**

1. **Create Proxy Wallet**
   ```python
   proxy = exchange.create_proxy_wallet()
   print(f"Proxy Address: {proxy.address}")
   ```

2. **Delegate Trading**
   - Proxy wallet manages orders on your behalf
   - Main wallet retains custody of funds
   - Can be revoked at any time

3. **Monitor Activity**
   ```python
   activity = exchange.get_proxy_activity()
   ```

**Security:**
- Proxy contracts are audited
- Limited permissions (trading only)
- Main wallet maintains full control

### Negative Risk

Negative risk occurs when holding NO tokens becomes more profitable than holding USDC.

**Concept:**

If you hold NO tokens and the YES price rises significantly, you can:

1. **Convert NO tokens** into a combination of:
   - Some YES tokens
   - Remaining USDC

2. **Benefit:** Lock in profit while maintaining exposure

**Example:**

```python
# Market at 80% YES, 20% NO
# You hold 100 NO tokens (worth ~$20)

# Convert to optimize:
result = exchange.convert_no_tokens(
    condition_id='condition_id',
    amount=100.0
)

# Result: ~20 YES tokens + $60 USDC
# Total value: $76 (20*0.8 + 60) vs original $20
```

**Use Cases:**
- Risk management
- Profit taking
- Portfolio optimization
- Trading opportunities

**Note:** This is an advanced feature. Understand the implications before using.

## SDKs and Tools

### Official SDKs

**Python:**
- [`py-clob-client`](https://github.com/Polymarket/py-clob-client) - Official Python client
- [`polymarket-apis`](https://pypi.org/project/polymarket-apis/) - Unified API with Pydantic validation

**TypeScript/JavaScript:**
- [`@polymarket/clob-client`](https://github.com/Polymarket/clob-client) - Official TypeScript client
- [`polymarket-kit`](https://github.com/HuakunShen/polymarket-proxy) - Fully typed SDK with OpenAPI schema

### Third-Party Tools

**Multi-Platform:**
- [PolyRouter](https://www.polyrouter.io/) - Unified API for multiple prediction markets
- [Dome API](https://docs.domeapi.io/) - Comprehensive prediction market data

**Python Libraries:**
- [`predmarket`](https://pypi.org/project/predmarket/) - Asyncio-native unified library

**Analytics & Data:**
- [OpticOdds](https://opticodds.com/sportsbooks/polymarket-api) - Sports betting API and real-time odds
- [FinFeedAPI](https://www.finfeedapi.com/products/prediction-markets-api) - Real-time and historical data

### Community Projects

Explore projects built by the community:
- Market analytics dashboards
- Trading bots
- Portfolio trackers
- Price alert systems

Visit the [API Showcase](https://docs.polymarket.com/quickstart/introduction/showcase) for featured projects.

## Examples

### Basic Market Fetching

```python
from dr_manhattan.exchanges.polymarket import Polymarket

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
from dr_manhattan.exchanges.polymarket import Polymarket
from dr_manhattan.models.order import OrderSide

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
from dr_manhattan.exchanges.polymarket import Polymarket

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

### Multi-Market Trading

```python
from dr_manhattan.exchanges.polymarket import Polymarket
from dr_manhattan.models.order import OrderSide

# Single exchange instance for multiple markets
exchange = Polymarket({
    'private_key': 'your_private_key',
    'verbose': True
})

# Get multiple markets
politics_markets = exchange.fetch_markets({'tags': 'politics', 'limit': 5})
sports_markets = exchange.fetch_markets({'tags': 'sports', 'limit': 5})

# Trade on different markets with same exchange instance
orders = []

for market in politics_markets:
    token_id = market.metadata.get('token_id')
    if token_id and market.prices.get('Yes', 0) < 0.4:
        order = exchange.create_order(
            market_id=market.id,
            outcome='Yes',
            side=OrderSide.BUY,
            price=0.35,
            size=50.0,
            params={'token_id': token_id}  # Specify per order
        )
        orders.append(order)

for market in sports_markets:
    token_id = market.metadata.get('token_id')
    if token_id and market.prices.get('No', 0) < 0.6:
        order = exchange.create_order(
            market_id=market.id,
            outcome='No',
            side=OrderSide.BUY,
            price=0.55,
            size=30.0,
            params={'token_id': token_id}  # Different token_id
        )
        orders.append(order)

print(f"Placed {len(orders)} orders across {len(politics_markets) + len(sports_markets)} markets")

# Monitor all orders
open_orders = exchange.fetch_open_orders()
print(f"Total open orders: {len(open_orders)}")
```

### Error Handling

```python
from dr_manhattan.exchanges.polymarket import Polymarket
from dr_manhattan.base.errors import NetworkError, RateLimitError, MarketNotFound

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

## Community and Support

### Official Resources

- **Discord Community**: Join the [Polymarket Discord](https://discord.gg/polymarket) for:
  - Developer support (#devs channel)
  - Trading discussions
  - Feature announcements
  - Community engagement

- **Twitter/X**: Follow [@Polymarket](https://x.com/Polymarket) for:
  - Platform updates
  - New features
  - Market highlights

- **Documentation**: [docs.polymarket.com](https://docs.polymarket.com/)
  - Developer Quickstart
  - API Reference
  - Integration Guides

### GitHub Repositories

Official open-source projects:

- [py-clob-client](https://github.com/Polymarket/py-clob-client) - Python client library
- [clob-client](https://github.com/Polymarket/clob-client) - TypeScript/JavaScript client
- [ctf-utils](https://github.com/Polymarket/ctf-utils) - Conditional Token Framework utilities
- [subgraph](https://github.com/Polymarket/polymarket-subgraph) - GraphQL subgraph

### Getting Help

1. **API Issues**: Post in Discord #devs channel
2. **Bug Reports**: Submit to relevant GitHub repository
3. **Feature Requests**: Discord or GitHub discussions
4. **General Questions**: Discord community channels

### Builder Program

Polymarket offers a Builder Program for developers:

- Order attribution rewards
- Technical support
- Partnership opportunities
- Featured in API Showcase

**Learn more**: [Builder Program Documentation](https://docs.polymarket.com/builders/introduction)

## Important Notes

### Token IDs for Trading

**The library automatically handles token ID retrieval:**

When you fetch markets using `fetch_markets()`, the Gamma API doesn't include token IDs (required for trading). The library solves this automatically:

1. **Lazy fetching**: Token IDs are fetched from CLOB API only when needed (when you select a market to trade)
2. **Automatic caching**: Once fetched, token IDs are cached in the market's metadata
3. **Method available**: You can manually fetch token IDs using `exchange.fetch_token_ids(condition_id)`

```python
# Token IDs are fetched automatically when needed
markets = exchange.fetch_markets()
selected_market = markets[0]

# When you try to trade, token ID is fetched automatically if not present
order = exchange.create_order(
    market_id=selected_market.id,
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.52,
    size=100.0
)

# Or manually fetch token IDs
token_ids = exchange.fetch_token_ids(selected_market.id)
# Returns: [NO_token_id, YES_token_id]
```

### Market Types

- **Binary Markets**: Two outcomes (Yes/No)
- **Categorical Markets**: Multiple outcomes
- **Scalar Markets**: Range of outcomes

### Price Format

Prices are represented as decimals between 0 and 1:
- `0.52` = 52% probability
- `1.00` = 100% probability (certain)

### Fees

Polymarket charges fees on trades:

- **Trading Fees**: 0.5-1% per transaction (on executed orders)
- **Gas Fees**: Minimal on Polygon network
- **Withdrawal Fees**: Network-dependent

**Fee Structure:**
- Maker orders: Lower fees (adds liquidity)
- Taker orders: Higher fees (removes liquidity)
- Post-only orders: Guaranteed maker fees

Check the [platform documentation](https://docs.polymarket.com/) for current fee structure.

### Best Practices

**1. Rate Limiting**
- Respect API rate limits (10 requests/second default)
- Implement exponential backoff
- Use WebSocket for real-time data instead of polling

**2. Order Management**
- Use post-only orders to avoid taker fees
- Batch orders when possible
- Cancel stale orders promptly

**3. Data Fetching**
- Use Gamma API for market discovery
- Use CLOB API for trading operations
- Use Data API for account information
- Use WebSocket for real-time updates

**4. Error Handling**
- Implement retry logic with exponential backoff
- Handle rate limit errors gracefully
- Log all API errors for debugging

**5. Security**
- Never commit private keys to version control
- Use environment variables for sensitive data
- Implement proper key rotation
- Monitor proxy wallet activity

**6. Multi-Market Trading**
- Initialize exchange with **Pattern A** for flexibility
- Pass `token_id` per order when trading on different markets
- Use WebSocket for real-time orderbook monitoring
- Use batch order endpoints when placing multiple orders
- Calculate fees before executing trades
- Monitor for slippage on large orders

### API Pricing

- **Free Access**: Core endpoints with generous rate limits
  - Up to 1,000 calls/hour for non-trading queries
  - Public market data
  - Orderbook access

- **Premium Features**: May require additional access
  - Extended historical data
  - Higher rate limits
  - Priority support

### Geographic Restrictions

**Note**: Polymarket may have geographic restrictions. Users should:
- Check local regulations before trading
- Ensure compliance with applicable laws
- Review terms of service

### Network Requirements

- **Blockchain**: Polygon PoS Chain
- **Chain ID**: 137 (Mainnet)
- **Currency**: USDC (bridged from Ethereum)
- **RPC Endpoint**: Standard Polygon RPC nodes

### Testing

**Dry Run Mode:**
```python
exchange = Polymarket({
    'private_key': 'test_key',
    'dry_run': True  # Simulates orders without execution
})
```

**Recommended Testing:**
- Start with small amounts
- Test in dry-run mode first
- Verify order placement and cancellation
- Monitor WebSocket connections
- Test error handling

## References

### Official Documentation

- [Polymarket Main Documentation](https://docs.polymarket.com/)
- [Developer Quickstart](https://docs.polymarket.com/quickstart)
- [API Endpoints](https://docs.polymarket.com/developers/CLOB/endpoints)
- [API Rate Limits](https://docs.polymarket.com/quickstart/api-rate-limits)
- [Glossary](https://docs.polymarket.com/quickstart/glossary)

### API Documentation

- [CLOB API](https://docs.polymarket.com/developers/CLOB/)
  - [Orders Overview](https://docs.polymarket.com/developers/CLOB/orders-overview)
  - [Place Order](https://docs.polymarket.com/developers/CLOB/place-order)
  - [Batch Orders](https://docs.polymarket.com/developers/CLOB/batch-orders)
  - [Cancel Orders](https://docs.polymarket.com/developers/CLOB/cancel-orders)
  - [Orderbook](https://docs.polymarket.com/developers/CLOB/orderbook)
  - [Pricing](https://docs.polymarket.com/developers/CLOB/pricing)
  - [Spreads](https://docs.polymarket.com/developers/CLOB/spreads)
  - [Trades](https://docs.polymarket.com/developers/CLOB/trades)

- [WebSocket API](https://docs.polymarket.com/developers/CLOB/websocket/)
  - [WSS Overview](https://docs.polymarket.com/developers/CLOB/wss-overview)
  - [WSS Quickstart](https://docs.polymarket.com/developers/CLOB/wss-quickstart)
  - [User Channel](https://docs.polymarket.com/developers/CLOB/user-channel)
  - [Market Channel](https://docs.polymarket.com/developers/CLOB/market-channel)

- [Gamma API](https://docs.polymarket.com/developers/gamma/)
  - [Events](https://docs.polymarket.com/developers/gamma/events)
  - [Markets](https://docs.polymarket.com/developers/gamma/markets)
  - [Sports](https://docs.polymarket.com/developers/gamma/sports)
  - [Tags](https://docs.polymarket.com/developers/gamma/tags)
  - [Series](https://docs.polymarket.com/developers/gamma/series)

- [Data API](https://docs.polymarket.com/developers/data-api/)
  - [Core Endpoints](https://docs.polymarket.com/developers/data-api/core)
  - [Misc Endpoints](https://docs.polymarket.com/developers/data-api/misc)

- [Subgraph](https://docs.polymarket.com/developers/subgraph/overview)
- [RTDS](https://docs.polymarket.com/developers/rtds/)

### Advanced Topics

- [Conditional Token Framework](https://docs.polymarket.com/developers/ctf/)
  - [Splitting USDC](https://docs.polymarket.com/developers/ctf/splitting)
  - [Merging Tokens](https://docs.polymarket.com/developers/ctf/merging)
  - [Redeeming Tokens](https://docs.polymarket.com/developers/ctf/redeeming)

- [Proxy Wallets](https://docs.polymarket.com/developers/proxy-wallet)
- [Negative Risk](https://docs.polymarket.com/developers/negative-risk)
- [Resolution](https://docs.polymarket.com/developers/resolution)
- [Liquidity Rewards](https://docs.polymarket.com/developers/rewards)

### Builder Program

- [Builder Program Introduction](https://docs.polymarket.com/builders/introduction)
- [Order Attribution](https://docs.polymarket.com/builders/order-attribution)
- [Builder Signing Server](https://docs.polymarket.com/builders/signing-server)
- [Relayer Client](https://docs.polymarket.com/builders/relayer-client)

### GitHub Repositories

- [py-clob-client](https://github.com/Polymarket/py-clob-client) - Official Python client
- [clob-client](https://github.com/Polymarket/clob-client) - Official TypeScript client
- [ctf-utils](https://github.com/Polymarket/ctf-utils) - Conditional Token Framework utilities
- [polymarket-subgraph](https://github.com/Polymarket/polymarket-subgraph) - GraphQL subgraph

### Community Resources

- [Discord Community](https://discord.gg/polymarket)
- [Twitter/X](https://x.com/Polymarket)
- [API Showcase](https://docs.polymarket.com/quickstart/introduction/showcase)

## See Also

- [Base Exchange Class](../../dr_manhattan/base/exchange.py)
- [WebSocket Implementation](../../dr_manhattan/base/websocket.py)
- [Polymarket WebSocket](../../dr_manhattan/exchanges/polymarket_ws.py)
- [Examples](../../examples/)
