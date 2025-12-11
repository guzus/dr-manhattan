"""
Agent Orchestrator

여러 Agent를 조율하여 거래 결정을 내리는 오케스트레이터
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import structlog

from .base import AgentResult
from .research import ResearchAgent
from .probability import ProbabilityAgent
from .sentiment import SentimentAgent
from .risk import RiskAgent
from .execution import ExecutionAgent
from .arbiter import ArbiterAgent

from src.core.llm import LLMProvider
from src.core.polymarket.models import MarketData, OrderBook

logger = structlog.get_logger()


@dataclass
class TradingDecision:
    """최종 거래 결정"""

    market_id: str
    decision: str  # BUY_YES, BUY_NO, SELL_YES, SELL_NO, HOLD, SKIP
    confidence: str
    position_size_usd: float
    limit_price: Optional[float]
    reasoning: str

    # Agent 분석 결과
    research_result: Optional[AgentResult] = None
    probability_result: Optional[AgentResult] = None
    sentiment_result: Optional[AgentResult] = None
    risk_result: Optional[AgentResult] = None
    execution_result: Optional[AgentResult] = None
    arbiter_result: Optional[AgentResult] = None

    # 메타데이터
    total_tokens: int = 0
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def should_trade(self) -> bool:
        return self.decision not in ["HOLD", "SKIP"]

    @property
    def side(self) -> Optional[str]:
        if self.decision in ["BUY_YES", "SELL_YES"]:
            return "YES"
        elif self.decision in ["BUY_NO", "SELL_NO"]:
            return "NO"
        return None

    @property
    def action(self) -> Optional[str]:
        if self.decision.startswith("BUY"):
            return "BUY"
        elif self.decision.startswith("SELL"):
            return "SELL"
        return None


class AgentOrchestrator:
    """
    Agent 오케스트레이터

    여러 전문 Agent를 조율하여 거래 결정을 생성합니다.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        model: Optional[str] = None,
    ):
        self.llm = llm_provider
        self.model = model or llm_provider.default_model

        # Initialize agents
        self.research_agent = ResearchAgent(
            name="Research Agent",
            llm_provider=llm_provider,
            model=model,
            temperature=0.7,
        )

        self.probability_agent = ProbabilityAgent(
            name="Probability Agent",
            llm_provider=llm_provider,
            model=model,
            temperature=0.5,  # 더 일관된 확률 추정을 위해 낮은 temperature
        )

        self.sentiment_agent = SentimentAgent(
            name="Sentiment Agent",
            llm_provider=llm_provider,
            model=model,
            temperature=0.7,
        )

        self.risk_agent = RiskAgent(
            name="Risk Agent",
            llm_provider=llm_provider,
            model=model,
            temperature=0.3,  # 리스크 관리는 보수적으로
        )

        self.execution_agent = ExecutionAgent(
            name="Execution Agent",
            llm_provider=llm_provider,
            model=model,
            temperature=0.3,
        )

        self.arbiter_agent = ArbiterAgent(
            name="Arbiter Agent",
            llm_provider=llm_provider,
            model=model,
            temperature=0.5,
        )

        logger.info("Agent orchestrator initialized")

    async def analyze_market(
        self,
        market: MarketData,
        total_equity: float = 1000.0,
        available_balance: float = 1000.0,
        position_count: int = 0,
        daily_pnl: float = 0.0,
        order_book: Optional[OrderBook] = None,
        price_change_24h: float = 0.0,
    ) -> TradingDecision:
        """
        시장 분석 및 거래 결정

        모든 Agent를 순차적으로 실행하고 최종 결정을 반환합니다.
        """
        logger.info(f"Analyzing market: {market.id}", question=market.question[:100])

        total_tokens = 0
        total_cost = 0.0
        total_latency = 0.0

        # 1. Research Agent
        research_result = await self.research_agent.analyze(market)
        total_tokens += research_result.total_tokens
        total_cost += research_result.cost
        total_latency += research_result.latency_ms

        if not research_result.success:
            logger.warning(f"Research analysis failed for {market.id}")

        # 2. Probability Agent (research 결과 활용)
        probability_result = await self.probability_agent.analyze(
            market,
            research_analysis=research_result.data if research_result.success else None,
        )
        total_tokens += probability_result.total_tokens
        total_cost += probability_result.cost
        total_latency += probability_result.latency_ms

        if not probability_result.success:
            logger.warning(f"Probability analysis failed for {market.id}")

        # 3. Sentiment Agent
        sentiment_result = await self.sentiment_agent.analyze(
            market,
            price_change_24h=price_change_24h,
        )
        total_tokens += sentiment_result.total_tokens
        total_cost += sentiment_result.cost
        total_latency += sentiment_result.latency_ms

        # 4. Risk Agent (probability 결과 활용)
        recommended_side = "YES"
        estimated_prob = 0.5
        if probability_result.success:
            recommended_side = probability_result.data.get("recommended_side", "YES")
            if recommended_side == "YES":
                estimated_prob = probability_result.data.get("estimated_probability_yes", 0.5)
            else:
                estimated_prob = probability_result.data.get("estimated_probability_no", 0.5)

        risk_result = await self.risk_agent.analyze(
            market,
            side=recommended_side,
            estimated_prob=estimated_prob,
            total_equity=total_equity,
            available_balance=available_balance,
            position_count=position_count,
            daily_pnl=daily_pnl,
        )
        total_tokens += risk_result.total_tokens
        total_cost += risk_result.cost
        total_latency += risk_result.latency_ms

        # 5. Execution Agent (risk가 승인한 경우만)
        execution_result = None
        if risk_result.success and risk_result.data.get("should_trade", False):
            target_size = risk_result.data.get("recommended_position_size_usd", 0)
            max_price = market.yes_price if recommended_side == "YES" else market.no_price

            execution_result = await self.execution_agent.analyze(
                market,
                side="BUY",
                outcome=recommended_side,
                target_size=target_size,
                max_price=max_price + 0.05,  # 약간의 여유
                order_book=order_book,
            )
            total_tokens += execution_result.total_tokens
            total_cost += execution_result.cost
            total_latency += execution_result.latency_ms

        # 6. Arbiter Agent (최종 결정)
        arbiter_result = await self.arbiter_agent.analyze(
            market,
            research_analysis=research_result.data if research_result.success else None,
            probability_analysis=probability_result.data if probability_result.success else None,
            sentiment_analysis=sentiment_result.data if sentiment_result.success else None,
            risk_analysis=risk_result.data if risk_result.success else None,
            execution_analysis=execution_result.data if execution_result and execution_result.success else None,
            total_equity=total_equity,
            available_balance=available_balance,
            position_count=position_count,
        )
        total_tokens += arbiter_result.total_tokens
        total_cost += arbiter_result.cost
        total_latency += arbiter_result.latency_ms

        # 최종 결정 생성
        if arbiter_result.success:
            decision_data = arbiter_result.data
        else:
            # Arbiter 실패 시 기본값
            decision_data = {
                "decision": "SKIP",
                "confidence": "low",
                "position_size_usd": 0,
                "limit_price": None,
                "reasoning": "Analysis failed",
            }

        decision = TradingDecision(
            market_id=market.id,
            decision=decision_data.get("decision", "SKIP"),
            confidence=decision_data.get("confidence", "low"),
            position_size_usd=decision_data.get("position_size_usd", 0),
            limit_price=decision_data.get("limit_price"),
            reasoning=decision_data.get("reasoning", ""),
            research_result=research_result,
            probability_result=probability_result,
            sentiment_result=sentiment_result,
            risk_result=risk_result,
            execution_result=execution_result,
            arbiter_result=arbiter_result,
            total_tokens=total_tokens,
            total_cost=total_cost,
            total_latency_ms=total_latency,
        )

        logger.info(
            "Market analysis completed",
            market_id=market.id,
            decision=decision.decision,
            confidence=decision.confidence,
            position_size=decision.position_size_usd,
            total_tokens=total_tokens,
            total_cost=f"${total_cost:.4f}",
            latency_ms=total_latency,
        )

        return decision

    async def analyze_markets_batch(
        self,
        markets: List[MarketData],
        total_equity: float = 1000.0,
        available_balance: float = 1000.0,
        position_count: int = 0,
        daily_pnl: float = 0.0,
        max_concurrent: int = 3,
    ) -> List[TradingDecision]:
        """
        여러 시장 일괄 분석

        동시 실행 수를 제한하여 비용과 속도를 조절합니다.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def analyze_with_semaphore(market: MarketData) -> TradingDecision:
            async with semaphore:
                return await self.analyze_market(
                    market,
                    total_equity=total_equity,
                    available_balance=available_balance,
                    position_count=position_count,
                    daily_pnl=daily_pnl,
                )

        tasks = [analyze_with_semaphore(m) for m in markets]
        decisions = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_decisions = []
        for d in decisions:
            if isinstance(d, TradingDecision):
                valid_decisions.append(d)
            else:
                logger.error(f"Market analysis failed with exception: {d}")

        return valid_decisions

    def get_agent_stats(self) -> Dict[str, Any]:
        """모든 Agent 통계"""
        return {
            "research": self.research_agent.get_stats(),
            "probability": self.probability_agent.get_stats(),
            "sentiment": self.sentiment_agent.get_stats(),
            "risk": self.risk_agent.get_stats(),
            "execution": self.execution_agent.get_stats(),
            "arbiter": self.arbiter_agent.get_stats(),
        }
