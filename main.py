"""Entrypoint: wires all components, starts the relay and worker threads, then runs the HTTP server."""

import logging
import threading
import time
from dataclasses import dataclass

import uvicorn
from fastapi import FastAPI

from app.api import create_app
from app.config import Settings
from app.relay import OutboxRelay
from app.repository import TaskRepository
from app.storage import FileStorage
from app.task_queue import InMemoryTaskQueue, TaskQueue
from app.transcriber import FasterWhisperTranscriber, Transcriber
from app.worker import TranscriptionWorker

logger = logging.getLogger("main")


@dataclass
class Components:
    app: FastAPI
    repository: TaskRepository
    storage: FileStorage
    queue: TaskQueue
    relay: OutboxRelay
    worker: TranscriptionWorker
    stop_event: threading.Event


def build_components(settings: Settings, transcriber: Transcriber) -> Components:
    repository = TaskRepository(settings.db_path)
    repository.init_schema()
    storage = FileStorage(settings.data_dir)
    queue = InMemoryTaskQueue()
    stop_event = threading.Event()
    return Components(
        app=create_app(settings, repository, storage),
        repository=repository,
        storage=storage,
        queue=queue,
        relay=OutboxRelay(repository, queue, settings.relay_poll_interval, stop_event),
        worker=TranscriptionWorker(repository, storage, queue, transcriber, stop_event),
        stop_event=stop_event,
    )


def start_background(components: Components) -> list[threading.Thread]:
    threads = [
        threading.Thread(target=components.relay.run, name="outbox-relay", daemon=True),
        threading.Thread(target=components.worker.run, name="transcription-worker", daemon=True),
    ]
    for thread in threads:
        thread.start()
    return threads


def stop_background(components: Components, threads: list[threading.Thread], timeout: float = 30) -> None:
    """Signal the threads to stop and wait; the worker finishes the task it is currently processing."""
    components.stop_event.set()
    for thread in threads:
        thread.join(timeout)
        if thread.is_alive():
            logger.warning("thread %s did not stop within %ss", thread.name, timeout)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    logger.info("loading whisper model %r (device=%s, compute_type=%s)",
                settings.whisper_model, settings.whisper_device, settings.whisper_compute_type)
    started = time.monotonic()
    transcriber = FasterWhisperTranscriber(
        settings.whisper_model, settings.whisper_device, settings.whisper_compute_type, settings.whisper_download_root
    )
    logger.info("model loaded in %.1fs", time.monotonic() - started)

    components = build_components(settings, transcriber)
    threads = start_background(components)
    try:
        uvicorn.run(components.app, host=settings.host, port=settings.port)
    finally:
        logger.info("shutting down background threads")
        stop_background(components, threads)
        logger.info("shutdown complete")


if __name__ == "__main__":
    main()
