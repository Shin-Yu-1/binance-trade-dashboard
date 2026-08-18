import asyncio
from typing import Any


class EventBus:
    """In-process pub/sub fanning out ingestion events to dashboard WS clients."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Any]] = set()

    def subscribe(self) -> asyncio.Queue[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Any]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: Any) -> None:
        for queue in self._subscribers:
            queue.put_nowait(event)
