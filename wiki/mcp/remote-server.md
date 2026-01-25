# Remote MCP Server (SSE)

Connect to Dr. Manhattan from Claude Desktop or Claude Code without local installation.

## Quick Start

**Server URL:** `https://dr-manhattan-mcp-production.up.railway.app/sse`

### Step 1: Approve Server as Operator

Before trading, approve the server's address as an operator on Polymarket (one-time on-chain transaction).

Server operator address: `[To be announced]`

**How to approve:**
1. Go to [Polymarket](https://polymarket.com) and connect your wallet
2. Visit the CTF Exchange contract on PolygonScan
3. Call `approveOperator(server_address)`
4. Confirm the transaction in your wallet

### Step 2: Configure Your Client

#### Claude Code

```bash
claude mcp add dr-manhattan \
  --transport sse \
  --url "https://dr-manhattan-mcp-production.up.railway.app/sse" \
  --header "X-Polymarket-Wallet-Address: 0xYourWalletAddress"
```

Or edit `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Wallet-Address": "0xYourWalletAddress"
      }
    }
  }
}
```

#### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Wallet-Address": "0xYourWalletAddress"
      }
    }
  }
}
```

Restart Claude after configuration.

### Step 3: Verify Connection

In Claude Code, run:

```
/mcp
```

You should see `dr-manhattan` listed with available tools.

## Read-Only Mode

You can connect without any credentials to use read-only features:

```bash
claude mcp add dr-manhattan \
  --transport sse \
  --url "https://dr-manhattan-mcp-production.up.railway.app/sse"
```

Available without credentials:
- `fetch_markets` - Browse all prediction markets
- `fetch_market` - Get market details and prices
- `fetch_orderbook` - View order book depth
- `search_markets` - Search markets by keyword

## How It Works

1. You provide your wallet address via the `X-Polymarket-Wallet-Address` header
2. You approve the server as an operator on Polymarket (one-time)
3. The server signs orders on your behalf
4. Orders execute from your account

**Security:**
- Your private key never leaves your wallet
- You can revoke access anytime by calling `revokeOperator()`
- Each order is executed from your account, not the server's

## Available Operations

### Read Operations (All Exchanges)

| Tool | Description |
|------|-------------|
| `list_exchanges` | List available exchanges |
| `fetch_markets` | Browse all markets |
| `search_markets` | Search by keyword |
| `fetch_market` | Get market details |
| `fetch_orderbook` | View order book |
| `fetch_token_ids` | Get token IDs |

### Write Operations (Polymarket Only)

| Tool | Description |
|------|-------------|
| `create_order` | Place an order |
| `cancel_order` | Cancel an order |
| `cancel_all_orders` | Cancel all orders |
| `fetch_balance` | Check balance |
| `fetch_positions` | View positions |
| `fetch_open_orders` | List open orders |

## Troubleshooting

### "User has not approved operator"

You need to approve the server address as an operator on Polymarket. See Step 1 above.

### "Write operations are not supported for X"

Write operations are only available for Polymarket. For other exchanges, use the [local MCP server](../../README.md#mcp-server).

### Connection timeout

The server may be cold-starting. Wait 10-30 seconds and retry.

### Check server status

```bash
curl https://dr-manhattan-mcp-production.up.railway.app/health
```

## Self-Hosting

Deploy your own instance for full control:

```bash
# Clone repository
git clone https://github.com/guzus/dr-manhattan.git
cd dr-manhattan

# Install dependencies
uv sync --extra mcp

# Set your operator key
export POLYMARKET_OPERATOR_KEY="0xYourPrivateKey"

# Run SSE server
uv run python -m dr_manhattan.mcp.server_sse
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8080 | Server port |
| `LOG_LEVEL` | INFO | Logging level |
| `POLYMARKET_OPERATOR_KEY` | - | Server's private key for signing |

## Alternative: Builder Profile

If you prefer to use your own API credentials instead of operator mode, you can use Polymarket's Builder profile.

### Getting Credentials

1. Go to [Polymarket](https://polymarket.com) and connect your wallet
2. Click on your profile icon > **Settings** > **API Keys**
3. Click **Create API Key** and set a passphrase
4. Save your credentials (API Secret is shown only once)

### Configuration

```bash
claude mcp add dr-manhattan \
  --transport sse \
  --url "https://dr-manhattan-mcp-production.up.railway.app/sse" \
  --header "X-Polymarket-Api-Key: your_api_key" \
  --header "X-Polymarket-Api-Secret: your_api_secret" \
  --header "X-Polymarket-Passphrase: your_passphrase"
```

Or in JSON config:

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Api-Key": "your_api_key",
        "X-Polymarket-Api-Secret": "your_api_secret",
        "X-Polymarket-Passphrase": "your_passphrase"
      }
    }
  }
}
```
