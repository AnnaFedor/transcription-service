import sqlite3

import pytest

from app.repository import TaskStatus


def create(repository, task_id="task-1", **overrides):
    params = {
        "task_id": task_id,
        "original_filename": "clip.wav",
        "file_path": f"uploads/{task_id}.wav",
        "language": "de",
        "summarize": False,
    }
    params.update(overrides)
    return repository.create_task(**params)


def outbox_count(repository):
    return repository._conn().execute("SELECT COUNT(*) FROM outbox").fetchone()[0]


def test_create_task_writes_task_and_outbox(repository):
    create(repository, "task-1", language="auto", summarize=True, original_filename="meeting.mp4",
           file_path="uploads/task-1.mp4")

    task = repository.get("task-1")
    assert task is not None
    assert task.status == TaskStatus.PENDING
    assert task.attempts == 0
    assert task.language == "auto"
    assert task.summarize is True
    assert task.original_filename == "meeting.mp4"
    assert task.file_path == "uploads/task-1.mp4"

    entries = repository.fetch_undispatched()
    assert [e.task_id for e in entries] == ["task-1"]


def test_create_task_is_atomic(repository):
    create(repository, "task-1")
    # Make the second insert (outbox) fail after the first (task) succeeded.
    repository._conn().execute(
        "CREATE TRIGGER fail_outbox BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'outbox down'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        create(repository, "task-2")

    assert repository.get("task-2") is None
    assert outbox_count(repository) == 1


def test_mark_queued_dispatches_outbox_entry(repository):
    create(repository, "task-1")
    create(repository, "task-2")

    entries = repository.fetch_undispatched()
    assert [e.task_id for e in entries] == ["task-1", "task-2"]

    repository.mark_queued(entries[0].id, entries[0].task_id)

    assert repository.get("task-1").status == TaskStatus.QUEUED
    assert [e.task_id for e in repository.fetch_undispatched()] == ["task-2"]
