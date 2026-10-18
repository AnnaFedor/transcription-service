"""Transcription worker: takes task ids from the queue, transcribes, stores the result, deletes the upload."""

import logging
import threading

from app.repository import TaskRepository
from app.storage import FileStorage
from app.task_queue import TaskQueue
from app.transcriber import Transcriber

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500


class TranscriptionWorker:
    """Processes one task at a time until `stop_event` is set; a failing task never stops the loop."""

    def __init__(
        self,
        repository: TaskRepository,
        storage: FileStorage,
        queue: TaskQueue,
        transcriber: Transcriber,
        stop_event: threading.Event,
        get_timeout: float = 0.5,
    ):
        self.repository = repository
        self.storage = storage
        self.queue = queue
        self.transcriber = transcriber
        self.stop_event = stop_event
        self.get_timeout = get_timeout

    def process_one(self, task_id: str) -> None:
        """Run one task to `done` or `failed`; the upload is deleted in either case."""
        task = self.repository.mark_processing(task_id)
        path = self.storage.absolute(task.file_path)
        logger.info("task %s processing (attempt %d)", task_id, task.attempts)
        try:
            language = None if task.language == "auto" else task.language
            result = self.transcriber.transcribe(path, language)
            self.repository.mark_done(task_id, result.to_json())
            logger.info("task %s done", task_id)
        except Exception as exc:
            logger.exception("task %s failed", task_id)
            # The error is shown to API clients, so replace the server-side file path.
            message = f"{type(exc).__name__}: {exc}".replace(str(path), task.original_filename)
            self.repository.mark_failed(task_id, message[:MAX_ERROR_LENGTH])
        finally:
            self.storage.delete(task.file_path)
            self.repository.clear_file_path(task_id)

    def run(self) -> None:
        logger.info("transcription worker started")
        while not self.stop_event.is_set():
            try:
                task_id = self.queue.get(self.get_timeout)
                if task_id:
                    self.process_one(task_id)
            except Exception:
                logger.exception("transcription worker iteration failed")
        logger.info("transcription worker stopped")
