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


class FasterWhisperTranscriber:
    """Whisper via faster-whisper (CTranslate2). The model is loaded in the constructor so setup errors fail early."""

    def __init__(self, model_name: str, device: str, compute_type: str, download_root: Path | None = None):
        from faster_whisper import WhisperModel  # heavy import, only needed when the real model is used

        self._model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=str(download_root) if download_root else None,
        )

    def transcribe(self, path: Path, language: str | None) -> TranscriptionResult:
        segments, info = self._model.transcribe(str(path), language=language, beam_size=5)
        # `segments` is a lazy generator: the actual transcription runs while it is consumed.
        segments = [Segment(start=s.start, end=s.end, text=s.text.strip()) for s in segments]
        return TranscriptionResult(
            text=" ".join(s.text for s in segments),
            segments=segments,
            language=info.language,
            duration=info.duration,
        )
