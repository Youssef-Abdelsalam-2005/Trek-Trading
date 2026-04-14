import uuid

from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class SkepticAuditCreate(BaseSchema):
    variation_id: uuid.UUID
    stage: str
    passed: bool
    score: float | None = None
    reasoning: str | None = None
    details: dict | None = None
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None
    llm_cost_usd: float | None = None


class SkepticAuditResponse(BaseResponseSchema):
    variation_id: uuid.UUID
    stage: str
    passed: bool
    score: float | None
    reasoning: str | None
    details: dict | None
    llm_input_tokens: int | None
    llm_output_tokens: int | None
    llm_cost_usd: float | None
