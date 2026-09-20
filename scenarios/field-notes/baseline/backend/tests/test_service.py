from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fieldnotes.models import Category, NewNote
from fieldnotes.repository import MemoryNoteRepository, NoteNotFound, StorageUnavailable
from fieldnotes.service import NoteService


def test_stable_order_search_and_summary() -> None:
    ids = iter([UUID(int=1), UUID(int=2), UUID(int=3)])
    now = datetime(2026, 1, 1, tzinfo=UTC)
    times = iter([now, now, now + timedelta(days=1)])
    service = NoteService(MemoryNoteRepository(), lambda: next(times), lambda: next(ids))
    first = service.create(NewNote(title="Straße", body="Trip", category=Category.PERSONAL))
    second = service.create(NewNote(title="Sketch", body="A useful IDEA", category=Category.IDEAS))
    third = service.create(NewNote(title="Newer", body="Plan", category=Category.WORK))
    assert service.list() == [third, second, first]
    assert service.list(query=" STRASSE ") == [first]
    assert service.list(Category.IDEAS, "idea") == [second]
    assert service.list(Category.WORK, "idea") == []
    assert service.summary().total == 3
    service.delete(second.id)
    assert service.summary().by_category[Category.IDEAS] == 0
    with pytest.raises(NoteNotFound):
        service.get(second.id)


def test_repository_does_not_overwrite_existing_note() -> None:
    repository = MemoryNoteRepository()
    service = NoteService(repository, new_id=lambda: UUID(int=1))
    first = service.create(NewNote(title="One", body="Keep me", category=Category.WORK))
    with pytest.raises(StorageUnavailable):
        service.create(NewNote(title="Two", body="Duplicate", category=Category.WORK))
    assert repository.get(first.id) == first
    detached_list = repository.list()
    detached_list.clear()
    assert repository.list() == [first]
