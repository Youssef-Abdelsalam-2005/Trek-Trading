import uuid
from datetime import datetime

from pydantic import Field

from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class ExperimentCreate(BaseSchema):
    name: str = Field(..., max_length=255)
    description: str | None = None
    max_iterations: int = Field(default=100, ge=1)
    fitness_function_config: dict | None = None
    risk_config_override: dict | None = None
    llm_config_override: dict | None = None


class ExperimentUpdate(BaseSchema):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    is_active: bool | None = None
    max_iterations: int | None = Field(default=None, ge=1)
    fitness_function_config: dict | None = None
    risk_config_override: dict | None = None
    llm_config_override: dict | None = None


class ExperimentResponse(BaseResponseSchema):
    name: str
    description: str | None
    is_active: bool
    max_iterations: int
    current_iteration: int
    fitness_function_config: dict | None
    risk_config_override: dict | None
    llm_config_override: dict | None
    deleted_at: datetime | None
    effective_risk_config: dict | None = None
