"""
Base Agent Class

모든 Agent의 기본 클래스
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
import structlog

from src.core.llm import LLMProvider, LLMResponse, Message
from src.core.polymarket.models import MarketData

logger = structlog.get_logger()


@dataclass
class AgentResult:
    """Agent 분석 결과"""

    agent_name: str
    agent_type: str
    market_id: str
    success: bool
    data: Dict[str, Any]
    raw_response: str = ""
    error_message: Optional[str] = None

    # Token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    # Timing
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


class BaseAgent(ABC):
    """Agent 기본 클래스"""

    def __init__(
        self,
        name: str,
        llm_provider: LLMProvider,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ):
        self.name = name
        self.llm = llm_provider
        self.model = model or llm_provider.default_model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Statistics
        self.total_calls = 0
        self.total_tokens_used = 0
        self.total_cost = 0.0

        logger.info(
            f"{self.agent_type} agent initialized",
            name=name,
            model=self.model,
        )

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Agent 타입"""
        pass

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """시스템 프롬프트 템플릿"""
        pass

    @abstractmethod
    def format_prompt(self, market: MarketData, **kwargs) -> str:
        """프롬프트 포맷팅"""
        pass

    @abstractmethod
    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """응답 파싱 및 검증"""
        pass

    async def analyze(
        self,
        market: MarketData,
        **kwargs,
    ) -> AgentResult:
        """
        시장 분석 실행

        Args:
            market: 분석할 시장 데이터
            **kwargs: 추가 컨텍스트

        Returns:
            AgentResult: 분석 결과
        """
        try:
            # Format prompt
            user_prompt = self.format_prompt(market, **kwargs)

            # Build messages
            messages = [
                Message(role="system", content=self.system_prompt),
                Message(role="user", content=user_prompt),
            ]

            # Call LLM
            response = await self.llm.generate(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                json_mode=True,
            )

            # Update statistics
            self.total_calls += 1
            self.total_tokens_used += response.total_tokens
            self.total_cost += response.cost

            # Parse response
            if response.parsed:
                data = self.parse_response(response.parsed)
            else:
                raise ValueError("Failed to get structured response from LLM")

            logger.debug(
                f"{self.agent_type} analysis completed",
                market_id=market.id,
                tokens=response.total_tokens,
                cost=response.cost,
            )

            return AgentResult(
                agent_name=self.name,
                agent_type=self.agent_type,
                market_id=market.id,
                success=True,
                data=data,
                raw_response=response.content,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                cost=response.cost,
                latency_ms=response.latency_ms,
            )

        except Exception as e:
            logger.error(
                f"{self.agent_type} analysis failed",
                market_id=market.id,
                error=str(e),
            )

            return AgentResult(
                agent_name=self.name,
                agent_type=self.agent_type,
                market_id=market.id,
                success=False,
                data={},
                error_message=str(e),
            )

    def get_stats(self) -> Dict[str, Any]:
        """Agent 통계"""
        return {
            "name": self.name,
            "type": self.agent_type,
            "model": self.model,
            "total_calls": self.total_calls,
            "total_tokens_used": self.total_tokens_used,
            "total_cost": self.total_cost,
            "avg_tokens_per_call": (
                self.total_tokens_used / self.total_calls
                if self.total_calls > 0
                else 0
            ),
        }
