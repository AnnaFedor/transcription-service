# Step 7 — Containerization

## Goal

Package the service as a Docker image with the Whisper model baked in, and run it with docker-compose using a named
volume for uploads and the database. The same compose file works on macOS and Windows (Docker Desktop); a manual
check proves the container serves the full pipeline.

## Prerequisites

- Step 6 done (service runs and transcribes locally).
- Docker Desktop running (verified: `docker` installed).
- Linux wheels for `ctranslate2` and `av` on Python 3.13 for both `linux/arm64` (Docker on Apple silicon) and
  `linux/amd64` (Windows) — checked at the start of this step by building for both platforms
  (`docker buildx build --platform linux/amd64,linux/arm64`) or at least for the native one plus `amd64`.

## Tests (written first)

No automated tests in this step. Test scope is limited to the four agreed test groups (see
[plan_overview.md](plan_overview.md) → Steps). The existing tests must stay green (`uv run pytest`).

Manual container checklist:

| Check | Expected |
|---|---|
| Build & start | `docker compose up -d --build` exits `0` |
| Health | `GET http://localhost:8000/health` returns `200`; `docker compose ps` shows `healthy` after the start period |
| Non-root | `docker compose exec transcription id -u` prints a value other than `0` |
| Model baked in | Container log shows the model-loaded line and no download progress (`HF_HUB_OFFLINE=1` would make a missing model fail startup) |
| Pipeline | In `http://localhost:8000/docs`, upload the German `say -v Anna` clip from step 6 → status `done`, transcript contains the sentence |
| Validation | Upload a text file → `422` |
| Persistence | `docker compose restart` → status of the earlier task is still `done` (SQLite on the named volume) |
| Teardown | `docker compose down` keeps the volume; `docker compose down -v` removes it |

## Implementation details

`Dockerfile` (multi-stage):
1. `builder` — `FROM python:3.13-slim`; `COPY --from=ghcr.io/astral-sh/uv:<pinned version> /uv /usr/local/bin/uv`;
   `ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy`; copy `pyproject.toml` + `uv.lock`;
   `uv sync --frozen --no-dev --no-install-project` (cached dependency layer); copy `app/` and `main.py`.
2. `model` — from `builder`; `ARG WHISPER_MODEL=small`;
   `RUN .venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8', download_root='/models')"`.
3. `runtime` — `FROM python:3.13-slim`; create user `app` (UID 10001); copy `/app/.venv`, `app/`, `main.py` from
   `builder` and `/models` from `model`; `mkdir /data && chown app /data`.
   `ENV PATH=/app/.venv/bin:$PATH DATA_DIR=/data HOST=0.0.0.0 PORT=8000 WHISPER_MODEL=${WHISPER_MODEL}
   WHISPER_DOWNLOAD_ROOT=/models HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1`;
   `USER app`; `EXPOSE 8000`; `VOLUME /data`;
   `HEALTHCHECK --interval=10s --timeout=3s --start-period=60s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"`
   (no curl in slim images);
   `CMD ["python", "main.py"]`.

`docker-compose.yml`:
```yaml
services:
  transcription:
    build: .
    image: transcription-service:latest
    ports:
      - "8000:8000"
    volumes:
      - transcription-data:/data
    environment:
      MAX_UPLOAD_MB: 25
      MAX_DURATION_SECONDS: 20
    restart: unless-stopped
volumes:
  transcription-data:
```

`.dockerignore`: `.venv`, `data`, `.git`, `.idea`, `__pycache__`, `.pytest_cache`, `plan`, `docs`, `tests`.

Notes:
- `WHISPER_MODEL` is a build arg and an env var; changing the model means rebuilding with
  `--build-arg WHISPER_MODEL=...` (decision #21).
- Expected image size: roughly 1 GB (Python + ctranslate2 + ~460 MB model); recorded in Deviations if very different.
- Commit: `Add Dockerfile and docker-compose`.

## Deliverables

| Artifact | Description |
|---|---|
| `Dockerfile` | Multi-stage build with baked model, non-root user, healthcheck |
| `docker-compose.yml` | One service, named volume `transcription-data`, port 8000 |
| `.dockerignore` | Keeps the build context small |
| Build arg / env | `WHISPER_MODEL` (build arg), `HF_HUB_OFFLINE=1`, `WHISPER_DOWNLOAD_ROOT=/models`, `DATA_DIR=/data`, `HOST=0.0.0.0` |

## References

### Internal

- [plan_overview.md](plan_overview.md) — Decisions (Docker, #8, #21), resolved open question
- [docs/design-decisions.md](../docs/design-decisions.md) — Tooling, layout, tests (Docker)
- [step_01_project-setup.md](step_01_project-setup.md) — env vars
- [step_06_whisper-and-main.md](step_06_whisper-and-main.md) — `main.py`, `WHISPER_DOWNLOAD_ROOT`

### External

- uv in Docker: https://docs.astral.sh/uv/guides/integration/docker/
- Dockerfile reference (HEALTHCHECK, multi-stage): https://docs.docker.com/reference/dockerfile/
- Compose file reference: https://docs.docker.com/reference/compose-file/
- Hugging Face Hub offline mode: https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables

## Deviations from plan

