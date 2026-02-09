"""Backward-compatible import for PolymarketBuilder.

This module preserves the legacy import path:
    dr_manhattan.exchanges.polymarket_builder
"""

from .polymarket.polymarket_builder import PolymarketBuilder

__all__ = ["PolymarketBuilder"]
