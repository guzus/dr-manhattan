"""
LLM Provider 추상화

다양한 LLM 제공자를 지원하기 위한 인터페이스
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class LLMModel(str, Enum):
    """지원하는 LLM 모델"""

    # OpenAI
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"
    GPT_4_TURBO = "gpt-4-turbo"

    # Anthropic (추후 확장)
    CLAUDE_3_HAIKU = "claude-3-haiku-20240307"
    CLAUDE_3_SONNET = "claude-3-sonnet-20240229"
    CLAUDE_3_OPUS = "claude-3-opus-20240229"

    # DeepSeek (추후 확장)
    DEEPSEEK_CHAT = "deepseek-chat"
    DEEPSEEK_CODER = "deepseek-coder"

    # Google (추후 확장)
    GEMINI_PRO = "gemini-pro"
    GEMINI_ULTRA = "gemini-ultra"


@dataclass
class Message:
    """채팅 메시지"""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """LLM 응답"""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Parsed response (JSON인 경우)
    parsed: Optional[Dict[str, Any]] = None

    # Cost estimation
    cost: float = 0.0

    # Metadata
    finish_reason: Optional[str] = None
    latency_ms: float = 0.0

    @property
    def is_json(self) -> bool:
        return self.parsed is not None


# Token costs per model (per 1M tokens)
MODEL_COSTS = {
    LLMModel.GPT_4O_MINI: {"input": 0.15, "output": 0.60},
    LLMModel.GPT_4O: {"input": 2.50, "output": 10.00},
    LLMModel.GPT_4_TURBO: {"input": 10.00, "output": 30.00},
    LLMModel.CLAUDE_3_HAIKU: {"input": 0.25, "output": 1.25},
    LLMModel.CLAUDE_3_SONNET: {"input": 3.00, "output": 15.00},
    LLMModel.CLAUDE_3_OPUS: {"input": 15.00, "output": 75.00},
    LLMModel.DEEPSEEK_CHAT: {"input": 0.14, "output": 0.28},
    LLMModel.DEEPSEEK_CODER: {"input": 0.14, "output": 0.28},
    LLMModel.GEMINI_PRO: {"input": 0.50, "output": 1.50},
    LLMModel.GEMINI_ULTRA: {"input": 5.00, "output": 15.00},
}


def calculate_cost(
    model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """토큰 사용량 기반 비용 계산"""
    try:
        model_enum = LLMModel(model)
        costs = MODEL_COSTS.get(model_enum, {"input": 0, "output": 0})

        input_cost = (prompt_tokens / 1_000_000) * costs["input"]
        output_cost = (completion_tokens / 1_000_000) * costs["output"]

        return input_cost + output_cost
    except ValueError:
        return 0.0


class LLMProvider(ABC):
    """LLM 제공자 추상 클래스"""

    @abstractmethod
    async def generate(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        json_mode: bool = False,
    ) -> LLMResponse:
        """
        텍스트 생성

        Args:
            messages: 대화 메시지 리스트
            model: 사용할 모델 (None이면 기본 모델)
            temperature: 샘플링 온도 (0.0 ~ 2.0)
            max_tokens: 최대 토큰 수
            json_mode: JSON 응답 모드

        Returns:
            LLMResponse: 생성된 응답
        """
        pass

    @abstractmethod
    async def generate_with_schema(
        self,
        messages: List[Message],
        schema: Dict[str, Any],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        """
        스키마에 맞는 구조화된 응답 생성

        Args:
            messages: 대화 메시지 리스트
            schema: JSON Schema 정의
            model: 사용할 모델
            temperature: 샘플링 온도
            max_tokens: 최대 토큰 수

        Returns:
            LLMResponse: 스키마에 맞게 파싱된 응답
        """
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """기본 모델"""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """제공자 이름"""
        pass
