# Step 5 — Queue, outbox relay and worker

## Goal

Add the background processing: an in-memory `TaskQueue`, an `OutboxRelay` that polls the outbox and enqueues tasks,
and a `TranscriptionWorker` that transcribes through a `Transcriber` interface, stores the result and deletes the
upload. With a `FakeTranscriber` the whole pipeline (upload → done → result) is tested end to end.

## Prerequisites

- Steps 2, 3 and 4 done (repository, storage, API with the result JSON contract).

## Tests (written first)

This project follows a test driven development.  
The following tests are therefore written first and confirmed red before continuing with the implementation.

Fixtures in `tests/conftest.py`:
- `FakeTranscriber` — records calls `(path, language)`, returns a fixed `TranscriptionResult(text="Hallo Welt",
  segments=[Segment(0.0, 1.5, "Hallo Welt")], language="de", duration=2.0)`; optional `error` to raise instead;
  asserts the file exists when called.
- `pipeline(settings, repository, storage)` → builds queue, stop event, relay (poll interval 0.05 s) and worker
  around a `FakeTranscriber`, starts both threads, yields a `TestClient` plus the parts, and on teardown sets the
  stop event and joins the threads.

Test groups 3 and 4 of 4. `tests/test_pipeline.py`:

| Test | Group | Expected |
|---|---|---|
| `test_end_to_end_pipeline` | 3 — pipeline | Upload a 2 s WAV → poll `GET /transcriptions/{id}` until `done` (timeout 5 s) → `?format=json` returns `{text: "Hallo Welt", segments: [...], language: "de", duration: 2.0}`, `?format=txt` returns `Hallo Welt` as `text/plain`; the upload file is gone and `file_path is None`; fake was called with `language == "de"` |
| `test_worker_failure` | 4 — worker failure | Fake set to raise `RuntimeError("decoder exploded")` → task reaches `failed`, status `error` contains `decoder exploded`, upload file deleted; worker thread still alive; after clearing the error, a second upload reaches `done` |

Red state: `ImportError` for `app.task_queue`, `app.relay`, `app.worker`, `app.transcriber`.

## Implementation details

`app/transcriber.py` (interface part; the real implementation follows in step 6):
- `@dataclass(frozen=True) class Segment(start: float, end: float, text: str)`.
- `@dataclass(frozen=True) class TranscriptionResult(text, segments, language, duration)` with `to_json() -> str`
  producing exactly the API contract `{text, segments: [{start, end, text}], language, duration}`.
- `class Transcriber(Protocol): def transcribe(self, path: Path, language: str | None) -> TranscriptionResult`.

`app/task_queue.py`:
- `class TaskQueue(Protocol)`: `put(task_id: str) -> None`, `get(timeout: float) -> str | None`.
- `class InMemoryTaskQueue` wrapping `queue.Queue`; `get` returns `None` on `queue.Empty`.

`app/relay.py`:
- `class OutboxRelay(repository, queue, poll_interval, stop_event)`.
- `run_once() -> int`: for each `fetch_undispatched()` entry: `repository.mark_queued(...)` **then**
  `queue.put(task_id)`. Marking first guarantees the worker never sees a task still `pending` (not covered by a
  dedicated test; a wrong order shows up as flaky `InvalidTransition` failures in the end-to-end test). A crash between the
  two leaves a `queued` task that is not in memory, which is exactly what the later crash-recovery step resets.
- `run()`: `while not stop_event.is_set(): run_once(); stop_event.wait(poll_interval)`; exceptions in `run_once`
  are logged and the loop continues.

`app/worker.py`:
- `class TranscriptionWorker(repository, storage, queue, transcriber, stop_event, get_timeout=0.5)`.
- `process_one(task_id)`:
  1. `task = repository.mark_processing(task_id)` (returns the updated task).
  2. `result = transcriber.transcribe(storage.absolute(task.file_path), None if task.language == "auto" else task.language)`.
  3. `repository.mark_done(task_id, result.to_json())`.
  4. `except Exception as exc`: `logger.exception(...)`, `repository.mark_failed(task_id, f"{type(exc).__name__}: {exc}"[:500])`.
  5. `finally`: `storage.delete(task.file_path)` and `repository.clear_file_path(task_id)` (upload deleted on any final state).
- `run()`: `while not stop_event.is_set(): task_id = queue.get(get_timeout); if task_id: process_one(task_id)`;
  the loop body is wrapped so no exception ends the thread.
- Logging: module loggers (`logging.getLogger(__name__)`), task id in every message.
- Commit: `Add in-memory queue, outbox relay and transcription worker`.

## Deliverables

| Artifact | Description |
|---|---|
| `app/transcriber.py` | `Segment`, `TranscriptionResult`, `Transcriber` protocol |
| `app/task_queue.py` | `TaskQueue` protocol, `InMemoryTaskQueue` |
| `app/relay.py` | `OutboxRelay` |
| `app/worker.py` | `TranscriptionWorker` |
| `tests/conftest.py` | `FakeTranscriber`, `pipeline` fixture |
| `tests/test_pipeline.py` | End-to-end pipeline and worker-failure tests |

## References

### Internal

- [plan_overview.md](plan_overview.md) — Architecture, Decisions (#3, #9, #10, #11, #12, #13)
- [docs/design-decisions.md](../docs/design-decisions.md) — Task lifecycle & outbox
- [step_02_task-repository.md](step_02_task-repository.md) — transition methods
- [step_04_api.md](step_04_api.md) — result JSON contract

### External

- Python `queue`: https://docs.python.org/3/library/queue.html
- Python `threading.Event`: https://docs.python.org/3/library/threading.html#event-objects

## Deviations from plan

- The worker replaces the absolute upload path in the stored error message with the task's original filename
  (`FileNotFoundError: … 'Meeting Notes.wav'` instead of `/…/data/uploads/<id>.wav`). Why: the error is returned to
  API clients by the status and `409` result responses; same reasoning as the `InvalidMedia` message fix in step 3.
  The full exception incl. path is still logged.
