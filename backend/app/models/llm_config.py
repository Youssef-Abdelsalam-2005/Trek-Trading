from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import SecretStr

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LLMConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_config"

    label: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_key_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    cost_per_input_token: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    cost_per_output_token: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
