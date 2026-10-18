"""Queue between the outbox relay and the worker; in-memory for now, swappable for a broker later."""

import queue
from typing import Protocol


class TaskQueue(Protocol):
    def put(self, task_id: str) -> None: ...

    def get(self, timeout: float) -> str | None:
        """Return the next task id, or None if nothing arrived within `timeout` seconds."""
        ...


class InMemoryTaskQueue:
    """Process-local FIFO queue; its contents are lost on restart (the outbox in SQLite is the source of truth)."""

    def __init__(self):
        self._queue: queue.Queue[str] = queue.Queue()

    def put(self, task_id: str) -> None:
        self._queue.put(task_id)

    def get(self, timeout: float) -> str | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
