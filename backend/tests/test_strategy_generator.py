"""Tests for the LLM strategy generation service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from trek.strategy_generator import (
    CostBreakdown,
    GenerationRequest,
    GenerationResult,
    build_prompt,
    estimate_cost,
    extract_code,
    generate_strategy,
    validate_code,
)

VALID_STRATEGY_CODE = """\
import pandas as pd
import numpy as np

def generate_signal(df: pd.DataFrame) -> pd.Series:
    sma_fast = df["close"].rolling(window=10).mean()
    sma_slow = df["close"].rolling(window=30).mean()
    signal = pd.Series(0, index=df.index)
    signal[sma_fast > sma_slow] = 1
    signal[sma_fast < sma_slow] = -1
    return signal.fillna(0)
"""

VALID_LLM_RESPONSE = f"```python\n{VALID_STRATEGY_CODE}```"


def test_build_prompt_includes_asset():
    req = GenerationRequest(experiment_id="exp-1", asset="SOL/USDC")
    prompt = build_prompt(req)
    assert "SOL/USDC" in prompt


def test_build_prompt_includes_indicators():
    req = GenerationRequest(experiment_id="exp-1")
    prompt = build_prompt(req)
    assert "RSI" in prompt
    assert "MACD" in prompt
    assert "Bollinger Bands" in prompt


def test_build_prompt_includes_fitness_function():
    req = GenerationRequest(
        experiment_id="exp-1",
        fitness_function="Maximize Sharpe ratio",
    )
    prompt = build_prompt(req)
    assert "Maximize Sharpe ratio" in prompt


def test_build_prompt_includes_constraints():
    req = GenerationRequest(
        experiment_id="exp-1",
        constraints="No overnight positions",
    )
    prompt = build_prompt(req)
    assert "No overnight positions" in prompt


def test_extract_code_from_fenced_block():
    code = extract_code(VALID_LLM_RESPONSE)
    assert "def generate_signal(" in code
    assert "```" not in code


def test_extract_code_from_plain_text():
    plain = VALID_STRATEGY_CODE
    code = extract_code(plain)
    assert "def generate_signal(" in code


def test_extract_code_with_language_tag():
    wrapped = f"```python\n{VALID_STRATEGY_CODE}```"
    code = extract_code(wrapped)
    assert "def generate_signal(" in code


def test_extract_code_no_fence():
    raw = "def generate_signal(df):\n    return df['close'] * 0"
    code = extract_code(raw)
    assert "def generate_signal" in code


def test_validate_code_valid():
    assert validate_code(VALID_STRATEGY_CODE) is None


def test_validate_code_missing_function():
    bad = "import pandas as pd\nx = 1"
    error = validate_code(bad)
    assert error is not None
    assert "Missing" in error


def test_validate_code_lookahead_bias():
    bad = 'def generate_signal(df):\n    return df["close"].shift(-1)'
    error = validate_code(bad)
    assert error is not None
    assert "lookahead" in error.lower()


def test_validate_code_syntax_error():
    bad = "def generate_signal(df:\n    return"
    error = validate_code(bad)
    assert error is not None
    assert "Syntax" in error


def test_estimate_cost_known_model():
    cost = estimate_cost("gpt-4o", prompt_tokens=1000, completion_tokens=500)
    expected = (1000 * 2.50 + 500 * 10.0) / 1_000_000
    assert abs(cost - expected) < 1e-10


def test_estimate_cost_unknown_model_uses_default():
    cost = estimate_cost("unknown-model", prompt_tokens=1000, completion_tokens=500)
    expected = (1000 * 2.50 + 500 * 10.0) / 1_000_000
    assert abs(cost - expected) < 1e-10


def test_estimate_cost_mini_model():
    cost = estimate_cost("gpt-4o-mini", prompt_tokens=10_000, completion_tokens=1000)
    expected = (10_000 * 0.15 + 1000 * 0.60) / 1_000_000
    assert abs(cost - expected) < 1e-10


def _mock_openai_response(text: str, prompt_tokens: int = 500, completion_tokens: int = 300):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def _install_mock_openai(mock_client):
    import sys

    fake = type(sys)("openai")
    fake.AsyncOpenAI = lambda: mock_client
    sys.modules["openai"] = fake
    return fake


@pytest.mark.asyncio
async def test_generate_strategy_success():
    mock_response = _mock_openai_response(VALID_LLM_RESPONSE)
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    _install_mock_openai(mock_client)
    try:
        req = GenerationRequest(experiment_id="exp-1")
        result = await generate_strategy(req)

        assert result.error is None
        assert result.status == "generated"
        assert "def generate_signal(" in result.code
        assert result.cost.prompt_tokens == 500
        assert result.cost.completion_tokens == 300
        assert result.cost.cost_usd > 0
        assert result.experiment_id == "exp-1"
    finally:
        import sys
        sys.modules.pop("openai", None)


@pytest.mark.asyncio
async def test_generate_strategy_with_parent_cost():
    mock_response = _mock_openai_response(VALID_LLM_RESPONSE)
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    _install_mock_openai(mock_client)
    try:
        req = GenerationRequest(
            experiment_id="exp-1",
            parent_variation_id="parent-var-1",
            parent_cumulative_cost_usd=0.005,
        )
        result = await generate_strategy(req)

        assert result.error is None
        assert result.parent_variation_id == "parent-var-1"
        assert result.cumulative_cost_usd > 0.005
    finally:
        import sys
        sys.modules.pop("openai", None)


@pytest.mark.asyncio
async def test_generate_strategy_validation_failure():
    bad_code = "```python\nimport pandas as pd\nx = 1\n```"
    mock_response = _mock_openai_response(bad_code)
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    _install_mock_openai(mock_client)
    try:
        req = GenerationRequest(experiment_id="exp-1")
        result = await generate_strategy(req)

        assert result.error is not None
        assert "validation" in result.error.lower()
        assert result.cost.prompt_tokens == 500
    finally:
        import sys
        sys.modules.pop("openai", None)


@pytest.mark.asyncio
async def test_generate_strategy_api_error():
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

    _install_mock_openai(mock_client)
    try:
        req = GenerationRequest(experiment_id="exp-1")
        result = await generate_strategy(req)

        assert result.error is not None
        assert "API down" in result.error
    finally:
        import sys
        sys.modules.pop("openai", None)


@pytest.mark.asyncio
async def test_generate_strategy_lookahead_detected():
    lookahead_code = '```python\nimport pandas as pd\nimport numpy as np\n\ndef generate_signal(df: pd.DataFrame) -> pd.Series:\n    return (df["close"].shift(-1) > df["close"]).astype(int)\n```'
    mock_response = _mock_openai_response(lookahead_code)
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    _install_mock_openai(mock_client)
    try:
        req = GenerationRequest(experiment_id="exp-1")
        result = await generate_strategy(req)

        assert result.error is not None
        assert "lookahead" in result.error.lower()
    finally:
        import sys
        sys.modules.pop("openai", None)
