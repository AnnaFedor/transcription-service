import math
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.repository import TaskRepository
from app.storage import FileStorage


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
