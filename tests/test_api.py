from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def upload(client, path: Path, **form):
    with path.open("rb") as f:
        return client.post("/transcriptions", files={"file": (path.name, f)}, data=form)


def uploaded_files(tmp_path):
    uploads = tmp_path / "uploads"
    return list(uploads.iterdir()) if uploads.exists() else []


def task_count(repository):
    return repository._conn().execute("SELECT COUNT(*) FROM tasks").fetchone()[0]


@pytest.mark.parametrize("source", ["generated_wav", "real_mp4"])
def test_upload_valid_clip(client, repository, storage, make_wav, source):
    path = make_wav(2) if source == "generated_wav" else FIXTURES / "honigbienen_de.mp4"

    response = upload(client, path)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    task = repository.get(body["task_id"])
    assert task is not None
    assert task.language == "de"
    assert task.original_filename == path.name
    assert storage.absolute(task.file_path).is_file()


def test_upload_too_large(client, repository, make_wav, tmp_path):
    response = upload(client, make_wav(40))

    assert response.status_code == 413
    assert task_count(repository) == 0
    assert uploaded_files(tmp_path) == []


def test_upload_non_media(client, repository, tmp_path):
    notes = tmp_path / "notes.mp3"
    notes.write_text("this is not audio")

    response = upload(client, notes)

    assert response.status_code == 422
    assert "audio" in response.json()["detail"]
    assert task_count(repository) == 0
    assert uploaded_files(tmp_path) == []


def test_upload_too_long(client, repository, make_wav, tmp_path):
    response = upload(client, make_wav(25))

    assert response.status_code == 422
    assert "20s" in response.json()["detail"]
    assert task_count(repository) == 0
    assert uploaded_files(tmp_path) == []
