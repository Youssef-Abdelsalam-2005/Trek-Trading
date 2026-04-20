"""Tests for the skeptic pipeline orchestrator (Step 26)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.src.trek.skeptic.orchestrator import (
    StageResult,
    _run_static_analysis,
)


class FakeVariation:
    def __init__(self, code: str, status: str = "backtested"):
        self.id = uuid.uuid4()
        self.code = code
        self.status = status
        self.error_message = None
        self.cumulative_llm_cost_usd = 0.0


@pytest.mark.asyncio
async def test_static_analysis_passes_clean_code():
    clean_code = """\
import pandas as pd

def generate_signal(df: pd.DataFrame) -> pd.Series:
    sma_fast = df['close'].rolling(10).mean()
    sma_slow = df['close'].rolling(50).mean()
    signal = (sma_fast > sma_slow).astype(float)
    return signal.shift(1)
"""
    variation = FakeVariation(code=clean_code)
    result = await _run_static_analysis(variation)
    assert result.passed is True
    assert result.stage == "static_analysis"


@pytest.mark.asyncio
async def test_static_analysis_fails_lookahead():
    bad_code = """\
import pandas as pd

def generate_signal(df: pd.DataFrame) -> pd.Series:
    future = df['close'].shift(-1)
    signal = (df['close'] < future).astype(float)
    return signal
"""
    variation = FakeVariation(code=bad_code)
    result = await _run_static_analysis(variation)
    assert result.passed is False
    assert result.stage == "static_analysis"
    assert result.details is not None
    assert result.details["total_findings"] > 0


@pytest.mark.asyncio
async def test_static_analysis_fails_unwindowed_normalization():
    bad_code = """\
import pandas as pd

def generate_signal(df: pd.DataFrame) -> pd.Series:
    normalized = (df['close'] - df['close'].mean()) / df['close'].std()
    return (normalized > 1).astype(float)
"""
    variation = FakeVariation(code=bad_code)
    result = await _run_static_analysis(variation)
    assert result.passed is False
    assert any(
        f["pattern"] == "unwindowed_normalization"
        for f in result.details["findings"]
    )


@pytest.mark.asyncio
async def test_static_analysis_handles_syntax_error():
    bad_code = "def foo(\n"
    variation = FakeVariation(code=bad_code)
    result = await _run_static_analysis(variation)
    assert result.passed is False
    assert "parse" in result.reasoning.lower()


def test_stage_result_defaults():
    r = StageResult(stage="test", passed=True)
    assert r.is_hard_gate is True
    assert r.score is None
    assert r.llm_cost_usd is None


def test_handler_registered():
    from backend.src.trek.worker import _handlers
    assert "skeptic_pipeline" in _handlers
