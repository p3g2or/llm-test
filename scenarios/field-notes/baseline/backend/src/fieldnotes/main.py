from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from fieldnotes.azure_repository import AzureNoteRepository
from fieldnotes.config import Settings
from fieldnotes.models import Category, NewNote, Note, PublicConfig, Summary
from fieldnotes.repository import (
    MemoryNoteRepository,
    NoteNotFound,
    NoteRepository,
    StorageUnavailable,
)
from fieldnotes.service import NoteService


def create_app(
    settings: Settings | None = None, repository: NoteRepository | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if repository is not None:
            app.state.notes = NoteService(repository)
            yield
        elif settings.storage_backend == "memory":
            app.state.notes = NoteService(MemoryNoteRepository())
            yield
        else:
            with (
                DefaultAzureCredential() as credential,
                ContainerClient(
                    account_url=settings.azure_storage_account_url,
                    container_name=settings.azure_storage_container,
                    credential=credential,
                ) as container,
            ):
                app.state.notes = NoteService(AzureNoteRepository(container))
                yield

    app = FastAPI(title="Field Notes API", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(NoteNotFound)
    async def not_found(request: Request, exc: NoteNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Note not found"})

    @app.exception_handler(StorageUnavailable)
    async def unavailable(request: Request, exc: StorageUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Note storage is unavailable"})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config", response_model=PublicConfig)
    def config() -> PublicConfig:
        return PublicConfig(board_title=settings.board_title)

    @app.get("/api/notes", response_model=list[Note])
    def list_notes(
        request: Request,
        category: Category | None = None,
        q: Annotated[str, Query(max_length=100)] = "",
    ) -> list[Note]:
        service: NoteService = request.app.state.notes
        return service.list(category, q)

    @app.post("/api/notes", response_model=Note, status_code=201)
    def create_note(draft: NewNote, request: Request, response: Response) -> Note:
        service: NoteService = request.app.state.notes
        note = service.create(draft)
        response.headers["Location"] = f"/api/notes/{note.id}"
        return note

    @app.get("/api/notes/{note_id}", response_model=Note)
    def get_note(note_id: UUID, request: Request) -> Note:
        service: NoteService = request.app.state.notes
        return service.get(note_id)

    @app.delete("/api/notes/{note_id}", status_code=204)
    def delete_note(note_id: UUID, request: Request) -> Response:
        service: NoteService = request.app.state.notes
        service.delete(note_id)
        return Response(status_code=204)

    @app.get("/api/summary", response_model=Summary)
    def summary(request: Request) -> Summary:
        service: NoteService = request.app.state.notes
        return service.summary()

    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")

    return app


app = create_app()
