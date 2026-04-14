from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg

from trek.encryption import decrypt_api_key
from trek.services.llm_client import LLMResponse, chat_completion, extract_python_code

log = logging.getLogger(__name__)

PARENT_SQL = """
SELECT sv.id, sv.experiment_id, sv.code, sv.generation, sv.name,
       sv.llm_cost_usd, sv.cumulative_llm_cost_usd, sv.status::text AS status
FROM strategy_variation sv
WHERE sv.id = $1;
"""

BEST_BACKTEST_SQL = """
SELECT sortino_ratio, sharpe_ratio, max_drawdown, total_return,
       win_rate, trade_count
FROM backtest_run
WHERE variation_id = $1 AND NOT has_error
ORDER BY sortino_ratio DESC NULLS LAST
LIMIT 1;
"""

LLM_CONFIG_SQL = """
SELECT id, provider, model_name, api_base_url, api_key_encrypted,
       temperature, max_tokens, cost_per_input_token, cost_per_output_token
FROM llm_config
WHERE is_active = true
ORDER BY created_at DESC
LIMIT 1;
"""

INSERT_CHILD_SQL = """
INSERT INTO strategy_variation (
    id, experiment_id, parent_id, name, status, code,
    generation, llm_input_tokens, llm_output_tokens,
    llm_cost_usd, cumulative_llm_cost_usd,
    created_at, updated_at
)
VALUES ($1, $2, $3, $4, 'generated', $5, $6, $7, $8, $9, $10, now(), now())
RETURNING id;
"""


@dataclass(frozen=True, slots=True)
class MutationResult:
    child_id: uuid.UUID
    generation: int
    llm_cost_usd: float
    cumulative_llm_cost_usd: float


def _format_metrics(backtest: dict[str, Any] | None) -> str:
    if backtest is None:
        return "No backtest results available."

    lines = []
    metric_names = [
        ("sortino_ratio", "Sortino Ratio"),
        ("sharpe_ratio", "Sharpe Ratio"),
        ("max_drawdown", "Max Drawdown"),
        ("total_return", "Total Return"),
        ("win_rate", "Win Rate"),
        ("trade_count", "Trade Count"),
    ]
    for key, label in metric_names:
        val = backtest.get(key)
        if val is not None:
            lines.append(f"- {label}: {val}")
    return "\n".join(lines) if lines else "No metrics recorded."


def _identify_weaknesses(backtest: dict[str, Any] | None) -> str:
    if backtest is None:
        return "No backtest data — generate a fundamentally different approach."

    issues = []
    sortino = backtest.get("sortino_ratio")
    sharpe = backtest.get("sharpe_ratio")
    max_dd = backtest.get("max_drawdown")
    total_ret = backtest.get("total_return")
    win_rate = backtest.get("win_rate")

    if sortino is not None and sortino < 1.0:
        issues.append("low Sortino ratio — reduce downside volatility")
    if sharpe is not None and sharpe < 1.0:
        issues.append("low Sharpe ratio — improve risk-adjusted returns")
    if max_dd is not None and max_dd < -0.15:
        issues.append(f"high max drawdown ({max_dd:.1%}) — add tighter stop-losses or position sizing")
    if total_ret is not None and total_ret < 0:
        issues.append("negative total return — the strategy loses money")
    if win_rate is not None and win_rate < 0.45:
        issues.append(f"low win rate ({win_rate:.1%}) — improve entry signal quality")

    if not issues:
        return "The parent performs reasonably. Try a different angle or indicator combination to find further alpha."
    return "Key weaknesses to address:\n" + "\n".join(f"- {i}" for i in issues)


def build_mutation_prompt(
    parent_code: str,
    backtest: dict[str, Any] | None,
) -> list[dict[str, str]]:
    metrics_str = _format_metrics(backtest)
    weaknesses_str = _identify_weaknesses(backtest)

    system_msg = (
        "You are a quantitative trading strategy developer. "
        "You will be given a parent trading strategy's Python code and its backtest performance metrics. "
        "Your task is to produce a MUTATED child strategy that improves on the parent's weaknesses.\n\n"
        "Rules:\n"
        "1. The strategy MUST implement: generate_signal(df: pd.DataFrame) -> pd.Series\n"
        "2. The input DataFrame has columns: open, high, low, close, volume (OHLCV for SOL/USDC)\n"
        "3. The output Series must contain position signals: 1 (long), 0 (flat), -1 (short)\n"
        "4. You may use pandas and numpy. Do NOT import anything else.\n"
        "5. Make meaningful changes — do not return the parent code unchanged.\n"
        "6. Return ONLY the Python code inside a single ```python code block.\n"
    )

    user_msg = (
        f"## Parent Strategy Code\n```python\n{parent_code}\n```\n\n"
        f"## Parent Backtest Metrics\n{metrics_str}\n\n"
        f"## Improvement Instructions\n{weaknesses_str}\n\n"
        "Produce an improved child strategy. Return only the code in a ```python block."
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


async def mutate_variation(
    pool: asyncpg.Pool,
    parent_variation_id: uuid.UUID,
) -> MutationResult:
    async with pool.acquire() as conn:
        parent = await conn.fetchrow(PARENT_SQL, parent_variation_id)
        if parent is None:
            raise ValueError(f"Parent variation {parent_variation_id} not found")

        backtest = await conn.fetchrow(BEST_BACKTEST_SQL, parent_variation_id)

        llm_cfg = await conn.fetchrow(LLM_CONFIG_SQL)
        if llm_cfg is None:
            raise RuntimeError("No active LLM configuration found")

    api_key = decrypt_api_key(llm_cfg["api_key_encrypted"])
    api_base = llm_cfg["api_base_url"] or "https://api.openai.com/v1"

    messages = build_mutation_prompt(
        parent_code=parent["code"],
        backtest=dict(backtest) if backtest else None,
    )

    llm_resp: LLMResponse = await chat_completion(
        api_key=api_key,
        api_base_url=api_base,
        model=llm_cfg["model_name"],
        messages=messages,
        temperature=llm_cfg["temperature"],
        max_tokens=llm_cfg["max_tokens"],
    )

    child_code = extract_python_code(llm_resp.content)

    own_cost = (
        llm_resp.input_tokens * llm_cfg["cost_per_input_token"]
        + llm_resp.output_tokens * llm_cfg["cost_per_output_token"]
    )
    child_generation = parent["generation"] + 1
    cumulative_cost = parent["cumulative_llm_cost_usd"] + own_cost
    child_id = uuid.uuid4()
    child_name = f"{parent['name'] or 'strategy'}-mut-g{child_generation}"

    async with pool.acquire() as conn:
        await conn.execute(
            INSERT_CHILD_SQL,
            child_id,
            parent["experiment_id"],
            parent_variation_id,
            child_name,
            child_code,
            child_generation,
            llm_resp.input_tokens,
            llm_resp.output_tokens,
            own_cost,
            cumulative_cost,
        )

    log.info(
        "Created child variation %s (gen %d) from parent %s, cost=$%.6f",
        child_id, child_generation, parent_variation_id, own_cost,
    )

    return MutationResult(
        child_id=child_id,
        generation=child_generation,
        llm_cost_usd=own_cost,
        cumulative_llm_cost_usd=cumulative_cost,
    )
