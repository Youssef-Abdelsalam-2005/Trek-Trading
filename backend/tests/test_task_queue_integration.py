"""Integration tests for the Postgres task queue.

Requirements from the architecture plan:
- Enqueue 100 tasks, 4 concurrent workers dequeue without duplicates
- Failed tasks retry up to 3 times
- NOTIFY wakes idle workers within 100ms

Requires a running Postgres instance. Set TEST_DATABASE_URL env var.
Default: postgresql://postgres:postgres@localhost:5432/trek_test
"""

import asyncio
import os
import time

import asyncpg
import pytest
import pytest_asyncio

from trek.services.task_queue import TaskQueueService

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/trek_test",
)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_queue (
    id UUID PRIMARY KEY,
    task_type VARCHAR(64) NOT NULL,
    payload JSON,
    result JSON,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_task_queue_dequeue
    ON task_queue (task_type, status, scheduled_at)
    WHERE status = 'pending';
"""


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(TEST_DSN, min_size=2, max_size=10)
    async with p.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
    yield p
    async with p.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS task_queue CASCADE")
    await p.close()


@pytest_asyncio.fixture
async def queue_service(pool):
    svc = TaskQueueService(pool, max_retries=3, base_backoff_seconds=0.01)
    yield svc
    await svc.close_listener()


@pytest.mark.asyncio
async def test_enqueue_dequeue_no_duplicates(queue_service: TaskQueueService):
    """100 tasks, 4 concurrent workers, no duplicates."""
    task_ids = []
    for i in range(100):
        tid = await queue_service.enqueue("test_job", {"index": i})
        task_ids.append(tid)

    assert len(task_ids) == 100
    assert len(set(task_ids)) == 100

    dequeued: list[dict] = []
    lock = asyncio.Lock()

    async def worker():
        while True:
            task = await queue_service.dequeue("test_job")
            if task is None:
                break
            async with lock:
                dequeued.append(task)

    workers = [asyncio.create_task(worker()) for _ in range(4)]
    await asyncio.gather(*workers)

    dequeued_ids = [t["id"] for t in dequeued]
    assert len(dequeued_ids) == 100, f"Expected 100, got {len(dequeued_ids)}"
    assert len(set(dequeued_ids)) == 100, "Duplicate tasks were dequeued"
    assert set(dequeued_ids) == set(task_ids)


@pytest.mark.asyncio
async def test_failed_tasks_retry_up_to_3_times(queue_service: TaskQueueService, pool):
    """Failed tasks get retried up to max_retries (3) times, then permanently fail on the 4th."""
    task_id = await queue_service.enqueue("retry_job", {"data": "test"}, max_retries=3)

    for attempt in range(3):
        await asyncio.sleep(0.05)
        task = await queue_service.dequeue("retry_job")
        assert task is not None, f"Expected task on retry attempt {attempt + 1}"
        assert task["id"] == task_id
        await queue_service.fail(task_id, f"error on attempt {attempt}")

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, retry_count FROM task_queue WHERE id = $1", task_id,
            )
            assert row["status"] == "pending", f"Expected pending after retry {attempt + 1}"
            assert row["retry_count"] == attempt + 1

    await asyncio.sleep(0.05)
    task = await queue_service.dequeue("retry_job")
    assert task is not None, "Expected task on final attempt (will permanently fail)"
    await queue_service.fail(task_id, "final failure")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, retry_count, error_message FROM task_queue WHERE id = $1",
            task_id,
        )
        assert row["status"] == "failed"
        assert row["retry_count"] == 4
        assert "final failure" in row["error_message"]

    task = await queue_service.dequeue("retry_job")
    assert task is None, "Should not be dequeued after exhausting retries"


@pytest.mark.asyncio
async def test_complete_marks_task_done(queue_service: TaskQueueService, pool):
    task_id = await queue_service.enqueue("complete_job", {"value": 42})
    task = await queue_service.dequeue("complete_job")
    assert task is not None
    await queue_service.complete(task_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, completed_at FROM task_queue WHERE id = $1",
            task_id,
        )
        assert row["status"] == "completed"
        assert row["completed_at"] is not None


@pytest.mark.asyncio
async def test_notify_wakes_listener_within_100ms(queue_service: TaskQueueService):
    """LISTEN/NOTIFY wakes idle workers within 100ms."""
    wake_event = asyncio.Event()
    conn = await queue_service.listen(TEST_DSN, "notify_job", wake_event)

    try:
        start = time.monotonic()
        await queue_service.enqueue("notify_job", {"ping": True})
        await asyncio.wait_for(wake_event.wait(), timeout=1.0)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 100, f"NOTIFY took {elapsed_ms:.1f}ms, expected < 100ms"
    finally:
        await conn.close()
        queue_service._listener_conn = None


@pytest.mark.asyncio
async def test_retry_backoff_increases(queue_service: TaskQueueService, pool):
    """Backoff doubles on each retry."""
    task_id = await queue_service.enqueue("backoff_job", {}, max_retries=3)

    task = await queue_service.dequeue("backoff_job")
    assert task is not None
    await queue_service.fail(task_id, "first failure")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT scheduled_at FROM task_queue WHERE id = $1", task_id,
        )
        assert row["scheduled_at"] is not None


@pytest.mark.asyncio
async def test_dequeue_respects_task_type(queue_service: TaskQueueService):
    """Dequeue only returns tasks of the requested type."""
    await queue_service.enqueue("type_a", {"a": 1})
    await queue_service.enqueue("type_b", {"b": 2})

    task = await queue_service.dequeue("type_a")
    assert task is not None
    assert task["task_type"] == "type_a"

    task = await queue_service.dequeue("type_a")
    assert task is None

    task = await queue_service.dequeue("type_b")
    assert task is not None
    assert task["task_type"] == "type_b"
