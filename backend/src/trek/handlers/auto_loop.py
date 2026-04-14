"""Auto-loop orchestrator (Step 40).

Runs one iteration of the evolutionary auto-loop for an experiment:
  Phase 1 (auto_loop_generate): Generate N variations via LLM, enqueue backtests.
  Phase 2 (auto_loop_collect_backtests): Poll backtest completion, filter by fitness, enqueue skeptic.
  Phase 3 (auto_loop_collect_skeptics): Poll skeptic completion, transition passing strategies
      to paper_trading, generate mutations for next generation, schedule next iteration.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from trek.encryption import decrypt_api_key
from trek.services.llm_client import LLMResponse, chat_completion, extract_python_code
from trek.worker import register_handler

log = logging.getLogger(__name__)

NOTIFY_CHANNEL = "new_task"

DEFAULT_VARIATIONS_PER_ITERATION = 5
DEFAULT_MUTATIONS_PER_PASSING = 3
DEFAULT_MIN_SORTINO = 1.5
DEFAULT_MAX_DRAWDOWN = 0.15
DEFAULT_ITERATION_DELAY_SECONDS = 300
DEFAULT_POLL_DELAY_SECONDS = 30
DEFAULT_BACKTEST_START = "2024-01-01T00:00:00+00:00"
DEFAULT_BACKTEST_END = "2025-01-01T00:00:00+00:00"

# -- SQL ------------------------------------------------------------------

FETCH_EXPERIMENT_SQL = """
SELECT id, name, is_active, max_iterations, current_iteration,
       fitness_function_config, risk_config_override, llm_config_override
FROM experiment WHERE id = $1;
"""

ACTIVE_RISK_CONFIG_SQL = """
SELECT min_sortino_threshold, max_max_drawdown_pct
FROM risk_config WHERE is_active = true
ORDER BY created_at DESC LIMIT 1;
"""

ACTIVE_LLM_CONFIG_SQL = """
SELECT id, provider, model_name, api_base_url, api_key_encrypted,
       temperature, max_tokens, cost_per_input_token, cost_per_output_token
FROM llm_config WHERE is_active = true
ORDER BY created_at DESC LIMIT 1;
"""

INSERT_VARIATION_SQL = """
INSERT INTO strategy_variation (
    id, experiment_id, parent_id, name, status, code,
    generation, llm_input_tokens, llm_output_tokens,
    llm_cost_usd, cumulative_llm_cost_usd,
    created_at, updated_at
) VALUES ($1, $2, $3, $4, 'generated', $5, $6, $7, $8, $9, $10, now(), now())
RETURNING id;
"""

UPDATE_STATUS_SQL = """
UPDATE strategy_variation SET status = $2, updated_at = now() WHERE id = $1;
"""

ENQUEUE_TASK_SQL = """
INSERT INTO task_queue (id, task_type, payload, status, retry_count, max_retries,
                        created_at, updated_at, scheduled_for)
VALUES ($1, $2, $3::jsonb, 'pending', 0, $4, now(), now(), $5);
"""

INCREMENT_ITERATION_SQL = """
UPDATE experiment SET current_iteration = current_iteration + 1, updated_at = now()
WHERE id = $1;
"""

FETCH_VARIATION_STATUS_SQL = """
SELECT id, status::text AS status FROM strategy_variation WHERE id = ANY($1::uuid[]);
"""

FETCH_BACKTEST_RESULTS_SQL = """
SELECT br.variation_id, br.sortino_ratio, br.max_drawdown, br.has_error
FROM backtest_run br
WHERE br.variation_id = ANY($1::uuid[])
  AND NOT br.has_error
ORDER BY br.sortino_ratio DESC NULLS LAST;
"""

FETCH_SKEPTIC_RESULTS_SQL = """
SELECT sa.variation_id,
       bool_and(sa.passed OR NOT (sa.stage IN ('static_analysis', 'cpcv', 'monte_carlo'))) AS all_hard_gates_passed
FROM skeptic_audit sa
WHERE sa.variation_id = ANY($1::uuid[])
GROUP BY sa.variation_id;
"""

FETCH_VARIATION_FOR_MUTATION_SQL = """
SELECT sv.id, sv.experiment_id, sv.code, sv.generation, sv.name,
       sv.llm_cost_usd, sv.cumulative_llm_cost_usd
FROM strategy_variation sv WHERE sv.id = $1;
"""

BEST_BACKTEST_SQL = """
SELECT sortino_ratio, sharpe_ratio, max_drawdown, total_return, win_rate, trade_count
FROM backtest_run WHERE variation_id = $1 AND NOT has_error
ORDER BY sortino_ratio DESC NULLS LAST LIMIT 1;
"""

# -- Config helpers -------------------------------------------------------


def _parse_auto_loop_config(experiment: dict[str, Any]) -> dict[str, Any]:
    """Extract auto-loop config from experiment's fitness_function_config and risk_config_override."""
    fitness_cfg = experiment.get("fitness_function_config") or {}
    if isinstance(fitness_cfg, str):
        fitness_cfg = json.loads(fitness_cfg)

    risk_override = experiment.get("risk_config_override") or {}
    if isinstance(risk_override, str):
        risk_override = json.loads(risk_override)

    llm_override = experiment.get("llm_config_override") or {}
    if isinstance(llm_override, str):
        llm_override = json.loads(llm_override)

    return {
        "variations_per_iteration": fitness_cfg.get(
            "variations_per_iteration", DEFAULT_VARIATIONS_PER_ITERATION
        ),
        "mutations_per_passing": fitness_cfg.get(
            "mutations_per_passing", DEFAULT_MUTATIONS_PER_PASSING
        ),
        "min_sortino": risk_override.get(
            "min_sortino_threshold", None
        ),
        "max_drawdown": risk_override.get(
            "max_max_drawdown_pct", None
        ),
        "iteration_delay_seconds": fitness_cfg.get(
            "iteration_delay_seconds", DEFAULT_ITERATION_DELAY_SECONDS
        ),
        "poll_delay_seconds": fitness_cfg.get(
            "poll_delay_seconds", DEFAULT_POLL_DELAY_SECONDS
        ),
        "backtest_start": fitness_cfg.get("backtest_start", DEFAULT_BACKTEST_START),
        "backtest_end": fitness_cfg.get("backtest_end", DEFAULT_BACKTEST_END),
        "llm_override": llm_override,
    }


async def _resolve_fitness_thresholds(
    pool: asyncpg.Pool,
    config: dict[str, Any],
) -> tuple[float, float]:
    """Resolve fitness thresholds: experiment override > global risk_config > defaults."""
    min_sortino = config.get("min_sortino")
    max_drawdown = config.get("max_drawdown")

    if min_sortino is not None and max_drawdown is not None:
        return float(min_sortino), float(max_drawdown)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(ACTIVE_RISK_CONFIG_SQL)

    if row is not None:
        if min_sortino is None:
            min_sortino = row["min_sortino_threshold"]
        if max_drawdown is None:
            max_drawdown = row["max_max_drawdown_pct"]

    return (
        float(min_sortino or DEFAULT_MIN_SORTINO),
        float(max_drawdown or DEFAULT_MAX_DRAWDOWN),
    )


async def _get_llm_config(pool: asyncpg.Pool, llm_override: dict[str, Any]) -> dict[str, Any]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(ACTIVE_LLM_CONFIG_SQL)
    if row is None:
        raise RuntimeError("No active LLM configuration found")
    cfg = dict(row)
    cfg["api_key"] = decrypt_api_key(cfg.pop("api_key_encrypted"))
    cfg["api_base_url"] = cfg.get("api_base_url") or "https://api.openai.com/v1"
    if llm_override.get("model_name"):
        cfg["model_name"] = llm_override["model_name"]
    if llm_override.get("temperature") is not None:
        cfg["temperature"] = llm_override["temperature"]
    return cfg


# -- LLM strategy generation ---------------------------------------------

GENERATION_SYSTEM_PROMPT = (
    "You are a quantitative trading strategy engineer. Generate Python trading "
    "strategy code that is correct, readable, and free of lookahead bias. "
    "Only use data available at each point in time."
)

GENERATION_USER_TEMPLATE = """\
Generate a Python trading strategy for the SOL/USDC pair.

The strategy must implement exactly this function:

```python
def generate_signal(df: pd.DataFrame) -> pd.Series:
```

Input DataFrame columns: open, high, low, close, volume (OHLCV).
Output: pandas Series of position signals: 1 (long), 0 (flat), -1 (short).

Rules:
1. Only import pandas and numpy.
2. Do NOT use .shift(-N) or any future-looking operation.
3. Handle NaN from indicator warm-up (fill with 0 or drop).
4. Return a Series of the same length as the input.

Variation #{variation_number} — try a DIFFERENT approach from any previous variations.
Use different indicator combinations, timeframes, or logic structures.

Return ONLY the Python code in a ```python block.
"""


async def _generate_variations(
    pool: asyncpg.Pool,
    experiment_id: uuid.UUID,
    n: int,
    generation: int,
    llm_cfg: dict[str, Any],
) -> list[uuid.UUID]:
    """Generate N new strategy variations via LLM and persist them."""
    variation_ids: list[uuid.UUID] = []

    for i in range(n):
        messages = [
            {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
            {"role": "user", "content": GENERATION_USER_TEMPLATE.format(variation_number=i + 1)},
        ]

        llm_resp: LLMResponse = await chat_completion(
            api_key=llm_cfg["api_key"],
            api_base_url=llm_cfg["api_base_url"],
            model=llm_cfg["model_name"],
            messages=messages,
            temperature=llm_cfg["temperature"],
            max_tokens=llm_cfg.get("max_tokens", 4096),
        )

        try:
            code = extract_python_code(llm_resp.content)
        except ValueError:
            log.warning("LLM response %d did not contain valid code, skipping", i + 1)
            continue

        own_cost = (
            llm_resp.input_tokens * llm_cfg["cost_per_input_token"]
            + llm_resp.output_tokens * llm_cfg["cost_per_output_token"]
        )
        vid = uuid.uuid4()
        name = f"auto-gen-g{generation}-v{i + 1}"

        async with pool.acquire() as conn:
            await conn.execute(
                INSERT_VARIATION_SQL,
                vid, experiment_id, None, name, code,
                generation, llm_resp.input_tokens, llm_resp.output_tokens,
                own_cost, own_cost,
            )

        log.info("Generated variation %s (%s), cost=$%.6f", vid, name, own_cost)
        variation_ids.append(vid)

    return variation_ids


# -- Mutation helper ------------------------------------------------------

MUTATION_SYSTEM_PROMPT = (
    "You are a quantitative trading strategy developer. "
    "Produce a MUTATED child strategy that improves on the parent's weaknesses."
)

MUTATION_USER_TEMPLATE = """\
## Parent Strategy Code
```python
{parent_code}
```

## Parent Backtest Metrics
{metrics}

## Instructions
Make meaningful changes — do not return the parent code unchanged.
Rules:
1. Must implement: generate_signal(df: pd.DataFrame) -> pd.Series
2. Input: open, high, low, close, volume (OHLCV for SOL/USDC)
3. Output: 1 (long), 0 (flat), -1 (short)
4. Only use pandas and numpy.
Return ONLY the Python code in a ```python block.
"""


def _format_metrics(backtest: dict[str, Any] | None) -> str:
    if backtest is None:
        return "No backtest results available."
    lines = []
    for key in ("sortino_ratio", "sharpe_ratio", "max_drawdown", "total_return", "win_rate", "trade_count"):
        val = backtest.get(key)
        if val is not None:
            lines.append(f"- {key}: {val}")
    return "\n".join(lines) if lines else "No metrics recorded."


async def _mutate_variation(
    pool: asyncpg.Pool,
    parent_id: uuid.UUID,
    llm_cfg: dict[str, Any],
) -> uuid.UUID | None:
    """Create one mutation of a parent variation."""
    async with pool.acquire() as conn:
        parent = await conn.fetchrow(FETCH_VARIATION_FOR_MUTATION_SQL, parent_id)
        if parent is None:
            log.error("Parent variation %s not found for mutation", parent_id)
            return None
        backtest = await conn.fetchrow(BEST_BACKTEST_SQL, parent_id)

    messages = [
        {"role": "system", "content": MUTATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": MUTATION_USER_TEMPLATE.format(
                parent_code=parent["code"],
                metrics=_format_metrics(dict(backtest) if backtest else None),
            ),
        },
    ]

    llm_resp = await chat_completion(
        api_key=llm_cfg["api_key"],
        api_base_url=llm_cfg["api_base_url"],
        model=llm_cfg["model_name"],
        messages=messages,
        temperature=llm_cfg["temperature"],
        max_tokens=llm_cfg.get("max_tokens", 4096),
    )

    try:
        child_code = extract_python_code(llm_resp.content)
    except ValueError:
        log.warning("Mutation LLM response for parent %s had no valid code", parent_id)
        return None

    own_cost = (
        llm_resp.input_tokens * llm_cfg["cost_per_input_token"]
        + llm_resp.output_tokens * llm_cfg["cost_per_output_token"]
    )
    child_generation = parent["generation"] + 1
    cumulative_cost = (parent["cumulative_llm_cost_usd"] or 0.0) + own_cost
    child_id = uuid.uuid4()
    child_name = f"{parent['name'] or 'strategy'}-mut-g{child_generation}"

    async with pool.acquire() as conn:
        await conn.execute(
            INSERT_VARIATION_SQL,
            child_id, parent["experiment_id"], parent_id, child_name, child_code,
            child_generation, llm_resp.input_tokens, llm_resp.output_tokens,
            own_cost, cumulative_cost,
        )

    log.info("Created mutation %s from parent %s, cost=$%.6f", child_id, parent_id, own_cost)
    return child_id


# -- Task enqueueing helper -----------------------------------------------

async def _enqueue_task(
    conn: asyncpg.Connection,
    task_type: str,
    payload: dict[str, Any],
    *,
    scheduled_at: datetime | None = None,
    max_retries: int = 3,
) -> uuid.UUID:
    task_id = uuid.uuid4()
    await conn.execute(
        ENQUEUE_TASK_SQL,
        task_id, task_type, json.dumps(payload), max_retries, scheduled_at,
    )
    await conn.execute(f"SELECT pg_notify('{NOTIFY_CHANNEL}', $1)", task_type)
    return task_id


# =========================================================================
# Phase 1: Generate variations and enqueue backtests
# =========================================================================

@register_handler("auto_loop_generate")
async def handle_auto_loop_generate(payload: dict[str, Any], pool: asyncpg.Pool) -> None:
    experiment_id = uuid.UUID(payload["experiment_id"])
    iteration = payload.get("iteration", 1)

    async with pool.acquire() as conn:
        experiment = await conn.fetchrow(FETCH_EXPERIMENT_SQL, experiment_id)
    if experiment is None:
        raise ValueError(f"Experiment {experiment_id} not found")
    if not experiment["is_active"]:
        log.info("Experiment %s is inactive, skipping auto-loop", experiment_id)
        return

    max_iter = experiment["max_iterations"]
    if max_iter is not None and iteration > max_iter:
        log.info("Experiment %s reached max iterations (%d), stopping", experiment_id, max_iter)
        return

    config = _parse_auto_loop_config(dict(experiment))
    n = config["variations_per_iteration"]

    log.info(
        "Auto-loop iteration %d for experiment %s: generating %d variations",
        iteration, experiment_id, n,
    )

    llm_cfg = await _get_llm_config(pool, config["llm_override"])
    variation_ids = await _generate_variations(pool, experiment_id, n, iteration, llm_cfg)

    if not variation_ids:
        log.warning("No variations generated for experiment %s iteration %d", experiment_id, iteration)
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            for vid in variation_ids:
                await _enqueue_task(conn, "backtest", {
                    "variation_id": str(vid),
                    "start_date": config["backtest_start"],
                    "end_date": config["backtest_end"],
                })

            poll_at = datetime.now(timezone.utc) + timedelta(seconds=config["poll_delay_seconds"])

            await _enqueue_task(
                conn,
                "auto_loop_collect_backtests",
                {
                    "experiment_id": str(experiment_id),
                    "iteration": iteration,
                    "variation_ids": [str(v) for v in variation_ids],
                    "config": config,
                },
                scheduled_at=poll_at,
            )

    log.info(
        "Enqueued %d backtests and collector for experiment %s iteration %d",
        len(variation_ids), experiment_id, iteration,
    )


# =========================================================================
# Phase 2: Collect backtest results, filter by fitness, enqueue skeptic
# =========================================================================

@register_handler("auto_loop_collect_backtests")
async def handle_auto_loop_collect_backtests(payload: dict[str, Any], pool: asyncpg.Pool) -> None:
    experiment_id = uuid.UUID(payload["experiment_id"])
    iteration = payload["iteration"]
    variation_ids = [uuid.UUID(v) for v in payload["variation_ids"]]
    config = payload["config"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(FETCH_VARIATION_STATUS_SQL, variation_ids)

    status_map = {row["id"]: row["status"] for row in rows}
    still_running = [vid for vid in variation_ids if status_map.get(vid) == "backtesting"]

    if still_running:
        log.info(
            "Experiment %s iteration %d: %d/%d backtests still running, re-polling",
            experiment_id, iteration, len(still_running), len(variation_ids),
        )
        poll_at = datetime.now(timezone.utc) + timedelta(
            seconds=config.get("poll_delay_seconds", DEFAULT_POLL_DELAY_SECONDS)
        )
        async with pool.acquire() as conn:
            await _enqueue_task(
                conn,
                "auto_loop_collect_backtests",
                payload,
                scheduled_at=poll_at,
            )
        return

    backtested_ids = [vid for vid in variation_ids if status_map.get(vid) == "backtested"]
    log.info(
        "Experiment %s iteration %d: all backtests done, %d/%d backtested",
        experiment_id, iteration, len(backtested_ids), len(variation_ids),
    )

    if not backtested_ids:
        log.warning("No successful backtests for experiment %s iteration %d", experiment_id, iteration)
        await _schedule_next_iteration(pool, experiment_id, iteration, config)
        return

    min_sortino, max_drawdown = await _resolve_fitness_thresholds(pool, config)

    async with pool.acquire() as conn:
        backtest_rows = await conn.fetch(FETCH_BACKTEST_RESULTS_SQL, backtested_ids)

    passing_ids: list[uuid.UUID] = []
    for row in backtest_rows:
        vid = row["variation_id"]
        sortino = row["sortino_ratio"]
        drawdown = row["max_drawdown"]

        sortino_ok = sortino is not None and sortino > min_sortino
        drawdown_ok = drawdown is not None and abs(drawdown) < max_drawdown

        if sortino_ok and drawdown_ok:
            passing_ids.append(vid)
            log.info(
                "Variation %s PASSES fitness: sortino=%.4f (>%.2f), drawdown=%.4f (<%.2f)",
                vid, sortino, min_sortino, abs(drawdown), max_drawdown,
            )
        else:
            log.info(
                "Variation %s FAILS fitness: sortino=%s, drawdown=%s",
                vid, sortino, drawdown,
            )

    if not passing_ids:
        log.info(
            "No variations passed fitness for experiment %s iteration %d, scheduling next",
            experiment_id, iteration,
        )
        await _schedule_next_iteration(pool, experiment_id, iteration, config)
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            for vid in passing_ids:
                await _enqueue_task(conn, "skeptic_pipeline", {
                    "variation_id": str(vid),
                })

            poll_at = datetime.now(timezone.utc) + timedelta(
                seconds=config.get("poll_delay_seconds", DEFAULT_POLL_DELAY_SECONDS)
            )

            await _enqueue_task(
                conn,
                "auto_loop_collect_skeptics",
                {
                    "experiment_id": str(experiment_id),
                    "iteration": iteration,
                    "variation_ids": [str(v) for v in passing_ids],
                    "config": config,
                },
                scheduled_at=poll_at,
            )

    log.info(
        "Enqueued %d skeptic pipelines for experiment %s iteration %d",
        len(passing_ids), experiment_id, iteration,
    )


# =========================================================================
# Phase 3: Collect skeptic results, transition, mutate, schedule next
# =========================================================================

@register_handler("auto_loop_collect_skeptics")
async def handle_auto_loop_collect_skeptics(payload: dict[str, Any], pool: asyncpg.Pool) -> None:
    experiment_id = uuid.UUID(payload["experiment_id"])
    iteration = payload["iteration"]
    variation_ids = [uuid.UUID(v) for v in payload["variation_ids"]]
    config = payload["config"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(FETCH_VARIATION_STATUS_SQL, variation_ids)

    status_map = {row["id"]: row["status"] for row in rows}
    still_running = [
        vid for vid in variation_ids
        if status_map.get(vid) == "skeptic_pending"
    ]

    if still_running:
        log.info(
            "Experiment %s iteration %d: %d/%d skeptic audits still running, re-polling",
            experiment_id, iteration, len(still_running), len(variation_ids),
        )
        poll_at = datetime.now(timezone.utc) + timedelta(
            seconds=config.get("poll_delay_seconds", DEFAULT_POLL_DELAY_SECONDS)
        )
        async with pool.acquire() as conn:
            await _enqueue_task(
                conn,
                "auto_loop_collect_skeptics",
                payload,
                scheduled_at=poll_at,
            )
        return

    skeptic_passed = [
        vid for vid in variation_ids
        if status_map.get(vid) == "skeptic_passed"
    ]
    skeptic_failed = [
        vid for vid in variation_ids
        if status_map.get(vid) == "skeptic_failed"
    ]

    log.info(
        "Experiment %s iteration %d: skeptic complete — %d passed, %d failed",
        experiment_id, iteration, len(skeptic_passed), len(skeptic_failed),
    )

    if skeptic_passed:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for vid in skeptic_passed:
                    await conn.execute(UPDATE_STATUS_SQL, vid, "paper_trading")
        log.info(
            "Transitioned %d variations to paper_trading for experiment %s",
            len(skeptic_passed), experiment_id,
        )

    mutations_per = config.get("mutations_per_passing", DEFAULT_MUTATIONS_PER_PASSING)
    if skeptic_passed and mutations_per > 0:
        llm_cfg = await _get_llm_config(pool, config.get("llm_override", {}))
        mutation_ids: list[uuid.UUID] = []

        for parent_id in skeptic_passed:
            for _ in range(mutations_per):
                child_id = await _mutate_variation(pool, parent_id, llm_cfg)
                if child_id:
                    mutation_ids.append(child_id)

        if mutation_ids:
            log.info(
                "Generated %d mutations from %d passing strategies for experiment %s",
                len(mutation_ids), len(skeptic_passed), experiment_id,
            )

    await _schedule_next_iteration(pool, experiment_id, iteration, config)


# =========================================================================
# Schedule next iteration
# =========================================================================

async def _schedule_next_iteration(
    pool: asyncpg.Pool,
    experiment_id: uuid.UUID,
    current_iteration: int,
    config: dict[str, Any],
) -> None:
    """Increment experiment iteration counter and schedule the next auto_loop_generate."""
    async with pool.acquire() as conn:
        await conn.execute(INCREMENT_ITERATION_SQL, experiment_id)

        experiment = await conn.fetchrow(FETCH_EXPERIMENT_SQL, experiment_id)

    if experiment is None or not experiment["is_active"]:
        log.info("Experiment %s is inactive, not scheduling next iteration", experiment_id)
        return

    max_iter = experiment["max_iterations"]
    next_iteration = current_iteration + 1
    if max_iter is not None and next_iteration > max_iter:
        log.info("Experiment %s reached max iterations (%d), stopping", experiment_id, max_iter)
        return

    delay = config.get("iteration_delay_seconds", DEFAULT_ITERATION_DELAY_SECONDS)
    scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)

    async with pool.acquire() as conn:
        task_id = await _enqueue_task(
            conn,
            "auto_loop_generate",
            {
                "experiment_id": str(experiment_id),
                "iteration": next_iteration,
            },
            scheduled_at=scheduled_at,
        )

    log.info(
        "Scheduled next auto-loop iteration %d for experiment %s in %ds (task %s)",
        next_iteration, experiment_id, delay, task_id,
    )
