from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trek.services.llm_client import LLMResponse, extract_python_code
from trek.services.variation_mutation import (
    MutationResult,
    _format_metrics,
    _identify_weaknesses,
    build_mutation_prompt,
    mutate_variation,
)


class TestExtractPythonCode:
    def test_extracts_fenced_python(self):
        raw = "Here is the code:\n```python\ndef generate_signal(df):\n    return df['close'] * 0\n```\nDone."
        assert "def generate_signal" in extract_python_code(raw)

    def test_extracts_unfenced_code_block(self):
        raw = "```\ndef generate_signal(df):\n    pass\n```"
        assert "def generate_signal" in extract_python_code(raw)

    def test_raises_on_no_code_block(self):
        with pytest.raises(ValueError, match="does not contain"):
            extract_python_code("No code here, just text.")

    def test_strips_whitespace(self):
        raw = "```python\n\n  def f(): pass\n\n```"
        result = extract_python_code(raw)
        assert result == "def f(): pass"


class TestFormatMetrics:
    def test_none_backtest(self):
        assert "No backtest" in _format_metrics(None)

    def test_formats_available_metrics(self):
        bt = {"sortino_ratio": 1.5, "sharpe_ratio": 1.2, "max_drawdown": -0.1}
        result = _format_metrics(bt)
        assert "Sortino Ratio: 1.5" in result
        assert "Sharpe Ratio: 1.2" in result
        assert "Max Drawdown: -0.1" in result

    def test_skips_none_metrics(self):
        bt = {"sortino_ratio": 1.5, "sharpe_ratio": None, "max_drawdown": None}
        result = _format_metrics(bt)
        assert "Sortino" in result
        assert "Sharpe" not in result


class TestIdentifyWeaknesses:
    def test_none_backtest(self):
        result = _identify_weaknesses(None)
        assert "No backtest data" in result

    def test_low_sortino(self):
        bt = {"sortino_ratio": 0.5, "sharpe_ratio": 2.0}
        result = _identify_weaknesses(bt)
        assert "Sortino" in result

    def test_negative_return(self):
        bt = {"total_return": -0.05}
        result = _identify_weaknesses(bt)
        assert "loses money" in result

    def test_no_weaknesses(self):
        bt = {"sortino_ratio": 2.0, "sharpe_ratio": 2.0, "max_drawdown": -0.05,
              "total_return": 0.3, "win_rate": 0.6}
        result = _identify_weaknesses(bt)
        assert "reasonably" in result


class TestBuildMutationPrompt:
    def test_returns_system_and_user(self):
        msgs = build_mutation_prompt("def generate_signal(df): pass", None)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_includes_parent_code(self):
        code = "def generate_signal(df): return df['close'] * 0"
        msgs = build_mutation_prompt(code, None)
        assert code in msgs[1]["content"]

    def test_includes_metrics(self):
        bt = {"sortino_ratio": 1.5}
        msgs = build_mutation_prompt("code", bt)
        assert "1.5" in msgs[1]["content"]

    def test_system_prompt_contains_rules(self):
        msgs = build_mutation_prompt("code", None)
        assert "generate_signal" in msgs[0]["content"]
        assert "pd.DataFrame" in msgs[0]["content"]


class TestCostCalculation:
    def test_cost_math(self):
        input_tokens = 1000
        output_tokens = 500
        cost_per_input = 0.00001
        cost_per_output = 0.00003
        expected = 1000 * 0.00001 + 500 * 0.00003
        assert expected == pytest.approx(0.025)


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class TestMutateVariation:
    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        conn = AsyncMock()
        pool.acquire.return_value = _FakeAcquire(conn)
        return pool, conn

    @pytest.mark.asyncio
    async def test_parent_not_found_raises(self, mock_pool):
        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await mutate_variation(pool, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_no_llm_config_raises(self, mock_pool):
        pool, conn = mock_pool
        parent_id = uuid.uuid4()

        call_count = 0
        async def mock_fetchrow(sql, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "id": parent_id,
                    "experiment_id": uuid.uuid4(),
                    "code": "def generate_signal(df): pass",
                    "generation": 0,
                    "name": "test",
                    "llm_cost_usd": 0.0,
                    "cumulative_llm_cost_usd": 0.0,
                    "status": "backtested",
                }
            if call_count == 2:
                return None
            return None

        conn.fetchrow = mock_fetchrow
        with pytest.raises(RuntimeError, match="No active LLM"):
            await mutate_variation(pool, parent_id)

    @pytest.mark.asyncio
    async def test_successful_mutation(self, mock_pool):
        pool, conn = mock_pool
        parent_id = uuid.uuid4()
        experiment_id = uuid.uuid4()

        parent_row = {
            "id": parent_id,
            "experiment_id": experiment_id,
            "code": "def generate_signal(df): return df['close'] * 0",
            "generation": 2,
            "name": "my-strategy",
            "llm_cost_usd": 0.01,
            "cumulative_llm_cost_usd": 0.03,
            "status": "backtested",
        }
        backtest_row = {
            "sortino_ratio": 0.8,
            "sharpe_ratio": 0.9,
            "max_drawdown": -0.2,
            "total_return": 0.05,
            "win_rate": 0.5,
            "trade_count": 42,
        }
        llm_config_row = {
            "id": uuid.uuid4(),
            "provider": "openai",
            "model_name": "gpt-4",
            "api_base_url": "https://api.openai.com/v1",
            "api_key_encrypted": "encrypted-key",
            "temperature": 0.7,
            "max_tokens": 4096,
            "cost_per_input_token": 0.00003,
            "cost_per_output_token": 0.00006,
        }

        call_count = 0
        async def mock_fetchrow(sql, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return parent_row
            if call_count == 2:
                return backtest_row
            if call_count == 3:
                return llm_config_row
            return None

        conn.fetchrow = mock_fetchrow
        conn.execute = AsyncMock()

        llm_response = LLMResponse(
            content="```python\ndef generate_signal(df):\n    return df['close'].pct_change().apply(lambda x: 1 if x > 0 else -1)\n```",
            input_tokens=500,
            output_tokens=200,
        )

        with patch("trek.services.variation_mutation.decrypt_api_key", return_value="sk-test"), \
             patch("trek.services.variation_mutation.chat_completion", return_value=llm_response):
            result = await mutate_variation(pool, parent_id)

        assert isinstance(result, MutationResult)
        assert result.generation == 3
        expected_cost = 500 * 0.00003 + 200 * 0.00006
        assert result.llm_cost_usd == pytest.approx(expected_cost)
        assert result.cumulative_llm_cost_usd == pytest.approx(0.03 + expected_cost)
        conn.execute.assert_called_once()
