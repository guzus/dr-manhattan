# Predict.fun

## Overview

- **Exchange ID**: `predict.fun` on the low-level exchange class; `predictfun` in `create_exchange()` and CLI examples
- **Exchange Name**: Predict.fun
- **Type**: Prediction Market
- **Base Class**: [Exchange](../../dr_manhattan/base/exchange.py)
- **REST API**: `https://api.predict.fun`
- **Testnet REST API**: `https://api-testnet.predict.fun`
- **Chain**: BNB Chain mainnet (`56`) or BNB testnet (`97`)
- **Documentation**: https://dev.predict.fun/

Predict.fun is a BNB-native prediction market with REST and WebSocket APIs for market data, orders, account activity, positions, search, and OAuth/delegated flows. This wrapper supports both EOA signing and Predict Account smart-wallet signing.

## Features

### Supported Methods

| Method | REST | WebSocket | Description |
|--------|------|-----------|-------------|
| `fetch_markets()` | Yes | No | Fetch active markets with pagination and filters |
| `fetch_market()` | Yes | No | Fetch a specific market by ID |
| `fetch_markets_by_slug()` | Yes | No | Resolve category/market slug or URL |
| `search_markets()` | Yes | No | Search categories and markets |
| `fetch_token_ids()` | Yes | No | Return outcome token IDs for a market |
| `get_orderbook()` | Yes | Yes | Fetch orderbook by market ID or token ID |
| `create_order()` | Yes | No | Create and submit signed orders |
| `cancel_order()` | Yes | No | Remove an order from the orderbook |
| `fetch_order()` | Yes | No | Fetch order by hash |
| `fetch_open_orders()` | Yes | No | List active user orders |
| `fetch_positions()` | Yes | No | List user positions |
| `fetch_balance()` | On-chain | No | Read USDT collateral balance |
| `get_websocket()` | No | Yes | Market WebSocket |
| `get_user_websocket()` | No | Yes | Authenticated user WebSocket |

### Exchange Capabilities

```python
exchange.describe()
# Returns id/name, host, chain_id, testnet, wallet mode, and supported methods.
```

## Authentication

### Public API

Predict.fun mainnet requires an API key for API access. Testnet does not require an API key according to the official docs.

```python
from dr_manhattan.exchanges.predictfun import PredictFun

exchange = PredictFun({
    "api_key": "your_api_key",
})
markets = exchange.fetch_markets({"limit": 20})
```

### EOA Trading

```python
exchange = PredictFun({
    "api_key": "your_api_key",
    "private_key": "your_eoa_private_key",
})
```

The wrapper requests `/v1/auth/message`, signs the returned message, exchanges it for a JWT, and signs orders using the Predict.fun CTF Exchange EIP-712 domain.

### Predict Account / Smart Wallet Trading

```python
exchange = PredictFun({
    "api_key": "your_api_key",
    "use_smart_wallet": True,
    "smart_wallet_address": "0xYourPredictAccount",
    "smart_wallet_owner_private_key": "your_privy_wallet_private_key",
})
```

Predict.fun's docs state that web app users have a Predict Account smart wallet. Programmatic smart-wallet access needs the Predict account address and the Privy wallet private key exported from account settings.

**Configuration Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `api_key` | str | Mainnet yes | API key from Predict.fun support |
| `private_key` | str | EOA trading | EOA private key for auth and order signing |
| `use_smart_wallet` | bool | No | Enable Predict Account signing |
| `smart_wallet_address` | str | Smart wallet trading | Predict Account/deposit address |
| `smart_wallet_owner_private_key` | str | Smart wallet trading | Owner/Privy wallet private key |
| `testnet` | bool | No | Use BNB testnet and `https://api-testnet.predict.fun` |
| `host` | str | No | Override API host |
| `timeout` | int | No | HTTP timeout |
| `verbose` | bool | No | Enable request/debug logging |

## Rate Limiting

Official docs list 240 requests per minute on testnet without an API key and 240 requests per minute by default on mainnet API keys. Tune the base `Exchange` retry settings if running crawlers or market makers.

```python
exchange = PredictFun({
    "api_key": "your_api_key",
    "rate_limit": 4,
    "max_retries": 3,
    "retry_delay": 1.0,
    "retry_backoff": 2.0,
})
```

## Market Data

### fetch_markets()

```python
markets = exchange.fetch_markets({
    "limit": 20,
    "status": "active",
})
```

The wrapper maps Predict.fun market responses into `Market` with outcomes, token IDs in metadata, prices, liquidity, volume, close time, and market status. It also caches token-to-market mappings so `get_orderbook(token_id)` can work after markets have been fetched.

### fetch_market()

```python
market = exchange.fetch_market("market_id")
```

Market IDs are Predict.fun market IDs. Use `fetch_markets_by_slug()` for category or market URLs.

### get_orderbook()

```python
book = exchange.get_orderbook("market_id_or_token_id")
```

For a second outcome/no token, the wrapper may invert YES-side prices to match the unified orderbook shape. Fetch market metadata first when you plan to address books by token ID.

## Trading

### create_order()

```python
from dr_manhattan.models.order import OrderSide

order = exchange.create_order(
    market_id="market_id",
    outcome="Yes",
    side=OrderSide.BUY,
    price=0.52,
    size=100,
    params={"token_id": "outcome_token_id"},
)
```

Operational caveats:

- `api_key` plus EOA or smart-wallet signing credentials are required.
- The wrapper can check and set collateral/exchange approvals before trading.
- Predict.fun uses USDT collateral on BNB Chain. Keep BNB available for approval and other on-chain transactions.
- `params` can carry order options such as expiration and self-trade-prevention strategy; keep values aligned with the official Predict.fun schema.

### cancel_order()

```python
order = exchange.cancel_order("order_hash")
```

Cancels are authenticated API calls and return the unified `Order` model where possible.

## Account

### fetch_balance()

```python
balance = exchange.fetch_balance()
# {"USDT": ..., "free": ..., "used": ..., "total": ...}
```

Balance is read from the configured BNB Chain USDT contract for the active wallet address. In smart-wallet mode the active address is `smart_wallet_address`; in EOA mode it is derived from `private_key`.

### fetch_positions()

```python
positions = exchange.fetch_positions()
positions_for_market = exchange.fetch_positions("market_id")
```

Authenticated position APIs require a valid JWT. The wrapper refreshes authentication on demand.

## WebSocket

```python
ws = exchange.get_websocket()
user_ws = exchange.get_user_websocket()
```

Predict.fun docs include WebSocket request/response formats, subscription topics, heartbeats, and a client example. Use the market WebSocket for orderbook/market subscriptions and the user WebSocket for authenticated order or position updates.

## Operational Notes

- Mainnet API keys are requested through the Predict.fun Discord support flow.
- The REST API is explicitly marked beta in official docs. Keep strategy code tolerant of schema additions, transient 4xx/5xx responses, and WebSocket reconnects.
- Official docs list primary infrastructure in `ap-northeast-1`; colocated or Asia-region runners should see lower latency.
- Factory usage differs from the exchange property: `create_exchange("predictfun", validate=False)` is correct, while `PredictFun().id` returns `predict.fun`.

## Examples

```python
from dr_manhattan import create_exchange

exchange = create_exchange("predictfun", validate=False)
for market in exchange.fetch_markets({"limit": 10}):
    print(market.id, market.question)
```

```bash
uv run python examples/list_all_markets.py predictfun --limit 20
```

## Sources

- Predict.fun Developer Documentation: https://dev.predict.fun/
- Predict.fun Python SDK: https://github.com/PredictDotFun/sdk-python
