# Implementation Plan — Overview

This plan implements the MVP transcription service described in
[docs/project-idea.md](../docs/project-idea.md). The design was refined in a design session and recorded in
[docs/design-decisions.md](../docs/design-decisions.md), which is the authoritative requirements document for this
plan; the project idea is the original source.

## Goal

A locally runnable and dockerized FastAPI service where a user uploads a short (≤ 20 s) German audio or video file
through Swagger UI, the file is validated and stored, a task is recorded in SQLite together with an outbox entry, an
outbox relay thread moves the task onto an in-memory queue, and a single worker thread transcribes it with
faster-whisper. The user polls the task status and downloads the transcript as JSON or TXT. The result is a tested,
committed code base, a Docker image + compose setup that runs on macOS and Windows, and a README.

## Decisions already made

| Decision | Choice | Where |
|---|---|---|
| Interaction model | Async: `POST` returns `202` + `task_id`, client polls status and fetches result | design-decisions.md · Decision log #1 |
| Whisper implementation | faster-whisper, model `small`, `compute_type=int8` | design-decisions.md · Model & runtime, #2 |
| Process layout | One process; `main.py` wires components, starts relay + worker threads, then `uvicorn.run(app)`; stop event + join on shutdown | design-decisions.md · Architecture, #3 |
| Hardware | CPU-only; device and compute type configurable via env | #4 |
| Language | `language` parameter, default `de`, `auto` allowed | #5 |
| Duration limit | Reject clips > `MAX_DURATION_SECONDS` (20) at upload with `422` | #6 |
| Upload validation | Size limit `MAX_UPLOAD_MB` (25) while streaming → `413`; PyAV must open file and find an audio stream → `422`; duration → `422`; no extension allowlist | design-decisions.md · Upload validation, #7 |
| Upload storage | Local directory under `DATA_DIR`, files named `{task_id}{ext}`, relative paths in DB, named Docker volume | design-decisions.md · Storage & data, #8 |
| Retention | Upload deleted when task reaches `done` or `failed`; `file_path` set to null | #9 |
| Task states | `pending → queued → processing → done \| failed` | design-decisions.md · Task lifecycle, #10 |
| Crash recovery | Deferred; `attempts` column and outbox `dispatched_at` included in schema now | #11 |
| Worker errors | Fail immediately with `error`; worker loop never dies; no retries | #12 |
| Relay | Pure polling of outbox every 1 s (`RELAY_POLL_INTERVAL`) | #13 |
| DB access | Plain `sqlite3` behind `TaskRepository`; one connection per thread, WAL, `busy_timeout` | #14 |
| Order of work | Run locally first, then Docker, README last | #15 |
| Media metadata | PyAV (bundled with faster-whisper); no system ffmpeg | #16 |
| Endpoints | `POST /transcriptions`, `GET /transcriptions/{id}`, `GET /transcriptions/{id}/result?format=json\|txt`, `GET /health` | design-decisions.md · API, #17 |
| Packaging | uv, `pyproject.toml` + `uv.lock`, Python 3.13 | #18 |
| Model loading | Eagerly at startup in `main.py` | #19 |
| Tests | Only four groups: repository, API validation, end-to-end pipeline with `FakeTranscriber`, worker failure; real model never used in tests | design-decisions.md · Tooling, layout, tests, #20 |
| Test approach | Test-first only for the four groups (steps 2, 4, 5); all other steps are verified manually | Plan review (resolved with the user) |
| Docker | `python:3.13-slim`, multi-stage uv build, non-root user, `HEALTHCHECK`, compose with named volume, port 8000 | design-decisions.md · Tooling, layout, tests |
| Model in Docker | Baked into the image at build time (confirmed, see open questions) | #21 |
| Version control | Commit after each step | #22 |
| Summarization | Out of scope; `summarize` parameter accepted but has no effect | design-decisions.md · API, Later |

## Architecture

```
            ┌──────────────────── single process (main.py) ────────────────────┐
 client ──▶ │ FastAPI (api.py)                                                 │
 (Swagger)  │   │ validate (media.py) + save (storage.py)                      │
            │   │                                                              │
            │   └──tx──▶ SQLite [tasks + outbox] (repository.py)               │
            │                 ▲                │ poll every 1 s                │
            │                 │                ▼                               │
            │                 │          Relay thread (relay.py)               │
            │                 │                │ put                           │
            │                 │                ▼                               │
            │                 │          TaskQueue (task_queue.py)             │
            │                 │                │ get                           │
            │                 │                ▼                               │
            │                 └─ status ─ Worker thread (worker.py)            │
            │                    result        │ transcribe                    │
            │                                  ▼                               │
            │                           Transcriber (transcriber.py)           │
            │                           faster-whisper | FakeTranscriber       │
            └──────────────────────────────────────────────────────────────────┘
                          DATA_DIR: uploads/ + db/app.sqlite
```

- `main.py` is the composition root: it builds config, repository, storage, queue, transcriber, relay and worker,
  starts the two threads, and calls `uvicorn.run(app)`. When uvicorn returns, it sets a shared `threading.Event` and
  joins both threads.
- The FastAPI app is created by a factory (`create_app(repository, storage, settings)`) so tests can build it with a
  temporary `DATA_DIR` and no threads, and `main.py` can inject the real components.
- Relay, worker, repository, storage, queue and transcriber have no FastAPI imports.
- Every component behind an interface (`TaskRepository`, `TaskQueue`, `FileStorage`, `Transcriber`) can be swapped
  later (Postgres, broker, S3, other models) without touching the others.

## Repository layout (target)

```
transcription-service/
  .gitignore              ← new: .venv/, data/, __pycache__/, .idea/, .pytest_cache/
  .dockerignore           ← new (step 7)
  README.md               ← exists; rewritten in step 8
  pyproject.toml          ← new: dependencies, pytest config
  uv.lock                 ← new
  .python-version         ← new: 3.13
  main.py                 ← exists (PyCharm stub); replaced by the entrypoint in step 6
  Dockerfile              ← new (step 7)
  docker-compose.yml      ← new (step 7)
  app/                    ← new: application package
    __init__.py
    config.py             ← Settings from env (pydantic-settings)
    repository.py         ← TaskRepository (sqlite3) + schema
    storage.py            ← FileStorage (local dir under DATA_DIR)
    media.py              ← PyAV validation (audio stream, duration)
    api.py                ← create_app() factory + endpoints
    task_queue.py         ← TaskQueue protocol + InMemoryTaskQueue
    relay.py              ← OutboxRelay thread
    worker.py             ← TranscriptionWorker thread
    transcriber.py        ← Transcriber protocol, TranscriptionResult, FasterWhisperTranscriber
  tests/                  ← new: pytest suite (four test groups)
    conftest.py           ← fixtures: tmp DATA_DIR, settings, generated WAV files, FakeTranscriber, pipeline
    test_repository.py    ← group 1 (step 2)
    test_api.py           ← group 2 (step 4)
    test_pipeline.py      ← groups 3 + 4 (step 5)
  docs/                   ← exists: project-idea.md, design-decisions.md
  plan/                   ← this plan
  data/                   ← runtime only, git-ignored (local DATA_DIR)
```

Test audio is generated in fixtures (sine-wave WAV via the standard-library `wave` module), so no binary fixtures
are committed.

## Steps

Each step is independently reviewable and ends with a working, verified increment.
Steps that contain one of the four agreed test groups (2, 4, 5) are **test-driven**: the tests named in the step
are written and failing before the implementation is written. All other steps name manual checks instead.

| # | Step | Depends on |
|---|---|---|
| 1 | Project setup & configuration (uv, pyproject, pytest, `.gitignore`, `Settings`) | — |
| 2 | `TaskRepository` and SQLite schema (tasks + outbox, transactional create, state transitions) | 1 |
| 3 | `FileStorage` and media validation (save/delete under `DATA_DIR`, PyAV audio stream + duration check) | 1 |
| 4 | API: upload with validation, status, result, health (`create_app` factory) | 2, 3 |
| 5 | Queue, outbox relay and worker with `Transcriber` interface (`FakeTranscriber` end-to-end pipeline) | 2, 3, 4 |
| 6 | `FasterWhisperTranscriber` and `main.py` wiring; run locally and verify in Swagger with a real German clip | 5 |
| 7 | Containerization: Dockerfile, docker-compose, manual container checks | 6 |
| 8 | README: how to run, architecture, API, next steps | 7 |

- Steps 2 and 3 are independent of each other and can be done in either order.
- The four test groups from the design session are placed in the steps where their code is written (test-first):
  repository → step 2, API validation → step 4, end-to-end pipeline and worker failure → step 5.
  Step 3's storage and validation code is tested through the API in step 4.
- Steps 1, 3, 6, 7 and 8 have no automated tests; each lists manual checks. Step 6 is the first point where the
  real model runs; it is verified manually in Swagger, never in automated tests.
- Each step ends with a commit.

## Open questions for the user

No open questions remain.

**Resolved:**

- **Test approach:** the plan templates call for test-driven development in every step, while the design session
  limited tests to four groups. Decision: test-first only for those four groups (steps 2, 4, 5); the other steps are
  verified manually. Justification: keeps the agreed test scope and the time budget, while staying compatible with
  the test-driven step workflow.

- **Model in Docker (decision #21):** the model weights are **baked into the image at build time**. Confirmed by the
  user. Justification: the container starts offline and predictably, with no first-start download. The cost is a
  larger image and a rebuild when the model changes. `WHISPER_MODEL` must match the baked model. Affects step 7 only.
