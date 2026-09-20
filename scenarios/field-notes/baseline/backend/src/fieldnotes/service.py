from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fieldnotes.models import Category, NewNote, Note, Summary
from fieldnotes.repository import NoteRepository


class NoteService:
    def __init__(
        self,
        repository: NoteRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_id: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository = repository
        self._clock = clock
        self._new_id = new_id

    def create(self, draft: NewNote) -> Note:
        note = Note(**draft.model_dump(), id=self._new_id(), created_at=self._clock())
        self.repository.add(note)
        return note

    def list(self, category: Category | None = None, query: str = "") -> list[Note]:
        query = query.strip().casefold()
        notes = [
            note
            for note in self.repository.list()
            if (category is None or note.category == category)
            and (query in note.title.casefold() or query in note.body.casefold())
        ]
        return sorted(notes, key=lambda note: (note.created_at, str(note.id)), reverse=True)

    def get(self, note_id: UUID) -> Note:
        return self.repository.get(note_id)

    def delete(self, note_id: UUID) -> None:
        self.repository.delete(note_id)

    def summary(self) -> Summary:
        notes = self.repository.list()
        counts = {category: 0 for category in Category}
        for note in notes:
            counts[note.category] += 1
        return Summary(total=len(notes), by_category=counts)
