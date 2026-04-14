import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SkepticAudit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skeptic_audit"

    variation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_variation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    llm_output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    llm_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    variation: Mapped["StrategyVariation"] = relationship(
        "StrategyVariation", back_populates="skeptic_audits"
    )
