# Remote MCP Server (SSE)

Connect to Dr. Manhattan from Claude Desktop or Claude Code without local installation.

## Quick Start

**Server URL:** `https://dr-manhattan-mcp-production.up.railway.app/sse`

### Step 1: Connect Your Wallet

Go to [dr-manhattan.io/approve](https://dr-manhattan.io/approve) to:
1. Connect your Polymarket wallet
2. Approve Dr. Manhattan as an operator (one-time on-chain transaction)
3. Sign an authentication message (free, proves wallet ownership)
4. Copy your configuration

### Step 2: Add Configuration

Paste the configuration into your Claude settings:

**Claude Code:** `~/.claude/settings.json`
**Claude Desktop:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

Example configuration:
```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Wallet-Address": "0xYourWalletAddress",
        "X-Polymarket-Auth-Signature": "0xYourSignature...",
        "X-Polymarket-Auth-Timestamp": "1706123456"
      }
    }
  }
}
```

### Step 3: Verify Connection

Restart Claude and run `/mcp` to see available tools.

## Read-Only Mode

You can connect without any credentials to browse markets:

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

1. You connect your wallet and approve Dr. Manhattan as an operator
2. You sign a message proving wallet ownership (no gas, free)
3. The signature is included in your configuration
4. The server verifies your signature on each request
5. Orders execute from your account

**Security:**
- Your private key never leaves your wallet
- Signatures expire after 24 hours (re-authenticate if needed)
- You can revoke operator access anytime on-chain
- Each order executes from your account, not the server's

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

### "Signature has expired"

Your authentication signature is valid for 24 hours. Re-authenticate at [dr-manhattan.io/approve](https://dr-manhattan.io/approve).

### "User has not approved operator"

You need to approve the server address as an operator on Polymarket. Visit [dr-manhattan.io/approve](https://dr-manhattan.io/approve) and complete Step 1.

### "Signature does not match wallet address"

Make sure you're using the same wallet that you authenticated with. Re-authenticate if needed.

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

If you prefer to use your own API credentials instead of operator mode.

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
