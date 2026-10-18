import time


def upload_and_wait(client, path, final_statuses=("done", "failed"), timeout=5.0):
    with path.open("rb") as f:
        response = client.post("/transcriptions", files={"file": (path.name, f)})
    assert response.status_code == 202
    task_id = response.json()["task_id"]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/transcriptions/{task_id}").json()
        if status["status"] in final_statuses:
            return task_id, status
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish within {timeout}s, last status: {status}")


def test_end_to_end_pipeline(pipeline, repository, storage, make_wav):
    client = pipeline.client

    task_id, status = upload_and_wait(client, make_wav(2))

    assert status["status"] == "done"
    result = client.get(f"/transcriptions/{task_id}/result?format=json")
    assert result.status_code == 200
    assert result.json() == {
        "text": "Hallo Welt",
        "segments": [{"start": 0.0, "end": 1.5, "text": "Hallo Welt"}],
        "language": "de",
        "duration": 2.0,
    }
    txt = client.get(f"/transcriptions/{task_id}/result?format=txt")
    assert txt.headers["content-type"].startswith("text/plain")
    assert txt.text == "Hallo Welt"

    (uploaded_path, language), = pipeline.transcriber.calls
    assert language == "de"
    assert not uploaded_path.exists()
    assert repository.get(task_id).file_path is None


def test_worker_failure(pipeline, repository, make_wav):
    client = pipeline.client
    pipeline.transcriber.error = RuntimeError("decoder exploded")

    failed_id, status = upload_and_wait(client, make_wav(2, name="bad.wav"))

    assert status["status"] == "failed"
    assert "decoder exploded" in status["error"]
    (uploaded_path, _), = pipeline.transcriber.calls
    assert not uploaded_path.exists()
    assert repository.get(failed_id).file_path is None
    assert pipeline.worker_thread.is_alive()

    pipeline.transcriber.error = None
    _, status = upload_and_wait(client, make_wav(2, name="good.wav"))
    assert status["status"] == "done"
