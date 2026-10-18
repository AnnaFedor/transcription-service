import io

import pytest

from app.storage import FileStorage


@pytest.mark.parametrize(
    ("original_filename", "expected_name"),
    [
        ("../../etc/passwd", "task-1"),
        ("../../evil.wav", "task-1.wav"),
        ("a.b.MP3", "task-1.mp3"),
        ("weird.ext$%", "task-1"),
        ("noext", "task-1"),
    ],
)
def test_save_keeps_files_inside_uploads(tmp_path, original_filename, expected_name):
    storage = FileStorage(tmp_path)

    relative = storage.save("task-1", original_filename, io.BytesIO(b"data"), max_bytes=1024)

    assert relative == f"uploads/{expected_name}"
    stored = storage.absolute(relative).resolve()
    assert stored.parent == (tmp_path / "uploads").resolve()
    assert stored.read_bytes() == b"data"
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == [expected_name]
