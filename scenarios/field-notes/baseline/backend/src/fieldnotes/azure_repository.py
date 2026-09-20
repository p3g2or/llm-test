from uuid import UUID

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.storage.blob import ContainerClient, ContentSettings
from pydantic import ValidationError

from fieldnotes.models import Note
from fieldnotes.repository import NoteNotFound, StorageUnavailable


class AzureNoteRepository:
    """One immutable JSON blob per note; the container is provisioned by Terraform."""

    def __init__(self, container: ContainerClient) -> None:
        self._container = container

    @staticmethod
    def _name(note_id: UUID) -> str:
        return f"notes/{note_id}.json"

    def list(self) -> list[Note]:
        notes = []
        try:
            for blob in self._container.list_blobs(name_starts_with="notes/"):
                try:
                    payload = self._container.download_blob(blob.name).readall()
                except ResourceNotFoundError as exc:
                    if getattr(exc, "error_code", None) == "BlobNotFound":
                        # A concurrent delete may remove a blob after it was listed.
                        continue
                    raise
                notes.append(Note.model_validate_json(payload))
            return notes
        except (AzureError, ValidationError) as exc:
            raise StorageUnavailable from exc

    def get(self, note_id: UUID) -> Note:
        try:
            payload = self._container.download_blob(self._name(note_id)).readall()
            return Note.model_validate_json(payload)
        except ResourceNotFoundError as exc:
            if getattr(exc, "error_code", None) == "BlobNotFound":
                raise NoteNotFound from exc
            raise StorageUnavailable from exc
        except (AzureError, ValidationError) as exc:
            raise StorageUnavailable from exc

    def add(self, note: Note) -> None:
        try:
            self._container.upload_blob(
                name=self._name(note.id),
                data=note.model_dump_json().encode("utf-8"),
                overwrite=False,
                content_settings=ContentSettings(content_type="application/json"),
            )
        except AzureError as exc:
            raise StorageUnavailable from exc

    def delete(self, note_id: UUID) -> None:
        try:
            self._container.delete_blob(self._name(note_id))
        except ResourceNotFoundError as exc:
            if getattr(exc, "error_code", None) == "BlobNotFound":
                raise NoteNotFound from exc
            raise StorageUnavailable from exc
        except AzureError as exc:
            raise StorageUnavailable from exc
