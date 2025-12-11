"""
Sentiment Agent

시장 심리 및 감성 분석 담당
"""

from typing import Any, Dict
from .base import BaseAgent
from src.core.polymarket.models import MarketData
from src.core.llm.prompts import SENTIMENT_AGENT_PROMPT


class SentimentAgent(BaseAgent):
    """감성 분석 Agent - 시장 심리 및 군중 행동 분석"""

    @property
    def agent_type(self) -> str:
        return "sentiment"

    @property
    def system_prompt(self) -> str:
        return """You are an expert in market psychology and sentiment analysis.
Your job is to assess crowd behavior, detect biases, and identify sentiment-based trading opportunities.
Look for emotional pricing, overreaction, and contrarian opportunities.
Always respond with valid JSON matching the required schema."""

    def format_prompt(
        self,
        market: MarketData,
        price_change_24h: float = 0.0,
        **kwargs,
    ) -> str:
        return SENTIMENT_AGENT_PROMPT.format(
            market_data=self._format_market_data(market),
            volume_24h=market.volume_24h,
            liquidity=market.liquidity,
            price_change=price_change_24h,
            yes_price=market.yes_price,
            no_price=market.no_price,
        )

    def _format_market_data(self, market: MarketData) -> str:
        return f"""
Market ID: {market.id}
Question: {market.question}
Category: {market.category or 'N/A'}
End Date: {market.end_date or 'N/A'}
"""

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """응답 파싱 및 검증"""
        # Normalize sentiment
        overall_sentiment = response.get("overall_sentiment", "neutral")
        if overall_sentiment not in ["bullish", "bearish", "neutral"]:
            overall_sentiment = "neutral"

        sentiment_strength = response.get("sentiment_strength", "moderate")
        if sentiment_strength not in ["strong", "moderate", "weak"]:
            sentiment_strength = "moderate"

        crowd_behavior = response.get("crowd_behavior", "uncertain")
        if crowd_behavior not in ["rational", "emotional", "uncertain"]:
            crowd_behavior = "uncertain"

        # Clamp sentiment score
        sentiment_score = response.get("sentiment_score", 0.0)
        sentiment_score = max(-1.0, min(1.0, float(sentiment_score)))

        return {
            "market_id": response.get("market_id"),
            "overall_sentiment": overall_sentiment,
            "sentiment_strength": sentiment_strength,
            "detected_biases": response.get("detected_biases", []),
            "crowd_behavior": crowd_behavior,
            "contrarian_opportunity": response.get("contrarian_opportunity", False),
            "sentiment_score": sentiment_score,
            "notes": response.get("notes", ""),
        }
