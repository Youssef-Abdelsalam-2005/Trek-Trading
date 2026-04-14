from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

NOTIFY_CHANNEL = "new_task"

ENQUEUE_SQL = """
INSERT INTO task_queue (id, task_type, payload, status, retry_count, max_retries,
                        created_at, updated_at, scheduled_at)
VALUES ($1, $2, $3::jsonb, 'pending', 0, $4, now(), now(), $5)
"""

DEQUEUE_SQL = """
UPDATE task_queue
SET status = 'running',
    started_at = now(),
    updated_at = now()
WHERE id = (
    SELECT id FROM task_queue
    WHERE task_type = $1
      AND status = 'pending'
      AND (scheduled_at IS NULL OR scheduled_at <= now())
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, task_type, payload, retry_count, max_retries, created_at, scheduled_at;
"""

COMPLETE_SQL = """
UPDATE task_queue
SET status = 'completed', completed_at = now(), updated_at = now()
WHERE id = $1 AND status = 'running';
"""

RETRY_SQL = """
UPDATE task_queue
SET status = 'pending',
    retry_count = retry_count + 1,
    error_message = $2,
    completed_at = NULL,
    started_at = NULL,
    scheduled_at = now() + make_interval(secs => $3),
    updated_at = now()
WHERE id = $1 AND status = 'running';
"""

FAIL_PERMANENT_SQL = """
UPDATE task_queue
SET status = 'failed',
    retry_count = retry_count + 1,
    error_message = $2,
    completed_at = now(),
    updated_at = now()
WHERE id = $1 AND status = 'running';
"""

STATUS_SQL = """
SELECT id, task_type, status, payload, retry_count, max_retries, error_message,
       created_at, updated_at, started_at, completed_at, scheduled_at
FROM task_queue WHERE id = $1;
"""


class TaskQueueService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
    ):
        self._pool = pool
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._listener_conn: asyncpg.Connection | None = None

    async def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        *,
        max_retries: int | None = None,
        scheduled_at: datetime | None = None,
    ) -> uuid.UUID:
        retries = max_retries if max_retries is not None else self._max_retries
        task_id = uuid.uuid4()
        payload_json = json.dumps(payload or {})

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    ENQUEUE_SQL, task_id, task_type, payload_json, retries, scheduled_at,
                )
                await conn.execute(
                    f"SELECT pg_notify('{NOTIFY_CHANNEL}', $1)", task_type,
                )

        log.info("enqueued task %s type=%s", task_id, task_type)
        return task_id

    async def dequeue(self, task_type: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(DEQUEUE_SQL, task_type)
                if row is None:
                    return None
                return dict(row)

    async def complete(self, task_id: uuid.UUID) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute(COMPLETE_SQL, task_id)
            if result == "UPDATE 0":
                raise ValueError(f"Task {task_id} not found or not in running state")
        log.info("completed task %s", task_id)

    async def fail(self, task_id: uuid.UUID, error: str) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                info = await conn.fetchrow(
                    "SELECT retry_count, max_retries, task_type FROM task_queue "
                    "WHERE id = $1 FOR UPDATE",
                    task_id,
                )
                if info is None:
                    raise ValueError(f"Task {task_id} not found")

                next_retry = info["retry_count"] + 1

                if next_retry < info["max_retries"]:
                    backoff = self._base_backoff * (2 ** (next_retry - 1))
                    await conn.execute(RETRY_SQL, task_id, error, backoff)
                    await conn.execute(
                        f"SELECT pg_notify('{NOTIFY_CHANNEL}', $1)", info["task_type"],
                    )
                    log.info(
                        "task %s failed (retry %d/%d, backoff %.1fs): %s",
                        task_id, next_retry, info["max_retries"], backoff, error,
                    )
                else:
                    await conn.execute(FAIL_PERMANENT_SQL, task_id, error)
                    log.info(
                        "task %s permanently failed after %d retries: %s",
                        task_id, next_retry, error,
                    )

    async def get_status(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(STATUS_SQL, task_id)
            return dict(row) if row else None

    async def listen(
        self,
        dsn: str,
        task_type: str,
        on_notify: asyncio.Event,
    ) -> asyncpg.Connection:
        conn = await asyncpg.connect(dsn)
        self._listener_conn = conn

        def _callback(conn, pid, channel, payload):
            if payload == task_type:
                on_notify.set()

        await conn.add_listener(NOTIFY_CHANNEL, _callback)
        return conn

    async def close_listener(self) -> None:
        if self._listener_conn is not None:
            await self._listener_conn.close()
            self._listener_conn = None
