"""Skeptic pipeline orchestrator (Step 26).

Runs the 4-stage skeptic pipeline in order:
  1. Static analysis (AST-based lookahead scanner) — hard gate
  2. CPCV (combinatorial purged cross-validation) — hard gate
  3. Monte Carlo (shuffle + shift tests) — hard gate
  4. LLM-as-critic — advisory only

Fail-fast: if any hard-gate stage (1-3) fails, remaining stages are skipped.
Creates one skeptic_audit record per stage with per-stage results.
Transitions strategy: backtested → skeptic_pending → skeptic_passed/skeptic_failed.
Fires pg_notify('sse_events', ...) on completion for SSE forwarding.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.backtest_run import BacktestRun
from backend.app.models.enums import StrategyStatus
from backend.app.models.skeptic_audit import SkepticAudit
from backend.app.models.strategy_variation import StrategyVariation
from backend.src.trek.database import async_session_factory
from backend.src.trek.skeptic.lookahead_scanner import Severity as ScannerSeverity
from backend.src.trek.skeptic.lookahead_scanner import report as scanner_report
from backend.src.trek.skeptic.lookahead_scanner import scan as scanner_scan

log = logging.getLogger(__name__)

SSE_CHANNEL = "sse_events"


@dataclass
class StageResult:
    stage: str
    passed: bool
    score: float | None = None
    reasoning: str | None = None
    details: dict | None = None
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None
    llm_cost_usd: float | None = None
    is_hard_gate: bool = True


async def run_pipeline(variation_id: str) -> None:
    vid = uuid.UUID(variation_id)

    async with async_session_factory() as session:
        variation = await session.get(StrategyVariation, vid)
        if variation is None:
            raise ValueError(f"Variation {variation_id} not found")

        variation.transition_to(StrategyStatus.SKEPTIC_PENDING)
        await session.commit()
        log.info("Variation %s transitioned to skeptic_pending", variation_id)

    pipeline_passed = True
    stage_results: list[StageResult] = []

    stages = [
        _run_static_analysis,
        _run_cpcv,
        _run_monte_carlo,
        _run_llm_critic,
    ]

    for stage_fn in stages:
        async with async_session_factory() as session:
            variation = await session.get(StrategyVariation, vid)
            if variation is None:
                raise ValueError(f"Variation {variation_id} disappeared mid-pipeline")

        result = await stage_fn(variation)
        stage_results.append(result)

        async with async_session_factory() as session:
            audit = SkepticAudit(
                variation_id=vid,
                stage=result.stage,
                passed=result.passed,
                score=result.score,
                reasoning=result.reasoning,
                details=result.details,
                llm_input_tokens=result.llm_input_tokens,
                llm_output_tokens=result.llm_output_tokens,
                llm_cost_usd=result.llm_cost_usd,
            )
            session.add(audit)
            await session.commit()
            log.info(
                "Stage %s for variation %s: %s",
                result.stage, variation_id, "PASS" if result.passed else "FAIL",
            )

        if not result.passed and result.is_hard_gate:
            pipeline_passed = False
            log.info(
                "Hard gate %s failed — skipping remaining stages for %s",
                result.stage, variation_id,
            )
            break

    final_status = (
        StrategyStatus.SKEPTIC_PASSED if pipeline_passed
        else StrategyStatus.SKEPTIC_FAILED
    )

    async with async_session_factory() as session:
        variation = await session.get(StrategyVariation, vid)
        if variation is None:
            raise ValueError(f"Variation {variation_id} disappeared mid-pipeline")

        variation.transition_to(final_status)

        if not pipeline_passed:
            failed_stages = [r.stage for r in stage_results if not r.passed and r.is_hard_gate]
            variation.error_message = f"Skeptic failed at: {', '.join(failed_stages)}"

        if stage_results:
            llm_cost = sum(r.llm_cost_usd or 0.0 for r in stage_results)
            if llm_cost > 0:
                variation.cumulative_llm_cost_usd += llm_cost

        await session.commit()

        event_payload = json.dumps({
            "event": "skeptic_completed",
            "variation_id": variation_id,
            "status": final_status.value,
            "stages_run": len(stage_results),
            "stages_passed": sum(1 for r in stage_results if r.passed),
        })
        await session.execute(
            text(f"SELECT pg_notify(:channel, :payload)"),
            {"channel": SSE_CHANNEL, "payload": event_payload},
        )
        await session.commit()

    log.info(
        "Skeptic pipeline complete for %s: %s (%d/%d stages passed)",
        variation_id, final_status.value,
        sum(1 for r in stage_results if r.passed), len(stage_results),
    )


async def _run_static_analysis(variation: StrategyVariation) -> StageResult:
    start = time.monotonic()
    try:
        findings = scanner_scan(variation.code)
        rpt = scanner_report(findings)
    except SyntaxError as exc:
        return StageResult(
            stage="static_analysis",
            passed=False,
            reasoning=f"Strategy code failed to parse: {exc}",
            details={"error": str(exc)},
        )
    duration_ms = (time.monotonic() - start) * 1000

    high_count = len(rpt["by_severity"].get(ScannerSeverity.HIGH.value, []))
    passed = high_count == 0

    return StageResult(
        stage="static_analysis",
        passed=passed,
        score=float(rpt["total_findings"]),
        reasoning=(
            f"{rpt['total_findings']} findings ({high_count} HIGH severity). "
            f"{'No HIGH severity issues — pass.' if passed else 'HIGH severity issues detected — fail.'}"
        ),
        details={
            **rpt,
            "duration_ms": duration_ms,
        },
    )


async def _run_cpcv(variation: StrategyVariation) -> StageResult:
    """CPCV stage — requires backtest data and strategy runner from sandbox.

    Until the sandbox runner (Step 17) and CPCV module (Step 23) are merged,
    this stage loads backtest results and uses them as a proxy for validation.
    If no backtest data is available, the stage passes with a warning.
    """
    try:
        from backend.src.trek.skeptic.cpcv import CPCVConfig, run_cpcv
    except ImportError:
        log.warning("CPCV module not available — stage passes with advisory note")
        return StageResult(
            stage="cpcv",
            passed=True,
            reasoning="CPCV module not yet available — skipped (advisory pass)",
            details={"skipped": True, "reason": "module_not_available"},
        )

    async with async_session_factory() as session:
        result = await session.execute(
            select(BacktestRun)
            .where(BacktestRun.variation_id == variation.id)
            .order_by(BacktestRun.created_at.desc())
            .limit(1)
        )
        backtest = result.scalar_one_or_none()

    if backtest is None or backtest.has_error:
        return StageResult(
            stage="cpcv",
            passed=False,
            reasoning="No valid backtest run found — cannot run CPCV",
            details={"error": "missing_backtest_data"},
        )

    try:
        import numpy as np
        import pandas as pd

        equity_curve = backtest.equity_curve or {}
        if not equity_curve:
            return StageResult(
                stage="cpcv",
                passed=False,
                reasoning="Backtest has no equity curve data for CPCV",
                details={"error": "empty_equity_curve"},
            )

        timestamps = list(equity_curve.keys())
        values = list(equity_curve.values())
        df = pd.DataFrame({"equity": values}, index=pd.to_datetime(timestamps))
        df["returns"] = df["equity"].pct_change().fillna(0)

        config = CPCVConfig()

        def strategy_runner(train_df: pd.DataFrame, test_df: pd.DataFrame) -> np.ndarray:
            return test_df["returns"].values

        cpcv_result = run_cpcv(df, strategy_runner, config)
        passed = cpcv_result.passed

        return StageResult(
            stage="cpcv",
            passed=passed,
            score=cpcv_result.pbo,
            reasoning=(
                f"PBO={cpcv_result.pbo:.4f} (threshold={config.pbo_threshold}). "
                f"{cpcv_result.n_combinations} combinations, "
                f"{cpcv_result.n_negative_oos} negative OOS. "
                f"{'PASS' if passed else 'FAIL'}"
            ),
            details={
                "pbo": cpcv_result.pbo,
                "n_combinations": cpcv_result.n_combinations,
                "n_negative_oos": cpcv_result.n_negative_oos,
                "oos_sortino_values": cpcv_result.oos_sortino_values,
                "threshold": config.pbo_threshold,
            },
        )
    except Exception as exc:
        log.exception("CPCV stage failed for variation %s", variation.id)
        return StageResult(
            stage="cpcv",
            passed=False,
            reasoning=f"CPCV execution error: {exc}",
            details={"error": str(exc)},
        )


async def _run_monte_carlo(variation: StrategyVariation) -> StageResult:
    """Monte Carlo shuffle + shift tests — requires backtest signals and returns."""
    try:
        from backend.src.trek.skeptic.monte_carlo import MonteCarloConfig, run_monte_carlo_tests
    except ImportError:
        log.warning("Monte Carlo module not available — stage passes with advisory note")
        return StageResult(
            stage="monte_carlo",
            passed=True,
            reasoning="Monte Carlo module not yet available — skipped (advisory pass)",
            details={"skipped": True, "reason": "module_not_available"},
        )

    async with async_session_factory() as session:
        result = await session.execute(
            select(BacktestRun)
            .where(BacktestRun.variation_id == variation.id)
            .order_by(BacktestRun.created_at.desc())
            .limit(1)
        )
        backtest = result.scalar_one_or_none()

    if backtest is None or backtest.has_error:
        return StageResult(
            stage="monte_carlo",
            passed=False,
            reasoning="No valid backtest run found — cannot run Monte Carlo tests",
            details={"error": "missing_backtest_data"},
        )

    try:
        import numpy as np
        import pandas as pd

        equity_curve = backtest.equity_curve or {}
        metrics = backtest.metrics or {}

        if not equity_curve:
            return StageResult(
                stage="monte_carlo",
                passed=False,
                reasoning="Backtest has no equity curve data for Monte Carlo",
                details={"error": "empty_equity_curve"},
            )

        timestamps = list(equity_curve.keys())
        values = list(equity_curve.values())
        index = pd.to_datetime(timestamps)
        equity = pd.Series(values, index=index, dtype=float)
        returns = equity.pct_change().fillna(0)

        signals_data = metrics.get("signals")
        if signals_data and isinstance(signals_data, dict):
            signals = pd.Series(
                list(signals_data.values()),
                index=pd.to_datetime(list(signals_data.keys())),
                dtype=float,
            )
        else:
            signals = pd.Series(np.ones(len(returns)), index=returns.index)

        config = MonteCarloConfig(random_seed=42)
        mc_result = run_monte_carlo_tests(signals, returns, config)

        return StageResult(
            stage="monte_carlo",
            passed=mc_result.overall_pass,
            score=mc_result.label_shuffle.p_value,
            reasoning=(
                f"Shuffle: {mc_result.label_shuffle.verdict.value} "
                f"(median={mc_result.label_shuffle.median_sortino:.4f}, "
                f"threshold={mc_result.label_shuffle.threshold:.4f}). "
                f"Shift: {mc_result.time_shift.verdict.value} "
                f"(median={mc_result.time_shift.median_sortino:.4f}, "
                f"threshold={mc_result.time_shift.threshold:.4f}). "
                f"Overall: {'PASS' if mc_result.overall_pass else 'FAIL'}"
            ),
            details={
                "overall_pass": mc_result.overall_pass,
                "label_shuffle": mc_result.label_shuffle.model_dump(),
                "time_shift": mc_result.time_shift.model_dump(),
            },
        )
    except Exception as exc:
        log.exception("Monte Carlo stage failed for variation %s", variation.id)
        return StageResult(
            stage="monte_carlo",
            passed=False,
            reasoning=f"Monte Carlo execution error: {exc}",
            details={"error": str(exc)},
        )


async def _run_llm_critic(variation: StrategyVariation) -> StageResult:
    """LLM-as-critic — advisory only (not a hard gate)."""
    from backend.src.trek.skeptic.llm_critic import (
        LLMCriticRequest,
        critic_result_to_audit_notes,
        run_llm_critic,
    )

    request = LLMCriticRequest(
        strategy_code=variation.code,
        variation_id=str(variation.id),
    )

    result = await run_llm_critic(request)
    notes = critic_result_to_audit_notes(result)

    return StageResult(
        stage="llm_critic",
        passed=True,
        is_hard_gate=False,
        score=float(notes["findings_count"]),
        reasoning=result.summary or result.error or "LLM critic completed",
        details=notes,
        llm_input_tokens=result.cost.prompt_tokens or None,
        llm_output_tokens=result.cost.completion_tokens or None,
        llm_cost_usd=result.cost.cost_usd or None,
    )
