"""Media inspection with PyAV: is the file decodable, does it have audio, how long is it."""

from dataclasses import dataclass
from pathlib import Path

import av


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    has_audio: bool


class InvalidMedia(Exception):
    """Raised when a file cannot be decoded or has no audio stream."""


class MediaTooLong(Exception):
    """Raised when a file is longer than the allowed duration."""


def probe(path: Path) -> MediaInfo:
    """Read duration and audio presence. Raises InvalidMedia if PyAV cannot open the file."""
    try:
        with av.open(str(path)) as container:
            audio = container.streams.audio[0] if container.streams.audio else None
            return MediaInfo(duration_seconds=_duration(container, audio), has_audio=audio is not None)
    except (av.error.FFmpegError, OSError) as exc:
        # The message may reach API clients, so keep server paths out of it; details stay on the chained exception.
        raise InvalidMedia("not a readable audio/video file") from exc


def validate(path: Path, max_duration: float) -> MediaInfo:
    """Probe the file and enforce: has an audio stream, duration ≤ `max_duration` seconds."""
    info = probe(path)
    if not info.has_audio:
        raise InvalidMedia("no audio stream")
    if info.duration_seconds > max_duration:
        raise MediaTooLong(f"{info.duration_seconds:.1f}s exceeds limit of {max_duration:.0f}s")
    return info


def _duration(container, audio) -> float:
    # Container header first, then the audio stream header; decode as a last resort.
    if container.duration is not None:
        return container.duration / av.time_base
    if audio is None:
        return 0.0
    if audio.duration is not None and audio.time_base is not None:
        return float(audio.duration * audio.time_base)
    return sum(frame.samples / frame.sample_rate for frame in container.decode(audio))
