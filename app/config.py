from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, read from environment variables (upper-case field names) or `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    max_upload_mb: int = 25
    max_duration_seconds: float = 20
    relay_poll_interval: float = 1.0
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_download_root: Path | None = None
    default_language: str = "de"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "app.sqlite"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024
