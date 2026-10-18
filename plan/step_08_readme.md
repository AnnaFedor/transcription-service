# Step 8 — README

## Goal

Rewrite `README.md` so someone with a fresh clone can run, use and understand the service: how to start it locally
and with Docker, how to use the API, how it is built, how to configure it, and what comes next.

## Prerequisites

- Step 7 done (local and Docker runs verified, so the documented commands are known to work).

## Tests (written first)

No automated tests in this step. Test scope is limited to the four agreed test groups (see
[plan_overview.md](plan_overview.md) → Steps).

Manual checks:
- Follow the README's quick start and Docker commands verbatim in a fresh clone; every command works.
- The configuration table lists exactly the fields of `Settings`; the API table lists all four endpoints.

## Implementation details

`README.md` sections:
1. **Intro** — one paragraph: what the service does, ≤ 20 s German clips, JSON/TXT.
2. **Quick start (local)** — `uv sync`, `uv run python main.py`, open `http://127.0.0.1:8000/docs`; note the
   one-time ~460 MB model download; how to create a test clip with `say -v Anna` (macOS).
3. **Run with Docker** — `docker compose up --build`, `http://localhost:8000/docs`, data in the named volume
   `transcription-data`, `docker compose down -v` to wipe it, `--build-arg WHISPER_MODEL=base` for a smaller model.
4. **API** — table of the four endpoints, status values, error codes (`404`, `409`, `413`, `422`), and a `curl`
   example: upload → poll → result (`?format=txt`).
5. **Architecture** — the diagram from [plan_overview.md](plan_overview.md), the task state machine, a short
   explanation of the transactional outbox and why the relay depends only on the database.
6. **Configuration** — table: env var, default, description (all `Settings` fields).
7. **Tests** — `uv run pytest`; what the four test groups cover and that the real model is checked manually.
8. **Design decisions** — link to [docs/design-decisions.md](../docs/design-decisions.md).
9. **Next steps** — crash recovery + retries, summarization via Ollama, Postgres/SQLAlchemy/Alembic, broker +
   separate worker containers, relay wake-up, CI, friendlier frontend, true streaming upload limit.
- Commit: `Rewrite README`.

## Deliverables

| Artifact | Description |
|---|---|
| `README.md` | Rewritten project documentation |

## References

### Internal

- [plan_overview.md](plan_overview.md) — Architecture diagram, Steps
- [docs/design-decisions.md](../docs/design-decisions.md) — Later / next steps
- [step_01_project-setup.md](step_01_project-setup.md) — env vars
- [step_04_api.md](step_04_api.md) — endpoints and error codes
- [step_07_containerization.md](step_07_containerization.md) — Docker commands

### External

- Docker Compose CLI: https://docs.docker.com/reference/cli/docker/compose/

## Deviations from plan

- Fresh-clone check covered the local quick start only (`uv sync`, `uv run pytest`, `main.py`, upload → `done`),
  on port 8010 and with the model already in the Hugging Face cache. The Docker commands were not re-run from the
  clone. Why: the user's local server and the step 7 container were occupying port 8000, and the Docker commands
  are the same ones verified in step 7. `docker compose build --build-arg WHISPER_MODEL=base` was checked only for
  flag support, not built.
- README additions beyond the planned sections: a port-clash warning (found in step 7), the test fixture as a
  ready-made clip, the path-traversal test (step 3), and "remove the `av<19` pin" under next steps (step 6).
