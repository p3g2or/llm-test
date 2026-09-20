from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.storage.blob import ContainerClient
from fieldnotes.azure_repository import AzureNoteRepository
from fieldnotes.models import Category, Note
from fieldnotes.repository import NoteNotFound, StorageUnavailable

NOTE = Note(
    id=UUID(int=1),
    title="Title",
    body="Body",
    category=Category.WORK,
    created_at=datetime(2026, 1, 1, tzinfo=UTC),
)
NAME = f"notes/{NOTE.id}.json"


def missing(code: str = "BlobNotFound") -> ResourceNotFoundError:
    error = ResourceNotFoundError("not found")
    error.error_code = code
    return error


def test_blob_round_trip_and_client_contract() -> None:
    container = MagicMock(spec=ContainerClient)
    repository = AzureNoteRepository(container)
    repository.add(NOTE)
    kwargs = container.upload_blob.call_args.kwargs
    assert kwargs["name"] == NAME
    assert kwargs["overwrite"] is False
    assert kwargs["content_settings"].content_type == "application/json"
    assert Note.model_validate_json(kwargs["data"]) == NOTE
    container.download_blob.return_value.readall.return_value = kwargs["data"]
    assert repository.get(NOTE.id) == NOTE
    container.download_blob.assert_called_with(NAME)
    blob = MagicMock()
    blob.name = NAME
    container.list_blobs.return_value = [blob]
    assert repository.list() == [NOTE]
    container.list_blobs.assert_called_once_with(name_starts_with="notes/")
    repository.delete(NOTE.id)
    container.delete_blob.assert_called_once_with(NAME)


@pytest.mark.parametrize("operation", ["get", "delete"])
@pytest.mark.parametrize(
    "code,expected",
    [
        ("BlobNotFound", NoteNotFound),
        ("ContainerNotFound", StorageUnavailable),
    ],
)
def test_missing_blob_differs_from_missing_container(operation, code, expected) -> None:
    container = MagicMock(spec=ContainerClient)
    container.download_blob.side_effect = missing(code)
    container.delete_blob.side_effect = missing(code)
    with pytest.raises(expected):
        getattr(AzureNoteRepository(container), operation)(NOTE.id)


def test_list_tolerates_concurrent_deletion_but_not_corrupt_data() -> None:
    container = MagicMock(spec=ContainerClient)
    container.list_blobs.return_value = [MagicMock(), MagicMock()]
    payload = MagicMock()
    payload.readall.return_value = NOTE.model_dump_json().encode()
    container.download_blob.side_effect = [missing(), payload]
    assert AzureNoteRepository(container).list() == [NOTE]
    container.download_blob.side_effect = None
    container.download_blob.return_value.readall.return_value = b"not json"
    with pytest.raises(StorageUnavailable):
        AzureNoteRepository(container).list()


@pytest.mark.parametrize("operation", ["list", "get", "add", "delete"])
def test_azure_errors_are_translated(operation: str) -> None:
    container = MagicMock(spec=ContainerClient)
    for method in ("list_blobs", "download_blob", "upload_blob", "delete_blob"):
        getattr(container, method).side_effect = HttpResponseError("upstream details")
    args = [] if operation == "list" else [NOTE if operation == "add" else NOTE.id]
    with pytest.raises(StorageUnavailable):
        getattr(AzureNoteRepository(container), operation)(*args)
