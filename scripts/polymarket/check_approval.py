"""Check Polymarket wallet balance and approval status."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
# Works when running: uv run scripts/polymarket/check_approval.py
env_path = Path.cwd() / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    print(f"⚠️  No .env file found at: {env_path}")
    print("Create .env in project root with:")
    print("  POLYMARKET_PRIVATE_KEY=0x...")
    print("  POLYMARKET_FUNDER=0x...")
    exit(1)

PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
FUNDER = os.getenv("POLYMARKET_FUNDER")

if not PRIVATE_KEY:
    print("❌ POLYMARKET_PRIVATE_KEY not found in .env")
    print("Add to .env file:")
    print("  POLYMARKET_PRIVATE_KEY=0x...")
    exit(1)

print("=" * 80)
print("Polymarket Wallet Check")
print("=" * 80)

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import BalanceAllowanceParams
    
    # Initialize client
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=PRIVATE_KEY,
        chain_id=137,
        signature_type=2,
        funder=FUNDER,
    )
    
    # Get API credentials
    api_creds = client.create_or_derive_api_creds()
    client.set_api_creds(api_creds)
    
    # Get address
    address = client.get_address()
    print(f"Wallet Address: {address}")
    if FUNDER:
        print(f"Funder Address: {FUNDER}")
    print()
    
    # Check balance and allowance
    params = BalanceAllowanceParams(
        asset_type="COLLATERAL",
        signature_type=2
    )
    
    balance_info = client.get_balance_allowance(params)
    
    # Parse balance (USDC has 6 decimals)
    balance_raw = int(balance_info.get("balance", 0))
    balance_usdc = balance_raw / 1e6
    
    allowance_raw = int(balance_info.get("allowance", 0))
    allowance_usdc = allowance_raw / 1e6
    
    print(f"USDC Balance: ${balance_usdc:.2f}")
    print(f"Exchange Allowance: ${allowance_usdc:.2f}")
    print()
    
    print("=" * 80)
    print("Diagnosis")
    print("=" * 80)
    
    # Diagnose issues
    issues = []
    
    if balance_usdc < 5:
        issues.append("Low USDC balance")
        print(f"⚠️  USDC Balance: ${balance_usdc:.2f} (need at least $5-10)")
    else:
        print(f"✅ USDC Balance: ${balance_usdc:.2f}")
    
    if allowance_usdc < balance_usdc:
        issues.append("Allowance not set")
        print(f"⚠️  Exchange Allowance: ${allowance_usdc:.2f}")
        print("   Exchange cannot spend your USDC")
    else:
        print(f"✅ Exchange Allowance: ${allowance_usdc:.2f}")
    
    if not issues:
        print()
        print("=" * 80)
        print("✅ WALLET IS READY FOR TRADING!")
        print("=" * 80)
    else:
        print()
        print("=" * 80)
        print("⚠️  ACTION REQUIRED")
        print("=" * 80)
        print()
        
        if balance_usdc < 5:
            print("1. Deposit USDC to Polygon network:")
            print(f"   Address: {FUNDER if FUNDER else address}")
            print("   Options:")
            print("   - Buy on Polymarket.com")
            print("   - Withdraw from CEX to Polygon")
            print("   - Bridge from Ethereum")
            print()
        
        if allowance_usdc < balance_usdc:
            print("2. Approve USDC spending:")
            print("   - Visit https://polymarket.com/")
            print("   - Connect wallet")
            print("   - Place any small order")
            print("   - Approve USDC when prompted")
            print()

except Exception as e:
    print(f"❌ Error: {e}")
    print()
    print("Make sure:")
    print("1. POLYMARKET_PRIVATE_KEY is set in .env")
    print("2. POLYMARKET_FUNDER is set in .env (for proxy wallets)")
    print("3. You have internet connection")
    exit(1)
