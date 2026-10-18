"""Transcriber interface and the result format shared by the worker and the API."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    segments: list[Segment]
    language: str
    duration: float

    def to_json(self) -> str:
        """Serialise to the API result contract: {text, segments: [{start, end, text}], language, duration}."""
        return json.dumps(asdict(self), ensure_ascii=False)


class Transcriber(Protocol):
    def transcribe(self, path: Path, language: str | None) -> TranscriptionResult:
        """Transcribe the file; `language=None` means auto-detect."""
        ...
