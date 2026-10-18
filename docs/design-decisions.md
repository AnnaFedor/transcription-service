# Transcription Service – MVP Design Decisions

Outcome of the design session on 2026-10-18, based on [project-idea.md](project-idea.md).
Time budget for the MVP: **~2 hours**.

## Goal & scope

A user uploads a short German audio or video file (≤ 20 s) through Swagger UI. The service transcribes it
asynchronously with Whisper and returns the transcript as JSON or TXT.

**In scope (MVP):** upload + validation, SQLite task table with transactional outbox, outbox relay, in-memory queue,
one transcription worker, result retrieval, a few tests, Docker, README.

**Deferred** (designed for, not built): crash recovery, retries, summarization via Ollama, Postgres, message broker,
CI. See [Later](#later--next-steps).

## Architecture

One Python 3.13 process. `main.py` is the entrypoint and wires everything explicitly:

1. Load config, open the database, create the schema.
2. Load the Whisper model (fail fast at boot if broken).
3. Start the **outbox relay** thread and the **worker** thread.
4. `uvicorn.run(app)` – blocks.
5. When uvicorn returns (SIGTERM / Ctrl-C): set a stop event, join the threads (current job finishes).

```
            ┌──────────── single process (main.py) ─────────────────────────┐
 client ──▶ │ FastAPI ──tx──▶ SQLite [tasks + outbox]                       │
 (Swagger)  │                      ▲          │ poll 1 s                    │
            │                      │          ▼                             │
            │                      │     Relay thread ──put──▶ queue.Queue  │
            │                      │                              │ get     │
            │                      └──── status/result ──── Worker thread   │
            │                                                (faster-whisper)│
            └────────────────────────────────────────────────────────────────┘
```

Components sit behind small interfaces so they can be swapped later without touching the rest:

| Component | MVP implementation | Later |
|---|---|---|
| `TaskRepository` | plain `sqlite3`, one connection per thread, WAL, `busy_timeout` | SQLAlchemy + Postgres |
| `TaskQueue` | `InMemoryTaskQueue` (`queue.Queue`) | Redis / RabbitMQ, separate worker containers |
| `FileStorage` | local directory under `DATA_DIR` | S3 / MinIO |
| `Transcriber` | `FasterWhisperTranscriber` | other models; `FakeTranscriber` in tests |

Relay and worker are plain Python classes with no FastAPI imports, so they can move into their own process unchanged.

## Task lifecycle & outbox

```
pending ──relay──▶ queued ──worker──▶ processing ──▶ done
                                           │
                                           └──────▶ failed
```

- `pending` – task row and outbox row written in **one transaction** by the API.
- `queued` – relay put the task on the queue and set the outbox row's `dispatched_at`.
- `processing` – worker picked it up.
- `done` / `failed` – final. `failed` carries a short `error` message (full traceback in logs).

**Relay:** pure polling every `RELAY_POLL_INTERVAL` (1 s):
`SELECT … FROM outbox WHERE dispatched_at IS NULL ORDER BY id LIMIT 10`, enqueue, mark dispatched, set task `queued`.
It depends only on the database, so it stays valid once API and worker run in separate processes.

**Worker errors:** fail immediately – catch the exception, set `failed` + `error`, delete the upload, continue.
Every task runs inside `try/except Exception`; the worker thread never dies. No retries in the MVP.

**Crash recovery (later step):** on startup, tasks stuck in `queued`/`processing` are reset to `pending` and their
outbox rows un-dispatched, so the relay re-enqueues them. The worker increments `attempts`; at `MAX_ATTEMPTS` (e.g. 3)
the task is marked `failed` (poison-file protection). The `attempts` column and outbox `dispatched_at` are in the
schema **from the start** so this needs no migration.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/transcriptions` | multipart `file`, `language` (default `de`, `auto` allowed), `summarize` (default `false`, accepted but no effect yet) → `202 {task_id, status}` |
| `GET` | `/transcriptions/{id}` | `{task_id, status, error?, created_at, updated_at}` |
| `GET` | `/transcriptions/{id}/result?format=json\|txt` | `200` when done · `409` not finished · `404` unknown. JSON: `{text, segments:[{start,end,text}], language, duration}`. TXT: `text/plain` |
| `GET` | `/health` | liveness (Docker healthcheck later) |

### Upload validation (all at upload time – no bad task reaches the queue)

1. **Size:** `MAX_UPLOAD_MB` (default 25), checked while streaming to disk in chunks → abort with `413`.
2. **Decodable media:** PyAV must open the file and find at least one audio stream → else `422`.
3. **Duration:** ≤ `MAX_DURATION_SECONDS` (default 20) → else `422`.

No file-extension allowlist; PyAV is the gate. The 20 s limit is operational (single CPU worker), not a model
limit – faster-whisper can handle long audio by moving through 30 s windows.

## Storage & data

Everything lives under `DATA_DIR` (`/data` in the container, `./data` locally):

```
DATA_DIR/
  uploads/{task_id}{original_ext}   ← e.g. 3f2a…c1.mp4
  db/app.sqlite
```

- The database stores paths **relative** to `DATA_DIR`.
- Files are named by `task_id`, never by the user's filename (no collisions, no path traversal). The original
  filename is stored in its own column for display only.
- **Retention:** the upload is deleted as soon as the task reaches `done` or `failed`; `file_path` is set to null.
  The transcript stays in the database.
- Docker: **named volume** `transcription-data:/data`.

## Model & runtime

- **faster-whisper** (CTranslate2), model `small`, `device=cpu`, `compute_type=int8` – all configurable via env
  (`WHISPER_MODEL`, …). CPU-only.
- Model is **loaded at startup** in `main.py`, before uvicorn starts. First local run downloads ~460 MB.
- **Language:** request parameter, default `de`, `auto` for detection.
- **PyAV** (bundled with faster-whisper) does validation and decoding → **no system ffmpeg** needed locally or in Docker.

## Tooling, layout, tests

- **Python 3.13**, **uv** (`pyproject.toml` + `uv.lock`, `uv sync`, `uv run python main.py`).
  Verified: faster-whisper 1.2.1, ctranslate2 4.8.3, PyAV 19.0.1 install as wheels on 3.13 / arm64 macOS.
- Config via `pydantic-settings` (env variables).

```
main.py                  ← entrypoint: wires everything, starts threads, uvicorn.run
app/
  config.py              ← settings from env
  api.py                 ← FastAPI app + endpoints
  repository.py          ← TaskRepository (sqlite3)
  storage.py             ← FileStorage (local dir)
  task_queue.py          ← TaskQueue interface + InMemoryTaskQueue
  relay.py               ← outbox relay thread
  worker.py              ← worker thread
  transcriber.py         ← Transcriber interface + FasterWhisperTranscriber
  media.py               ← PyAV validation
tests/
```

**Tests** (pytest, `FakeTranscriber`, temporary `DATA_DIR`, never the real model):

1. **Repository** – task + outbox written in one transaction; `fetch_undispatched` / `mark_queued` transitions.
2. **API validation** – `413` oversized, `422` non-media, `422` > 20 s (generated sine-wave WAV), `202` valid.
3. **End-to-end pipeline** – real relay + worker threads: POST → poll until `done` → JSON + TXT result → upload deleted.
4. **Worker failure** – fake transcriber raises → task `failed` with error, worker thread still alive.

If time runs short, keep 3 and 2. The real model is checked manually in Swagger.

**Test approach** (decided during plan review): these four groups are written test-first in the step that builds
their code (repository → step 2, API validation → step 4, pipeline + worker failure → step 5, see `plan/`). All
other steps are verified manually.

**Docker** (after everything runs locally): `python:3.13-slim`, multi-stage build with `uv sync --frozen --no-dev`,
non-root user, `HEALTHCHECK` on `/health`, `docker-compose.yml` with one service, the `transcription-data` named
volume and port 8000. Model weights: **baked into the image at build time** (container starts offline;
`WHISPER_MODEL` must match the baked model).

## Implementation plan

Commit after each step (git repo already initialised; `.gitignore` for `.venv/`, `data/`, `__pycache__/`, `.idea/`).

1. Project setup (uv, config), `TaskRepository` + schema
2. API: upload + validation, status, result, health
3. Relay, worker, transcriber, `main.py` → run locally, end-to-end test in Swagger with a real German clip
4. Tests (the four groups above)
5. Dockerfile + compose
6. README: how to run, architecture, next steps

## Decision log

| # | Question | Decision |
|---|---|---|
| 1 | How clients get results | Async: `202` + `task_id`, poll status, fetch result |
| 2 | Whisper library | faster-whisper, `small`, int8 |
| 3 | Process layout | One process; `main.py` starts threads, then `uvicorn.run`; `TaskQueue` interface for a later split |
| 4 | GPU or CPU | CPU-only; device/compute type configurable |
| 5 | Language | `language` param, default `de`, `auto` allowed |
| 6 | Clips > 20 s | Reject at upload with `422`; limit via env |
| 7 | Upload validation | Size limit (`413`), PyAV opens + audio stream, duration; no extension allowlist |
| 8 | Upload storage | Local dir under `DATA_DIR`, named Docker volume, relative paths in DB |
| 9 | Retention | Delete upload on final state |
| 10 | Task states | `pending → queued → processing → done \| failed` |
| 11 | Crash recovery | Re-dispatch with `attempts` limit – **later step**; columns in schema now |
| 12 | Worker errors | Fail immediately, worker never dies, no retries |
| 13 | Relay trigger | Pure polling, 1 s |
| 14 | DB access | Plain `sqlite3` behind `TaskRepository` |
| 15 | Scope & order | Run locally first, then tests, then Docker; README last |
| 16 | Media metadata | PyAV, no system ffmpeg |
| 17 | Endpoints | As in the API table |
| 18 | Packaging | uv, layout above |
| 19 | Model loading | At startup in `main.py` |
| 20 | Tests | The four groups above |
| 21 | Model in Docker | Baked into image at build time |
| 22 | Version control | Commit per step; repo already initialised |
| 23 | Test approach | Test-first only for the four test groups; other steps verified manually |

## Later / next steps

- Crash recovery + retries (shared `attempts` counter)
- Summarization: Ollama as a second compose service with a lightweight LLM, `summarize` task type, later default on, separate endpoint
- Postgres + SQLAlchemy + Alembic
- Real broker (Redis/RabbitMQ) and separate worker containers
- Relay wake-up via event instead of pure polling
- CI (lint, tests, image build)
- More user-friendly frontend
