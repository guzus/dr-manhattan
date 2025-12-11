"""
Probability Agent

확률 추정 및 Edge 계산 담당
"""

from typing import Any, Dict, Optional
from .base import BaseAgent, AgentResult
from src.core.polymarket.models import MarketData
from src.core.llm.prompts import PROBABILITY_AGENT_PROMPT


class ProbabilityAgent(BaseAgent):
    """확률 추정 Agent - 실제 확률 추정 및 Edge 계산"""

    @property
    def agent_type(self) -> str:
        return "probability"

    @property
    def system_prompt(self) -> str:
        return """You are an expert probability assessor for prediction markets.
Your job is to estimate the true probability of events, independent of market prices.
Be well-calibrated: your 70% predictions should be right 70% of the time.
Always respond with valid JSON matching the required schema."""

    def format_prompt(
        self,
        market: MarketData,
        research_analysis: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        research_str = "No research analysis available."
        if research_analysis:
            research_str = f"""
Summary: {research_analysis.get('summary', 'N/A')}
Key Factors: {', '.join(research_analysis.get('key_factors', []))}
Information Quality: {research_analysis.get('information_quality', 'N/A')}
Market Efficiency: {research_analysis.get('market_efficiency', 'N/A')}
Notes: {research_analysis.get('notes', '')}
"""

        return PROBABILITY_AGENT_PROMPT.format(
            market_data=self._format_market_data(market),
            research_analysis=research_str,
            yes_price=market.yes_price,
            no_price=market.no_price,
            yes_prob=market.yes_price,
            no_prob=market.no_price,
        )

    def _format_market_data(self, market: MarketData) -> str:
        return f"""
Market ID: {market.id}
Question: {market.question}
Description: {market.description or 'N/A'}
Category: {market.category or 'N/A'}
End Date: {market.end_date or 'N/A'}
"""

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """응답 파싱 및 검증"""
        # Ensure probabilities are valid
        prob_yes = response.get("estimated_probability_yes", 0.5)
        prob_no = response.get("estimated_probability_no", 0.5)

        # Clamp probabilities to [0.01, 0.99]
        prob_yes = max(0.01, min(0.99, float(prob_yes)))
        prob_no = max(0.01, min(0.99, float(prob_no)))

        # Calculate edge
        edge_yes = response.get("edge_yes", 0)
        edge_no = response.get("edge_no", 0)

        # Determine recommended side
        recommended_side = response.get("recommended_side", "NONE")
        if recommended_side not in ["YES", "NO", "NONE"]:
            recommended_side = "NONE"

        # Normalize confidence
        confidence = response.get("confidence", "medium")
        if confidence not in ["high", "medium", "low"]:
            confidence = "medium"

        return {
            "market_id": response.get("market_id"),
            "estimated_probability_yes": prob_yes,
            "estimated_probability_no": prob_no,
            "confidence": confidence,
            "edge_yes": float(edge_yes),
            "edge_no": float(edge_no),
            "recommended_side": recommended_side,
            "reasoning": response.get("reasoning", ""),
        }
