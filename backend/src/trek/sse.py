from __future__ import annotations

import asyncio
import time
from typing import Any


_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()


def broadcast(event_type: str, data: Any) -> None:
    message = {
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
    }
    for queue in _subscribers.copy():
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            pass


def subscribe() -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[dict[str, Any]]) -> None:
    _subscribers.discard(queue)
