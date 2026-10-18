# Step 1 — Project setup & configuration

## Goal

Turn the empty PyCharm project into a uv-managed Python 3.13 project with pytest configured and a single `Settings`
class that holds every configurable value of the service. All later steps import their configuration from one place.

## Prerequisites

- uv installed (verified: 0.11.16).
- Git repository initialised (verified: "initial commit" exists).
- Plan overview approved ([plan_overview.md](plan_overview.md)).

## Tests (written first)

No automated tests in this step. Test scope is limited to the four agreed test groups (see
[plan_overview.md](plan_overview.md) → Steps); none of them covers setup or configuration.

Manual checks instead:
- `uv sync` succeeds and creates `uv.lock`.
- `uv run python -c "from app.config import Settings; print(Settings())"` prints the defaults.
- `DATA_DIR=/tmp/x MAX_UPLOAD_MB=5 uv run python -c "from app.config import Settings; s = Settings(); print(s.data_dir, s.max_upload_mb)"`
  prints `/tmp/x 5`.
- `uv run pytest` runs (reports "no tests ran" until step 2).

## Implementation details

1. `uv init --bare --python 3.13` (or write `pyproject.toml` by hand), add `.python-version` with `3.13`.
2. Dependencies (`uv add`): `fastapi`, `uvicorn`, `python-multipart`, `pydantic-settings`, `faster-whisper`
   (pulls in `av` / PyAV and `ctranslate2`).
   Dev dependencies (`uv add --dev`): `pytest`, `httpx` (required by FastAPI's `TestClient`).
3. `pyproject.toml` pytest config:
   ```toml
   [tool.pytest.ini_options]
   testpaths = ["tests"]
   ```
4. `app/__init__.py` (empty) and `app/config.py`:
   - `class Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`;
     env var names are the upper-case field names, no prefix.
   - Fields: `data_dir: Path = Path("data")`, `max_upload_mb: int = 25`, `max_duration_seconds: float = 20`,
     `relay_poll_interval: float = 1.0`, `whisper_model: str = "small"`, `whisper_device: str = "cpu"`,
     `whisper_compute_type: str = "int8"`, `whisper_download_root: Path | None = None`,
     `default_language: str = "de"`, `host: str = "127.0.0.1"`, `port: int = 8000`.
   - Properties: `uploads_dir` (`data_dir / "uploads"`), `db_path` (`data_dir / "db" / "app.sqlite"`),
     `max_upload_bytes` (`max_upload_mb * 1024 * 1024`).
   - No directory creation here (side-effect free); directories are created by the components that use them.
5. `tests/conftest.py` created empty (fixtures added in steps 2, 4 and 5).
6. `.gitignore`: `.venv/`, `data/`, `__pycache__/`, `.idea/`, `.pytest_cache/`, `.env`.
7. The PyCharm stub `main.py` stays untouched until step 6.
8. Commit: `Set up uv project, pytest and Settings`.

## Deliverables

| Artifact | Description |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | Project metadata, locked dependencies, Python 3.13 |
| `.gitignore` | Ignores venv, runtime data, caches, IDE files |
| `app/__init__.py`, `app/config.py` | `Settings` class |
| `tests/conftest.py` | Empty pytest setup |
| Env vars | `DATA_DIR`, `MAX_UPLOAD_MB`, `MAX_DURATION_SECONDS`, `RELAY_POLL_INTERVAL`, `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `WHISPER_DOWNLOAD_ROOT`, `DEFAULT_LANGUAGE`, `HOST`, `PORT` |

## References

### Internal

- [plan_overview.md](plan_overview.md) — Repository layout, Decisions (#4, #6, #7, #13, #18, #19)
- [docs/design-decisions.md](../docs/design-decisions.md) — Upload validation, Model & runtime, Tooling

### External

- uv projects: https://docs.astral.sh/uv/concepts/projects/
- pydantic-settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/

## Deviations from plan

