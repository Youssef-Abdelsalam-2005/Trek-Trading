import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Experiment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "experiment"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    current_iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fitness_function_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_config_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_config_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    variations: Mapped[list["StrategyVariation"]] = relationship(
        "StrategyVariation", back_populates="experiment", lazy="selectin"
    )
