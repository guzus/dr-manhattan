# Remote MCP Server (SSE)

Connect to Dr. Manhattan from Claude Desktop or Claude Code without local installation.

## Quick Start

**Server URL:** `https://dr-manhattan-mcp-production.up.railway.app/sse`

### Read-Only Mode (No Credentials)

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

Trading operations (`create_order`, `cancel_order`, `fetch_balance`, etc.) require credentials.

### Claude Code

#### Option 1: CLI Command (Recommended)

```bash
claude mcp add dr-manhattan \
  --transport sse \
  --url "https://dr-manhattan-mcp-production.up.railway.app/sse" \
  --header "X-Polymarket-Private-Key: 0x_your_private_key" \
  --header "X-Polymarket-Funder: 0x_your_funder_address"
```

#### Option 2: Global Configuration

Edit `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Private-Key": "0x_your_private_key",
        "X-Polymarket-Funder": "0x_your_funder_address"
      }
    }
  }
}
```

#### Option 3: Project Configuration

Create `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Private-Key": "0x_your_private_key",
        "X-Polymarket-Funder": "0x_your_funder_address"
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

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Private-Key": "0x_your_private_key",
        "X-Polymarket-Funder": "0x_your_funder_address"
      }
    }
  }
}
```

Restart Claude after configuration.

## Credential Headers

Pass credentials via HTTP headers. Only include headers for exchanges you want to use.

### Polymarket

| Header | Required | Description |
|--------|----------|-------------|
| `X-Polymarket-Private-Key` | Yes | Ethereum private key (0x...) |
| `X-Polymarket-Funder` | Yes | Funder address (0x...) |
| `X-Polymarket-Proxy-Wallet` | No | Proxy wallet address |
| `X-Polymarket-Signature-Type` | No | 0 = EOA (default), 1 = Poly Proxy, 2 = Gnosis |

### Limitless

| Header | Required | Description |
|--------|----------|-------------|
| `X-Limitless-Private-Key` | Yes | Ethereum private key (0x...) |

### Kalshi

| Header | Required | Description |
|--------|----------|-------------|
| `X-Kalshi-Api-Key` | Yes | Kalshi API key ID |
| `X-Kalshi-Private-Key` | Yes | Kalshi RSA private key (base64 or PEM) |

### Opinion

| Header | Required | Description |
|--------|----------|-------------|
| `X-Opinion-Private-Key` | Yes | Ethereum private key (0x...) |
| `X-Opinion-Api-Key` | No | Opinion API key |
| `X-Opinion-Multi-Sig-Addr` | No | Multi-sig address |

### Predict.fun

| Header | Required | Description |
|--------|----------|-------------|
| `X-Predictfun-Private-Key` | Yes | Ethereum private key (0x...) |
| `X-Predictfun-Api-Key` | No | Predict.fun API key |

## Multi-Exchange Configuration

Configure multiple exchanges by including all their headers:

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "type": "sse",
      "url": "https://dr-manhattan-mcp-production.up.railway.app/sse",
      "headers": {
        "X-Polymarket-Private-Key": "0x...",
        "X-Polymarket-Funder": "0x...",
        "X-Limitless-Private-Key": "0x...",
        "X-Kalshi-Api-Key": "your_api_key",
        "X-Kalshi-Private-Key": "your_private_key"
      }
    }
  }
}
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sse` | GET | SSE connection endpoint |
| `/messages/` | POST | MCP message endpoint |
| `/health` | GET | Health check |

## Security

- All traffic encrypted via HTTPS
- Credentials passed per-request, not stored on server
- Sensitive headers never logged
- Private keys exist in server memory only during request processing

### Best Practices

1. Use a dedicated wallet with limited funds for trading
2. Never commit configuration files with real credentials
3. Consider using environment variables for credentials
4. For large funds, prefer the [local MCP server](../README.md#mcp-server)

## Troubleshooting

### "Missing required credentials"

Ensure you've included all required headers for the exchange. Check the tables above.

### Connection timeout

The server may be cold-starting. Wait 10-30 seconds and retry.

### "Invalid credentials"

Verify your private key format:
- Ethereum keys: Must be 64 hex characters (with or without 0x prefix)
- Kalshi keys: Base64-encoded RSA private key

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
| Credentials | In .env file | Via HTTP headers |
| Security | Keys stay local | Keys sent to server |
| Latency | Faster | Slightly slower |
| Availability | When machine is on | Always on |

**Recommendation:** Use local server for significant funds, remote for convenience/testing.
