"""Tests for the LLM-as-critic skeptic stage."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from trek.skeptic.llm_critic import (
    CostBreakdown,
    Finding,
    FindingCategory,
    FindingSeverity,
    LLMCriticRequest,
    LLMCriticResult,
    _parse_critic_response,
    critic_result_to_audit_notes,
    estimate_cost,
    run_llm_critic,
)

SAMPLE_STRATEGY = """\
import pandas as pd

def generate_signal(df: pd.DataFrame) -> pd.Series:
    df["future_return"] = df["close"].shift(-1) / df["close"] - 1
    signal = (df["future_return"] > 0).astype(int)
    return signal
"""

VALID_LLM_RESPONSE = json.dumps(
    {
        "findings": [
            {
                "line_numbers": [4, 5],
                "category": "lookahead_bias",
                "severity": "high",
                "explanation": "shift(-1) uses future close prices to compute the signal, "
                "which is not available at inference time.",
            }
        ],
        "summary": "Critical lookahead bias via shift(-1) on close price.",
    }
)

NO_ISSUES_RESPONSE = json.dumps({"findings": [], "summary": "No issues detected."})


def test_parse_critic_response_valid():
    findings, summary = _parse_critic_response(VALID_LLM_RESPONSE)
    assert len(findings) == 1
    assert findings[0].category == FindingCategory.LOOKAHEAD_BIAS
    assert findings[0].severity == FindingSeverity.HIGH
    assert 4 in findings[0].line_numbers
    assert "lookahead" in summary.lower()


def test_parse_critic_response_no_issues():
    findings, summary = _parse_critic_response(NO_ISSUES_RESPONSE)
    assert findings == []
    assert summary == "No issues detected."


def test_parse_critic_response_with_markdown_fences():
    wrapped = f"```json\n{VALID_LLM_RESPONSE}\n```"
    findings, _ = _parse_critic_response(wrapped)
    assert len(findings) == 1


def test_parse_critic_response_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        _parse_critic_response("this is not json")


def test_estimate_cost_known_model():
    cost = estimate_cost("claude-sonnet-4-20250514", prompt_tokens=1000, completion_tokens=500)
    expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
    assert abs(cost - expected) < 1e-10


def test_estimate_cost_unknown_model_uses_default():
    cost = estimate_cost("unknown-model", prompt_tokens=1000, completion_tokens=500)
    expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
    assert abs(cost - expected) < 1e-10


def test_critic_result_to_audit_notes():
    result = LLMCriticResult(
        variation_id="var-123",
        findings=[
            Finding(
                line_numbers=[4],
                category=FindingCategory.LOOKAHEAD_BIAS,
                severity=FindingSeverity.HIGH,
                explanation="test",
            )
        ],
        summary="test summary",
        cost=CostBreakdown(
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.001,
            model="claude-sonnet-4-20250514",
            latency_ms=500.0,
        ),
    )
    notes = critic_result_to_audit_notes(result)
    assert notes["stage"] == "llm_critic"
    assert notes["status"] == "completed"
    assert notes["findings_count"] == 1
    assert notes["high_severity_count"] == 1
    assert notes["cost"]["cost_usd"] == 0.001


def test_critic_result_to_audit_notes_error():
    result = LLMCriticResult(variation_id="var-123", error="API timeout")
    notes = critic_result_to_audit_notes(result)
    assert notes["status"] == "error"
    assert notes["error"] == "API timeout"


def _mock_anthropic_response(text: str, input_tokens: int = 500, output_tokens: int = 200):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _install_mock_anthropic(mock_client):
    """Inject a fake anthropic module into sys.modules so the dynamic import resolves."""
    import sys

    fake = type(sys)("anthropic")
    fake.AsyncAnthropic = lambda: mock_client
    sys.modules["anthropic"] = fake
    return fake


@pytest.mark.asyncio
async def test_run_llm_critic_success():
    mock_response = _mock_anthropic_response(VALID_LLM_RESPONSE)
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    _install_mock_anthropic(mock_client)
    try:
        req = LLMCriticRequest(strategy_code=SAMPLE_STRATEGY, variation_id="var-abc")
        result = await run_llm_critic(req)

        assert result.error is None
        assert len(result.findings) == 1
        assert result.findings[0].category == FindingCategory.LOOKAHEAD_BIAS
        assert result.cost.prompt_tokens == 500
        assert result.cost.completion_tokens == 200
        assert result.cost.cost_usd > 0
    finally:
        import sys
        sys.modules.pop("anthropic", None)


@pytest.mark.asyncio
async def test_run_llm_critic_parse_failure():
    mock_response = _mock_anthropic_response("not valid json at all")
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    _install_mock_anthropic(mock_client)
    try:
        req = LLMCriticRequest(strategy_code=SAMPLE_STRATEGY, variation_id="var-abc")
        result = await run_llm_critic(req)

        assert result.error is not None
        assert "parse" in result.error.lower()
        assert result.cost.prompt_tokens == 500
    finally:
        import sys
        sys.modules.pop("anthropic", None)
