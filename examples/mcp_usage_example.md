# Dr. Manhattan MCP Usage Guide

Real-world examples and setup guide for using Dr. Manhattan MCP server with AI agents like Claude Desktop.

## Table of Contents
- [Security Warning](#security-warning)
- [Setup](#setup)
- [Understanding Polymarket Wallets](#understanding-polymarket-wallets)
- [Signature Types Explained](#signature-types-explained)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)

## Security Warning

**CRITICAL: Private Key Security**

Your private key gives full control over your wallet funds. Follow these security practices:

1. **Never commit `.env` to version control** - The `.gitignore` should exclude `.env`
2. **Never share your private key** - Not with support, not in screenshots
3. **Use a dedicated wallet** - Create a separate wallet for trading, not your main holdings
4. **Limit funds** - Only deposit what you're willing to risk
5. **Verify .gitignore** - Run `git status` to confirm `.env` is not tracked

```bash
# Verify .env is properly ignored
git status --ignored | grep ".env"
# Should show: .env
```

Consider using hardware wallets or encrypted keystore files for additional security. The MCP server loads credentials at startup, so restart after any credential changes.

## Setup

### 1. Installation

Install Dr. Manhattan with MCP support:

```bash
# Clone the repository
git clone https://github.com/guzus/dr-manhattan.git
cd dr-manhattan

# Install with MCP dependencies
uv pip install -e ".[mcp]"
```

### 2. Environment Configuration

Create a `.env` file in the project root:

```bash
# Copy the example file
cp .env.example .env

# Edit with your credentials
nano .env  # or use your preferred editor
```

**Required environment variables for Polymarket:**

```bash
# REQUIRED: Your MetaMask wallet private key (for signing transactions)
POLYMARKET_PRIVATE_KEY=your_private_key_here

# REQUIRED: Your MetaMask wallet address (THIS wallet is used for ALL trading)
POLYMARKET_FUNDER=your_metamask_address_here
```

**Optional environment variables (defaults are in code):**

```bash
# OPTIONAL: Your Polymarket proxy wallet address (for display only)
# POLYMARKET_PROXY_WALLET=your_polymarket_proxy_address_here

# OPTIONAL: Signature type (default: 0 for normal MetaMask accounts)
# POLYMARKET_SIGNATURE_TYPE=0  # 0=EOA (default), 1=POLY_PROXY, 2=Gnosis Safe
```

### 3. Configure Claude Desktop

Add the MCP server to your Claude Desktop configuration file:

**Windows (WSL):**
- File location: `C:\Users\YourName\AppData\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "command": "wsl",
      "args": [
        "/home/youruser/dr-manhattan/.venv/bin/python3",
        "-m",
        "dr_manhattan.mcp.server"
      ],
      "cwd": "/home/youruser/dr-manhattan"
    }
  }
}
```

**Linux/WSL (native):**
- File location: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "command": "/home/youruser/dr-manhattan/.venv/bin/python3",
      "args": ["-m", "dr_manhattan.mcp.server"],
      "cwd": "/home/youruser/dr-manhattan"
    }
  }
}
```

**macOS:**
- File location: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "dr-manhattan": {
      "command": "/Users/youruser/dr-manhattan/.venv/bin/python3",
      "args": ["-m", "dr_manhattan.mcp.server"],
      "cwd": "/Users/youruser/dr-manhattan"
    }
  }
}
```

**Important:**
- Replace `/home/youruser/dr-manhattan` with your actual project path
- Use absolute paths, not relative paths
- Restart Claude Desktop after configuration changes

### 4. Verify Setup

After restarting Claude Desktop, verify the MCP server is working:

```
"Check available exchanges"
```

You should see a list including Polymarket, Opinion, and Limitless.

## Understanding Polymarket Wallets

Polymarket uses a **dual-wallet system** that can be confusing for API/MCP users:

### Funder Wallet (MetaMask)
- **Your actual trading wallet** for API/MCP usage
- All buy/sell orders execute through this wallet
- All profits/losses are reflected in this wallet
- **You MUST have USDC in this wallet** to trade via MCP (minimum 5 USDC for most markets)

### Proxy Wallet (Polymarket)
- Created automatically by Polymarket website
- Used ONLY for web-based trading
- **Cannot be used for API/MCP trading**
- The MCP server can display this balance for reference, but all trades use the Funder wallet

### Money Flow Example

```
Initial State:
  Funder Wallet: 20 USDC
  Proxy Wallet: 8 USDC (from web deposit)

Buy Order (10 USDC via MCP):
  Funder Wallet: 10 USDC (-10)
  Tokens: +10 Yes tokens

Sell Order (tokens appreciate to 12 USDC):
  Funder Wallet: 22 USDC (+12)
  Tokens: 0

Result: 2 USDC profit in Funder Wallet
```

### Balance Display in MCP

When you check your balance via MCP, you'll see both wallets:

```json
{
  "funder_balance": 20.82,      // ← Your trading balance (used for orders)
  "funder_wallet": "0xbABC...",
  "proxy_balance": 8.86,         // ← Reference only (web balance)
  "proxy_wallet": "0x821A...",
  "trading_wallet": "funder",
  "note": "Trading uses funder wallet balance. Ensure funder wallet has sufficient USDC."
}
```

### How to Fund Your Funder Wallet

**Option 1: Withdraw from Polymarket Proxy Wallet**

If you already deposited USDC via the Polymarket website:

1. Go to [polymarket.com](https://polymarket.com) and connect your MetaMask
2. Navigate to **Settings** → **Wallet**
3. Click **"Withdraw"**
4. Transfer USDC from your Proxy Wallet to your Funder wallet (MetaMask address)
5. Wait for the transaction to confirm on Polygon

**Option 2: Direct Deposit**

1. Send USDC directly to your Funder wallet address
2. **Important:** Must be USDC on **Polygon network** (not Ethereum or other chains)
3. You can bridge USDC to Polygon using:
   - [Polygon Bridge](https://wallet.polygon.technology/bridge)
   - Exchange withdrawal (select Polygon network)

**Option 3: Find Your Proxy Wallet Address (Optional)**

To display your Polymarket web balance in MCP:

1. Go to [polymarket.com](https://polymarket.com)
2. Click your profile → **Settings** → **Wallet**
3. Copy the **"Proxy Wallet Address"** (starts with 0x)
4. Add it to `.env` as `POLYMARKET_PROXY_WALLET`

## Signature Types Explained

The `POLYMARKET_SIGNATURE_TYPE` setting determines how orders are signed and which wallet system is used.

### Overview

| Type | Name | Description | Use Case | Status |
|------|------|-------------|----------|--------|
| **0** | EOA (Externally Owned Account) | Direct wallet signing | **Normal MetaMask accounts** | ✅ Recommended |
| **1** | POLY_PROXY | Polymarket Proxy system | Legacy proxy wallets | ⚠️ Deprecated |
| **2** | POLY_GNOSIS_SAFE | Gnosis Safe multisig | Multisig wallet users | ⚠️ Specialized use only |

### Type 0: EOA (Recommended for Most Users)

**What it does:**
- Uses your MetaMask wallet (Funder wallet) directly for all trading
- Signs orders with your private key using standard Ethereum signatures
- All transactions execute from your Funder wallet
- All profits/losses go to your Funder wallet

**When to use:**
- ✅ You have a normal MetaMask wallet
- ✅ You're using MCP/API for trading
- ✅ You want simple, direct wallet control

**Configuration:**
```bash
POLYMARKET_SIGNATURE_TYPE=0
```

**Requirements:**
- USDC must be in your Funder wallet (MetaMask address)
- Minimum balance: 5 USDC (for most markets)

### Type 1: POLY_PROXY (Legacy)

**What it does:**
- Attempts to use the Polymarket Proxy wallet system
- **Currently not functional for MCP/API trading**

**When NOT to use:**
- ❌ For any MCP/API trading
- ❌ Results in "invalid signature" errors

**Status:** Deprecated for MCP usage

### Type 2: POLY_GNOSIS_SAFE (Specialized)

**What it does:**
- Uses Gnosis Safe multisig wallet signatures
- Requires special multisig wallet setup

**When to use:**
- ⚠️ Only if you're using a Gnosis Safe wallet
- ⚠️ Requires additional configuration beyond this guide

**When NOT to use:**
- ❌ With normal MetaMask wallets
- ❌ Results in "invalid signature" errors

**Status:** Only for advanced users with Gnosis Safe

### Common Signature Type Errors

**Error: "invalid signature"**

Possible causes:
1. Using `signature_type=2` with a normal MetaMask wallet
   - **Solution:** Change to `signature_type=0`

2. Using `signature_type=1`
   - **Solution:** Change to `signature_type=0`

3. Mismatched private key and funder address
   - **Solution:** Verify your private key matches your funder address

**Error: "not enough balance / allowance"**

Possible causes:
1. USDC is in Proxy wallet, not Funder wallet
   - **Solution:** Withdraw from Proxy to Funder wallet (see above)

2. Insufficient USDC in Funder wallet
   - **Solution:** Deposit USDC to Funder wallet (minimum 5 USDC)

3. USDC allowance not set for exchange contracts
   - **Solution:** Approve USDC spending (requires MATIC for gas)

### Signature Type Summary

**For 99% of users:**
```bash
POLYMARKET_SIGNATURE_TYPE=0
```

**Key Points:**
- ✅ Use type 0 for normal MetaMask wallets
- ✅ Ensure USDC is in your Funder wallet
- ❌ Do NOT use type 1 or 2 unless you have specific requirements
- ❌ Proxy wallet funds are NOT accessible via MCP (must withdraw to Funder first)

## Usage Examples

### Example 1: Market Research

**User Query:**
```
"Find the most active prediction markets about the 2024 election"
```

**Agent Actions:**
```python
1. [fetch_markets] with filters for election-related topics
2. Sort by volume
3. Filter for active markets
4. Present top result
```

**Response:**
```
Found: "Will Donald Trump win the 2024 US Presidential Election?"

Market Details:
• Exchange: Polymarket
• Market ID: 0x0f0...
• Type: Binary (Yes/No)
• Current Prices:
  - Yes: $0.52 (52% implied probability)
  - No: $0.48 (48% implied probability)
• Spread: $0.04 (4%)
• Volume (24h): $45.2M
• Total Volume: $320.5M
• Liquidity: $2.1M
• Close Date: 2024-11-05

Trading Info:
• Tick Size: $0.01
• Min Order: $5
• Supported Orders: GTC, GTD, FOK, IOC
```

### Example 2: Portfolio Analysis

**User Query:**
```
"What's my current exposure across all exchanges?"
```

**Agent Actions:**
```python
# For each exchange:
1. [fetch_balance] to get cash
2. [fetch_positions] to get open positions
3. [calculate_nav] to get net asset value

# Aggregate results
```

**Response:**
```
Portfolio Summary:

Total NAV: $5,234.56

By Exchange:

Polymarket:
  Trading Balance (Funder): $1,234.56
  Web Balance (Proxy): $500.00 (reference only)
  Open Positions: 3
  Position Value: $1,145.23
  Total NAV: $2,379.79

Opinion:
  Cash: $1,850.00
  Open Positions: 2
  Position Value: $1,004.77
  Total NAV: $2,854.77

Limitless:
  Cash: $0.00
  Open Positions: 0
  Position Value: $0.00
  Total NAV: $0.00

Top Positions:
1. Trump election win (Polymarket): +$234.56 (+23.4%)
2. Fed rate cut Q1 (Opinion): -$45.23 (-4.5%)
3. Bitcoin >$50k (Polymarket): +$156.78 (+15.7%)
```

### Example 3: Execute Trade

**User Query:**
```
"Buy 10 USDC worth of 'Yes' on the Trump election market at 0.52"
```

**Agent Actions:**
```python
1. [fetch_markets_by_slug] to find market
2. [get_best_bid_ask] to check current prices
3. [create_order] to place order
```

**Response:**
```
Order Placed Successfully:

Market: Will Trump win the 2024 US Presidential Election?
Side: Buy Yes
Price: $0.52 per share
Size: 19.23 shares (10 USDC)
Order ID: 0xabc123...
Status: Live

Estimated Outcome:
• If Yes wins: Receive 19.23 USDC (+92.3%)
• If No wins: Lose 10 USDC (-100%)
• Break-even price: $0.52
```

### Example 4: Market Making Strategy

**User Query:**
```
"Start market making on the Bitcoin >$50k market with 5% spread"
```

**Agent Actions:**
```python
1. [fetch_market] to get market details
2. [create_strategy_session] with parameters:
   - strategy_type: "market_making"
   - max_position: 100
   - spread: 0.05
   - order_size: 10
```

**Response:**
```
Market Making Strategy Started:

Session ID: mm_btc_001
Market: Bitcoin >$50k by end of 2024
Strategy: Market Making
Spread: 5%
Order Size: $10 per side
Max Position: ±100 shares

Current State:
• Bid: $0.47 (10 shares)
• Ask: $0.53 (10 shares)
• Net Position: 0 shares
• Unrealized P&L: $0.00

The strategy will automatically:
- Place bid/ask orders around market price
- Adjust prices as market moves
- Maintain position limits
- Collect spread as profit

Monitor with: "Show market making status"
Stop with: "Stop market making"
```

## Troubleshooting

### MCP Server Not Connecting

**Symptoms:**
- Claude Desktop doesn't show Dr. Manhattan tools
- Connection errors in Claude Desktop logs

**Solutions:**
1. Check the MCP server is running:
   ```bash
   ps aux | grep dr_manhattan.mcp.server
   ```

2. Verify configuration file path is correct
3. Check logs in Claude Desktop
4. Restart Claude Desktop completely
5. Verify `.env` file exists and has correct format

### Invalid Signature Errors

**Symptoms:**
```
Error: invalid signature
```

**Solutions:**
1. **Check signature type:**
   ```bash
   # In .env file
   POLYMARKET_SIGNATURE_TYPE=0  # Must be 0 for normal wallets
   ```

2. **Verify private key matches funder address:**
   ```python
   from eth_account import Account
   account = Account.from_key(your_private_key)
   print(account.address)  # Should match POLYMARKET_FUNDER
   ```

3. **Restart MCP server** after changing `.env`:
   - Restart Claude Desktop completely

### Balance / Allowance Errors

**Symptoms:**
```
Error: not enough balance / allowance
```

**Solutions:**

1. **Check which wallet has USDC:**
   ```
   "Check my Polymarket balance"
   ```
   - If `proxy_balance` is high but `funder_balance` is low:
     - **Withdraw USDC from Proxy to Funder wallet** (see setup guide)

2. **Verify minimum order size:**
   - Most markets require minimum 5 USDC
   - Check market details for specific requirements

3. **Set USDC allowance** (one-time setup):
   - This requires a blockchain transaction
   - Needs MATIC for gas fees on Polygon
   - Usually done automatically on first trade via Polymarket website

### Market Not Found

**Symptoms:**
```
Error: Market not found
```

**Solutions:**
1. Check market is active and not closed
2. Use correct market ID or slug
3. Try fetching markets to see available options:
   ```
   "Show active Polymarket markets"
   ```

### Low Performance / Timeouts

**Symptoms:**
- Slow responses from MCP server
- Timeout errors

**Solutions:**
1. Check network connection to Polygon RPC
2. Reduce number of concurrent requests
3. Use market ID instead of slug when possible (faster lookup)
4. Clear cache and restart MCP server

## Best Practices

1. **Always validate credentials** before trading
   ```
   "Validate my Polymarket credentials"
   ```

2. **Start with small positions** to test
   - Use minimum order sizes first
   - Verify orders execute correctly

3. **Monitor strategy closely** in first minutes
   - Check positions frequently
   - Verify P&L calculations

4. **Set appropriate limits** (max_position, max_delta)
   - Don't risk more than you can afford to lose
   - Use position limits to control risk

5. **Check exchange status** before large operations
   ```
   "Check Polymarket status"
   ```

6. **Use market orders cautiously**
   - They have price impact
   - May execute at worse prices than limit orders

7. **Keep some cash reserve** for opportunities
   - Don't deploy 100% of capital
   - Leave room for adjustments

8. **Rebalance regularly** to maintain target delta
   - Markets move continuously
   - Positions may drift from targets

## Security Notes

### Private Key Safety

- **NEVER commit `.env` file to git** (already in `.gitignore`)
- **Store private keys securely**
- **Use separate wallets** for trading vs holding large amounts
- **Monitor wallet activity** regularly for unauthorized transactions

### USDC Allowances

- Review and revoke unused allowances periodically
- Only approve the minimum necessary amounts
- Use reputable block explorers to verify contracts

### Testing

- Test with small amounts first
- Use testnet if available
- Verify all calculations before executing large trades

## Additional Resources

- [Polymarket Documentation](https://docs.polymarket.com)
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
- [MCP Protocol Specification](https://spec.modelcontextprotocol.io)
- [Claude Desktop Documentation](https://claude.ai/desktop)

## Support

For issues or questions:
- GitHub Issues: [https://github.com/guzus/dr-manhattan/issues](https://github.com/guzus/dr-manhattan/issues)
- Discussions: [https://github.com/guzus/dr-manhattan/discussions](https://github.com/guzus/dr-manhattan/discussions)

---

**Version:** 0.0.2
**Last Updated:** 2026-01-03
**License:** MIT
