import uuid
from datetime import datetime

from backend.app.models.enums import TaskStatus
from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class TaskQueueCreate(BaseSchema):
    task_type: str
    payload: dict | None = None
    max_retries: int = 3
    scheduled_at: datetime | None = None


class TaskQueueResponse(BaseResponseSchema):
    task_type: str
    status: TaskStatus
    payload: dict | None
    result: dict | None
    error_message: str | None
    retry_count: int
    max_retries: int
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
