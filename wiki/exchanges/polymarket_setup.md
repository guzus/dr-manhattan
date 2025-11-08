# Polymarket Setup Guide

## Prerequisites

- USDC on Polygon network (~$20 minimum)
- MATIC for gas (~0.1 MATIC / $0.05)
- Private key and funder address

## Quick Setup

### 1. Install

```bash
cd dr-manhattan
uv sync
```

### 2. Configure

Create `.env` in project root:

```env
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_FUNDER=0x...
```

### 3. Activate Wallet (First Time Only)

**Required before automated trading:**

1. Go to https://polymarket.com/
2. Connect your wallet (funder address)
3. Place one small order ($1-2)
4. Approve USDC when prompted

This registers your proxy wallet on Polymarket's servers.

### 4. Start Trading

```bash
cd examples
uv run python spread_strategy.py
```

## Understanding Proxy Wallets

Polymarket uses a two-address system:

- **Private Key**: Signs transactions (proxy wallet)
- **Funder Address**: Holds USDC (~$20-30)

Both required in `.env` file.

## Common Issues

### "Invalid Signature"
→ Complete step 3 (place one order via UI first)

### "Not Enough Balance / Allowance"
→ Approve USDC on Polymarket.com (done in step 3)

### No USDC
→ Buy on Polymarket.com or bridge from Ethereum

### Check Your Setup

```bash
uv run scripts/polymarket/check_approval.py
```

Should show:
- ✅ USDC Balance
- ✅ Allowance Approved
- ✅ MATIC for Gas

## Addresses (Polygon)

- USDC: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
- Exchange: `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`

## Links

- [Polymarket](https://polymarket.com/)
- [Docs](https://docs.polymarket.com/)
- [PolygonScan](https://polygonscan.com/)
- [Bridge](https://portal.polygon.technology/)

---

**Ready?** → Complete steps 1-3, then run your strategy! 🚀
