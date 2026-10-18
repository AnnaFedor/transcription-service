"""Local file storage for uploads under DATA_DIR/uploads."""

import re
from pathlib import Path, PurePosixPath
from typing import BinaryIO

UPLOADS_DIR = "uploads"  # part of the relative paths stored in the database; changing it breaks existing rows
CHUNK_SIZE = 1024 * 1024
_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")


class FileTooLarge(Exception):
    """Raised when an upload exceeds the configured size limit."""


class FileStorage:
    """Stores uploads as `uploads/{task_id}{ext}`; the user's filename never becomes part of the path."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def save(self, task_id: str, original_filename: str, source: BinaryIO, max_bytes: int) -> str:
        """Copy `source` to disk in chunks and return the path relative to `data_dir`.

        Raises FileTooLarge (and removes the partial file) once more than `max_bytes` were read.
        """
        relative = PurePosixPath(UPLOADS_DIR) / f"{task_id}{_safe_extension(original_filename)}"
        target = self.absolute(str(relative))
        target.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        try:
            with target.open("wb") as out:
                while chunk := source.read(CHUNK_SIZE):
                    written += len(chunk)
                    if written > max_bytes:
                        raise FileTooLarge(f"upload exceeds {max_bytes} bytes")
                    out.write(chunk)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return str(relative)

    def absolute(self, relative: str) -> Path:
        return self.data_dir / relative

    def delete(self, relative: str) -> None:
        """Remove a stored file; does nothing if it is already gone."""
        self.absolute(relative).unlink(missing_ok=True)


def _safe_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if _SAFE_EXTENSION.match(suffix) else ""
