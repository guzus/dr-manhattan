from dataclasses import dataclass
from typing import Dict


@dataclass
class Position:
    """Represents a position in a prediction market"""
    market_id: str
    outcome: str
    size: float
    average_price: float
    current_price: float

    @property
    def cost_basis(self) -> float:
        """Total cost of position"""
        return self.size * self.average_price

    @property
    def current_value(self) -> float:
        """Current value of position"""
        return self.size * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        """Unrealized profit/loss"""
        return self.current_value - self.cost_basis

    @property
    def unrealized_pnl_percent(self) -> float:
        """Unrealized profit/loss percentage"""
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100
