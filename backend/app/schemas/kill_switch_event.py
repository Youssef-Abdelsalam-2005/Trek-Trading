from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class KillSwitchEventCreate(BaseSchema):
    reason: str | None = None
    triggered_by: str = "user"


class KillSwitchEventResponse(BaseResponseSchema):
    reason: str | None
    triggered_by: str
    strategies_affected: int
    details: dict | None
