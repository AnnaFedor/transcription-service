"""HTTP API: upload a clip, poll its status, fetch the transcript as JSON or TXT."""

import json
import re
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import media
from app.config import Settings
from app.repository import TaskRepository, TaskStatus
from app.storage import FileStorage, FileTooLarge

LANGUAGE_PATTERN = re.compile(r"^(auto|[a-z]{2,3})$")
MULTIPART_OVERHEAD_BYTES = 64 * 1024  # headroom for multipart boundaries and form fields in Content-Length


class TaskCreated(BaseModel):
    task_id: str
    status: TaskStatus


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    error: str | None
    created_at: str
    updated_at: str


class Segment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionResponse(BaseModel):
    text: str
    segments: list[Segment]
    language: str
    duration: float


def create_app(settings: Settings, repository: TaskRepository, storage: FileStorage) -> FastAPI:
    """Build the FastAPI app around injected components (no background threads are started here)."""
    app = FastAPI(
        title="Transcription Service",
        description=(
            "Upload a short audio/video clip, then poll `GET /transcriptions/{task_id}` until the status is "
            "`done` and fetch the transcript from `/result`."
        ),
    )

    @app.post("/transcriptions", status_code=status.HTTP_202_ACCEPTED, response_model=TaskCreated)
    def create_transcription(
        request: Request,
        file: UploadFile = File(...),
        language: str = Form(settings.default_language, description="ISO code such as `de`, or `auto` to detect"),
        summarize: bool = Form(False, description="Accepted, not yet implemented"),
    ) -> TaskCreated:
        if not LANGUAGE_PATTERN.match(language):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "language must be 'auto' or an ISO code like 'de'")

        content_length = int(request.headers.get("content-length", 0))
        if content_length > settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES:
            raise _too_large(settings)

        task_id = str(uuid4())
        try:
            file_path = storage.save(task_id, file.filename or "", file.file, settings.max_upload_bytes)
        except FileTooLarge:
            raise _too_large(settings)

        try:
            media.validate(storage.absolute(file_path), settings.max_duration_seconds)
            repository.create_task(task_id, file.filename or "", file_path, language, summarize)
        except (media.InvalidMedia, media.MediaTooLong) as exc:
            storage.delete(file_path)
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
        except BaseException:
            storage.delete(file_path)
            raise
        return TaskCreated(task_id=task_id, status=TaskStatus.PENDING)

    @app.get("/transcriptions/{task_id}", response_model=TaskStatusResponse)
    def get_transcription_status(task_id: str) -> TaskStatusResponse:
        task = _get_or_404(repository, task_id)
        return TaskStatusResponse(
            task_id=task.id, status=task.status, error=task.error,
            created_at=task.created_at, updated_at=task.updated_at,
        )

    @app.get(
        "/transcriptions/{task_id}/result",
        response_model=TranscriptionResponse,
        responses={200: {"content": {"text/plain": {}}}},
    )
    def get_transcription_result(task_id: str, format: Literal["json", "txt"] = "json"):
        task = _get_or_404(repository, task_id)
        if task.status != TaskStatus.DONE:
            detail = f"task is {task.status}" + (f": {task.error}" if task.error else "")
            raise HTTPException(status.HTTP_409_CONFLICT, detail)

        result = TranscriptionResponse(**json.loads(task.result_json))
        if format == "txt":
            stem = re.sub(r"[^A-Za-z0-9._-]", "_", task.original_filename.rsplit(".", 1)[0]) or "transcript"
            return PlainTextResponse(
                result.text, headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'}
            )
        return result

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _get_or_404(repository: TaskRepository, task_id: str):
    task = repository.get(task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return task


def _too_large(settings: Settings) -> HTTPException:
    return HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"file exceeds {settings.max_upload_mb} MB")
