from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.llm_config import LLMConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class LLMResult:
    content: str
    usage: LLMUsage
    model: str
    provider: str


def compute_cost(
    input_tokens: int,
    output_tokens: int,
    cost_per_input_token: float,
    cost_per_output_token: float,
) -> float:
    return (input_tokens * cost_per_input_token) + (
        output_tokens * cost_per_output_token
    )


async def get_active_llm_config(
    session: AsyncSession,
    config_id: uuid.UUID | None = None,
) -> LLMConfig:
    if config_id:
        stmt = select(LLMConfig).where(LLMConfig.id == config_id)
    else:
        stmt = select(LLMConfig).where(LLMConfig.is_active.is_(True)).limit(1)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None:
        raise ValueError("No active LLM configuration found")
    return config


def extract_usage_from_response(
    raw_response: dict,
    cost_per_input_token: float,
    cost_per_output_token: float,
) -> LLMUsage:
    usage = raw_response.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
    cost = compute_cost(
        input_tokens, output_tokens, cost_per_input_token, cost_per_output_token
    )
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )


def parse_llm_response(
    raw_response: dict,
    config: LLMConfig,
) -> LLMResult:
    usage = extract_usage_from_response(
        raw_response,
        config.cost_per_input_token,
        config.cost_per_output_token,
    )

    content = ""
    choices = raw_response.get("choices", [])
    if choices:
        message = choices[0].get("message", {})
        content = message.get("content", "")
    elif "content" in raw_response:
        blocks = raw_response["content"]
        if isinstance(blocks, list):
            content = "".join(
                b.get("text", "") for b in blocks if b.get("type") == "text"
            )
        elif isinstance(blocks, str):
            content = blocks

    logger.info(
        "llm_call",
        extra={
            "provider": config.provider,
            "model": config.model_name,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": usage.cost_usd,
        },
    )

    return LLMResult(
        content=content,
        usage=usage,
        model=config.model_name,
        provider=config.provider,
    )
