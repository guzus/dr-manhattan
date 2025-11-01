# Utility Scripts

Diagnostic and operational tools organized by exchange.

## Structure

```
scripts/
├── polymarket/          # Polymarket-specific utilities
│   └── check_approval.py
└── README.md
```

## Polymarket Tools

### polymarket/check_approval.py

**Purpose:** Check wallet balance and USDC approval status.

**Usage:**
```bash
# From project root
uv run scripts/polymarket/check_approval.py
```

**Checks:**
- ✅ USDC balance
- ✅ Exchange contract allowance

**Requirements:** `.env` file in project root with:
- `POLYMARKET_PRIVATE_KEY`
- `POLYMARKET_FUNDER`

**Output:**
```
USDC Balance: $29.98
Exchange Allowance: $0.00
⚠️  ACTION REQUIRED
```

---

## Adding New Scripts

Utility scripts should:
1. Be organized by exchange (`polymarket/`, `limitless/`, etc.)
2. Be focused on a single operational task
3. Require minimal setup (use .env)
4. Provide clear output and guidance
5. Handle errors gracefully

