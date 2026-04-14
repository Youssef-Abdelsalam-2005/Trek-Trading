import uuid
from datetime import datetime, timezone

import pytest
from pydantic import SecretStr, ValidationError

from backend.app.models.enums import StrategyStatus, TradeDirection, TradeSource
from backend.app.schemas.experiment import ExperimentCreate, ExperimentResponse
from backend.app.schemas.strategy_variation import (
    StatusTransitionRequest,
    StrategyVariationCreate,
    StrategyVariationResponse,
)
from backend.app.schemas.llm_config import LLMConfigCreate, LLMConfigResponse
from backend.app.schemas.risk_config import RiskConfigCreate
from backend.app.schemas.trade import TradeCreate
from backend.app.schemas.backtest_run import BacktestRunResponse
from backend.app.schemas.ohlcv_data import OHLCVDataPoint


class TestExperimentSchemas:
    def test_create_minimal(self):
        schema = ExperimentCreate(name="Test Experiment")
        assert schema.name == "Test Experiment"
        assert schema.max_iterations == 100

    def test_create_full(self):
        schema = ExperimentCreate(
            name="Full",
            description="A test",
            max_iterations=50,
            fitness_function_config={"metric": "sortino"},
        )
        assert schema.max_iterations == 50
        assert schema.fitness_function_config == {"metric": "sortino"}

    def test_response_from_attributes(self):
        now = datetime.now(timezone.utc)
        uid = uuid.uuid4()

        class FakeExperiment:
            id = uid
            created_at = now
            updated_at = now
            name = "Test"
            description = None
            is_active = True
            max_iterations = 100
            current_iteration = 5
            fitness_function_config = None
            risk_config_override = None
            llm_config_override = None
            deleted_at = None

        resp = ExperimentResponse.model_validate(FakeExperiment())
        assert resp.id == uid
        assert resp.name == "Test"
        assert resp.current_iteration == 5


class TestStrategyVariationSchemas:
    def test_create(self):
        exp_id = uuid.uuid4()
        schema = StrategyVariationCreate(
            experiment_id=exp_id,
            code="def generate_signal(df): return df['close'] > df['close'].shift(1)",
        )
        assert schema.experiment_id == exp_id
        assert schema.generation == 0

    def test_status_transition_request(self):
        req = StatusTransitionRequest(target_status=StrategyStatus.BACKTESTING)
        assert req.target_status == StrategyStatus.BACKTESTING

    def test_response_serialization(self):
        now = datetime.now(timezone.utc)
        uid = uuid.uuid4()
        exp_id = uuid.uuid4()

        class FakeVariation:
            id = uid
            created_at = now
            updated_at = now
            experiment_id = exp_id
            parent_id = None
            name = "v1"
            status = StrategyStatus.GENERATED
            code = "def generate_signal(df): pass"
            generation = 0
            llm_input_tokens = 100
            llm_output_tokens = 200
            llm_cost_usd = 0.01
            cumulative_llm_cost_usd = 0.01
            error_message = None

        resp = StrategyVariationResponse.model_validate(FakeVariation())
        data = resp.model_dump()
        assert data["status"] == "generated"
        assert data["llm_cost_usd"] == 0.01


class TestLLMConfigSchemas:
    def test_create_with_secret_key(self):
        schema = LLMConfigCreate(
            provider="openai",
            model_name="gpt-4",
            api_key=SecretStr("sk-test-key-123"),
        )
        assert schema.api_key.get_secret_value() == "sk-test-key-123"
        serialized = schema.model_dump()
        assert serialized["api_key"] != "sk-test-key-123"

    def test_response_excludes_api_key(self):
        now = datetime.now(timezone.utc)
        uid = uuid.uuid4()

        class FakeLLMConfig:
            id = uid
            created_at = now
            updated_at = now
            label = "default"
            is_active = True
            provider = "openai"
            model_name = "gpt-4"
            api_base_url = None
            temperature = 0.7
            max_tokens = 4096
            cost_per_input_token = 0.00003
            cost_per_output_token = 0.00006

        resp = LLMConfigResponse.model_validate(FakeLLMConfig())
        data = resp.model_dump()
        assert "api_key" not in data
        assert "api_key_encrypted" not in data


class TestRiskConfigSchema:
    def test_validation_constraints(self):
        with pytest.raises(ValidationError):
            RiskConfigCreate(per_strategy_drawdown_halt=101)

    def test_valid_config(self):
        config = RiskConfigCreate()
        assert config.max_concurrent_live == 10
        assert config.per_strategy_drawdown_halt == 15.0
        assert config.paper_trading_days == 7


class TestTradeSchema:
    def test_create(self):
        now = datetime.now(timezone.utc)
        trade = TradeCreate(
            variation_id=uuid.uuid4(),
            source=TradeSource.LIVE,
            direction=TradeDirection.BUY,
            price=150.5,
            quantity=1.0,
            value_usd=150.5,
            executed_at=now,
        )
        assert trade.pair == "SOL/USDC"

    def test_price_must_be_positive(self):
        with pytest.raises(ValidationError):
            TradeCreate(
                variation_id=uuid.uuid4(),
                source=TradeSource.LIVE,
                direction=TradeDirection.BUY,
                price=-1,
                quantity=1.0,
                value_usd=150.5,
                executed_at=datetime.now(timezone.utc),
            )


class TestOHLCVSchema:
    def test_data_point(self):
        dp = OHLCVDataPoint(
            timestamp=datetime.now(timezone.utc),
            resolution="1h",
            open=100.0,
            high=105.0,
            low=99.0,
            close=103.0,
            volume=50000.0,
        )
        assert dp.pair == "SOL/USDC"
        data = dp.model_dump()
        assert "timestamp" in data
