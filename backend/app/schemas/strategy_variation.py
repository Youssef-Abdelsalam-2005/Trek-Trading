import uuid

from pydantic import Field

from backend.app.models.enums import StrategyStatus
from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class StrategyVariationCreate(BaseSchema):
    experiment_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=255)
    code: str
    generation: int = Field(default=0, ge=0)
    llm_input_tokens: int = Field(default=0, ge=0)
    llm_output_tokens: int = Field(default=0, ge=0)
    llm_cost_usd: float = Field(default=0.0, ge=0.0)
    cumulative_llm_cost_usd: float = Field(default=0.0, ge=0.0)


class StrategyVariationUpdate(BaseSchema):
    name: str | None = Field(default=None, max_length=255)
    error_message: str | None = None


class StatusTransitionRequest(BaseSchema):
    target_status: StrategyStatus


class StrategyVariationResponse(BaseResponseSchema):
    experiment_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str | None
    status: StrategyStatus
    code: str
    generation: int
    llm_input_tokens: int
    llm_output_tokens: int
    llm_cost_usd: float
    cumulative_llm_cost_usd: float
    error_message: str | None


class StrategyVariationSummary(BaseResponseSchema):
    experiment_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str | None
    status: StrategyStatus
    generation: int
    llm_cost_usd: float
    cumulative_llm_cost_usd: float
