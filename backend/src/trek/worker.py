from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

DEQUEUE_SQL = """
UPDATE task_queue
SET status = 'processing',
    started_at = now()
WHERE id = (
    SELECT id FROM task_queue
    WHERE status = 'pending'
      AND (scheduled_for IS NULL OR scheduled_for <= now())
    ORDER BY priority DESC, created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, task_type, payload, retry_count;
"""

COMPLETE_SQL = """
UPDATE task_queue
SET status = 'completed', finished_at = now()
WHERE id = $1;
"""

FAIL_SQL = """
UPDATE task_queue
SET status = CASE WHEN retry_count < max_retries THEN 'pending' ELSE 'failed' END,
    retry_count = retry_count + 1,
    last_error = $2,
    finished_at = CASE WHEN retry_count < max_retries THEN NULL ELSE now() END,
    scheduled_for = CASE WHEN retry_count < max_retries
        THEN now() + make_interval(secs => power(2, retry_count + 1))
        ELSE NULL END
WHERE id = $1;
"""

TaskHandler = Callable[[dict[str, Any]], Awaitable[None]]

_handlers: dict[str, TaskHandler] = {}


def register_handler(task_type: str) -> Callable[[TaskHandler], TaskHandler]:
    def decorator(fn: TaskHandler) -> TaskHandler:
        _handlers[task_type] = fn
        return fn
    return decorator


@register_handler("test")
async def handle_test(payload: dict[str, Any]) -> None:
    log.info("Executing test task with payload: %s", payload)


@register_handler("paper_trading")
async def handle_paper_trading(payload: dict[str, Any]) -> None:
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from trek.models import PaperSession, StrategyStatus
    from trek.orm import PaperSessionRow
    from trek.paper_session_store import create_session

    variation_id = uuid.UUID(payload["variation_id"])
    duration_days = payload.get("duration_days", 7)
    drop_rate = payload.get("drop_rate", 0.30)
    sortino_threshold = payload.get("sortino_threshold", 1.0)
    max_drawdown_threshold = payload.get("max_drawdown_threshold", 0.30)
    initial_capital = payload.get("initial_capital", 1000.0)
    total_steps = payload.get("total_steps", duration_days * 24)

    db_url = os.environ.get("DATABASE_URL", os.environ.get("TREK_DATABASE_URL", ""))
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as db:
            session = PaperSession(
                variation_id=variation_id,
                duration_days=duration_days,
                drop_rate=drop_rate,
                sortino_threshold=sortino_threshold,
                max_drawdown_threshold=max_drawdown_threshold,
                initial_capital=initial_capital,
            )
            await create_session(db, session, total_steps=total_steps)
            await db.commit()
            log.info("Created paper session %s for variation %s (%d steps)", session.id, variation_id, total_steps)
    finally:
        await engine.dispose()


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def _process_one(pool: asyncpg.Pool) -> bool:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(DEQUEUE_SQL)
            if row is None:
                return False

            task_id = row["id"]
            task_type = row["task_type"]
            payload = row["payload"]
            retry = row["retry_count"]

            log.info(
                "Dequeued task %s type=%s retry=%d",
                task_id, task_type, retry,
            )

            handler = _handlers.get(task_type)
            if handler is None:
                await conn.execute(
                    FAIL_SQL, task_id, f"Unknown task type: {task_type}",
                )
                log.error("No handler for task type %s", task_type)
                return True

    try:
        await handler(payload or {})
    except Exception:
        log.exception("Task %s failed", task_id)
        async with pool.acquire() as conn:
            await conn.execute(FAIL_SQL, task_id, f"Handler raised exception")
        return True

    async with pool.acquire() as conn:
        await conn.execute(COMPLETE_SQL, task_id)
    log.info("Task %s completed", task_id)
    return True


async def _drain_queue(pool: asyncpg.Pool) -> int:
    count = 0
    while await _process_one(pool):
        count += 1
    return count


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    dsn = _database_url()
    if not dsn:
        log.error("DATABASE_URL not set")
        return

    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5)
    log.info("Worker started — connected to database")

    listener_conn = await asyncpg.connect(dsn)
    notify_event = asyncio.Event()

    def _on_notify(
        conn: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        notify_event.set()

    await listener_conn.add_listener("new_task", _on_notify)
    log.info("Listening on channel 'new_task'")

    try:
        try:
            processed = await _drain_queue(pool)
            if processed:
                log.info("Drained %d pending tasks on startup", processed)
        except asyncpg.exceptions.UndefinedTableError:
            log.warning("task_queue table does not exist yet — waiting for migrations")

        while not stop.is_set():
            notify_event.clear()
            notify_task = asyncio.create_task(notify_event.wait())
            stop_task = asyncio.create_task(stop.wait())
            done, pending = await asyncio.wait(
                [notify_task, stop_task],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=30.0,
            )
            for t in pending:
                t.cancel()

            if stop.is_set():
                break

            try:
                await _drain_queue(pool)
            except asyncpg.exceptions.UndefinedTableError:
                pass
    finally:
        log.info("Worker shutting down — draining in-flight tasks")
        await listener_conn.remove_listener("new_task", _on_notify)
        await listener_conn.close()
        await pool.close()
        log.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
