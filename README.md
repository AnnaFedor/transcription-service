# transcription-service

MVP service that transcribes short German audio or video clips (≤ 20 s) with Whisper `small` (via faster-whisper,
CPU) and returns the transcript as JSON (with timestamped segments) or plain text. Uploads are processed
asynchronously: the API records a task, a background worker transcribes it, and the client polls for the result.
Swagger UI serves as the frontend. Runs locally with uv or in Docker on macOS and Windows.

## Quick start (local)

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.13 itself if needed.

```bash
uv sync
uv run python main.py
```

Open **http://127.0.0.1:8000/docs**. The first start downloads the Whisper model (~460 MB) into the Hugging Face cache;
later starts load it in about a second. Stop with Ctrl-C.

Test clips:
- `tests/fixtures/honigbienen_de.mp4` — 7.8 s of German speech.
- On macOS, generate one: `say -v Anna -o data/sample.aiff "Guten Tag. Dies ist ein kurzer Test."`

## Run with Docker

```bash
docker compose up --build
```

Open **http://localhost:8000/docs**. The Whisper model is baked into the image at build time, so the container starts
offline. Uploads and the SQLite database live in the named volume `transcription-data` and survive restarts.

| Task | Command |
|---|---|
| Stop (keep data) | `docker compose down` |
| Stop and delete all data | `docker compose down -v` |
| Use a smaller/faster model | `docker compose build --build-arg WHISPER_MODEL=base` |

> **Port clash:** if the local server (`uv run python main.py`) is still running, `localhost:8000` reaches it instead
> of the container. Stop the local server first.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/transcriptions` | Upload a clip (multipart `file`; optional `language`, default `de`, or `auto`; `summarize` is accepted but not implemented yet). Returns `202` with `task_id`. |
| `GET` | `/transcriptions/{task_id}` | Task status: `pending → queued → processing → done \| failed`, plus `error` if failed. |
| `GET` | `/transcriptions/{task_id}/result?format=json\|txt` | Transcript. JSON: `{text, segments: [{start, end, text}], language, duration}`. TXT: plain text download. |
| `GET` | `/health` | Liveness check. |

Error responses:

| Code | When |
|---|---|
| `404` | Unknown `task_id` |
| `409` | Result requested before the task is `done` (the message includes the status, and the error for `failed`) |
| `413` | Upload larger than `MAX_UPLOAD_MB` |
| `422` | Not a readable audio/video file, no audio stream, longer than `MAX_DURATION_SECONDS`, or invalid `language` |

Example with curl:

```bash
curl -F file=@tests/fixtures/honigbienen_de.mp4 http://localhost:8000/transcriptions
# {"task_id":"3f2a…","status":"pending"}

curl http://localhost:8000/transcriptions/3f2a…
# {"task_id":"3f2a…","status":"done","error":null,…}

curl "http://localhost:8000/transcriptions/3f2a…/result?format=txt"
# Honigbienen leben in Völkern mit genau einer Königin, …
```

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
            │                           faster-whisper                         │
            └──────────────────────────────────────────────────────────────────┘
                          DATA_DIR: uploads/ + db/app.sqlite
```

- **Upload:** the API checks size, decodability, audio stream and duration (PyAV), stores the file as
  `uploads/{task_id}{ext}` (the user's filename never becomes part of the path), then writes the task row and an
  outbox row **in one transaction**.
- **Transactional outbox:** the relay thread polls the outbox, marks each task `queued` and puts it on the in-memory
  queue. Because the relay reads only from the database, SQLite stays the source of truth: the queue is disposable,
  and the design keeps working once the queue becomes a real broker and the worker a separate process.
- **Worker:** transcribes one task at a time, stores the result or the error, and deletes the upload in either case.
  A failing task never stops the worker.
- **Composition:** `main.py` wires everything, loads the model at startup (fail fast), starts the relay and worker
  threads, runs Uvicorn, and stops the threads cleanly on shutdown.
- Repository, queue, storage and transcriber sit behind small interfaces, so each can be swapped (Postgres, broker,
  S3, another model) without touching the rest.

## Configuration

All settings are environment variables (or a `.env` file).

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `data` (`/data` in Docker) | Directory for uploads and the SQLite database |
| `MAX_UPLOAD_MB` | `25` | Maximum upload size |
| `MAX_DURATION_SECONDS` | `20` | Maximum clip duration |
| `RELAY_POLL_INTERVAL` | `1.0` | Seconds between outbox polls |
| `WHISPER_MODEL` | `small` | Whisper model size (`tiny`, `base`, `small`, …); in Docker, set with `--build-arg` |
| `WHISPER_DEVICE` | `cpu` | Inference device |
| `WHISPER_COMPUTE_TYPE` | `int8` | CTranslate2 compute type |
| `WHISPER_DOWNLOAD_ROOT` | unset (Hugging Face cache) | Where model files are stored (`/models` in Docker) |
| `DEFAULT_LANGUAGE` | `de` | Language used when an upload does not specify one |
| `HOST` | `127.0.0.1` (`0.0.0.0` in Docker) | Bind address |
| `PORT` | `8000` | Port |

## Tests

```bash
uv run pytest
```

The suite covers the four agreed test groups and runs in about a second, without the real model:

1. **Repository:** task and outbox row are written atomically; the relay's outbox queries.
2. **API validation:** `202` for valid clips (generated WAV and a real MP4), `413` too large, `422` non-media and too long.
3. **End-to-end pipeline:** real relay and worker threads with a fake transcriber; upload → `done` → JSON/TXT result; upload deleted.
4. **Worker failure:** a failing transcription marks the task `failed` and the worker keeps running.

Plus a path-traversal test for upload filenames. The real Whisper model and the Docker image are verified manually
(see the checklists in `plan/step_06_*.md` and `plan/step_07_*.md`).

## Design decisions

The reasoning behind each choice is recorded in [docs/design-decisions.md](docs/design-decisions.md); the
implementation plan and per-step deviations are in [plan/](plan/plan_overview.md).

## Next steps

- **Crash recovery and retries:** on startup, reset tasks stuck in `queued`/`processing` and re-dispatch them, with
  an `attempts` limit (the column already exists).
- **Summarization:** Ollama with a lightweight LLM as a second compose service, a `summarize` task type, and a
  separate endpoint.
- **Postgres** with SQLAlchemy and Alembic instead of SQLite.
- **Real message broker** (Redis/RabbitMQ) and separate worker containers.
- **Relay wake-up** via an event instead of pure polling.
- **CI:** lint, tests and image build.
- **Friendlier frontend** than Swagger UI.
- **True streaming upload limit:** reject oversized uploads while they are received, not after Starlette has buffered them.
- **Remove the `av<19` pin** once faster-whisper supports PyAV 19.
