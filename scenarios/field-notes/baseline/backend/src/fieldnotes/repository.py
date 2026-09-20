from threading import Lock
from typing import Protocol
from uuid import UUID

from fieldnotes.models import Note


class NoteNotFound(Exception):
    pass


class StorageUnavailable(Exception):
    pass


class NoteRepository(Protocol):
    def list(self) -> list[Note]: ...
    def get(self, note_id: UUID) -> Note: ...
    def add(self, note: Note) -> None: ...
    def delete(self, note_id: UUID) -> None: ...


class MemoryNoteRepository:
    def __init__(self) -> None:
        self._notes: dict[UUID, Note] = {}
        self._lock = Lock()

    def list(self) -> list[Note]:
        with self._lock:
            return list(self._notes.values())

    def get(self, note_id: UUID) -> Note:
        with self._lock:
            try:
                return self._notes[note_id]
            except KeyError as exc:
                raise NoteNotFound from exc

    def add(self, note: Note) -> None:
        with self._lock:
            if note.id in self._notes:
                raise StorageUnavailable("Duplicate note ID")
            self._notes[note.id] = note

    def delete(self, note_id: UUID) -> None:
        with self._lock:
            try:
                del self._notes[note_id]
            except KeyError as exc:
                raise NoteNotFound from exc
