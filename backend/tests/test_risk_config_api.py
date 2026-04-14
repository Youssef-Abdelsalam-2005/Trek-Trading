import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.base import Base
from backend.app.models.experiment import Experiment
from backend.app.models.risk_config import RiskConfig
from backend.src.trek.api import app


@pytest.fixture
def sync_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def sync_session(sync_engine):
    with Session(sync_engine) as session:
        yield session


class TestRiskConfigModel:
    def test_global_config_round_trip(self, sync_session):
        config = RiskConfig(**RiskConfig.GLOBAL_DEFAULTS)
        sync_session.add(config)
        sync_session.commit()

        loaded = sync_session.get(RiskConfig, config.id)
        assert loaded.per_strategy_drawdown_halt == 15.0
        assert loaded.portfolio_circuit_breaker == 25.0
        assert loaded.max_concurrent_live == 10
        assert loaded.paper_trading_days == 7
        assert loaded.max_drawdown_cap == 30.0
        assert loaded.pbo_fail_threshold == 0.40
        assert loaded.fill_failure_rate == 30.0
        assert loaded.experiment_id is None

    def test_experiment_override_partial(self, sync_session):
        exp = Experiment(name="Test Exp", max_iterations=10)
        sync_session.add(exp)
        sync_session.flush()

        override = RiskConfig(
            experiment_id=exp.id,
            per_strategy_drawdown_halt=20.0,
        )
        sync_session.add(override)
        sync_session.commit()

        loaded = sync_session.get(RiskConfig, override.id)
        assert loaded.per_strategy_drawdown_halt == 20.0
        assert loaded.portfolio_circuit_breaker is None
        assert loaded.experiment_id == exp.id


class TestRiskConfigSchemas:
    def test_create_defaults(self):
        from backend.app.schemas.risk_config import RiskConfigCreate

        config = RiskConfigCreate()
        assert config.per_strategy_drawdown_halt == 15.0
        assert config.max_concurrent_live == 10
        assert config.paper_trading_days == 7

    def test_create_validation_percentage_bounds(self):
        from pydantic import ValidationError

        from backend.app.schemas.risk_config import RiskConfigCreate

        with pytest.raises(ValidationError):
            RiskConfigCreate(per_strategy_drawdown_halt=101)

        with pytest.raises(ValidationError):
            RiskConfigCreate(per_strategy_drawdown_halt=-1)

    def test_create_validation_integer_bounds(self):
        from pydantic import ValidationError

        from backend.app.schemas.risk_config import RiskConfigCreate

        with pytest.raises(ValidationError):
            RiskConfigCreate(max_concurrent_live=0)

        with pytest.raises(ValidationError):
            RiskConfigCreate(paper_trading_days=0)

    def test_override_create_all_optional(self):
        from backend.app.schemas.risk_config import RiskConfigOverrideCreate

        override = RiskConfigOverrideCreate(experiment_id=uuid.uuid4())
        assert override.per_strategy_drawdown_halt is None
        assert override.max_concurrent_live is None

    def test_update_partial(self):
        from backend.app.schemas.risk_config import RiskConfigUpdate

        update = RiskConfigUpdate(per_strategy_drawdown_halt=20.0)
        dumped = update.model_dump(exclude_unset=True)
        assert dumped == {"per_strategy_drawdown_halt": 20.0}

    def test_resolved_all_required(self):
        from backend.app.schemas.risk_config import RiskConfigResolved

        resolved = RiskConfigResolved(
            experiment_id=None,
            per_strategy_drawdown_halt=15.0,
            portfolio_circuit_breaker=25.0,
            max_concurrent_live=10,
            paper_trading_days=7,
            max_drawdown_cap=30.0,
            pbo_fail_threshold=0.40,
            fill_failure_rate=30.0,
        )
        assert resolved.per_strategy_drawdown_halt == 15.0


class TestResolveLogic:
    def test_resolve_global_only(self):
        from backend.app.routes.risk_config import _resolve

        global_row = RiskConfig(**RiskConfig.GLOBAL_DEFAULTS)
        result = _resolve(global_row, None)
        assert result["per_strategy_drawdown_halt"] == 15.0
        assert result["max_concurrent_live"] == 10

    def test_resolve_with_override(self):
        from backend.app.routes.risk_config import _resolve

        global_row = RiskConfig(**RiskConfig.GLOBAL_DEFAULTS)
        override = RiskConfig(
            experiment_id=uuid.uuid4(),
            per_strategy_drawdown_halt=20.0,
            max_concurrent_live=5,
        )
        result = _resolve(global_row, override)
        assert result["per_strategy_drawdown_halt"] == 20.0
        assert result["max_concurrent_live"] == 5
        assert result["portfolio_circuit_breaker"] == 25.0
        assert result["paper_trading_days"] == 7
