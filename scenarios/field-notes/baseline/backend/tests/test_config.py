from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fieldnotes.config import Settings
from fieldnotes.main import create_app


def test_environment_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "azure")
    monkeypatch.setenv("BOARD_TITLE", " Team Notes ")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://examplenotes.blob.core.windows.net/")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "team-notes")
    settings = Settings.from_env()
    assert settings.storage_backend == "azure"
    assert settings.board_title == "Team Notes"
    assert settings.azure_storage_container == "team-notes"


@pytest.mark.parametrize(
    "variable,value",
    [
        ("STORAGE_BACKEND", "typo"),
        ("BOARD_TITLE", " "),
        ("BOARD_TITLE", "x" * 81),
        ("AZURE_STORAGE_ACCOUNT_URL", "http://insecure.example"),
        ("AZURE_STORAGE_CONTAINER", "Bad--Name"),
    ],
)
def test_invalid_configuration_fails_fast(monkeypatch, variable, value) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "azure")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://examplenotes.blob.core.windows.net/")
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_serves_frontend_without_shadowing_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Notebook</h1>")
    with TestClient(create_app(Settings(static_dir=tmp_path))) as client:
        assert client.get("/").text == "<h1>Notebook</h1>"
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/unknown").status_code == 404


def test_default_memory_storage_is_isolated_per_app() -> None:
    with TestClient(create_app(Settings())) as first, TestClient(create_app(Settings())) as second:
        first.post("/api/notes", json={"title": "One", "body": "Two", "category": "work"})
        assert second.get("/api/notes").json() == []
