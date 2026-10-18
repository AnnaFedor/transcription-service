# Step 3 — FileStorage and media validation

## Goal

Store uploads safely under `DATA_DIR/uploads` with a hard size limit, and check with PyAV that a stored file is
decodable media with an audio stream and an acceptable duration. Both pieces are independent of FastAPI so the API
(step 4) and the worker (step 5) can reuse them.

## Prerequisites

- Step 1 done (`Settings.uploads_dir`, `max_upload_bytes`, `max_duration_seconds`).
- PyAV installed as a dependency of faster-whisper (verified: `av` 19.0.1 on Python 3.13 / arm64).

## Tests (written first)

No automated tests in this step. Test scope is limited to the four agreed test groups (see
[plan_overview.md](plan_overview.md) → Steps). Storage and validation are tested through the API in step 4
(test group 2: `413`, `422` non-media, `422` too long, `202` valid).

Manual check instead: in `uv run python`, `media.validate(Path("some.wav"), 20)` on a short WAV returns a
`MediaInfo` with the expected duration, and on a text file raises `InvalidMedia`.

## Implementation details

`app/storage.py`:
- `class FileTooLarge(Exception)`.
- `class FileStorage(data_dir: Path)`:
  - `save(task_id, original_filename, source: BinaryIO, max_bytes) -> str` — creates `uploads/` if missing, copies
    in 1 MiB chunks, counts bytes, on exceeding `max_bytes` closes and deletes the partial file and raises
    `FileTooLarge`. Returns the path relative to `data_dir` (POSIX separators).
  - `_safe_extension(name)` — `Path(name).suffix.lower()` kept only if it matches `^\.[a-z0-9]{1,10}$`, else `""`.
    The stored name is always `{task_id}{ext}`; the user's filename is never part of the path.
  - `absolute(relative) -> Path`, `delete(relative)` (`missing_ok=True`).

`app/media.py`:
- `@dataclass(frozen=True) class MediaInfo(duration_seconds: float, has_audio: bool)`.
- `class InvalidMedia(Exception)`, `class MediaTooLong(Exception)`.
- `probe(path) -> MediaInfo` — `av.open(path)`; any `av.error.FFmpegError` / `OSError` → `InvalidMedia`.
  Duration from `container.duration / av.time_base`; if missing, from the audio stream's
  `duration * time_base`; if still missing, decode the audio stream and sum `frame.samples / frame.sample_rate`
  (cheap for ≤ 25 MB files).
- `validate(path, max_duration) -> MediaInfo` — `probe`, then no audio stream → `InvalidMedia("no audio stream")`,
  `duration > max_duration` → `MediaTooLong(f"{duration:.1f}s exceeds limit of {max_duration:.0f}s")`.
- Commit: `Add FileStorage and PyAV media validation`.

## Deliverables

| Artifact | Description |
|---|---|
| `app/storage.py` | `FileStorage`, `FileTooLarge` |
| `app/media.py` | `MediaInfo`, `probe`, `validate`, `InvalidMedia`, `MediaTooLong` |

## References

### Internal

- [plan_overview.md](plan_overview.md) — Decisions (#6, #7, #8, #16)
- [docs/design-decisions.md](../docs/design-decisions.md) — Upload validation, Storage & data
- [step_01_project-setup.md](step_01_project-setup.md) — `Settings`
- [step_04_api.md](step_04_api.md) — where this code is tested

### External

- PyAV documentation: https://pyav.basswood-io.com/docs/stable/

## Deviations from plan

