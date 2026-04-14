"""Core tables for Trek Trading v1

Revision ID: 0001
Revises:
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

strategy_status = sa.Enum(
    "generated",
    "backtesting",
    "backtested",
    "skeptic_pending",
    "skeptic_passed",
    "skeptic_failed",
    "paper_trading",
    "paper_passed",
    "paper_failed",
    "live",
    "halted",
    "killed",
    "retired",
    name="strategy_status",
)

task_status = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    name="task_status",
)

trade_side = sa.Enum(
    "buy",
    "sell",
    name="trade_side",
)

trade_status = sa.Enum(
    "filled",
    "failed",
    "skipped",
    name="trade_status",
)


def upgrade() -> None:
    strategy_status.create(op.get_bind(), checkfirst=True)
    task_status.create(op.get_bind(), checkfirst=True)
    trade_side.create(op.get_bind(), checkfirst=True)
    trade_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "experiment",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("fitness_config", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("iteration_config", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "strategy_variation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("experiment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("strategy_variation.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", strategy_status, nullable=False, server_default="generated"),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("lineage_depth", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_token_input", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_token_output", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_cost", sa.Numeric(precision=12, scale=6), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_cumulative_cost", sa.Numeric(precision=12, scale=6), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_strategy_variation_experiment_id", "strategy_variation", ["experiment_id"])
    op.create_index("ix_strategy_variation_parent_id", "strategy_variation", ["parent_id"])
    op.create_index("ix_strategy_variation_status", "strategy_variation", ["status"])

    op.create_table(
        "backtest_run",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("variation_id", UUID(as_uuid=True), sa.ForeignKey("strategy_variation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("sortino", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("total_return", sa.Float(), nullable=True),
        sa.Column("sharpe", sa.Float(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.Column("equity_curve", JSONB(), nullable=True),
        sa.Column("fees", sa.Float(), nullable=False, server_default=sa.text("0.001")),
        sa.Column("slippage", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_backtest_run_variation_id", "backtest_run", ["variation_id"])

    op.create_table(
        "skeptic_audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("variation_id", UUID(as_uuid=True), sa.ForeignKey("strategy_variation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("pbo_value", sa.Float(), nullable=True),
        sa.Column("static_analysis", JSONB(), nullable=True),
        sa.Column("cpcv_results", JSONB(), nullable=True),
        sa.Column("monte_carlo_results", JSONB(), nullable=True),
        sa.Column("llm_review", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_skeptic_audit_variation_id", "skeptic_audit", ["variation_id"])

    op.create_table(
        "paper_session",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("variation_id", UUID(as_uuid=True), sa.ForeignKey("strategy_variation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default=sa.text("7")),
        sa.Column("fill_failure_rate", sa.Float(), nullable=False, server_default=sa.text("0.30")),
        sa.Column("sortino", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("total_pnl", sa.Numeric(precision=18, scale=8), nullable=False, server_default=sa.text("0")),
        sa.Column("equity_curve", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_paper_session_variation_id", "paper_session", ["variation_id"])

    op.create_table(
        "live_deployment",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("variation_id", UUID(as_uuid=True), sa.ForeignKey("strategy_variation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initial_equity", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("peak_equity", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("current_equity", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_live_deployment_variation_id", "live_deployment", ["variation_id"])

    op.create_table(
        "trade",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("variation_id", UUID(as_uuid=True), sa.ForeignKey("strategy_variation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paper_session_id", UUID(as_uuid=True), sa.ForeignKey("paper_session.id", ondelete="SET NULL"), nullable=True),
        sa.Column("live_deployment_id", UUID(as_uuid=True), sa.ForeignKey("live_deployment.id", ondelete="SET NULL"), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", trade_side, nullable=False),
        sa.Column("input_amount", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("output_amount", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("quoted_price", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("fill_price", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("price_impact", sa.Float(), nullable=True),
        sa.Column("fees", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("slippage", sa.Float(), nullable=True),
        sa.Column("jito_tip", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("tx_signature", sa.Text(), nullable=True),
        sa.Column("status", trade_status, nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_trade_variation_id", "trade", ["variation_id"])
    op.create_index("ix_trade_paper_session_id", "trade", ["paper_session_id"])
    op.create_index("ix_trade_live_deployment_id", "trade", ["live_deployment_id"])
    op.create_index("ix_trade_timestamp", "trade", ["timestamp"])

    op.create_table(
        "risk_config",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("experiment.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("per_strategy_drawdown_halt", sa.Float(), nullable=False, server_default=sa.text("15.0")),
        sa.Column("portfolio_circuit_breaker", sa.Float(), nullable=False, server_default=sa.text("25.0")),
        sa.Column("max_concurrent_live", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("paper_trading_days", sa.Integer(), nullable=False, server_default=sa.text("7")),
        sa.Column("max_drawdown_cap", sa.Float(), nullable=False, server_default=sa.text("30.0")),
        sa.Column("pbo_fail_threshold", sa.Float(), nullable=False, server_default=sa.text("0.40")),
        sa.Column("fill_failure_rate", sa.Float(), nullable=False, server_default=sa.text("30.0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "llm_config",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("experiment.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "wallet_state",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("sol_balance", sa.Numeric(precision=18, scale=9), nullable=False),
        sa.Column("usdc_balance", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wallet_state_recorded_at", "wallet_state", ["recorded_at"])

    op.create_table(
        "kill_switch_event",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("strategies_killed", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "task_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", task_status, nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_task_queue_dequeue", "task_queue", ["task_type", "status", "scheduled_at"])

    op.create_table(
        "ohlcv_data",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pair", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("volume", sa.Numeric(precision=18, scale=8), nullable=False),
    )
    op.create_primary_key("pk_ohlcv_data", "ohlcv_data", ["timestamp", "pair", "resolution"])

    op.execute("SELECT create_hypertable('ohlcv_data', 'timestamp', if_not_exists => TRUE)")


def downgrade() -> None:
    op.drop_table("ohlcv_data")
    op.drop_table("task_queue")
    op.drop_table("kill_switch_event")
    op.drop_table("wallet_state")
    op.drop_table("llm_config")
    op.drop_table("risk_config")
    op.drop_table("trade")
    op.drop_table("live_deployment")
    op.drop_table("paper_session")
    op.drop_table("skeptic_audit")
    op.drop_table("backtest_run")
    op.drop_table("strategy_variation")
    op.drop_table("experiment")

    trade_status.drop(op.get_bind(), checkfirst=True)
    trade_side.drop(op.get_bind(), checkfirst=True)
    task_status.drop(op.get_bind(), checkfirst=True)
    strategy_status.drop(op.get_bind(), checkfirst=True)
