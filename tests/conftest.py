import math
import struct
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.relay import OutboxRelay
from app.repository import TaskRepository
from app.storage import FileStorage
from app.task_queue import InMemoryTaskQueue
from app.transcriber import Segment, TranscriptionResult
from app.worker import TranscriptionWorker


class FakeTranscriber:
    """Stands in for Whisper: records calls and returns a fixed result, or raises `error` if set."""

    result = TranscriptionResult(
        text="Hallo Welt", segments=[Segment(0.0, 1.5, "Hallo Welt")], language="de", duration=2.0
    )

    def __init__(self):
        self.calls: list[tuple[Path, str | None]] = []
        self.error: Exception | None = None

    def transcribe(self, path: Path, language: str | None) -> TranscriptionResult:
        assert path.is_file(), f"worker passed a missing file: {path}"
        self.calls.append((path, language))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def repository(tmp_path):
    repo = TaskRepository(tmp_path / "db" / "app.sqlite")
    repo.init_schema()
    return repo


@pytest.fixture
def make_wav(tmp_path):
    def _make_wav(seconds: float, name: str = "tone.wav", rate: int = 16000) -> Path:
        path = tmp_path / "input" / name
        path.parent.mkdir(exist_ok=True)
        samples = (int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(int(seconds * rate)))
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(b"".join(struct.pack("<h", s) for s in samples))
        return path

    return _make_wav


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, max_upload_mb=1)


@pytest.fixture
def storage(tmp_path):
    return FileStorage(tmp_path)


@pytest.fixture
def client(settings, repository, storage):
    return TestClient(create_app(settings, repository, storage))


@pytest.fixture
def pipeline(settings, repository, storage):
    queue = InMemoryTaskQueue()
    stop_event = threading.Event()
    transcriber = FakeTranscriber()
    relay = OutboxRelay(repository, queue, poll_interval=0.05, stop_event=stop_event)
    worker = TranscriptionWorker(repository, storage, queue, transcriber, stop_event, get_timeout=0.05)
    threads = [threading.Thread(target=relay.run, daemon=True), threading.Thread(target=worker.run, daemon=True)]
    for thread in threads:
        thread.start()

    yield SimpleNamespace(
        client=TestClient(create_app(settings, repository, storage)),
        transcriber=transcriber,
        relay_thread=threads[0],
        worker_thread=threads[1],
    )

    stop_event.set()
    for thread in threads:
        thread.join(timeout=2)
