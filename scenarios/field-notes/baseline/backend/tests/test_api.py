from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from fieldnotes.models import BODY_LIMIT, TITLE_LIMIT
from fieldnotes.repository import MemoryNoteRepository, StorageUnavailable

DRAFT = {"title": " Release checklist ", "body": " Review deployment ", "category": "work"}


def test_note_lifecycle(client: TestClient) -> None:
    assert client.get("/api/notes").json() == []
    created = client.post("/api/notes", json=DRAFT)
    assert created.status_code == 201
    note = created.json()
    assert UUID(note["id"])
    assert note["title"] == "Release checklist"
    assert note["body"] == "Review deployment"
    assert note["created_at"].endswith("Z")
    location = created.headers["location"]
    assert client.get(location).json() == note
    assert client.get("/api/notes").json() == [note]
    assert client.get("/api/summary").json() == {
        "total": 1,
        "by_category": {"work": 1, "personal": 0, "ideas": 0},
    }
    assert client.delete(location).status_code == 204
    assert client.delete(location).status_code == 404
    assert client.get(location).status_code == 404
    assert client.get("/api/summary").json()["total"] == 0


def test_filters_and_query_validation(client: TestClient) -> None:
    client.post("/api/notes", json=DRAFT)
    client.post("/api/notes", json={**DRAFT, "title": "A thought", "category": "ideas"})
    result = client.get("/api/notes", params={"category": "work", "q": "DEPLOY"}).json()
    assert len(result) == 1
    assert result[0]["category"] == "work"
    assert client.get("/api/notes", params={"q": "missing"}).json() == []
    assert client.get("/api/notes?category=unknown").status_code == 422
    assert client.get("/api/notes", params={"q": "x" * 101}).status_code == 422
    assert client.get("/api/notes/not-a-uuid").status_code == 422


@pytest.mark.parametrize(
    "patch",
    [
        {"title": " "},
        {"body": "\n"},
        {"category": "invalid"},
        {"title": "x" * (TITLE_LIMIT + 1)},
        {"body": "x" * (BODY_LIMIT + 1)},
        {"unexpected": "field"},
        {"title": None},
    ],
)
def test_invalid_note_does_not_write(client: TestClient, patch: dict[str, object]) -> None:
    assert client.post("/api/notes", json={**DRAFT, **patch}).status_code == 422
    assert client.get("/api/notes").json() == []


def test_limits_and_public_configuration(client: TestClient) -> None:
    config = client.get("/api/config").json()
    assert config == {
        "board_title": "Test Notes",
        "title_limit": TITLE_LIMIT,
        "body_limit": BODY_LIMIT,
        "categories": ["work", "personal", "ideas"],
    }
    assert (
        client.post(
            "/api/notes",
            json={
                "title": "x" * config["title_limit"],
                "body": "y" * config["body_limit"],
                "category": config["categories"][0],
            },
        ).status_code
        == 201
    )


def test_storage_failure_is_sanitized(
    client: TestClient, repository: MemoryNoteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> None:
        raise StorageUnavailable("sensitive upstream details")

    monkeypatch.setattr(repository, "list", unavailable)
    response = client.get("/api/notes")
    assert response.status_code == 503
    assert response.json() == {"detail": "Note storage is unavailable"}
    assert client.get("/api/health").json() == {"status": "ok"}
