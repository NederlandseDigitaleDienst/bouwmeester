"""Pydantic schemas voor opmerkingen en bijlagen op een taak."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskCommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=50000)


class TaskCommentResponse(BaseModel):
    id: UUID
    task_id: UUID
    author_id: UUID | None = None
    author_naam: str | None = None
    content: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _fill_author_naam(cls, data: Any) -> Any:
        # Zelfde kunstgreep als LeadActivityResponse: de naam komt uit de
        # relationship, het ORM-object heeft geen kolom author_naam.
        author = getattr(data, "author", None)
        if author is not None and not getattr(data, "author_naam", None):
            try:
                data.author_naam = author.naam
            except AttributeError:
                pass
        return data


class TaskAttachmentResponse(BaseModel):
    id: UUID
    task_id: UUID
    bestandsnaam: str
    content_type: str | None = None
    bestandsgrootte: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
