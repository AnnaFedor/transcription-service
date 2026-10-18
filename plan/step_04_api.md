# Step 4 — API: upload, status, result, health

## Goal

Expose the service through FastAPI with Swagger UI: an upload endpoint that validates the file and creates a task
(task + outbox row), a status endpoint, a result endpoint that returns JSON or TXT, and a health endpoint. The app is
built by a `create_app` factory so it can be tested without background threads.

## Prerequisites

- Step 2 done (`TaskRepository`).
- Step 3 done (`FileStorage`, `media.validate`).

## Tests (written first)

This project follows a test driven development.  
The following tests are therefore written first and confirmed red before continuing with the implementation.

Fixtures in `tests/conftest.py`:
- `make_wav(tmp_path)` → factory `make_wav(seconds, name="tone.wav") -> Path` writing a 16 kHz mono 16-bit sine
  WAV with the standard-library `wave` module (no binary fixtures committed).
- `settings(tmp_path)` → `Settings(data_dir=tmp_path, max_upload_mb=1)` (1 MB keeps the oversize test small).
- `storage(tmp_path)` → `FileStorage(tmp_path)`.
- `client(settings, repository, storage)` → `TestClient(create_app(settings, repository, storage))`; no relay or
  worker running, so tasks stay `pending`.

Test group 2 of 4 (API validation). `tests/test_api.py`:

| Test | Request | Expected |
|---|---|---|
| `test_upload_valid_clip` | `POST /transcriptions` with 2 s WAV | `202`, body `{task_id, status: "pending"}`; task in repository with `language == "de"`; file exists at `file_path` |
| `test_upload_too_large` | 40 s WAV (~1.3 MB) with `max_upload_mb=1` | `413`; no task, `uploads/` empty |
| `test_upload_non_media` | text file named `notes.mp3` | `422` with a readable `detail`; no task, `uploads/` empty |
| `test_upload_too_long` | 25 s WAV (16 kHz mono 16-bit ≈ 0.8 MB, under the 1 MB test limit) | `422`, `detail` mentions the 20 s limit; no task, `uploads/` empty |

Status and result endpoints (JSON and TXT) are covered by the end-to-end test in step 5. Manual check: open
`http://127.0.0.1:8000/docs` once the app runs (step 6) and try `404` / `409` on status and result.

Red state: `ImportError` for `app.api`.

## Implementation details

`app/api.py`:

- `create_app(settings, repository, storage) -> FastAPI` — stores dependencies on `app.state`; title
  "Transcription Service", description pointing to the async flow.
- Pydantic response models: `TaskCreated(task_id, status)`, `TaskStatusResponse(task_id, status, error, created_at,
  updated_at)`, `Segment(start, end, text)`, `TranscriptionResponse(text, segments, language, duration)`.
- `POST /transcriptions` (`status_code=202`, sync `def` so file I/O runs in FastAPI's threadpool):
  - Parameters: `file: UploadFile = File(...)`, `language: str = Form(settings.default_language)`,
    `summarize: bool = Form(False)` (documented as "accepted, not yet implemented").
  - `language` must match `^(auto|[a-z]{2,3})$` → else `422`.
  - Early reject: `Content-Length` header larger than `max_upload_bytes` + a small multipart margin → `413` before
    reading. Note: Starlette has already buffered the multipart body into a spooled temp file at this point, so the
    chunked copy in `FileStorage.save` is the authoritative limit; true streaming rejection would need middleware
    and is out of MVP scope.
  - `task_id = str(uuid4())` → `storage.save(...)` (`FileTooLarge` → `413`) → `media.validate(...)`
    (`InvalidMedia` / `MediaTooLong` → delete file, `422`) → `repository.create_task(...)` → `TaskCreated`.
  - Any exception after saving deletes the file before re-raising.
- `GET /transcriptions/{task_id}` → `TaskStatusResponse` or `404`.
- `GET /transcriptions/{task_id}/result` with `format: Literal["json", "txt"] = "json"`:
  - unknown → `404`; status not `done` → `409` (`detail = f"task is {status}"`, plus the error for `failed`).
  - `json` → `TranscriptionResponse` parsed from `result_json`.
  - `txt` → `PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'})`,
    with `stem` sanitised to `[A-Za-z0-9._-]`.
- `GET /health` → `{"status": "ok"}`.
- The result JSON shape (`text`, `segments`, `language`, `duration`) is the contract the worker writes in step 5.
- Commit: `Add transcription API endpoints`.

## Deliverables

| Artifact | Description |
|---|---|
| `app/api.py` | `create_app` factory, endpoints, response models |
| `tests/conftest.py` | `make_wav`, `settings`, `storage`, `client` fixtures |
| `tests/test_api.py` | API validation tests |

## References

### Internal

- [plan_overview.md](plan_overview.md) — Architecture, Decisions (#1, #5, #6, #7, #17)
- [docs/design-decisions.md](../docs/design-decisions.md) — API, Upload validation
- [step_02_task-repository.md](step_02_task-repository.md), [step_03_storage-and-media-validation.md](step_03_storage-and-media-validation.md)

### External

- FastAPI request files: https://fastapi.tiangolo.com/tutorial/request-files/
- FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/
- HTTP 202 / 409 / 413 / 422 semantics: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status

## Deviations from plan

- `test_upload_valid_clip` is parametrised over a generated WAV **and** a real file, `tests/fixtures/honigbienen_de.mp4`
  (7.8 s German speech, audio-only MP4/AAC, 30 KB), moved there from the project root. Why: the user provided the
  sample; it checks validation on a real container format, not only on generated WAV. This adds one committed
  binary fixture, contrary to the overview's "no binary fixtures" note — acceptable at 30 KB.
