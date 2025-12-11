"""
Arbiter Agent

최종 의사결정 및 Agent 조율 담당
"""

from typing import Any, Dict, Optional
from .base import BaseAgent
from src.core.polymarket.models import MarketData
from src.core.llm.prompts import ARBITER_AGENT_PROMPT


class ArbiterAgent(BaseAgent):
    """조율 Agent - 최종 거래 결정"""

    @property
    def agent_type(self) -> str:
        return "arbiter"

    @property
    def system_prompt(self) -> str:
        return """You are the chief decision maker for a prediction market trading system.
Your job is to synthesize analyses from multiple specialist agents and make the final trading decision.
Be decisive but prudent. Only trade when there is clear edge and manageable risk.
Consider all perspectives but give more weight to quantitative analysis.
Always respond with valid JSON matching the required schema."""

    def format_prompt(
        self,
        market: MarketData,
        research_analysis: Optional[Dict[str, Any]] = None,
        probability_analysis: Optional[Dict[str, Any]] = None,
        sentiment_analysis: Optional[Dict[str, Any]] = None,
        risk_analysis: Optional[Dict[str, Any]] = None,
        execution_analysis: Optional[Dict[str, Any]] = None,
        total_equity: float = 1000.0,
        available_balance: float = 1000.0,
        position_count: int = 0,
        **kwargs,
    ) -> str:
        return ARBITER_AGENT_PROMPT.format(
            market_data=self._format_market_data(market),
            research_analysis=self._format_analysis(research_analysis, "Research"),
            probability_analysis=self._format_analysis(probability_analysis, "Probability"),
            sentiment_analysis=self._format_analysis(sentiment_analysis, "Sentiment"),
            risk_analysis=self._format_analysis(risk_analysis, "Risk"),
            execution_analysis=self._format_analysis(execution_analysis, "Execution"),
            total_equity=total_equity,
            available_balance=available_balance,
            position_count=position_count,
        )

    def _format_market_data(self, market: MarketData) -> str:
        return f"""
Market ID: {market.id}
Question: {market.question}
Category: {market.category or 'N/A'}
End Date: {market.end_date or 'N/A'}
YES Price: ${market.yes_price:.4f} ({market.yes_price:.1%} implied)
NO Price: ${market.no_price:.4f} ({market.no_price:.1%} implied)
Liquidity: ${market.liquidity:,.2f}
24h Volume: ${market.volume_24h:,.2f}
"""

    def _format_analysis(
        self, analysis: Optional[Dict[str, Any]], agent_name: str
    ) -> str:
        if not analysis:
            return f"No {agent_name} analysis available."

        lines = []
        for key, value in analysis.items():
            if key == "market_id":
                continue
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value) if value else "None"
            elif isinstance(value, float):
                value = f"{value:.4f}"
            lines.append(f"- {key}: {value}")

        return "\n".join(lines)

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """응답 파싱 및 검증"""
        # Normalize decision
        decision = response.get("decision", "SKIP")
        valid_decisions = ["BUY_YES", "BUY_NO", "SELL_YES", "SELL_NO", "HOLD", "SKIP"]
        if decision not in valid_decisions:
            decision = "SKIP"

        # Normalize confidence
        confidence = response.get("confidence", "medium")
        if confidence not in ["high", "medium", "low"]:
            confidence = "medium"

        # Clamp position size
        position_size_usd = response.get("position_size_usd", 0.0)
        position_size_usd = max(0.0, float(position_size_usd))

        # Clamp limit price
        limit_price = response.get("limit_price")
        if limit_price is not None:
            limit_price = max(0.01, min(0.99, float(limit_price)))

        return {
            "market_id": response.get("market_id"),
            "decision": decision,
            "confidence": confidence,
            "position_size_usd": position_size_usd,
            "limit_price": limit_price,
            "reasoning": response.get("reasoning", ""),
            "key_factors": response.get("key_factors", []),
            "concerns": response.get("concerns", []),
            "expected_value": float(response.get("expected_value", 0)),
            "time_horizon": response.get("time_horizon", ""),
        }
