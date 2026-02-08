"""Polymarket exchange - unified API"""
from __future__ import annotations

from ..base.exchange import Exchange
from .polymarket_clob import PolymarketCLOB
from .polymarket_core import PolymarketCore, PublicTrade, PricePoint, Tag
from .polymarket_ctf import PolymarketCTF
from .polymarket_data import PolymarketData
from .polymarket_gamma import PolymarketGamma


class Polymarket(PolymarketCore, PolymarketCLOB, PolymarketGamma, PolymarketData, PolymarketCTF, Exchange):
    """Polymarket exchange implementation - all APIs unified via mixins"""
    pass
