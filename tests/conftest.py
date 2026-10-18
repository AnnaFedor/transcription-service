import pytest

from app.repository import TaskRepository


@pytest.fixture
def repository(tmp_path):
    repo = TaskRepository(tmp_path / "db" / "app.sqlite")
    repo.init_schema()
    return repo
