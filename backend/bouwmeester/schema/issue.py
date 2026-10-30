"""Pydantic schemas voor Issue (een onderzoeksvraag of ander issue op een casus)."""

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bouwmeester.schema.task import TaskAssigneeSummary


class IssueStatus(enum.StrEnum):
    open = "open"
    in_progress = "in_progress"
    done = "done"


class IssueCreate(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    toelichting: str | None = Field(None, max_length=10000)
    status: IssueStatus = IssueStatus.open
    is_onderzoeksvraag: bool = True
    assignee_id: UUID | None = None


class IssueUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=1000)
    toelichting: str | None = Field(None, max_length=10000)
    status: IssueStatus | None = None
    is_onderzoeksvraag: bool | None = None
    assignee_id: UUID | None = None
    # Verhuizen naar een andere casus van hetzelfde initiatief; de taken
    # eronder gaan mee.
    casus_id: UUID | None = None
    # Afgevinkte DoD-eisen bij het afronden; de tekst van elke eis.
    dod_checked: list[str] | None = Field(None, max_length=50)


class IssueReorder(BaseModel):
    issue_ids: list[UUID]


class IssueResponse(BaseModel):
    id: UUID
    casus_id: UUID
    title: str
    toelichting: str | None = None
    status: IssueStatus
    is_onderzoeksvraag: bool = True
    assignee_id: UUID | None = None
    assignee: TaskAssigneeSummary | None = None
    sort_order: int = 0
    dod_checked: list[str] = Field(default_factory=list)
    task_count: int = 0
    task_done_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
