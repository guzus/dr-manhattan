from dataclasses import dataclass


@dataclass
class PositionBreakdown:
    """Position breakdown for NAV calculation"""
    market_id: str
    outcome: str
    size: float
    mid_price: float
    value: float


@dataclass
class NAV:
    """Net Asset Value breakdown"""
    nav: float
    cash: float
    positions_value: float
    positions: list[PositionBreakdown]
