from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TITLE_LIMIT = 100
BODY_LIMIT = 4000


class Category(StrEnum):
    WORK = "work"
    PERSONAL = "personal"
    IDEAS = "ideas"


class NewNote(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1, max_length=TITLE_LIMIT)
    body: str = Field(min_length=1, max_length=BODY_LIMIT)
    category: Category


class Note(NewNote):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", frozen=True)

    id: UUID
    created_at: datetime


class Summary(BaseModel):
    total: int
    by_category: dict[Category, int]


class PublicConfig(BaseModel):
    board_title: str
    title_limit: int = TITLE_LIMIT
    body_limit: int = BODY_LIMIT
    categories: list[Category] = Field(default_factory=lambda: list(Category))
