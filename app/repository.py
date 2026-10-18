"""SQLite persistence for transcription tasks and the transactional outbox."""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
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
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    created_at TEXT NOT NULL,
    dispatched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_undispatched ON outbox(dispatched_at, id);
"""


class TaskStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class InvalidTransition(Exception):
    """Raised when a task is not in a state that allows the requested transition."""


@dataclass(frozen=True)
class Task:
    id: str
    task_type: str
    status: TaskStatus
    language: str
    summarize: bool
    original_filename: str
    file_path: str | None
    result_json: str | None
    error: str | None
    attempts: int
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Task":
        return cls(
            id=row["id"],
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            language=row["language"],
            summarize=bool(row["summarize"]),
            original_filename=row["original_filename"],
            file_path=row["file_path"],
            result_json=row["result_json"],
            error=row["error"],
            attempts=row["attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True)
class OutboxEntry:
    id: int
    task_id: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TaskRepository:
    """SQLite persistence for tasks and the outbox. Safe to share between threads: one connection per thread."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def init_schema(self) -> None:
        """Create tables and indexes if missing; safe to call on every startup."""
        self._conn().executescript(SCHEMA)

    def create_task(
        self, task_id: str, original_filename: str, file_path: str, language: str, summarize: bool
    ) -> Task:
        """Insert a `pending` task and its outbox entry atomically: both rows are written or neither."""
        now = _now()
        conn = self._conn()
        with conn:
            conn.execute(
                "INSERT INTO tasks (id, status, language, summarize, original_filename, file_path, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, TaskStatus.PENDING, language, int(summarize), original_filename, file_path, now, now),
            )
            conn.execute("INSERT INTO outbox (task_id, created_at) VALUES (?, ?)", (task_id, now))
        return self.get(task_id)

    def get(self, task_id: str) -> Task | None:
        row = self._conn().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return Task.from_row(row) if row else None

    def fetch_undispatched(self, limit: int = 10) -> list[OutboxEntry]:
        """Return outbox entries not yet handed to the queue, oldest first."""
        rows = self._conn().execute(
            "SELECT id, task_id FROM outbox WHERE dispatched_at IS NULL ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
        return [OutboxEntry(id=row["id"], task_id=row["task_id"]) for row in rows]

    # State transitions: each UPDATE only matches if the task is in an allowed source status,
    # otherwise InvalidTransition is raised and nothing changes.

    def mark_queued(self, outbox_id: int, task_id: str) -> None:
        """`pending → queued`; marks the outbox entry dispatched in the same transaction."""
        conn = self._conn()
        with conn:
            conn.execute("UPDATE outbox SET dispatched_at = ? WHERE id = ?", (_now(), outbox_id))
            cursor = conn.execute(
                "UPDATE tasks SET status = 'queued', updated_at = ?"
                " WHERE id = ? AND status = 'pending'",
                (_now(), task_id),
            )
            _ensure_updated(cursor, task_id, TaskStatus.QUEUED)

    def mark_processing(self, task_id: str) -> Task:
        """`queued → processing`; increments `attempts` and returns the updated task."""
        conn = self._conn()
        with conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'processing', attempts = attempts + 1, updated_at = ?"
                " WHERE id = ? AND status = 'queued'",
                (_now(), task_id),
            )
            _ensure_updated(cursor, task_id, TaskStatus.PROCESSING)
        return self.get(task_id)

    def mark_done(self, task_id: str, result_json: str) -> None:
        """`processing → done`; stores the transcription result."""
        conn = self._conn()
        with conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'done', result_json = ?, error = NULL, updated_at = ?"
                " WHERE id = ? AND status = 'processing'",
                (result_json, _now(), task_id),
            )
            _ensure_updated(cursor, task_id, TaskStatus.DONE)

    def mark_failed(self, task_id: str, error: str) -> None:
        """`queued | processing → failed`; stores the error message."""
        conn = self._conn()
        with conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'failed', error = ?, updated_at = ?"
                " WHERE id = ? AND status IN ('queued', 'processing')",
                (error, _now(), task_id),
            )
            _ensure_updated(cursor, task_id, TaskStatus.FAILED)

    def clear_file_path(self, task_id: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute("UPDATE tasks SET file_path = NULL, updated_at = ? WHERE id = ?", (_now(), task_id))


def _ensure_updated(cursor: sqlite3.Cursor, task_id: str, to_status: TaskStatus) -> None:
    if cursor.rowcount == 0:
        raise InvalidTransition(f"task {task_id} cannot move to {to_status} from its current status")
