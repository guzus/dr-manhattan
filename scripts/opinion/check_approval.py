"""Check Opinion wallet balance and approval status."""

import os
from pathlib import Path

from dotenv import load_dotenv

env_path = Path.cwd() / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    print(f"No .env file found at: {env_path}")
    print("Create .env in project root with:")
    print("  OPINION_API_KEY=...")
    print("  OPINION_PRIVATE_KEY=...")
    print("  OPINION_MULTI_SIG_ADDR=...")
    exit(1)

API_KEY = os.getenv("OPINION_API_KEY")
PRIVATE_KEY = os.getenv("OPINION_PRIVATE_KEY")
MULTI_SIG_ADDR = os.getenv("OPINION_MULTI_SIG_ADDR")

if not API_KEY or not PRIVATE_KEY or not MULTI_SIG_ADDR:
    print("Missing Opinion credentials in .env")
    print("Required variables:")
    print("  OPINION_API_KEY=...")
    print("  OPINION_PRIVATE_KEY=...")
    print("  OPINION_MULTI_SIG_ADDR=...")
    exit(1)

print("=" * 80)
print("Opinion Wallet Check")
print("=" * 80)

try:
    import dr_manhattan

    exchange = dr_manhattan.Opinion(
        {
            "api_key": API_KEY,
            "private_key": PRIVATE_KEY,
            "multi_sig_addr": MULTI_SIG_ADDR,
        }
    )

    print(f"Multi-sig Address: {MULTI_SIG_ADDR}")
    print()

    # Check balance
    balances = exchange.fetch_balance()

    print("Balances:")
    if balances:
        for symbol, amount in balances.items():
            print(f"  {symbol}: {amount:.2f}")
    else:
        print("  No balances found")
    print()

    # Check positions
    positions = exchange.fetch_positions()

    print("Positions:")
    if positions:
        for pos in positions:
            pnl_str = f"+{pos.unrealized_pnl:.2f}" if pos.unrealized_pnl >= 0 else f"{pos.unrealized_pnl:.2f}"
            print(f"  Market {pos.market_id} | {pos.outcome}: {pos.size:.2f} @ {pos.average_price:.4f} (PnL: {pnl_str})")
    else:
        print("  No positions")
    print()

    # Check open orders
    orders = exchange.fetch_open_orders()

    print("Open Orders:")
    if orders:
        for order in orders:
            print(f"  {order.id} | {order.side.value} {order.size} @ {order.price:.4f}")
    else:
        print("  No open orders")
    print()

    print("=" * 80)
    print("WALLET CHECK COMPLETE")
    print("=" * 80)

except Exception as e:
    print(f"Error: {e}")
    print()
    print("Make sure:")
    print("1. OPINION_API_KEY is set in .env")
    print("2. OPINION_PRIVATE_KEY is set in .env")
    print("3. OPINION_MULTI_SIG_ADDR is set in .env")
    print("4. You have internet connection")
    exit(1)
