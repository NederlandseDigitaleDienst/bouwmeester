"""Pydantic schemas voor Issue (een onderzoeksvraag, in een casus of zonder)."""

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bouwmeester.schema.publieke_tekst import geen_verwijzingen, zonder_witruimte
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
    # eronder gaan mee. Uitdrukkelijk null: uit de casus, naar het initiatief.
    casus_id: UUID | None = None
    # Afgevinkte DoD-eisen bij het afronden; de tekst van elke eis.
    dod_checked: list[str] | None = Field(None, max_length=50)
    # Het antwoord, interne versie (rich text). Leeg of null wist het.
    antwoord: str | None = Field(None, max_length=20000)


class IssueReorder(BaseModel):
    issue_ids: list[UUID]


class IssuePubliek(BaseModel):
    """Een afgeronde onderzoeksvraag vrijgeven voor buiten.

    Alleen deze twee teksten gaan naar buiten; schrijf ze voor een lezer die
    de casus niet kent, zonder namen of interne details. Spaties eromheen
    gaan eraf vóór de lengtecontrole, dus alleen spaties is leeg. Een @- of
    #-verwijzing wordt geweigerd: die zet een naam, een taaktitel en een id
    in de publieke tekst.
    """

    public_title: str = Field(min_length=1, max_length=1000)
    public_answer: str = Field(min_length=1, max_length=5000)

    _strip = field_validator("public_title", "public_answer", mode="before")(
        zonder_witruimte
    )
    _verwijzingen = field_validator("public_title", "public_answer")(geen_verwijzingen)


class IssueResponse(BaseModel):
    id: UUID
    # Leeg: een vraag van het initiatief zonder casus.
    casus_id: UUID | None = None
    initiatief_id: UUID | None = None
    title: str
    toelichting: str | None = None
    status: IssueStatus
    is_onderzoeksvraag: bool = True
    assignee_id: UUID | None = None
    assignee: TaskAssigneeSummary | None = None
    sort_order: int = 0
    dod_checked: list[str] = Field(default_factory=list)
    antwoord: str | None = None
    task_count: int = 0
    task_done_count: int = 0
    # Naar buiten: de publieke tekst en wanneer vrijgegeven (leeg is binnen).
    public_title: str | None = None
    public_answer: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
