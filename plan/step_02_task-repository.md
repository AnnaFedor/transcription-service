# Step 2 — TaskRepository and SQLite schema

## Goal

Implement the persistence layer: a `TaskRepository` on plain `sqlite3` that owns the schema (tasks + outbox) and
offers one method per state transition. Creating a task writes the task row and its outbox row in one transaction,
which is the core of the transactional outbox pattern.

## Prerequisites

- Step 1 done: `Settings` with `db_path`, pytest running.

## Tests (written first)

This project follows a test driven development.  
The following tests are therefore written first and confirmed red before continuing with the implementation.

Fixture in `tests/conftest.py`: `repository(tmp_path)` → `TaskRepository(tmp_path / "db" / "app.sqlite")` with
`init_schema()` called.

Test group 1 of 4 (repository). `tests/test_repository.py`:

| Test | Expected |
|---|---|
| `test_create_task_writes_task_and_outbox` | After `create_task(...)`: `get(id)` returns a `Task` with `status == "pending"`, `attempts == 0`, given `language`, `summarize`, `original_filename`, `file_path`; `fetch_undispatched()` returns exactly one entry for that task |
| `test_create_task_is_atomic` | Creating a second task with an already used `task_id` raises `sqlite3.IntegrityError`, and the outbox still contains exactly one row (no orphan outbox row from the failed transaction) |
| `test_mark_queued_dispatches_outbox_entry` | Two tasks created; `fetch_undispatched()` returns them in creation order; after `mark_queued(outbox_id, task_id)` for the first, its status is `queued` and `fetch_undispatched()` returns only the second |

The remaining transitions (`mark_processing`, `mark_done`, `mark_failed`, `clear_file_path`) are covered by the
pipeline tests in step 5.

Red state: `ImportError` for `app.repository`.

## Implementation details

`app/repository.py`:

- Schema (`CREATE TABLE IF NOT EXISTS`):
  ```sql
  tasks(
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL DEFAULT 'transcription',
    status TEXT NOT NULL,
    language TEXT NOT NULL,
    summarize INTEGER NOT NULL DEFAULT 0,
    original_filename TEXT NOT NULL,
    file_path TEXT,
    result_json TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )
  outbox(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    created_at TEXT NOT NULL,
    dispatched_at TEXT
  )
  CREATE INDEX IF NOT EXISTS idx_outbox_undispatched ON outbox(dispatched_at, id)
  ```
  `task_type` and `attempts` exist now so summarization and crash recovery need no migration.
- `@dataclass(frozen=True) class Task` and `class OutboxEntry(id, task_id)`; `class InvalidTransition(Exception)`.
- Status constants: `PENDING`, `QUEUED`, `PROCESSING`, `DONE`, `FAILED` (a `StrEnum`).
- Connections: `threading.local()` holds one `sqlite3.Connection` per thread, created lazily with
  `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `PRAGMA foreign_keys=ON`, `row_factory = sqlite3.Row`.
  The parent directory of `db_path` is created on first connect.
- Transactions via `with conn:` (commit on success, rollback on exception).
- Methods:
  - `init_schema()`
  - `create_task(task_id, original_filename, file_path, language, summarize) -> Task` — inserts task (`pending`)
    and outbox row in one transaction.
  - `get(task_id) -> Task | None`
  - `fetch_undispatched(limit=10) -> list[OutboxEntry]` — `WHERE dispatched_at IS NULL ORDER BY id LIMIT ?`
  - `mark_queued(outbox_id, task_id)` — one transaction: set `dispatched_at`, task `pending → queued`.
  - `mark_processing(task_id)` — `queued → processing`, `attempts = attempts + 1`.
  - `mark_done(task_id, result_json)` — `processing → done`.
  - `mark_failed(task_id, error)` — `processing → failed` (also allowed from `queued`, for errors before processing starts).
  - `clear_file_path(task_id)`
- Transition guard: `UPDATE ... WHERE id = ? AND status IN (...)`; `rowcount == 0` → `InvalidTransition`.
- Timestamps: `datetime.now(UTC).isoformat()`.
- Commit: `Add TaskRepository with tasks and outbox tables`.

## Deliverables

| Artifact | Description |
|---|---|
| `app/repository.py` | `TaskRepository`, `Task`, `OutboxEntry`, `TaskStatus`, `InvalidTransition` |
| `tests/conftest.py` | `repository` fixture |
| `tests/test_repository.py` | Repository tests |

## References

### Internal

- [plan_overview.md](plan_overview.md) — Architecture, Decisions (#10, #11, #14)
- [docs/design-decisions.md](../docs/design-decisions.md) — Task lifecycle & outbox, Storage & data
- [step_01_project-setup.md](step_01_project-setup.md) — `Settings.db_path`

### External

- Python `sqlite3`: https://docs.python.org/3/library/sqlite3.html
- SQLite WAL mode: https://www.sqlite.org/wal.html
- Transactional outbox pattern: https://microservices.io/patterns/data/transactional-outbox.html

## Deviations from plan

