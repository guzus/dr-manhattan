# Kalshi

## Overview

- **Exchange ID**: `kalshi`
- **Exchange Name**: Kalshi
- **Type**: Prediction Market (CFTC-Regulated)
- **Base Class**: [Exchange](../../dr_manhattan/base/exchange.py)
- **REST API**: `https://trading-api.kalshi.com/trade-api/v2/`
- **Demo API**: `https://demo-api.kalshi.co/trade-api/v2/`
- **WebSocket API**: `wss://api.elections.kalshi.com/trade-api/ws/v2`
- **Demo WebSocket**: `wss://demo-api.kalshi.co/trade-api/ws/v2`
- **Documentation**: https://docs.kalshi.com/

Kalshi is the first CFTC-regulated exchange for trading on event outcomes in the United States. Users can trade on real-world events including economics, politics, weather, and more.

### Key Features

- **Regulated Exchange**: First CFTC-regulated prediction market in the US
- **Multiple APIs**: REST, WebSocket, and FIX protocol support
- **Real-time Data**: WebSocket streaming for orderbook, trades, and fills
- **Institutional Support**: FIX 4.4 protocol for high-frequency trading
- **Market Tickers**: Simplified market identification using tickers
- **Event Groups**: Markets organized by events and series

### Quick Links

- [Official Documentation](https://docs.kalshi.com/)
- [Python SDK](https://pypi.org/project/kalshi-python/)
- [API Help Center](https://help.kalshi.com/kalshi-api)
- [Discord Community](https://discord.gg/kalshi) (#dev channel)
- [Starter Code](https://github.com/Kalshi/kalshi-starter-code-python)

## Table of Contents

- [Features](#features)
- [API Structure](#api-structure)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Market Data](#market-data)
- [Trading](#trading)
- [Account](#account)
- [WebSocket](#websocket)
- [SDKs and Tools](#sdks-and-tools)
- [Implementation Guide](#implementation-guide)
- [Examples](#examples)
- [Important Notes](#important-notes)
- [References](#references)

## Features

### Supported Methods

| Method | REST | WebSocket | Description |
|--------|------|-----------|-------------|
| `fetch_markets()` | YES | NO | Fetch all available markets |
| `fetch_market()` | YES | NO | Fetch a specific market by ticker |
| `create_order()` | YES | NO | Create a new order |
| `cancel_order()` | YES | NO | Cancel an existing order |
| `fetch_order()` | YES | NO | Fetch order details |
| `fetch_open_orders()` | YES | NO | Fetch all open orders |
| `fetch_positions()` | YES | NO | Fetch current positions |
| `fetch_balance()` | YES | NO | Fetch account balance |
| `watch_orderbook()` | NO | YES | Real-time orderbook updates |
| `watch_trades()` | NO | YES | Real-time trade feed |
| `watch_fills()` | NO | YES | Real-time fill notifications |

### Exchange Capabilities

```python
exchange.describe()
# Returns:
{
    'id': 'kalshi',
    'name': 'Kalshi',
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

Kalshi provides multiple API interfaces for different use cases:

### REST API (v2)

- **Production URL**: `https://trading-api.kalshi.com/trade-api/v2/`
- **Demo URL**: `https://demo-api.kalshi.co/trade-api/v2/`
- **Purpose**: Standard request-response operations

**Key Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/markets` | GET | List all markets |
| `/markets/{ticker}` | GET | Get market by ticker |
| `/events` | GET | List all events |
| `/events/{event_ticker}` | GET | Get event details |
| `/portfolio/orders` | POST | Create order |
| `/portfolio/orders` | GET | List open orders |
| `/portfolio/orders/{order_id}` | DELETE | Cancel order |
| `/portfolio/positions` | GET | Get positions |
| `/portfolio/balance` | GET | Get account balance |
| `/exchange/status` | GET | Exchange status |

### WebSocket API

- **Production URL**: `wss://api.elections.kalshi.com/trade-api/ws/v2`
- **Demo URL**: `wss://demo-api.kalshi.co/trade-api/ws/v2`
- **Purpose**: Real-time streaming data

**Available Channels:**

| Channel | Description | Auth Required |
|---------|-------------|---------------|
| `ticker` | Real-time price updates | No |
| `orderbook_delta` | Incremental orderbook changes | No |
| `orderbook_snapshot` | Full orderbook state | No |
| `trades` | Trade execution feed | No |
| `fill` | Order fill notifications | Yes |

### FIX Protocol

- **Version**: FIX 4.4
- **Purpose**: Institutional and high-frequency trading
- **Features**: Industry-standard, low-latency, professional trading integration

## Authentication

Kalshi uses RSA-PSS signature-based authentication for all private endpoints.

### 1. Public API (Read-Only)

No authentication required for public market data:

```python
from dr_manhattan.exchanges.kalshi import Kalshi

exchange = Kalshi()
markets = exchange.fetch_markets()
```

**Available without authentication:**
- Market listings and details
- Event information
- Public orderbook data
- Exchange status

### 2. API Key Authentication (Trading)

For trading operations, RSA key-pair authentication is required:

```python
exchange = Kalshi({
    'api_key': 'your_api_key_id',
    'private_key_path': '/path/to/private_key.pem',
    # OR provide key directly:
    'private_key': '-----BEGIN RSA PRIVATE KEY-----\n...',
    'demo': False,  # Set True for demo environment
    'verbose': True
})
```

**Authentication Process:**

1. Generate an RSA key pair (2048-bit recommended)
2. Register public key in Kalshi account settings
3. Sign requests using RSA-PSS signature scheme
4. Include required headers with each request

**Required Headers:**

| Header | Description |
|--------|-------------|
| `KALSHI-ACCESS-KEY` | Your API key identifier |
| `KALSHI-ACCESS-SIGNATURE` | RSA-PSS signature of the request |
| `KALSHI-ACCESS-TIMESTAMP` | Unix timestamp in milliseconds |

**Signature Generation:**

```python
# Signature payload format:
# timestamp + method + path (+ body for POST/PUT)

import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def sign_request(private_key, timestamp, method, path, body=''):
    message = f"{timestamp}{method}{path}{body}"
    signature = private_key.sign(
        message.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode()
```

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `api_key` | str | Yes* | API key identifier |
| `private_key` | str | Yes* | RSA private key (PEM format) |
| `private_key_path` | str | Yes* | Path to private key file |
| `demo` | bool | No | Use demo environment (default: False) |
| `verbose` | bool | No | Enable verbose logging (default: False) |
| `timeout` | int | No | Request timeout in seconds (default: 30) |

*Required for trading operations only. Either `private_key` or `private_key_path` is required.

### 3. WebSocket Authentication

WebSocket connections require the same RSA signature mechanism:

```python
# WebSocket authentication headers
headers = {
    'KALSHI-ACCESS-KEY': api_key,
    'KALSHI-ACCESS-SIGNATURE': sign_request(
        private_key,
        timestamp,
        'GET',
        '/trade-api/ws/v2'
    ),
    'KALSHI-ACCESS-TIMESTAMP': str(timestamp)
}
```

## Rate Limiting

Kalshi implements tiered rate limiting based on account level:

- **Default Rate Limit**: Varies by tier
- **Automatic Retry**: Built-in retry logic with exponential backoff
- **Max Retries**: 3 attempts (configurable)

### Rate Limit Tiers

| Tier | Description | Rate Limits |
|------|-------------|-------------|
| Standard | Individual traders | Base limits |
| Professional | Active traders | Enhanced throughput |
| Institutional | High-frequency operations | Maximum limits |

### Configuration

```python
exchange = Kalshi({
    'api_key': 'your_api_key',
    'private_key_path': '/path/to/key.pem',
    'rate_limit': 10,        # requests per second
    'max_retries': 3,        # retry attempts
    'retry_delay': 1.0,      # base delay in seconds
    'retry_backoff': 2.0,    # exponential backoff multiplier
    'timeout': 30            # request timeout in seconds
})
```

## Market Data

### Market Structure

Kalshi organizes markets hierarchically:

```
Series (e.g., "US Elections")
  └── Event (e.g., "2024 Presidential Election")
       └── Market (e.g., "Will Democrat win?")
```

### fetch_markets()

Fetch all available markets.

```python
markets = exchange.fetch_markets(params={
    'status': 'active',     # Filter by status
    'event_ticker': 'EVT',  # Filter by event
    'series_ticker': 'SER', # Filter by series
    'limit': 100,           # Limit results
    'cursor': 'abc123'      # Pagination cursor
})
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | str | No | Market status filter (active, closed, settled) |
| `event_ticker` | str | No | Filter by event ticker |
| `series_ticker` | str | No | Filter by series ticker |
| `limit` | int | No | Maximum results (default: 100) |
| `cursor` | str | No | Pagination cursor |

**Returns:** `list[Market]`

**Market Object:**
```python
Market(
    id='TICKER-ABC',           # Market ticker
    question='Will X happen?',
    outcomes=['Yes', 'No'],
    close_time=datetime,
    volume=50000.0,
    liquidity=25000.0,
    prices={'Yes': 0.65, 'No': 0.35},
    metadata={
        'ticker': 'TICKER-ABC',
        'event_ticker': 'EVENT-1',
        'yes_bid': 0.64,
        'yes_ask': 0.66,
        'no_bid': 0.34,
        'no_ask': 0.36,
        'open_interest': 10000,
        'volume_24h': 5000
    }
)
```

### fetch_market()

Fetch a specific market by ticker.

```python
market = exchange.fetch_market('TICKER-ABC')
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market ticker |

**Returns:** `Market`

**Raises:**
- `MarketNotFound` - Market does not exist

### fetch_events()

Fetch events (groups of related markets).

```python
events = exchange.fetch_events(params={
    'series_ticker': 'ELECTIONS',
    'status': 'active',
    'limit': 50
})
```

### get_orderbook()

Fetch the current orderbook for a market.

```python
orderbook = exchange.get_orderbook('TICKER-ABC')
# Returns:
{
    'yes': {
        'bids': [(0.64, 1000), (0.63, 2000)],
        'asks': [(0.66, 1500), (0.67, 3000)]
    },
    'no': {
        'bids': [(0.34, 1000), (0.33, 2000)],
        'asks': [(0.36, 1500), (0.37, 3000)]
    }
}
```

## Trading

### Order Types

Kalshi supports multiple order types:

| Order Type | Code | Description |
|------------|------|-------------|
| **Limit** | `limit` | Order at specified price |
| **Market** | `market` | Execute immediately at best price |

### Time-in-Force Options

| TIF | Description |
|-----|-------------|
| **GTC** | Good-Til-Cancelled - remains until filled or cancelled |
| **IOC** | Immediate-or-Cancel - fill what's possible, cancel rest |
| **FOK** | Fill-or-Kill - fill completely or cancel entirely |

### create_order()

Create a new order.

```python
from dr_manhattan.models.order import OrderSide

order = exchange.create_order(
    market_id='TICKER-ABC',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.65,             # Price in dollars (0-1)
    size=100,               # Number of contracts
    params={
        'type': 'limit',             # Order type
        'time_in_force': 'gtc',      # GTC, IOC, or FOK
        'client_order_id': 'my-123', # Optional client ID
        'post_only': False,          # Maker-only order
        'reduce_only': False         # Reduce position only
    }
)
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market_id` | str | Yes | Market ticker |
| `outcome` | str | Yes | 'Yes' or 'No' |
| `side` | OrderSide | Yes | BUY or SELL |
| `price` | float | Yes | Price per contract (0-1 in dollars) |
| `size` | int | Yes | Number of contracts |
| `params.type` | str | No | Order type (default: 'limit') |
| `params.time_in_force` | str | No | TIF (default: 'gtc') |
| `params.client_order_id` | str | No | Client-assigned ID |
| `params.post_only` | bool | No | Maker-only (default: False) |
| `params.reduce_only` | bool | No | Reduce only (default: False) |

**Returns:** `Order`

### cancel_order()

Cancel an existing order.

```python
order = exchange.cancel_order(
    order_id='order_id_123',
    market_id='TICKER-ABC'  # Optional
)
```

**Returns:** `Order`

### cancel_all_orders()

Cancel all open orders.

```python
result = exchange.cancel_all_orders(
    market_id='TICKER-ABC'  # Optional: filter by market
)
```

### fetch_order()

Fetch order details.

```python
order = exchange.fetch_order('order_id_123')
```

**Returns:** `Order`

### fetch_open_orders()

Fetch all open orders.

```python
orders = exchange.fetch_open_orders(
    market_id='TICKER-ABC',  # Optional filter
    params={}
)
```

**Returns:** `list[Order]`

## Account

### fetch_balance()

Fetch account balance.

```python
balance = exchange.fetch_balance()
# Returns: {'USD': 1000.00}
```

**Returns:** `Dict[str, float]` - Currency to balance mapping

### fetch_positions()

Fetch current positions.

```python
positions = exchange.fetch_positions(
    market_id='TICKER-ABC',  # Optional filter
    params={}
)
```

**Returns:** `list[Position]`

**Position Object:**
```python
Position(
    market_id='TICKER-ABC',
    outcome='Yes',
    size=100,                    # Number of contracts
    average_price=0.52,          # Average entry price
    current_price=0.65           # Current market price
)
```

### fetch_fills()

Fetch trade fills history.

```python
fills = exchange.fetch_fills(params={
    'ticker': 'TICKER-ABC',
    'limit': 100,
    'cursor': None
})
```

## WebSocket

Kalshi supports real-time data streaming via WebSocket.

### Getting Started

```python
import asyncio
from dr_manhattan.exchanges.kalshi import Kalshi

async def main():
    exchange = Kalshi({
        'api_key': 'your_api_key',
        'private_key_path': '/path/to/key.pem',
        'verbose': True
    })

    ws = exchange.get_websocket()

    def on_orderbook_update(ticker, orderbook):
        print(f"Orderbook update for {ticker}")
        print(f"  Best Bid: {orderbook['yes']['bids'][0]}")
        print(f"  Best Ask: {orderbook['yes']['asks'][0]}")

    await ws.connect()
    await ws.subscribe_orderbook('TICKER-ABC', on_orderbook_update)
    await ws._receive_loop()

asyncio.run(main())
```

### WebSocket Channels

#### Ticker Channel

Subscribe to real-time price updates:

```python
await ws.subscribe('ticker', ['TICKER-ABC'], callback)
```

#### Orderbook Delta Channel

Subscribe to incremental orderbook changes:

```python
await ws.subscribe('orderbook_delta', ['TICKER-ABC'], callback)
```

#### Orderbook Snapshot Channel

Subscribe to full orderbook state:

```python
await ws.subscribe('orderbook_snapshot', ['TICKER-ABC'], callback)
```

#### Trades Channel

Subscribe to trade execution feed:

```python
await ws.subscribe('trades', ['TICKER-ABC'], callback)
```

#### Fill Notifications (Authenticated)

Subscribe to your order fills:

```python
await ws.subscribe('fill', None, callback)  # Requires authentication
```

### Subscription Message Format

```python
{
    'id': 1,                              # Message ID
    'cmd': 'subscribe',                   # Command
    'params': {
        'channels': ['orderbook_delta'],  # Channel(s)
        'market_tickers': ['TICKER-ABC']  # Market(s)
    }
}
```

### Response Message Format

```python
{
    'type': 'orderbook_update',  # Message type
    'sid': 12345,                # Sequence ID
    'seq': 1,                    # Sequence number
    'msg': {
        'market_ticker': 'TICKER-ABC',
        'yes': [...],
        'no': [...]
    }
}
```

## SDKs and Tools

### Official SDKs

**Python:**
- [`kalshi-python`](https://pypi.org/project/kalshi-python/) - Official Python SDK (auto-generated from OpenAPI)
- [Starter Code](https://github.com/Kalshi/kalshi-starter-code-python) - Official examples

**Installation:**
```bash
pip install kalshi-python
```

### Community Libraries

**Python:**
- [`kalshi-python-unofficial`](https://github.com/humz2k/kalshi-python-unofficial) - Lightweight wrapper
- [`kalshi-py`](https://apty.github.io/kalshi-py/) - Type-safe client with daily updates

**Rust:**
- [`kalshi`](https://crates.io/crates/kalshi) - HTTPS and WebSocket wrapper

**Go:**
- [`ammario/kalshi`](https://pkg.go.dev/github.com/ammario/kalshi) - Go client library

## Implementation Guide

### Step 1: Create Exchange Class

Create `dr_manhattan/exchanges/kalshi.py`:

```python
from typing import Optional, Dict, Any, List
import time
import base64
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from ..base import Exchange
from ..models import Market, Order, OrderSide, OrderStatus, Position
from ..base.errors import (
    ExchangeError, AuthenticationError, MarketNotFound,
    NetworkError, RateLimitError, InvalidOrder
)


class Kalshi(Exchange):
    """
    Kalshi prediction market exchange implementation.
    CFTC-regulated exchange for trading on event outcomes.
    """

    # API endpoints
    PROD_REST_URL = "https://trading-api.kalshi.com/trade-api/v2"
    DEMO_REST_URL = "https://demo-api.kalshi.co/trade-api/v2"
    PROD_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        self.demo = self.config.get('demo', False)
        self.base_url = self.DEMO_REST_URL if self.demo else self.PROD_REST_URL
        self.ws_url = self.DEMO_WS_URL if self.demo else self.PROD_WS_URL

        # Authentication
        self._api_key = self.config.get('api_key')
        self._private_key = None

        # Load private key if provided
        private_key_path = self.config.get('private_key_path')
        private_key_pem = self.config.get('private_key')

        if private_key_path:
            with open(private_key_path, 'rb') as f:
                self._private_key = serialization.load_pem_private_key(
                    f.read(), password=None, backend=default_backend()
                )
        elif private_key_pem:
            self._private_key = serialization.load_pem_private_key(
                private_key_pem.encode(), password=None, backend=default_backend()
            )

    @property
    def id(self) -> str:
        return "kalshi"

    @property
    def name(self) -> str:
        return "Kalshi"

    def _sign_request(self, timestamp: int, method: str, path: str, body: str = '') -> str:
        """Generate RSA-PSS signature for request authentication."""
        if not self._private_key:
            raise AuthenticationError("Private key required for authenticated requests")

        message = f"{timestamp}{method}{path}{body}"
        signature = self._private_key.sign(
            message.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode()

    def _get_auth_headers(self, method: str, path: str, body: str = '') -> Dict[str, str]:
        """Generate authentication headers for a request."""
        timestamp = int(time.time() * 1000)
        signature = self._sign_request(timestamp, method, path, body)

        return {
            'KALSHI-ACCESS-KEY': self._api_key,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': str(timestamp),
            'Content-Type': 'application/json'
        }

    def _request(self, method: str, endpoint: str, params: Dict = None,
                 data: Dict = None, authenticated: bool = False) -> Dict:
        """Make HTTP request to Kalshi API."""
        url = f"{self.base_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        body = ''

        if data:
            import json
            body = json.dumps(data)

        if authenticated:
            if not self._api_key or not self._private_key:
                raise AuthenticationError("API key and private key required")
            headers = self._get_auth_headers(method, endpoint, body)

        try:
            self._check_rate_limit()

            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=body if body else None,
                timeout=self.timeout
            )

            if response.status_code == 401:
                raise AuthenticationError("Invalid authentication")
            elif response.status_code == 404:
                raise MarketNotFound(f"Resource not found: {endpoint}")
            elif response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            elif response.status_code >= 400:
                raise ExchangeError(f"API error: {response.text}")

            return response.json()

        except requests.exceptions.Timeout:
            raise NetworkError("Request timeout")
        except requests.exceptions.ConnectionError:
            raise NetworkError("Connection error")

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> List[Market]:
        """Fetch all available markets."""
        params = params or {}
        response = self._request('GET', '/markets', params=params)

        markets = []
        for m in response.get('markets', []):
            markets.append(self._parse_market(m))

        return markets

    def fetch_market(self, market_id: str) -> Market:
        """Fetch a specific market by ticker."""
        response = self._request('GET', f'/markets/{market_id}')
        return self._parse_market(response.get('market', {}))

    def _parse_market(self, data: Dict) -> Market:
        """Parse market data from API response."""
        from datetime import datetime

        close_time = None
        if data.get('close_time'):
            close_time = datetime.fromisoformat(
                data['close_time'].replace('Z', '+00:00')
            )

        yes_bid = data.get('yes_bid', 0) / 100.0
        yes_ask = data.get('yes_ask', 0) / 100.0

        return Market(
            id=data.get('ticker', ''),
            question=data.get('title', ''),
            outcomes=['Yes', 'No'],
            close_time=close_time,
            volume=float(data.get('volume', 0)),
            liquidity=float(data.get('open_interest', 0)),
            prices={
                'Yes': (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else 0,
                'No': 1 - ((yes_bid + yes_ask) / 2) if yes_bid and yes_ask else 0
            },
            metadata={
                'ticker': data.get('ticker'),
                'event_ticker': data.get('event_ticker'),
                'yes_bid': yes_bid,
                'yes_ask': yes_ask,
                'no_bid': 1 - yes_ask,
                'no_ask': 1 - yes_bid,
                'open_interest': data.get('open_interest'),
                'volume_24h': data.get('volume_24h'),
                'status': data.get('status'),
                'result': data.get('result')
            }
        )

    def create_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        params: Optional[Dict[str, Any]] = None
    ) -> Order:
        """Create a new order."""
        params = params or {}

        # Convert price to cents (Kalshi uses cents)
        price_cents = int(price * 100)

        order_data = {
            'ticker': market_id,
            'action': 'buy' if side == OrderSide.BUY else 'sell',
            'side': 'yes' if outcome.lower() == 'yes' else 'no',
            'count': int(size),
            'type': params.get('type', 'limit'),
        }

        if order_data['type'] == 'limit':
            if outcome.lower() == 'yes':
                order_data['yes_price'] = price_cents
            else:
                order_data['no_price'] = price_cents

        # Optional parameters
        if params.get('client_order_id'):
            order_data['client_order_id'] = params['client_order_id']
        if params.get('time_in_force'):
            order_data['time_in_force'] = params['time_in_force']
        if params.get('post_only'):
            order_data['post_only'] = params['post_only']
        if params.get('reduce_only'):
            order_data['reduce_only'] = params['reduce_only']

        response = self._request(
            'POST', '/portfolio/orders',
            data=order_data, authenticated=True
        )

        return self._parse_order(response.get('order', {}))

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Cancel an existing order."""
        response = self._request(
            'DELETE', f'/portfolio/orders/{order_id}',
            authenticated=True
        )
        return self._parse_order(response.get('order', {}))

    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Fetch order details."""
        response = self._request(
            'GET', f'/portfolio/orders/{order_id}',
            authenticated=True
        )
        return self._parse_order(response.get('order', {}))

    def fetch_open_orders(
        self,
        market_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        """Fetch all open orders."""
        query_params = params or {}
        if market_id:
            query_params['ticker'] = market_id

        response = self._request(
            'GET', '/portfolio/orders',
            params=query_params, authenticated=True
        )

        return [self._parse_order(o) for o in response.get('orders', [])]

    def _parse_order(self, data: Dict) -> Order:
        """Parse order data from API response."""
        from datetime import datetime

        status_map = {
            'resting': OrderStatus.OPEN,
            'pending': OrderStatus.PENDING,
            'executed': OrderStatus.FILLED,
            'canceled': OrderStatus.CANCELLED
        }

        created_at = None
        if data.get('created_time'):
            created_at = datetime.fromisoformat(
                data['created_time'].replace('Z', '+00:00')
            )

        return Order(
            id=data.get('order_id', ''),
            market_id=data.get('ticker', ''),
            outcome='Yes' if data.get('side') == 'yes' else 'No',
            side=OrderSide.BUY if data.get('action') == 'buy' else OrderSide.SELL,
            price=data.get('yes_price', data.get('no_price', 0)) / 100.0,
            size=float(data.get('count', 0)),
            filled=float(data.get('filled_count', 0)),
            status=status_map.get(data.get('status'), OrderStatus.PENDING),
            created_at=created_at,
            updated_at=created_at
        )

    def fetch_positions(
        self,
        market_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Position]:
        """Fetch current positions."""
        query_params = params or {}
        if market_id:
            query_params['ticker'] = market_id

        response = self._request(
            'GET', '/portfolio/positions',
            params=query_params, authenticated=True
        )

        positions = []
        for p in response.get('market_positions', []):
            positions.append(self._parse_position(p))

        return positions

    def _parse_position(self, data: Dict) -> Position:
        """Parse position data from API response."""
        return Position(
            market_id=data.get('ticker', ''),
            outcome='Yes' if data.get('position', 0) > 0 else 'No',
            size=abs(data.get('position', 0)),
            average_price=data.get('average_price', 0) / 100.0,
            current_price=data.get('market_price', 0) / 100.0
        )

    def fetch_balance(self) -> Dict[str, float]:
        """Fetch account balance."""
        response = self._request(
            'GET', '/portfolio/balance',
            authenticated=True
        )

        # Balance is returned in cents
        balance_cents = response.get('balance', 0)
        return {'USD': balance_cents / 100.0}

    def get_websocket(self):
        """Get WebSocket instance for real-time updates."""
        # Import and return WebSocket implementation
        from .kalshi_ws import KalshiWebSocket
        return KalshiWebSocket(self.config)
```

### Step 2: Create WebSocket Class

Create `dr_manhattan/exchanges/kalshi_ws.py`:

```python
import asyncio
import json
import time
import base64
from typing import Optional, Dict, Any, Callable

from ..base.websocket import OrderBookWebSocket


class KalshiWebSocket(OrderBookWebSocket):
    """WebSocket implementation for Kalshi real-time data."""

    PROD_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    DEMO_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        demo = config.get('demo', False)
        url = self.DEMO_URL if demo else self.PROD_URL
        super().__init__(url, config)

        self._api_key = config.get('api_key')
        self._private_key = None
        self._message_id = 0
        self._subscriptions = {}

        # Load private key for authenticated channels
        # ... (similar to main class)

    async def connect(self):
        """Connect to WebSocket with authentication headers."""
        import websockets

        headers = {}
        if self._api_key and self._private_key:
            headers = self._get_auth_headers()

        self.ws = await websockets.connect(self.url, extra_headers=headers)
        self.state = 'CONNECTED'

    async def subscribe(
        self,
        channel: str,
        tickers: list,
        callback: Callable
    ):
        """Subscribe to a channel for specific market tickers."""
        self._message_id += 1

        message = {
            'id': self._message_id,
            'cmd': 'subscribe',
            'params': {
                'channels': [channel]
            }
        }

        if tickers:
            message['params']['market_tickers'] = tickers

        await self.ws.send(json.dumps(message))

        # Store callback
        for ticker in (tickers or ['_global']):
            key = f"{channel}:{ticker}"
            self._subscriptions[key] = callback

    async def subscribe_orderbook(self, ticker: str, callback: Callable):
        """Subscribe to orderbook updates for a market."""
        await self.subscribe('orderbook_delta', [ticker], callback)

    async def _receive_loop(self):
        """Main receive loop for WebSocket messages."""
        async for message in self.ws:
            data = json.loads(message)
            await self._handle_message(data)

    async def _handle_message(self, data: Dict):
        """Handle incoming WebSocket message."""
        msg_type = data.get('type')

        if msg_type == 'subscribed':
            if self.verbose:
                print(f"Subscribed: {data}")
            return

        if msg_type == 'error':
            if self.verbose:
                print(f"WebSocket error: {data}")
            return

        # Route to appropriate callback
        ticker = data.get('msg', {}).get('market_ticker', '_global')

        for channel in ['ticker', 'orderbook_delta', 'orderbook_snapshot', 'trades', 'fill']:
            if msg_type.startswith(channel) or msg_type == channel:
                key = f"{channel}:{ticker}"
                if key in self._subscriptions:
                    callback = self._subscriptions[key]
                    callback(ticker, data.get('msg', {}))
                break
```

### Step 3: Register Exchange

Update `dr_manhattan/__init__.py`:

```python
from .exchanges.kalshi import Kalshi

exchanges = {
    "polymarket": Polymarket,
    "limitless": Limitless,
    "kalshi": Kalshi,  # Add this line
}

__all__ = [
    # ... existing exports
    "Kalshi",
]
```

### Step 4: Add Tests

Create `tests/test_kalshi.py`:

```python
import pytest
from unittest.mock import Mock, patch
from dr_manhattan.exchanges.kalshi import Kalshi
from dr_manhattan.models import Market, Order, OrderSide, Position


class TestKalshi:
    def test_exchange_id(self):
        exchange = Kalshi()
        assert exchange.id == "kalshi"
        assert exchange.name == "Kalshi"

    def test_demo_environment(self):
        exchange = Kalshi({'demo': True})
        assert exchange.demo is True
        assert 'demo' in exchange.base_url

    @patch('requests.request')
    def test_fetch_markets(self, mock_request):
        mock_request.return_value = Mock(
            status_code=200,
            json=lambda: {
                'markets': [{
                    'ticker': 'TEST-123',
                    'title': 'Test Market',
                    'yes_bid': 50,
                    'yes_ask': 52,
                    'volume': 10000,
                    'open_interest': 5000
                }]
            }
        )

        exchange = Kalshi()
        markets = exchange.fetch_markets()

        assert len(markets) == 1
        assert markets[0].id == 'TEST-123'
        assert markets[0].question == 'Test Market'
```

## Examples

### Basic Market Fetching

```python
from dr_manhattan.exchanges.kalshi import Kalshi

exchange = Kalshi({'verbose': True})

# Fetch active markets
markets = exchange.fetch_markets({'status': 'active', 'limit': 10})

for market in markets:
    print(f"{market.id}: {market.question}")
    print(f"  Yes: {market.prices['Yes']:.2%}")
    print(f"  Volume: {market.volume:,.0f}")
```

### Trading Example

```python
from dr_manhattan.exchanges.kalshi import Kalshi
from dr_manhattan.models.order import OrderSide

exchange = Kalshi({
    'api_key': 'your_api_key',
    'private_key_path': '/path/to/private_key.pem',
    'demo': True,  # Use demo for testing
    'verbose': True
})

# Check balance
balance = exchange.fetch_balance()
print(f"Balance: ${balance['USD']:.2f}")

# Create a buy order
order = exchange.create_order(
    market_id='TICKER-ABC',
    outcome='Yes',
    side=OrderSide.BUY,
    price=0.55,
    size=10,
    params={'type': 'limit', 'time_in_force': 'gtc'}
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
from dr_manhattan.exchanges.kalshi import Kalshi

async def stream_orderbook():
    exchange = Kalshi({
        'api_key': 'your_api_key',
        'private_key_path': '/path/to/key.pem',
        'verbose': True
    })

    ws = exchange.get_websocket()

    def on_update(ticker, data):
        print(f"Update for {ticker}:")
        print(f"  Yes Bid: {data.get('yes_bid')}")
        print(f"  Yes Ask: {data.get('yes_ask')}")

    await ws.connect()
    await ws.subscribe_orderbook('TICKER-ABC', on_update)

    try:
        await ws._receive_loop()
    except KeyboardInterrupt:
        await ws.disconnect()

asyncio.run(stream_orderbook())
```

### Error Handling

```python
from dr_manhattan.exchanges.kalshi import Kalshi
from dr_manhattan.base.errors import (
    NetworkError, RateLimitError, MarketNotFound,
    AuthenticationError, InvalidOrder
)

exchange = Kalshi({'verbose': True})

try:
    market = exchange.fetch_market('INVALID-TICKER')
except MarketNotFound as e:
    print(f"Market not found: {e}")
except NetworkError as e:
    print(f"Network error: {e}")
except RateLimitError as e:
    print(f"Rate limited: {e}")
except AuthenticationError as e:
    print(f"Auth error: {e}")
```

## Important Notes

### Market Identification

Kalshi uses **tickers** for market identification:
- Tickers are found at the top of every market page on Kalshi
- Example: `PRES-2024-DEM`, `ECON-CPI-DEC`
- Use `fetch_market(ticker)` to get market details

### Price Format

Kalshi prices are in **cents** internally but the dr_manhattan interface uses **dollars**:
- Input prices as decimals (0-1): `0.55` = 55 cents
- API returns prices in cents, automatically converted

### Binary Markets

All Kalshi markets are binary (Yes/No):
- Buy Yes = Betting the event happens
- Buy No = Betting the event doesn't happen
- Yes + No prices always sum to approximately $1.00

### Fees

Kalshi fee structure:
- Exchange fees apply to executed trades
- Fees vary by market type and volume
- Check [Kalshi fee schedule](https://kalshi.com/fees) for current rates

### Settlement

- Markets settle to $1.00 (winner) or $0.00 (loser)
- Settlement occurs after event outcome is verified
- Funds are automatically credited to account

### Geographic Restrictions

- Kalshi is US-only (CFTC-regulated)
- Users must verify US residency
- Some states may have additional restrictions

### Demo Environment

Always test in demo environment first:
```python
exchange = Kalshi({'demo': True})
```

Demo provides:
- Full API functionality
- Paper trading (no real money)
- Same market structure as production

## References

### Official Documentation

- [Kalshi Docs](https://docs.kalshi.com/)
- [Python SDK](https://docs.kalshi.com/python-sdk)
- [WebSocket Quick Start](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [Help Center](https://help.kalshi.com/kalshi-api)

### API Endpoints

- [Create Order](https://docs.kalshi.com/api-reference/portfolio/create-order)
- [Markets](https://docs.kalshi.com/api-reference/markets)
- [Portfolio](https://docs.kalshi.com/api-reference/portfolio)

### SDKs

- [kalshi-python (PyPI)](https://pypi.org/project/kalshi-python/)
- [Starter Code (GitHub)](https://github.com/Kalshi/kalshi-starter-code-python)

### Community

- [Discord](https://discord.gg/kalshi) - #dev channel for API support
- [Kalshi Blog](https://news.kalshi.com/)

## See Also

- [Base Exchange Class](../../dr_manhattan/base/exchange.py)
- [WebSocket Implementation](../../dr_manhattan/base/websocket.py)
- [Polymarket Exchange](./polymarket.md)
- [Examples](../../examples/)
