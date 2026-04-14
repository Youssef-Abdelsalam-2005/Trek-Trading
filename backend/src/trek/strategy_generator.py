"""LLM strategy generation service — produces generate_signal() code via OpenAI-compatible API."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from trek.models import StrategyStatus

log = logging.getLogger(__name__)

AVAILABLE_INDICATORS = [
    "SMA (Simple Moving Average)",
    "EMA (Exponential Moving Average)",
    "RSI (Relative Strength Index)",
    "MACD (Moving Average Convergence Divergence)",
    "Bollinger Bands (upper, middle, lower)",
    "ATR (Average True Range)",
    "OBV (On-Balance Volume)",
    "VWAP (Volume-Weighted Average Price)",
    "Stochastic Oscillator (%K, %D)",
    "ADX (Average Directional Index)",
]

SYSTEM_PROMPT = (
    "You are a quantitative trading strategy engineer. You generate Python trading "
    "strategy code that is correct, readable, and free of lookahead bias. You only "
    "use data available at each point in time. You never use future data to make "
    "current decisions."
)

USER_PROMPT_TEMPLATE = """\
Generate a Python trading strategy for the {asset} pair.

The strategy must implement exactly this function signature:

```python
def generate_signal(df: pd.DataFrame) -> pd.Series:
```

**Input DataFrame columns:** `open`, `high`, `low`, `close`, `volume` (OHLCV data, \
indexed by datetime).

**Output:** A pandas Series of position signals aligned with the DataFrame index:
- `1` = long / buy
- `0` = flat / no position
- `-1` = short / sell (if applicable, otherwise use 0)

**Available indicators you may compute from the OHLCV data:**
{indicators}

**Fitness criteria (what makes a good strategy):**
{fitness_function}

**Constraints:**
{constraints}

**Rules:**
1. Only import `pandas` and `numpy`. No other libraries.
2. Do NOT use `.shift(-N)` or any operation that looks into the future.
3. Handle NaN values from indicator warm-up periods (fill with 0 or drop).
4. The function must be deterministic given the same input data.
5. Return a Series of the same length as the input DataFrame.

Respond with ONLY the Python code block — no explanation, no markdown outside the \
code fence.

```python
import pandas as pd
import numpy as np

def generate_signal(df: pd.DataFrame) -> pd.Series:
    ...
```
"""


class GenerationRequest(BaseModel):
    experiment_id: str
    asset: str = "SOL/USDC"
    fitness_function: str = "Maximize Sortino ratio while keeping max drawdown under 30%"
    constraints: str = "Minimum 20 trades over the backtest period. No single position held longer than 7 days."
    model: str = "gpt-4o"
    max_tokens: int = 2048
    parent_variation_id: str | None = None
    parent_cumulative_cost_usd: float = 0.0


class CostBreakdown(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    latency_ms: float = 0.0


class GenerationResult(BaseModel):
    variation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    experiment_id: str = ""
    parent_variation_id: str | None = None
    status: str = StrategyStatus.GENERATED.value
    code: str = ""
    cost: CostBreakdown = Field(default_factory=CostBreakdown)
    cumulative_cost_usd: float = 0.0
    error: str | None = None


TOKEN_COSTS_PER_MILLION: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
}

DEFAULT_COST_PER_MILLION = {"input": 2.50, "output": 10.0}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = TOKEN_COSTS_PER_MILLION.get(model, DEFAULT_COST_PER_MILLION)
    return (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000


def build_prompt(request: GenerationRequest) -> str:
    indicators_text = "\n".join(f"- {ind}" for ind in AVAILABLE_INDICATORS)
    return USER_PROMPT_TEMPLATE.format(
        asset=request.asset,
        indicators=indicators_text,
        fitness_function=request.fitness_function,
        constraints=request.constraints,
    )


_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extract_code(raw: str) -> str:
    match = _CODE_FENCE_RE.search(raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def validate_code(code: str) -> str | None:
    if "def generate_signal(" not in code:
        return "Missing generate_signal function definition"
    if ".shift(-" in code:
        return "Potential lookahead bias: .shift(-N) detected"
    try:
        compile(code, "<strategy>", "exec")
    except SyntaxError as exc:
        return f"Syntax error: {exc}"
    return None


async def generate_strategy(request: GenerationRequest) -> GenerationResult:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return GenerationResult(
            experiment_id=request.experiment_id,
            error="openai SDK not installed — add 'openai' to dependencies",
        )

    client = AsyncOpenAI()
    user_message = build_prompt(request)

    start = time.monotonic()
    try:
        response = await client.chat.completions.create(
            model=request.model,
            max_tokens=request.max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
        )
    except Exception as exc:
        log.error("LLM strategy generation call failed: %s", exc)
        return GenerationResult(
            experiment_id=request.experiment_id,
            parent_variation_id=request.parent_variation_id,
            error=str(exc),
        )
    latency_ms = (time.monotonic() - start) * 1000

    raw_text = response.choices[0].message.content or "" if response.choices else ""
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    cost_usd = estimate_cost(request.model, prompt_tokens, completion_tokens)
    cumulative_cost_usd = request.parent_cumulative_cost_usd + cost_usd

    cost = CostBreakdown(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        model=request.model,
        latency_ms=latency_ms,
    )

    code = extract_code(raw_text)
    validation_error = validate_code(code)
    if validation_error:
        log.warning("Generated code failed validation: %s", validation_error)
        return GenerationResult(
            experiment_id=request.experiment_id,
            parent_variation_id=request.parent_variation_id,
            code=code,
            cost=cost,
            cumulative_cost_usd=cumulative_cost_usd,
            error=f"Code validation failed: {validation_error}",
        )

    result = GenerationResult(
        experiment_id=request.experiment_id,
        parent_variation_id=request.parent_variation_id,
        code=code,
        cost=cost,
        cumulative_cost_usd=cumulative_cost_usd,
    )

    await create_strategy_variation(result)

    return result


_db_pool = None


def set_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def create_strategy_variation(result: GenerationResult) -> None:
    if _db_pool is None:
        log.info(
            "strategy_variation %s created [status=%s, cost=$%.6f, cumulative=$%.6f] (no DB pool)",
            result.variation_id, result.status, result.cost.cost_usd, result.cumulative_cost_usd,
        )
        return

    async with _db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO strategy_variation
                (id, experiment_id, parent_id, status, code, lineage_depth,
                 llm_token_input, llm_token_output, llm_cost, llm_cumulative_cost,
                 error, created_at, updated_at)
            VALUES ($1, $2, $3, $4::strategy_status, $5, $6, $7, $8, $9, $10, $11, now(), now())
            """,
            uuid.UUID(result.variation_id),
            uuid.UUID(result.experiment_id) if result.experiment_id else None,
            uuid.UUID(result.parent_variation_id) if result.parent_variation_id else None,
            result.status,
            result.code,
            0,
            result.cost.prompt_tokens,
            result.cost.completion_tokens,
            result.cost.cost_usd,
            result.cumulative_cost_usd,
            result.error,
        )
    log.info("strategy_variation %s persisted", result.variation_id)


async def get_parent_cumulative_cost(variation_id: str) -> float:
    if _db_pool is None:
        log.info("Parent cost lookup for %s (no DB pool)", variation_id)
        return 0.0

    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT llm_cumulative_cost FROM strategy_variation WHERE id = $1",
            uuid.UUID(variation_id),
        )
    if row is None:
        return 0.0
    return float(row["llm_cumulative_cost"])
