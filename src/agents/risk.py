"""
Risk Agent

리스크 관리 및 포지션 사이징 담당
"""

from typing import Any, Dict, Optional
from .base import BaseAgent
from src.core.polymarket.models import MarketData
from src.core.llm.prompts import RISK_AGENT_PROMPT


class RiskAgent(BaseAgent):
    """리스크 관리 Agent - 포지션 사이징 및 리스크 평가"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Default risk parameters
        self.max_position_pct = 10.0  # 최대 포지션 비율
        self.max_positions = 10
        self.daily_loss_limit = 5.0  # 일일 손실 한도 %
        self.max_drawdown = 20.0  # 최대 드로우다운 %

    @property
    def agent_type(self) -> str:
        return "risk"

    @property
    def system_prompt(self) -> str:
        return """You are an expert risk manager for a trading system.
Your job is to assess trade risks, calculate appropriate position sizes, and enforce risk limits.
Use Kelly Criterion for position sizing but be conservative (use fractional Kelly).
Always prioritize capital preservation over profit maximization.
Always respond with valid JSON matching the required schema."""

    def format_prompt(
        self,
        market: MarketData,
        side: str = "YES",
        estimated_prob: float = 0.5,
        total_equity: float = 1000.0,
        available_balance: float = 1000.0,
        position_count: int = 0,
        daily_pnl: float = 0.0,
        **kwargs,
    ) -> str:
        market_price = market.yes_price if side == "YES" else market.no_price
        edge = estimated_prob - market_price

        daily_pnl_pct = (daily_pnl / total_equity * 100) if total_equity > 0 else 0

        return RISK_AGENT_PROMPT.format(
            market_data=self._format_market_data(market),
            side=side,
            estimated_prob=estimated_prob,
            market_price=market_price,
            edge=edge,
            total_equity=total_equity,
            available_balance=available_balance,
            position_count=position_count,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            max_position_pct=self.max_position_pct,
            max_positions=self.max_positions,
            daily_loss_limit=self.daily_loss_limit,
            max_drawdown=self.max_drawdown,
        )

    def _format_market_data(self, market: MarketData) -> str:
        return f"""
Market ID: {market.id}
Question: {market.question}
Category: {market.category or 'N/A'}
End Date: {market.end_date or 'N/A'}
Liquidity: ${market.liquidity:,.2f}
24h Volume: ${market.volume_24h:,.2f}
"""

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """응답 파싱 및 검증"""
        # Normalize risk assessment
        risk_assessment = response.get("risk_assessment", "medium")
        if risk_assessment not in ["low", "medium", "high", "very_high"]:
            risk_assessment = "medium"

        # Clamp Kelly fraction
        kelly_fraction = response.get("kelly_fraction", 0.25)
        kelly_fraction = max(0.0, min(1.0, float(kelly_fraction)))

        # Clamp position size
        position_size_pct = response.get("recommended_position_size_pct", 0.0)
        position_size_pct = max(0.0, min(self.max_position_pct, float(position_size_pct)))

        position_size_usd = response.get("recommended_position_size_usd", 0.0)
        position_size_usd = max(0.0, float(position_size_usd))

        return {
            "market_id": response.get("market_id"),
            "risk_assessment": risk_assessment,
            "specific_risks": response.get("specific_risks", []),
            "kelly_fraction": kelly_fraction,
            "recommended_position_size_pct": position_size_pct,
            "recommended_position_size_usd": position_size_usd,
            "should_trade": response.get("should_trade", False),
            "rejection_reason": response.get("rejection_reason"),
            "stop_loss_price": response.get("stop_loss_price"),
            "take_profit_price": response.get("take_profit_price"),
            "notes": response.get("notes", ""),
        }

    def set_risk_parameters(
        self,
        max_position_pct: Optional[float] = None,
        max_positions: Optional[int] = None,
        daily_loss_limit: Optional[float] = None,
        max_drawdown: Optional[float] = None,
    ):
        """리스크 파라미터 설정"""
        if max_position_pct is not None:
            self.max_position_pct = max_position_pct
        if max_positions is not None:
            self.max_positions = max_positions
        if daily_loss_limit is not None:
            self.daily_loss_limit = daily_loss_limit
        if max_drawdown is not None:
            self.max_drawdown = max_drawdown
