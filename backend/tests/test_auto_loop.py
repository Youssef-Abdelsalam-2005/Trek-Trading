"""Unit tests for the auto-loop orchestrator (Step 40).

Tests verify the orchestration logic: task chaining, fitness filtering,
state transitions, mutation scheduling, and iteration management.
Uses mock database pools and LLM responses.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def experiment_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def experiment_row(experiment_id: uuid.UUID) -> dict[str, Any]:
    return {
        "id": experiment_id,
        "name": "test-experiment",
        "is_active": True,
        "max_iterations": 10,
        "current_iteration": 1,
        "fitness_function_config": json.dumps({
            "variations_per_iteration": 3,
            "mutations_per_passing": 2,
            "iteration_delay_seconds": 60,
            "poll_delay_seconds": 10,
            "backtest_start": "2024-01-01T00:00:00+00:00",
            "backtest_end": "2025-01-01T00:00:00+00:00",
        }),
        "risk_config_override": json.dumps({
            "min_sortino_threshold": 1.0,
            "max_max_drawdown_pct": 0.20,
        }),
        "llm_config_override": json.dumps({}),
    }


@pytest.fixture
def llm_config_row() -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "provider": "openai",
        "model_name": "gpt-4o",
        "api_base_url": "https://api.openai.com/v1",
        "api_key_encrypted": "encrypted_key",
        "temperature": 0.7,
        "max_tokens": 4096,
        "cost_per_input_token": 2.5e-6,
        "cost_per_output_token": 10.0e-6,
    }


def _make_mock_pool(fetchrow_side_effect=None, fetch_side_effect=None):
    """Build a mock asyncpg.Pool with a mock connection context manager."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    mock_conn.fetch = AsyncMock(side_effect=fetch_side_effect)

    mock_tx = AsyncMock()
    mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
    mock_tx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = MagicMock(return_value=mock_tx)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=mock_ctx)

    return pool, mock_conn


class TestParseAutoLoopConfig:
    def test_defaults_when_empty(self):
        from trek.handlers.auto_loop import _parse_auto_loop_config

        config = _parse_auto_loop_config({
            "fitness_function_config": None,
            "risk_config_override": None,
            "llm_config_override": None,
        })
        assert config["variations_per_iteration"] == 5
        assert config["mutations_per_passing"] == 3
        assert config["min_sortino"] is None
        assert config["max_drawdown"] is None

    def test_reads_from_json_strings(self):
        from trek.handlers.auto_loop import _parse_auto_loop_config

        config = _parse_auto_loop_config({
            "fitness_function_config": json.dumps({"variations_per_iteration": 7}),
            "risk_config_override": json.dumps({"min_sortino_threshold": 2.0}),
            "llm_config_override": json.dumps({"model_name": "gpt-4"}),
        })
        assert config["variations_per_iteration"] == 7
        assert config["min_sortino"] == 2.0
        assert config["llm_override"]["model_name"] == "gpt-4"

    def test_reads_from_dicts(self):
        from trek.handlers.auto_loop import _parse_auto_loop_config

        config = _parse_auto_loop_config({
            "fitness_function_config": {"mutations_per_passing": 1},
            "risk_config_override": {"max_max_drawdown_pct": 0.10},
            "llm_config_override": {},
        })
        assert config["mutations_per_passing"] == 1
        assert config["max_drawdown"] == 0.10


class TestResolveFitnessThresholds:
    @pytest.mark.asyncio
    async def test_uses_experiment_override(self):
        from trek.handlers.auto_loop import _resolve_fitness_thresholds

        pool, _ = _make_mock_pool()
        config = {"min_sortino": 2.0, "max_drawdown": 0.10}
        min_s, max_d = await _resolve_fitness_thresholds(pool, config)
        assert min_s == 2.0
        assert max_d == 0.10

    @pytest.mark.asyncio
    async def test_falls_back_to_global_risk_config(self):
        from trek.handlers.auto_loop import _resolve_fitness_thresholds

        pool, mock_conn = _make_mock_pool(
            fetchrow_side_effect=[{
                "min_sortino_threshold": 1.8,
                "max_max_drawdown_pct": 0.12,
            }]
        )
        config = {"min_sortino": None, "max_drawdown": None}
        min_s, max_d = await _resolve_fitness_thresholds(pool, config)
        assert min_s == 1.8
        assert max_d == 0.12

    @pytest.mark.asyncio
    async def test_defaults_when_no_config(self):
        from trek.handlers.auto_loop import _resolve_fitness_thresholds

        pool, mock_conn = _make_mock_pool(fetchrow_side_effect=[None])
        config = {"min_sortino": None, "max_drawdown": None}
        min_s, max_d = await _resolve_fitness_thresholds(pool, config)
        assert min_s == 1.5
        assert max_d == 0.15


class TestHandleAutoLoopGenerate:
    @pytest.mark.asyncio
    async def test_skips_inactive_experiment(self, experiment_id):
        from trek.handlers.auto_loop import handle_auto_loop_generate

        inactive_experiment = {
            "id": experiment_id,
            "name": "test",
            "is_active": False,
            "max_iterations": None,
            "current_iteration": 1,
            "fitness_function_config": None,
            "risk_config_override": None,
            "llm_config_override": None,
        }
        pool, mock_conn = _make_mock_pool(fetchrow_side_effect=[inactive_experiment])

        await handle_auto_loop_generate(
            {"experiment_id": str(experiment_id), "iteration": 1},
            pool,
        )
        # Should not enqueue any tasks (only one fetchrow call for the experiment)
        assert mock_conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    async def test_stops_at_max_iterations(self, experiment_id):
        from trek.handlers.auto_loop import handle_auto_loop_generate

        experiment = {
            "id": experiment_id,
            "name": "test",
            "is_active": True,
            "max_iterations": 5,
            "current_iteration": 5,
            "fitness_function_config": None,
            "risk_config_override": None,
            "llm_config_override": None,
        }
        pool, mock_conn = _make_mock_pool(fetchrow_side_effect=[experiment])

        await handle_auto_loop_generate(
            {"experiment_id": str(experiment_id), "iteration": 6},
            pool,
        )
        assert mock_conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    @patch("trek.handlers.auto_loop._generate_variations")
    @patch("trek.handlers.auto_loop._get_llm_config")
    async def test_enqueues_backtests_and_collector(
        self, mock_get_llm, mock_gen_vars, experiment_id, experiment_row
    ):
        from trek.handlers.auto_loop import handle_auto_loop_generate

        vid1, vid2, vid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        mock_gen_vars.return_value = [vid1, vid2, vid3]
        mock_get_llm.return_value = {"api_key": "k", "api_base_url": "http://x", "model_name": "m", "temperature": 0.7, "cost_per_input_token": 0, "cost_per_output_token": 0}

        pool, mock_conn = _make_mock_pool(fetchrow_side_effect=[experiment_row])

        await handle_auto_loop_generate(
            {"experiment_id": str(experiment_id), "iteration": 1},
            pool,
        )

        # Should have called execute multiple times:
        # 3 status updates + 3 backtest enqueues + 3 notifies + 1 collector enqueue + 1 notify
        execute_calls = mock_conn.execute.call_args_list
        assert len(execute_calls) > 0

        # Verify backtest tasks were enqueued (check for task_type in args)
        enqueue_calls = [
            c for c in execute_calls
            if any(isinstance(a, str) and "backtest" == a for a in c.args)
        ]
        assert len(enqueue_calls) >= 3

        # Verify collector was enqueued
        collector_calls = [
            c for c in execute_calls
            if any(isinstance(a, str) and "auto_loop_collect_backtests" in a for a in c.args)
        ]
        assert len(collector_calls) >= 1


class TestHandleAutoLoopCollectBacktests:
    @pytest.mark.asyncio
    async def test_repolls_when_backtests_still_running(self, experiment_id):
        from trek.handlers.auto_loop import handle_auto_loop_collect_backtests

        vid1, vid2 = uuid.uuid4(), uuid.uuid4()
        variation_statuses = [
            {"id": vid1, "status": "backtested"},
            {"id": vid2, "status": "backtesting"},
        ]

        pool, mock_conn = _make_mock_pool(fetch_side_effect=[variation_statuses])

        payload = {
            "experiment_id": str(experiment_id),
            "iteration": 1,
            "variation_ids": [str(vid1), str(vid2)],
            "config": {"poll_delay_seconds": 10},
        }

        await handle_auto_loop_collect_backtests(payload, pool)

        # Should have enqueued a re-poll task
        execute_calls = mock_conn.execute.call_args_list
        repoll_calls = [
            c for c in execute_calls
            if len(c.args) > 1 and c.args[1] == "auto_loop_collect_backtests"
        ]
        assert len(repoll_calls) == 1

    @pytest.mark.asyncio
    @patch("trek.handlers.auto_loop._schedule_next_iteration")
    @patch("trek.handlers.auto_loop._resolve_fitness_thresholds")
    async def test_filters_by_fitness_and_enqueues_skeptic(
        self, mock_thresholds, mock_schedule_next, experiment_id
    ):
        from trek.handlers.auto_loop import handle_auto_loop_collect_backtests

        mock_thresholds.return_value = (1.0, 0.20)
        mock_schedule_next.return_value = None

        vid_pass = uuid.uuid4()
        vid_fail = uuid.uuid4()

        variation_statuses = [
            {"id": vid_pass, "status": "backtested"},
            {"id": vid_fail, "status": "backtested"},
        ]

        backtest_results = [
            {"variation_id": vid_pass, "sortino_ratio": 2.5, "max_drawdown": -0.10, "has_error": False},
            {"variation_id": vid_fail, "sortino_ratio": 0.5, "max_drawdown": -0.30, "has_error": False},
        ]

        call_count = [0]

        async def fetch_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return variation_statuses
            return backtest_results

        pool, mock_conn = _make_mock_pool()
        mock_conn.fetch = AsyncMock(side_effect=fetch_side_effect)

        payload = {
            "experiment_id": str(experiment_id),
            "iteration": 1,
            "variation_ids": [str(vid_pass), str(vid_fail)],
            "config": {"poll_delay_seconds": 10},
        }

        await handle_auto_loop_collect_backtests(payload, pool)

        # Should have enqueued skeptic for passing variation
        execute_calls = mock_conn.execute.call_args_list
        skeptic_calls = [
            c for c in execute_calls
            if len(c.args) > 1 and c.args[1] == "skeptic_pipeline"
        ]
        assert len(skeptic_calls) == 1

    @pytest.mark.asyncio
    @patch("trek.handlers.auto_loop._schedule_next_iteration")
    @patch("trek.handlers.auto_loop._resolve_fitness_thresholds")
    async def test_schedules_next_when_no_pass_fitness(
        self, mock_thresholds, mock_schedule_next, experiment_id
    ):
        from trek.handlers.auto_loop import handle_auto_loop_collect_backtests

        mock_thresholds.return_value = (1.0, 0.20)
        mock_schedule_next.return_value = None

        vid = uuid.uuid4()
        variation_statuses = [{"id": vid, "status": "backtested"}]
        backtest_results = [
            {"variation_id": vid, "sortino_ratio": 0.3, "max_drawdown": -0.35, "has_error": False},
        ]

        call_count = [0]

        async def fetch_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return variation_statuses
            return backtest_results

        pool, mock_conn = _make_mock_pool()
        mock_conn.fetch = AsyncMock(side_effect=fetch_side_effect)

        payload = {
            "experiment_id": str(experiment_id),
            "iteration": 1,
            "variation_ids": [str(vid)],
            "config": {},
        }

        await handle_auto_loop_collect_backtests(payload, pool)
        mock_schedule_next.assert_called_once()


class TestHandleAutoLoopCollectSkeptics:
    @pytest.mark.asyncio
    async def test_repolls_when_skeptic_still_running(self, experiment_id):
        from trek.handlers.auto_loop import handle_auto_loop_collect_skeptics

        vid = uuid.uuid4()
        variation_statuses = [{"id": vid, "status": "skeptic_pending"}]
        pool, mock_conn = _make_mock_pool(fetch_side_effect=[variation_statuses])

        payload = {
            "experiment_id": str(experiment_id),
            "iteration": 1,
            "variation_ids": [str(vid)],
            "config": {"poll_delay_seconds": 10},
        }

        await handle_auto_loop_collect_skeptics(payload, pool)

        execute_calls = mock_conn.execute.call_args_list
        repoll_calls = [
            c for c in execute_calls
            if len(c.args) > 1 and c.args[1] == "auto_loop_collect_skeptics"
        ]
        assert len(repoll_calls) == 1

    @pytest.mark.asyncio
    @patch("trek.handlers.auto_loop._schedule_next_iteration")
    @patch("trek.handlers.auto_loop._mutate_variation")
    @patch("trek.handlers.auto_loop._get_llm_config")
    async def test_transitions_to_paper_and_mutates(
        self, mock_get_llm, mock_mutate, mock_schedule_next, experiment_id
    ):
        from trek.handlers.auto_loop import handle_auto_loop_collect_skeptics

        mock_get_llm.return_value = {"api_key": "k", "api_base_url": "http://x", "model_name": "m", "temperature": 0.7, "cost_per_input_token": 0, "cost_per_output_token": 0}
        child_id = uuid.uuid4()
        mock_mutate.return_value = child_id
        mock_schedule_next.return_value = None

        vid_pass = uuid.uuid4()
        vid_fail = uuid.uuid4()

        variation_statuses = [
            {"id": vid_pass, "status": "skeptic_passed"},
            {"id": vid_fail, "status": "skeptic_failed"},
        ]
        pool, mock_conn = _make_mock_pool(fetch_side_effect=[variation_statuses])

        payload = {
            "experiment_id": str(experiment_id),
            "iteration": 1,
            "variation_ids": [str(vid_pass), str(vid_fail)],
            "config": {"mutations_per_passing": 2, "llm_override": {}},
        }

        await handle_auto_loop_collect_skeptics(payload, pool)

        # Should transition passing strategy to paper_trading
        # execute args are (SQL, variation_id, new_status)
        execute_calls = mock_conn.execute.call_args_list
        paper_transitions = [
            c for c in execute_calls
            if len(c.args) >= 3 and c.args[2] == "paper_trading"
        ]
        assert len(paper_transitions) == 1

        # Should generate 2 mutations for the passing strategy
        assert mock_mutate.call_count == 2

        # Should schedule next iteration
        mock_schedule_next.assert_called_once()


class TestScheduleNextIteration:
    @pytest.mark.asyncio
    async def test_increments_and_schedules(self, experiment_id, experiment_row):
        from trek.handlers.auto_loop import _schedule_next_iteration

        experiment_row["current_iteration"] = 2
        pool, mock_conn = _make_mock_pool(
            fetchrow_side_effect=[experiment_row]
        )

        await _schedule_next_iteration(pool, experiment_id, 2, {"iteration_delay_seconds": 60})

        # Should have incremented iteration and enqueued next generate task
        execute_calls = mock_conn.execute.call_args_list
        assert len(execute_calls) >= 2

        # _enqueue_task calls: execute(ENQUEUE_SQL, id, type, payload, retries, scheduled)
        # plus execute(pg_notify, type) — check for the notify call
        enqueue_calls = [
            c for c in execute_calls
            if any(
                isinstance(a, str) and "auto_loop_generate" in a
                for a in c.args
            )
        ]
        assert len(enqueue_calls) >= 1

    @pytest.mark.asyncio
    async def test_stops_when_inactive(self, experiment_id):
        from trek.handlers.auto_loop import _schedule_next_iteration

        inactive = {
            "id": experiment_id,
            "name": "test",
            "is_active": False,
            "max_iterations": None,
            "current_iteration": 2,
            "fitness_function_config": None,
            "risk_config_override": None,
            "llm_config_override": None,
        }
        pool, mock_conn = _make_mock_pool(fetchrow_side_effect=[inactive])

        await _schedule_next_iteration(pool, experiment_id, 1, {})

        enqueue_calls = [
            c for c in mock_conn.execute.call_args_list
            if len(c.args) > 1 and c.args[1] == "auto_loop_generate"
        ]
        assert len(enqueue_calls) == 0

    @pytest.mark.asyncio
    async def test_stops_at_max_iterations(self, experiment_id):
        from trek.handlers.auto_loop import _schedule_next_iteration

        at_max = {
            "id": experiment_id,
            "name": "test",
            "is_active": True,
            "max_iterations": 3,
            "current_iteration": 3,
            "fitness_function_config": None,
            "risk_config_override": None,
            "llm_config_override": None,
        }
        pool, mock_conn = _make_mock_pool(fetchrow_side_effect=[at_max])

        await _schedule_next_iteration(pool, experiment_id, 3, {})

        enqueue_calls = [
            c for c in mock_conn.execute.call_args_list
            if len(c.args) > 1 and c.args[1] == "auto_loop_generate"
        ]
        assert len(enqueue_calls) == 0
