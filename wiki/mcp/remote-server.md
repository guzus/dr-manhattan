# Remote MCP Server (SSE)

Connect to Dr. Manhattan from Claude Desktop or Claude Code without local installation.

## Security Model

The remote server uses a security-first approach:

- **Polymarket**: Full read/write via two authentication modes:
  - **Operator Mode** (Recommended): Provide your wallet address, server signs on your behalf
  - **Builder Profile**: Provide your API credentials (api_key, api_secret, passphrase)
- **Other exchanges**: Read-only (no private keys on server)

For write operations on non-Polymarket exchanges, use the [local MCP server](../../README.md#mcp-server).

## Quick Start

**Server URL:** `https://dr-manhattan-mcp-production.up.railway.app/sse`

### Read-Only Mode (No Credentials)

You can connect without any credentials to use read-only features on all exchanges:

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

### Claude Code

#### Option 1: CLI Command (Recommended)

**Read-only:**
```bash
claude mcp add dr-manhattan \
  --transport sse \
  --url "https://dr-manhattan-mcp-production.up.railway.app/sse"
```

**With Polymarket trading (Operator Mode - Recommended):**
```bash
claude mcp add dr-manhattan \
  --transport sse \
  --url "https://dr-manhattan-mcp-production.up.railway.app/sse" \
  --header "X-Polymarket-Wallet-Address: your_wallet_address"
```

**With Polymarket trading (Builder Profile):**
```bash
claude mcp add dr-manhattan \
  --transport sse \
  --url "https://dr-manhattan-mcp-production.up.railway.app/sse" \
  --header "X-Polymarket-Api-Key: your_api_key" \
  --header "X-Polymarket-Api-Secret: your_api_secret" \
  --header "X-Polymarket-Passphrase: your_passphrase"
```

#### Option 2: Global Configuration

Edit `~/.claude/settings.json`:

**Operator Mode (Recommended):**
```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Wallet-Address": "your_wallet_address"
      }
    }
  }
}
```

**Builder Profile:**
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

#### Option 3: Project Configuration

Create `.mcp.json` in your project root:

**Operator Mode (Recommended):**
```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Wallet-Address": "your_wallet_address"
      }
    }
  }
}
```

**Builder Profile:**
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

#### Verify Connection

After configuration, restart Claude Code and run:

```
/mcp
```

You should see `dr-manhattan` listed with available tools like `fetch_markets`, `create_order`, etc.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

**Operator Mode (Recommended):**
```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Wallet-Address": "your_wallet_address"
      }
    }
  }
}
```

**Builder Profile:**
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

Restart Claude after configuration.

## Polymarket Operator Mode (Recommended)

The server acts as an operator that signs orders on your behalf. This is the simplest and most secure authentication method.

### How It Works

1. You provide your wallet address to the server
2. You approve the server's address as an operator on Polymarket (one-time setup)
3. The server signs orders using its own key, with your address as the funder
4. You can revoke access anytime via the Polymarket contract

### Setup

**Step 1: Get Your Wallet Address**

Your wallet address is the public address of your Polymarket account (e.g., `0x1234...abcd`). You can find it in:
- MetaMask or other wallet extension
- Polymarket profile settings

**Step 2: Approve Server as Operator**

Before trading, you must approve the server's address as an operator on Polymarket. This is a one-time on-chain transaction.

Server operator address: `[To be announced]`

**How to approve:**
1. Go to [Polymarket](https://polymarket.com) and connect your wallet
2. Visit the CTF Exchange contract on PolygonScan
3. Call `approveOperator(server_address)`
4. Confirm the transaction in your wallet

**Step 3: Configure the Header**

Add your wallet address to the `X-Polymarket-Wallet-Address` header:

```bash
claude mcp add dr-manhattan \
  --transport sse \
  --url "https://dr-manhattan-mcp-production.up.railway.app/sse" \
  --header "X-Polymarket-Wallet-Address: 0xYourWalletAddress"
```

### Required Header

| Header | Description |
|--------|-------------|
| `X-Polymarket-Wallet-Address` | Your wallet address (the account to trade for) |

### Security

- Your private key never leaves your wallet
- Server only signs orders on your behalf
- You can revoke approval anytime by calling `revokeOperator()`
- Each order is executed from your account, not the server's

## Polymarket Builder Profile (Alternative)

If you prefer to use your own API credentials instead of operator mode.

### How It Works

1. You register as a trader on Polymarket and get Builder API credentials
2. These credentials allow the server to submit orders on your behalf
3. Your private key never leaves your machine
4. You can revoke access anytime from Polymarket

### Getting Credentials

To get your Polymarket API credentials:

1. Go to [Polymarket](https://polymarket.com) and connect your wallet
2. Click on your profile icon in the top right corner
3. Select **Settings** from the dropdown menu
4. Navigate to the **API Keys** section
5. Click **Create API Key**
6. Set a passphrase (you'll need to remember this)
7. Copy and save your credentials:
   - **API Key** - Your unique identifier
   - **API Secret** - Your secret key (shown only once)
   - **Passphrase** - The passphrase you set

**Important:**
- The API Secret is only shown once when created. Save it securely.
- Keep your credentials private. Never share them publicly.
- You can create multiple API keys and revoke them anytime.

### Required Headers

| Header | Description |
|--------|-------------|
| `X-Polymarket-Api-Key` | Your Polymarket API key |
| `X-Polymarket-Api-Secret` | Your Polymarket API secret |
| `X-Polymarket-Passphrase` | Your Polymarket passphrase |

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

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sse` | GET | SSE connection endpoint |
| `/messages/` | POST | MCP message endpoint |
| `/health` | GET | Health check |

## Security

- **No private keys**: Server never receives your private key
- **Builder profile**: Uses Polymarket's official delegation system
- **Read-only for others**: Other exchanges cannot perform write operations
- **HTTPS only**: All traffic encrypted
- **Revocable**: You can revoke API access anytime on Polymarket

### Best Practices

1. Use separate API credentials for the remote server
2. Never commit configuration files with real credentials
3. Consider using environment variables for credentials
4. Monitor your Polymarket activity regularly

## Troubleshooting

### "Write operations are not supported for X"

Write operations (create_order, cancel_order, etc.) are only available for Polymarket. For other exchanges, use the local MCP server.

### "Missing required credentials for polymarket"

Ensure you've included all three Polymarket headers:
- `X-Polymarket-Api-Key`
- `X-Polymarket-Api-Secret`
- `X-Polymarket-Passphrase`

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

# Run SSE server
uv run python -m dr_manhattan.mcp.server_sse
```

### Docker

```bash
docker build -t dr-manhattan-mcp .
docker run -p 8080:8080 dr-manhattan-mcp
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8080 | Server port |
| `LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

## Local vs Remote

| Feature | Local Server | Remote Server (SSE) |
|---------|-------------|---------------------|
| Setup | Requires Python, uv | None |
| Polymarket | Full access | Full access (Builder profile) |
| Other exchanges | Full access | Read-only |
| Security | Keys stay local | No private keys needed |
| Latency | Faster | Slightly slower |
| Availability | When machine is on | Always on |

**Recommendation:** Use remote server for Polymarket trading and market research. Use local server if you need write operations on other exchanges.
