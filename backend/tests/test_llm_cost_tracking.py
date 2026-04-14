import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.models.base import Base
from backend.app.models.experiment import Experiment
from backend.app.models.strategy_variation import StrategyVariation
from backend.app.models.skeptic_audit import SkepticAudit
from backend.app.models.llm_config import LLMConfig
from trek.services.llm_service import (
    LLMUsage,
    compute_cost,
    extract_usage_from_response,
    parse_llm_response,
)
from trek.services.cost_tracker import compute_cumulative_cost


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def experiment(session):
    exp = Experiment(name="Cost Test", max_iterations=10)
    session.add(exp)
    session.flush()
    return exp


def _make_variation(session, experiment, parent=None, cost=0.0, cumulative=0.0):
    var = StrategyVariation(
        experiment_id=experiment.id,
        parent_id=parent.id if parent else None,
        code="def generate_signal(df): pass",
        generation=parent.generation + 1 if parent else 0,
        llm_cost_usd=cost,
        cumulative_llm_cost_usd=cumulative,
    )
    session.add(var)
    session.flush()
    return var


class TestComputeCost:
    def test_basic(self):
        cost = compute_cost(
            input_tokens=1000,
            output_tokens=500,
            cost_per_input_token=0.00001,
            cost_per_output_token=0.00003,
        )
        assert abs(cost - 0.025) < 1e-9

    def test_zero_tokens(self):
        assert compute_cost(0, 0, 0.00001, 0.00003) == 0.0


class TestLLMUsage:
    def test_total_tokens(self):
        u = LLMUsage(input_tokens=100, output_tokens=50, cost_usd=0.01)
        assert u.total_tokens == 150


class TestExtractUsageFromResponse:
    def test_openai_format(self):
        resp = {
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        }
        usage = extract_usage_from_response(resp, 0.00001, 0.00003)
        assert usage.input_tokens == 200
        assert usage.output_tokens == 100
        assert abs(usage.cost_usd - 0.005) < 1e-9

    def test_anthropic_format(self):
        resp = {
            "usage": {"input_tokens": 300, "output_tokens": 150},
        }
        usage = extract_usage_from_response(resp, 0.00001, 0.00003)
        assert usage.input_tokens == 300
        assert usage.output_tokens == 150

    def test_missing_usage(self):
        usage = extract_usage_from_response({}, 0.00001, 0.00003)
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cost_usd == 0.0


class TestParseLLMResponse:
    def _make_config(self):
        return LLMConfig(
            label="test",
            provider="openai",
            model_name="gpt-4",
            api_key_encrypted="encrypted",
            cost_per_input_token=0.00003,
            cost_per_output_token=0.00006,
        )

    def test_openai_chat_format(self):
        config = self._make_config()
        resp = {
            "choices": [{"message": {"content": "strategy code here"}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 200},
        }
        result = parse_llm_response(resp, config)
        assert result.content == "strategy code here"
        assert result.usage.input_tokens == 500
        assert result.usage.output_tokens == 200
        assert result.model == "gpt-4"
        assert result.provider == "openai"

    def test_anthropic_content_block_format(self):
        config = self._make_config()
        config.provider = "anthropic"
        resp = {
            "content": [{"type": "text", "text": "generated code"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        result = parse_llm_response(resp, config)
        assert result.content == "generated code"


class TestComputeCumulativeCost:
    def test_no_parent(self):
        assert compute_cumulative_cost(0.05, None) == 0.05

    def test_with_parent(self):
        assert abs(compute_cumulative_cost(0.03, 0.10) - 0.13) < 1e-9


class TestThreeGenerationLineage:
    def test_cumulative_cost_across_lineage(self, session, experiment):
        grandparent = _make_variation(
            session, experiment, cost=0.05, cumulative=0.05
        )
        parent_cumulative = compute_cumulative_cost(0.03, grandparent.cumulative_llm_cost_usd)
        parent = _make_variation(
            session, experiment, parent=grandparent,
            cost=0.03, cumulative=parent_cumulative,
        )
        child_cumulative = compute_cumulative_cost(0.02, parent.cumulative_llm_cost_usd)
        child = _make_variation(
            session, experiment, parent=parent,
            cost=0.02, cumulative=child_cumulative,
        )

        assert grandparent.cumulative_llm_cost_usd == 0.05
        assert abs(parent.cumulative_llm_cost_usd - 0.08) < 1e-9
        assert abs(child.cumulative_llm_cost_usd - 0.10) < 1e-9

    def test_skeptic_cost_adds_to_variation(self, session, experiment):
        var = _make_variation(session, experiment, cost=0.05, cumulative=0.05)

        audit = SkepticAudit(
            variation_id=var.id,
            stage="logic_review",
            passed=True,
            score=0.85,
            reasoning="Looks good",
            llm_input_tokens=200,
            llm_output_tokens=100,
            llm_cost_usd=0.01,
        )
        session.add(audit)
        session.flush()

        var.llm_input_tokens += audit.llm_input_tokens
        var.llm_output_tokens += audit.llm_output_tokens
        var.llm_cost_usd += audit.llm_cost_usd
        var.cumulative_llm_cost_usd = compute_cumulative_cost(var.llm_cost_usd, None)
        session.flush()

        assert var.llm_cost_usd == pytest.approx(0.06)
        assert var.cumulative_llm_cost_usd == pytest.approx(0.06)

    def test_cost_propagation_three_generations(self, session, experiment):
        g0 = _make_variation(session, experiment, cost=0.10, cumulative=0.10)
        g1 = _make_variation(
            session, experiment, parent=g0,
            cost=0.05,
            cumulative=compute_cumulative_cost(0.05, g0.cumulative_llm_cost_usd),
        )
        g2 = _make_variation(
            session, experiment, parent=g1,
            cost=0.02,
            cumulative=compute_cumulative_cost(0.02, g1.cumulative_llm_cost_usd),
        )

        assert g0.cumulative_llm_cost_usd == pytest.approx(0.10)
        assert g1.cumulative_llm_cost_usd == pytest.approx(0.15)
        assert g2.cumulative_llm_cost_usd == pytest.approx(0.17)

        g0.llm_cost_usd += 0.03
        g0.cumulative_llm_cost_usd = compute_cumulative_cost(g0.llm_cost_usd, None)
        g1.cumulative_llm_cost_usd = compute_cumulative_cost(
            g1.llm_cost_usd, g0.cumulative_llm_cost_usd
        )
        g2.cumulative_llm_cost_usd = compute_cumulative_cost(
            g2.llm_cost_usd, g1.cumulative_llm_cost_usd
        )

        assert g0.cumulative_llm_cost_usd == pytest.approx(0.13)
        assert g1.cumulative_llm_cost_usd == pytest.approx(0.18)
        assert g2.cumulative_llm_cost_usd == pytest.approx(0.20)
