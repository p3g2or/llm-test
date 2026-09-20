from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from fieldnotes.config import Settings
from fieldnotes.main import create_app
from fieldnotes.repository import MemoryNoteRepository


@pytest.fixture
def repository() -> MemoryNoteRepository:
    return MemoryNoteRepository()


@pytest.fixture
def client(repository: MemoryNoteRepository) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(board_title="Test Notes"), repository)) as client:
        yield client
