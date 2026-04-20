import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.models.enums import TradeDirection, TradeSource, TradeStatus
from backend.app.schemas.trade import TradeCreate, TradeResponse, TradeListParams


class TestTradeStatus:
    def test_enum_values(self):
        assert TradeStatus.FILLED.value == "filled"
        assert TradeStatus.FAILED.value == "failed"
        assert TradeStatus.SKIPPED.value == "skipped"


class TestTradeCreateSchema:
    def _base_kwargs(self, **overrides):
        defaults = dict(
            variation_id=uuid.uuid4(),
            source=TradeSource.PAPER,
            direction=TradeDirection.BUY,
            status=TradeStatus.FILLED,
            input_amount=10.0,
            quoted_price=150.0,
            fill_price=150.5,
            executed_at=datetime.now(timezone.utc),
        )
        defaults.update(overrides)
        return defaults

    def test_minimal_filled_trade(self):
        trade = TradeCreate(**self._base_kwargs())
        assert trade.pair == "SOL/USDC"
        assert trade.status == TradeStatus.FILLED
        assert trade.paper_session_id is None
        assert trade.jito_tip_lamports is None

    def test_full_live_trade(self):
        dep_id = uuid.uuid4()
        trade = TradeCreate(**self._base_kwargs(
            source=TradeSource.LIVE,
            live_deployment_id=dep_id,
            output_amount=9.95,
            fill_price=149.0,
            price_impact_bps=5.2,
            fee_usd=0.25,
            slippage_bps=3.1,
            jito_tip_lamports=10000,
            tx_signature="5V2x" * 22,
        ))
        assert trade.live_deployment_id == dep_id
        assert trade.jito_tip_lamports == 10000

    def test_paper_trade_with_session(self):
        session_id = uuid.uuid4()
        trade = TradeCreate(**self._base_kwargs(
            paper_session_id=session_id,
        ))
        assert trade.paper_session_id == session_id

    def test_failed_trade_requires_reason(self):
        with pytest.raises(ValidationError, match="failure_reason"):
            TradeCreate(**self._base_kwargs(
                status=TradeStatus.FAILED,
                fill_price=None,
            ))

    def test_failed_trade_with_reason(self):
        trade = TradeCreate(**self._base_kwargs(
            status=TradeStatus.FAILED,
            fill_price=None,
            failure_reason="Insufficient SOL balance",
        ))
        assert trade.failure_reason == "Insufficient SOL balance"

    def test_filled_trade_requires_fill_price(self):
        with pytest.raises(ValidationError, match="fill_price"):
            TradeCreate(**self._base_kwargs(fill_price=None))

    def test_skipped_trade_no_fill_price_needed(self):
        trade = TradeCreate(**self._base_kwargs(
            status=TradeStatus.SKIPPED,
            fill_price=None,
        ))
        assert trade.status == TradeStatus.SKIPPED

    def test_paper_trade_rejects_live_deployment_id(self):
        with pytest.raises(ValidationError, match="Paper trades"):
            TradeCreate(**self._base_kwargs(
                source=TradeSource.PAPER,
                live_deployment_id=uuid.uuid4(),
            ))

    def test_live_trade_rejects_paper_session_id(self):
        with pytest.raises(ValidationError, match="Live trades"):
            TradeCreate(**self._base_kwargs(
                source=TradeSource.LIVE,
                paper_session_id=uuid.uuid4(),
            ))

    def test_input_amount_must_be_positive(self):
        with pytest.raises(ValidationError):
            TradeCreate(**self._base_kwargs(input_amount=-1))

    def test_quoted_price_must_be_positive(self):
        with pytest.raises(ValidationError):
            TradeCreate(**self._base_kwargs(quoted_price=0))


class TestTradeResponse:
    def test_from_attributes(self):
        now = datetime.now(timezone.utc)
        uid = uuid.uuid4()
        var_id = uuid.uuid4()

        class FakeTrade:
            id = uid
            created_at = now
            updated_at = now
            variation_id = var_id
            paper_session_id = None
            live_deployment_id = None
            source = TradeSource.PAPER
            direction = TradeDirection.SELL
            status = TradeStatus.FILLED
            pair = "SOL/USDC"
            input_amount = 5.0
            output_amount = 745.0
            quoted_price = 150.0
            fill_price = 149.0
            price_impact_bps = 2.5
            fee_usd = 0.10
            slippage_bps = 1.5
            jito_tip_lamports = None
            tx_signature = None
            failure_reason = None
            executed_at = now

        resp = TradeResponse.model_validate(FakeTrade())
        assert resp.id == uid
        assert resp.variation_id == var_id
        assert resp.status == TradeStatus.FILLED
        assert resp.input_amount == 5.0
        assert resp.fill_price == 149.0


class TestTradeListParams:
    def test_defaults(self):
        params = TradeListParams()
        assert params.limit == 100
        assert params.offset == 0
        assert params.variation_id is None

    def test_filter_by_source(self):
        params = TradeListParams(source=TradeSource.LIVE)
        assert params.source == TradeSource.LIVE

    def test_limit_bounds(self):
        with pytest.raises(ValidationError):
            TradeListParams(limit=0)
        with pytest.raises(ValidationError):
            TradeListParams(limit=1001)
