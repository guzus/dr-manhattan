"""
OpenAI LLM Provider

GPT-4o-mini 및 기타 OpenAI 모델 지원
"""

import json
import time
from typing import List, Optional, Dict, Any
import structlog
from openai import AsyncOpenAI

from .provider import (
    LLMProvider,
    LLMResponse,
    Message,
    LLMModel,
    calculate_cost,
)

logger = structlog.get_logger()


class OpenAIProvider(LLMProvider):
    """OpenAI API 제공자"""

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-4o-mini",
        organization: Optional[str] = None,
    ):
        self._api_key = api_key
        self._default_model = default_model
        self._organization = organization

        self._client = AsyncOpenAI(
            api_key=api_key,
            organization=organization,
        )

        logger.info(
            "OpenAI provider initialized",
            default_model=default_model,
        )

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def provider_name(self) -> str:
        return "openai"

    async def generate(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        json_mode: bool = False,
    ) -> LLMResponse:
        """텍스트 생성"""
        model = model or self._default_model
        start_time = time.time()

        try:
            # Convert messages to OpenAI format
            openai_messages = [
                {"role": m.role, "content": m.content} for m in messages
            ]

            # Build request kwargs
            kwargs = {
                "model": model,
                "messages": openai_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            # Make API call
            response = await self._client.chat.completions.create(**kwargs)

            latency_ms = (time.time() - start_time) * 1000
            content = response.choices[0].message.content or ""

            # Parse JSON if in json_mode
            parsed = None
            if json_mode:
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON response", content=content[:100])

            # Calculate cost
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0
            cost = calculate_cost(model, prompt_tokens, completion_tokens)

            logger.debug(
                "OpenAI generation completed",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=latency_ms,
            )

            return LLMResponse(
                content=content,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                parsed=parsed,
                cost=cost,
                finish_reason=response.choices[0].finish_reason,
                latency_ms=latency_ms,
            )

        except Exception as e:
            logger.error(f"OpenAI generation failed: {e}")
            raise

    async def generate_with_schema(
        self,
        messages: List[Message],
        schema: Dict[str, Any],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        """스키마에 맞는 구조화된 응답 생성"""
        model = model or self._default_model
        start_time = time.time()

        try:
            # Add schema instruction to system message
            schema_instruction = f"""
You must respond with a valid JSON object that matches this schema:
{json.dumps(schema, indent=2)}

Only respond with the JSON object, no other text.
"""

            # Prepend schema instruction
            enhanced_messages = [
                Message(role="system", content=schema_instruction),
                *messages,
            ]

            openai_messages = [
                {"role": m.role, "content": m.content} for m in enhanced_messages
            ]

            # Make API call with JSON mode
            response = await self._client.chat.completions.create(
                model=model,
                messages=openai_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            latency_ms = (time.time() - start_time) * 1000
            content = response.choices[0].message.content or ""

            # Parse JSON
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse structured response: {e}")
                parsed = None

            # Calculate cost
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0
            cost = calculate_cost(model, prompt_tokens, completion_tokens)

            logger.debug(
                "OpenAI structured generation completed",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=latency_ms,
            )

            return LLMResponse(
                content=content,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                parsed=parsed,
                cost=cost,
                finish_reason=response.choices[0].finish_reason,
                latency_ms=latency_ms,
            )

        except Exception as e:
            logger.error(f"OpenAI structured generation failed: {e}")
            raise
