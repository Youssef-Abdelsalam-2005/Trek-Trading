import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import StrategyStatus, validate_transition


class StrategyVariation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "strategy_variation"

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_variation.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[StrategyStatus] = mapped_column(
        default=StrategyStatus.GENERATED, nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cumulative_llm_cost_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    experiment: Mapped["Experiment"] = relationship(
        "Experiment", back_populates="variations"
    )
    parent: Mapped["StrategyVariation | None"] = relationship(
        "StrategyVariation", remote_side="StrategyVariation.id", back_populates="children"
    )
    children: Mapped[list["StrategyVariation"]] = relationship(
        "StrategyVariation", back_populates="parent", lazy="selectin"
    )
    backtest_runs: Mapped[list["BacktestRun"]] = relationship(
        "BacktestRun", back_populates="variation", lazy="selectin"
    )
    skeptic_audits: Mapped[list["SkepticAudit"]] = relationship(
        "SkepticAudit", back_populates="variation", lazy="selectin"
    )
    paper_sessions: Mapped[list["PaperSession"]] = relationship(
        "PaperSession", back_populates="variation", lazy="selectin"
    )
    live_deployments: Mapped[list["LiveDeployment"]] = relationship(
        "LiveDeployment", back_populates="variation", lazy="selectin"
    )

    def transition_to(self, target: StrategyStatus) -> None:
        if not validate_transition(self.status, target):
            raise ValueError(
                f"Invalid transition: {self.status.value} → {target.value}"
            )
        self.status = target
