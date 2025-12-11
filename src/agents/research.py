"""
Research Agent

시장 조사 및 정보 수집 담당
"""

from typing import Any, Dict
from .base import BaseAgent
from src.core.polymarket.models import MarketData
from src.core.llm.prompts import RESEARCH_AGENT_PROMPT


class ResearchAgent(BaseAgent):
    """리서치 Agent - 시장 정보 수집 및 분석"""

    @property
    def agent_type(self) -> str:
        return "research"

    @property
    def system_prompt(self) -> str:
        return """You are an expert market researcher specializing in prediction markets.
Your job is to analyze markets, identify key factors, and provide actionable research insights.
Always respond with valid JSON matching the required schema."""

    def format_prompt(self, market: MarketData, **kwargs) -> str:
        return RESEARCH_AGENT_PROMPT.format(
            market_data=self._format_market_data(market),
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
24h Volume: ${market.volume_24h:,.2f}
Total Liquidity: ${market.liquidity:,.2f}
Tags: {', '.join(market.tags) if market.tags else 'N/A'}
"""

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """응답 파싱 및 검증"""
        required_fields = [
            "market_id",
            "summary",
            "key_factors",
            "information_quality",
            "market_efficiency",
        ]

        for field in required_fields:
            if field not in response:
                response[field] = None

        # Normalize values
        if response.get("information_quality"):
            response["information_quality"] = response["information_quality"].lower()

        if response.get("market_efficiency"):
            response["market_efficiency"] = response["market_efficiency"].lower()

        return {
            "market_id": response.get("market_id"),
            "summary": response.get("summary", ""),
            "key_factors": response.get("key_factors", []),
            "recent_developments": response.get("recent_developments", []),
            "information_quality": response.get("information_quality", "medium"),
            "market_efficiency": response.get("market_efficiency", "uncertain"),
            "notes": response.get("notes", ""),
        }
