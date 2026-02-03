---
name: dr-manhattan
description: Trade prediction markets (Polymarket, Kalshi, Opinion, Limitless, Predict.fun) using a unified CCXT-style API. Use when the user wants to browse, search, or trade prediction markets, check balances and positions, manage orders, run market-making strategies, or compare prices across exchanges.
license: Apache-2.0
compatibility: Requires Python >= 3.11 and uv. Requires network access for exchange APIs. Optionally requires exchange credentials (private keys, API keys) for trading.
metadata:
  author: guzus
  version: "1.0"
---

# Dr. Manhattan - Prediction Market Trading

Dr. Manhattan is a unified API for prediction markets, similar to how CCXT works for cryptocurrency exchanges. It supports Polymarket, Kalshi, Opinion, Limitless, and Predict.fun through a single interface.

## Setup

Install dependencies with uv:

```bash
uv venv && uv pip install -e .
```

For MCP server (Claude integration):

```bash
uv sync --extra mcp
```

## Supported Exchanges

| Exchange     | Chain/Type     | Auth                                      |
|------------- |--------------- |------------------------------------------ |
| Polymarket   | Polygon        | Private key + funder address              |
| Kalshi       | Regulated CEX  | API key + RSA private key                 |
| Opinion      | BNB Chain      | API key + private key + multi-sig address |
| Limitless    | Base           | Private key                               |
| Predict.fun  | BNB Chain      | API key + private key (EOA or smart wallet) |

## Usage as a Python Library

### Read-Only (No Credentials)

```python
import dr_manhattan

polymarket = dr_manhattan.Polymarket({'timeout': 30})
markets = polymarket.fetch_markets()
for market in markets:
    print(f"{market.question}: {market.prices}")
```

### With Authentication

```python
import dr_manhattan

polymarket = dr_manhattan.Polymarket({
    'private_key': '0x...',
    'funder': '0x...',
})

order = polymarket.create_order(
    market_id="market_123",
    outcome="Yes",
    side=dr_manhattan.OrderSide.BUY,
    price=0.65,
    size=100,
    params={'token_id': 'token_id'}
)
```

### Exchange Factory

```python
from dr_manhattan import create_exchange, list_exchanges

print(list_exchanges())  # ['polymarket', 'opinion', 'limitless', 'predictfun', 'kalshi']
exchange = create_exchange('polymarket', {'timeout': 30})
```

## Usage via MCP Server

Dr. Manhattan exposes all trading capabilities as MCP tools. Configure in Claude Code (`~/.claude/settings.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "command": "/path/to/dr-manhattan/.venv/bin/python",
      "args": ["-m", "dr_manhattan.mcp.server"],
      "cwd": "/path/to/dr-manhattan"
    }
  }
}
```

### MCP Tools Reference

**Exchange Tools:**
- `list_exchanges` - List all available prediction market exchanges.
- `get_exchange_info(exchange)` - Get metadata and capabilities for an exchange.
- `validate_credentials(exchange)` - Check if credentials are valid without trading.

**Market Discovery:**
- `search_markets(exchange, query)` - Search markets by keyword. This is the fastest way to find markets about a topic.
- `fetch_markets(exchange, limit?, offset?)` - Fetch all markets with pagination.
- `fetch_market(exchange, market_id)` - Fetch a specific market by ID.
- `fetch_markets_by_slug(exchange, slug)` - Fetch markets by slug or URL (Polymarket, Limitless).
- `find_tradeable_market(exchange, binary?, limit?, min_liquidity?)` - Find a suitable market for trading.
- `find_crypto_hourly_market(exchange, token_symbol?)` - Find crypto hourly price markets (Polymarket).
- `fetch_token_ids(exchange, market_id)` - Get token IDs for a market.
- `parse_market_identifier(identifier)` - Extract slug from a Polymarket URL.
- `get_tag_by_slug(slug)` - Get Polymarket tag information.

**Orderbook:**
- `get_orderbook(exchange, token_id)` - Get full orderbook (bids and asks).
- `get_best_bid_ask(exchange, token_id)` - Get best bid and ask prices.

**Trading:**
- `create_order(exchange, market_id, outcome, side, price, size)` - Place a buy or sell order. Price is 0-1 (probability). Side is "buy" or "sell".
- `cancel_order(exchange, order_id, market_id?)` - Cancel a specific order.
- `cancel_all_orders(exchange, market_id?)` - Cancel all open orders.
- `fetch_order(exchange, order_id, market_id?)` - Get order details and fill status.
- `fetch_open_orders(exchange, market_id?)` - List all open orders.

**Account:**
- `fetch_balance(exchange)` - Get account balance (USDC).
- `fetch_positions(exchange, market_id?)` - Get current positions with PnL.
- `fetch_positions_for_market(exchange, market_id)` - Get positions for a specific market.
- `calculate_nav(exchange, market_id?)` - Calculate net asset value (cash + positions).

**Strategy Management:**
- `create_strategy_session(strategy_type, exchange, market_id, ...)` - Start a market-making strategy in the background.
- `get_strategy_status(session_id)` - Get real-time strategy status (NAV, positions, delta).
- `get_strategy_metrics(session_id)` - Get performance metrics (uptime, fills).
- `pause_strategy(session_id)` - Pause a running strategy.
- `resume_strategy(session_id)` - Resume a paused strategy.
- `stop_strategy(session_id, cleanup?)` - Stop a strategy and optionally cancel orders.
- `list_strategy_sessions` - List all active strategy sessions.

**Insider Verification:**
- `fetch_wallet_trades(exchange, wallet_address, market_id?, limit?)` - Fetch all trades for a wallet address.
- `analyze_wallet_performance(exchange, wallet_address, limit?)` - Analyze trading performance and patterns.
- `detect_insider_signals(exchange, wallet_address, market_id?, limit?)` - Detect potential insider trading signals.
- `compare_wallets(exchange, wallet_addresses, limit_per_wallet?)` - Compare trading patterns across multiple wallets.

## Common Workflows

### Find and Analyze a Market

1. Use `search_markets` with a keyword to find relevant markets.
2. Pick a market from the results and note its `id` and `metadata.clobTokenIds`.
3. Use `get_orderbook` with a token ID to see current bids and asks.
4. Use `get_best_bid_ask` for a quick spread check.

### Place a Trade

1. Find the market using `search_markets` or `fetch_markets_by_slug`.
2. Check `fetch_balance` to confirm available funds.
3. Get the orderbook with `get_orderbook` to see current prices.
4. Use `create_order` with the market ID, outcome ("Yes" or "No"), side ("buy" or "sell"), price (0-1), and size.
5. Monitor with `fetch_order` or `fetch_open_orders`.

### Run a Market-Making Strategy

1. Find a market with `search_markets` or `find_tradeable_market`.
2. Start with `create_strategy_session(strategy_type="market_making", exchange, market_id)`.
3. Monitor with `get_strategy_status` and `get_strategy_metrics`.
4. Control with `pause_strategy`, `resume_strategy`, or `stop_strategy`.

### Check Portfolio

1. `fetch_balance` to see cash.
2. `fetch_positions` to see all open positions with unrealized PnL.
3. `calculate_nav` for total portfolio value (cash + positions).

### Verify Insider Trading Activity

1. Use `fetch_wallet_trades` with a wallet address to get trading history.
2. Use `analyze_wallet_performance` to see metrics like win rate, market exposure, and timing patterns.
3. Use `detect_insider_signals` to identify suspicious patterns (market concentration, large trades, one-sided trading).
4. Use `compare_wallets` with multiple addresses to detect coordinated trading between accounts.

## Key Concepts

- **Prices are probabilities** ranging from 0 to 1 (exclusive). A price of 0.65 means the market implies a 65% chance.
- **Outcomes** are typically "Yes" and "No" for binary markets. Their prices sum to approximately 1.
- **Token IDs** are exchange-specific identifiers for each outcome of a market. Needed for orderbook queries.
- **Slugs** are human-readable URL identifiers (e.g., "trump-2024") used by Polymarket and Limitless.
- **Order types** supported: GTC (Good-Til-Cancel), FOK (Fill-Or-Kill), IOC (Immediate-Or-Cancel).

## Running Examples

```bash
uv run python examples/list_all_markets.py polymarket
uv run python examples/spread_strategy.py --exchange polymarket --slug fed-decision
uv run python examples/spike_strategy.py -e opinion -m 813 --spike-threshold 0.02
uv run python examples/verify_insider.py 0xWALLET_ADDRESS --detect-signals
uv run python examples/verify_insider.py --compare 0xWALLET1 0xWALLET2
```

## Data Models

**Market** fields: `id`, `question`, `outcomes`, `prices`, `volume`, `liquidity`, `close_time`, `tick_size`, `description`, `metadata` (contains `slug`, `clobTokenIds`).

**Order** fields: `id`, `market_id`, `outcome`, `side` (BUY/SELL), `price`, `size`, `filled`, `status` (PENDING/OPEN/FILLED/CANCELLED), `time_in_force`.

**Position** fields: `market_id`, `outcome`, `size`, `average_price`, `current_price`. Properties: `cost_basis`, `current_value`, `unrealized_pnl`.

**Orderbook** fields: `bids` (price, size descending), `asks` (price, size ascending). Properties: `best_bid`, `best_ask`, `mid_price`, `spread`.
