# Polymarket Exchange

Unified Python client for the Polymarket prediction market platform.  
Built as a mixin-based package — all methods are accessible directly on the `Polymarket` class.

```python
from dr_manhattan.exchanges import Polymarket

pm = Polymarket()
market = pm.search_markets(query="bitcoin")[0]
pm.get_price(market)
```

---

## Architecture

```
polymarket/
├── __init__.py              Polymarket class (combines all mixins)
├── polymarket_core.py       Constants, config, dataclasses, shared helpers
├── polymarket_gamma.py      Gamma API — market discovery & metadata
├── polymarket_clob.py       CLOB API — orderbook, pricing, orders, positions
├── polymarket_data.py       Data API — trades, leaderboard, analytics
├── polymarket_ctf.py        CTF contract — split, merge, redeem tokens
├── polymarket_ws.py         WebSocket — orderbook & user streams
├── polymarket_ws_ext.py     WebSocket — sports & RTDS streams
├── polymarket_builder.py    Builder/operator utilities
├── polymarket_operator.py   Operator management
└── polymarket_bridge.py     Cross-chain bridge helpers
```

---

## Dataclasses

Defined in `polymarket_core.py`:

| Class | Description |
|-------|-------------|
| `PublicTrade` | A single trade from the Data API — wallet, side, asset, price, size, timestamp, market metadata |
| `PricePoint` | A price history data point — timestamp + price |
| `Tag` | A market/event tag — id, label, slug, visibility flags |

Imported from `models/`:

| Class | Description |
|-------|-------------|
| `Market` | Core market object — id (condition_id), question, outcomes, prices, metadata (gamma_id, token_ids, slug) |
| `Order` | Order object — id, status, side, price, size, timestamps |
| `Position` | Position object — market, outcome, size, avg price, P&L |

---

## Market Identifiers

Most market-related methods accept `Market | str`.  
When a string is passed, it is auto-detected:

| Format | Example | Detection |
|--------|---------|-----------|
| Condition ID | `"0x3fd189cac928..."` | Starts with `0x`, 66 chars |
| Gamma ID | `"630806"` | Digits only, < 20 chars |
| Token ID | `"104698087530604..."` | Digits only, ≥ 20 chars |
| Slug | `"will-trump-win..."` | Everything else |

A `Market` object contains all of these internally — passing one avoids extra API calls.

---

## Files

### `polymarket_core.py` — Foundation
Constants, initialization, shared utilities.

| Method | Input | Output |
|--------|-------|--------|
| `normalize_token` | `token: str` | `str` |
| `parse_market_identifier` | `identifier: str` | `str` |

Internal helpers: `_resolve_condition_id`, `_resolve_gamma_id`, `_resolve_token_id`,
`_retry_on_failure`, `_collect_paginated`, `_ensure_market`.

---

### `polymarket_gamma.py` — Market Discovery
Gamma API for browsing markets, events, tags, series, and sports.

| Method | Input | Output |
|--------|-------|--------|
| `fetch_markets` | `params?: Dict` | `list[Market]` |
| `fetch_market` | `market: Market \| str` | `Market` |
| `fetch_markets_by_slug` | `slug_or_url: str` | `list[Market]` |
| `search_markets` | `query?: str` + filters | `list[Market]` |
| `find_tradeable_market` | `binary?: bool` | `Market` |
| `find_crypto_hourly_market` | `token_symbol?: str` | `tuple[Market, ...]` |
| `fetch_market_tags` | `market: Market \| str` | `list[Dict]` |
| `fetch_events` | `limit?, offset?` | `list[Dict]` |
| `fetch_event` | `event_id: str` | `Dict` |
| `fetch_event_by_slug` | `slug: str` | `Dict` |
| `fetch_event_tags` | `event_id: str` | `list[Dict]` |
| `fetch_tags` | `limit?, offset?` | `list[Dict]` |
| `fetch_tag_by_id` | `tag_id: str` | `Dict` |
| `get_tag_by_slug` | `slug: str` | `Tag` |
| `fetch_series` | `limit?, offset?` | `list[Dict]` |
| `fetch_series_by_id` | `series_id: str` | `Dict` |
| `fetch_sports_market_types` | — | `list[Dict]` |
| `fetch_sports_metadata` | — | `Dict` |
| `fetch_supported_assets` | — | `list[Dict]` |
| `get_gamma_status` | — | `Dict` |

---

### `polymarket_clob.py` — Orderbook & Trading
CLOB API for pricing, orderbooks, orders, positions, and price history.

| Method | Input | Output |
|--------|-------|--------|
| `get_price` | `market: Market \| str`, `outcome?` | `Dict` |
| `get_midpoint` | `market: Market \| str`, `outcome?` | `Dict` |
| `get_orderbook` | `market: Market \| str`, `outcome?` | `Dict` |
| `fetch_token_ids` | `market: Market \| str` | `list[str]` |
| `fetch_price_history` | `market: Market \| str`, `interval?` | `list[PricePoint]` |
| `calculate_spread` | `market: Market` | `float` |
| `calculate_expected_value` | `market: Market`, `outcome`, `price` | `float` |
| `get_optimal_order_size` | `market: Market`, `max_size` | `float` |
| `calculate_implied_probability` | `price: float` | `float` |
| `create_order` | `market_id, outcome, side, price, size` | `Order` 🔐 |
| `cancel_order` | `order_id` | `Order` 🔐 |
| `fetch_order` | `order_id` | `Order` 🔐 |
| `fetch_open_orders` | `market_id?` | `list[Order]` 🔐 |
| `fetch_positions` | `market_id?` | `list[Position]` 🔐 |
| `fetch_positions_for_market` | `market: Market` | `list[Position]` 🔐 |
| `fetch_balance` | — | `Dict` 🔐 |
| `get_websocket` | — | `PolymarketWebSocket` |
| `get_user_websocket` | — | `PolymarketUserWebSocket` 🔐 |
| `get_sports_websocket` | — | `PolymarketSportsWebSocket` |
| `get_rtds_websocket` | — | `PolymarketRTDSWebSocket` |

🔐 = requires private key / wallet configuration

---

### `polymarket_data.py` — Analytics & Public Data
Data API for trades, leaderboards, holdings, and portfolio analytics.

| Method | Input | Output |
|--------|-------|--------|
| `fetch_public_trades` | `market?: Market \| str`, `limit?` | `list[PublicTrade]` |
| `fetch_leaderboard` | `category?, time_period?, order_by?` | `list[Dict]` |
| `fetch_open_interest` | `market: Market \| str` | `Dict` |
| `fetch_top_holders` | `market: Market \| str`, `limit?` | `list[Dict]` |
| `fetch_user_activity` | `address: str`, `limit?` | `list[Dict]` |
| `fetch_closed_positions` | `address: str`, `limit?` | `list[Dict]` |
| `fetch_positions_data` | `address: str`, `limit?` | `list[Dict]` |
| `fetch_portfolio_value` | `address: str` | `Dict` |
| `fetch_traded_count` | `address: str` | `Dict` |
| `fetch_live_volume` | `event_id: int` | `Dict` |
| `fetch_builder_leaderboard` | `limit?, period?` | `list[Dict]` |
| `fetch_builder_volume` | `builder_id: str`, `period?` | `list[Dict]` |

Supports pagination — pass `limit > 500` and results are auto-fetched across pages.

---

### `polymarket_ctf.py` — On-chain Token Operations
CTF contract interactions for splitting, merging, and redeeming conditional tokens.

| Method | Input | Output |
|--------|-------|--------|
| `split` | `market: Market \| str`, `amount: float` | `Dict` 🔐 |
| `merge` | `market: Market \| str`, `amount: float` | `Dict` 🔐 |
| `redeem` | `market: Market \| str` | `Dict` 🔐 |
| `redeem_all` | — | `list[Dict]` 🔐 |
| `fetch_redeemable_positions` | — | `list[Dict]` 🔐 |

All methods require wallet (private key + funder/Safe address).

---

### `polymarket_ws.py` — Core WebSockets
Real-time orderbook and user event streams.

| Class | Description |
|-------|-------------|
| `PolymarketWebSocket` | Orderbook updates — subscribe to token_id channels |
| `PolymarketUserWebSocket` | User-specific events — orders, trades, positions 🔐 |

---

### `polymarket_ws_ext.py` — Extended WebSockets
Sports and real-time data streams.

| Class | Description |
|-------|-------------|
| `PolymarketSportsWebSocket` | Live sports event updates |
| `PolymarketRTDSWebSocket` | Real-Time Data Service stream |

---

### `polymarket_builder.py` — Builder Utilities
Helper methods for building complex operations.

### `polymarket_operator.py` — Operator Management
Operator approval and management for the CLOB client.

### `polymarket_bridge.py` — Bridge Helpers
Cross-chain deposit/withdrawal utilities.

---

## Quick Examples

```python
from dr_manhattan.exchanges import Polymarket

pm = Polymarket()

# Search and inspect
markets = pm.search_markets(query="bitcoin", limit=5)
market = markets[0]

# All of these work the same:
pm.get_price(market)                          # Market object
pm.get_price("0x3fd189cac928...")              # condition_id
pm.get_price("104698087530604...")             # token_id
pm.get_price("will-bitcoin-go-up")            # slug

# Yes/No pricing
pm.get_price(market, outcome="Yes")
pm.get_price(market, outcome="No")

# Analytics
pm.fetch_open_interest(market)
pm.fetch_top_holders(market, limit=10)
pm.fetch_public_trades(market=market, limit=100)

# Leaderboard
pm.fetch_leaderboard(category="CRYPTO", time_period="WEEK", limit=10)

# User analytics (by wallet address)
pm.fetch_portfolio_value("0x1234...")
pm.fetch_user_activity("0x1234...", limit=50)

# Pagination (auto-handles pages)
trades = pm.fetch_public_trades(limit=2000)  # fetches 4 pages of 500
```

---

## Stats

- **Total methods**: 76
- **Public (no auth)**: 60
- **Auth required**: 16
- **Lines of code**: ~4,900
- **Test coverage**: 64/64 public methods verified
