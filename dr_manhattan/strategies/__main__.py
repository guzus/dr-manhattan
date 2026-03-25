"""
Entrypoint for running BTCScalpStrategy directly.

Usage:
    uv run python -m dr_manhattan.strategies

Required environment variables:
    POLYMARKET_PRIVATE_KEY  — 64-hex EVM private key (with or without 0x)
    POLYMARKET_FUNDER       — Wallet address that holds USDC collateral

Optional:
    POLYMARKET_API_KEY      — L2 CLOB API key (auto-derived if absent)
    ENTRY_PRICE             — Limit buy price for both outcomes (default: 0.32)
    PROFIT_TARGET           — Initial sell price after fill (default: 0.35)
    ORDER_SIZE_USD          — USD to risk per side before Kelly scaling (default: 10.0)
    ORDER_LIFETIME          — Seconds before cancelling unfilled buys (default: 72)
    MAX_DAILY_LOSS          — Stop placing entries when session P&L < -MAX (default: 50.0)
"""

import logging
import os
import sys

from dr_manhattan import create_exchange
from dr_manhattan.strategies.btc_scalp import BTCScalpStrategy

logger = logging.getLogger(__name__)


def main():
    try:
        exchange = create_exchange("polymarket", use_env=True, verbose=True)

        strategy = BTCScalpStrategy(
            exchange=exchange,
            entry_price=float(os.environ.get("ENTRY_PRICE", "0.32").strip()),
            profit_target=float(os.environ.get("PROFIT_TARGET", "0.35").strip()),
            order_size_usd=float(os.environ.get("ORDER_SIZE_USD", "10.0").strip()),
            order_lifetime=float(os.environ.get("ORDER_LIFETIME", "72").strip()),
            max_daily_loss=float(os.environ.get("MAX_DAILY_LOSS", "50.0").strip()),
        )
        strategy.run()
    except Exception as e:
        logger.error("Fatal startup error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
