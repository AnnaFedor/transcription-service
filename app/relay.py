"""Outbox relay: moves newly created tasks from the database outbox onto the task queue."""

import logging
import threading

from app.repository import TaskRepository
from app.task_queue import TaskQueue

logger = logging.getLogger(__name__)


class OutboxRelay:
    """Polls the outbox every `poll_interval` seconds until `stop_event` is set."""

    def __init__(self, repository: TaskRepository, queue: TaskQueue, poll_interval: float, stop_event: threading.Event):
        self.repository = repository
        self.queue = queue
        self.poll_interval = poll_interval
        self.stop_event = stop_event

    def run_once(self) -> int:
        """Dispatch all pending outbox entries and return how many were dispatched."""
        entries = self.repository.fetch_undispatched()
        for entry in entries:
            # Mark first, then enqueue: the worker must never receive a task that is still `pending`.
            self.repository.mark_queued(entry.id, entry.task_id)
            self.queue.put(entry.task_id)
            logger.info("task %s queued", entry.task_id)
        return len(entries)

    def run(self) -> None:
        logger.info("outbox relay started")
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("outbox relay iteration failed")
            self.stop_event.wait(self.poll_interval)
        logger.info("outbox relay stopped")
