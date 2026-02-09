"""Backward-compatible import for PolymarketOperator.

This module preserves the legacy import path:
    dr_manhattan.exchanges.polymarket_operator
"""

from .polymarket.polymarket_operator import PolymarketOperator

__all__ = ["PolymarketOperator"]
