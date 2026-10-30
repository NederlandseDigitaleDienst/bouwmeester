"""Pydantic schemas for Task."""

import enum
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskStatus(enum.StrEnum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


class TaskPriority(enum.StrEnum):
    laag = "laag"
    normaal = "normaal"
    hoog = "hoog"
    kritiek = "kritiek"


class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    node_id: UUID | None = None
    casus_id: UUID | None = None
    issue_id: UUID | None = None
    assignee_id: UUID | None = None
    organisatie_eenheid_id: UUID | None = None
    parent_id: UUID | None = None
    parlementair_item_id: UUID | None = None
    opdracht_id: UUID | None = None
    status: TaskStatus = TaskStatus.open
    priority: TaskPriority = TaskPriority.normaal
    deadline: date | None = Field(None, alias="due_date")
    work_type: str | None = Field(None, max_length=100)

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _require_anchor(self) -> "TaskBase":
        # Een taak hangt aan een corpus-node of aan een casus. Een issue
        # alleen is genoeg: de route vult casus_id dan aan vanuit het issue.
        # Een subtaak hangt aan een node, net als op main.
        if self.node_id is None and self.casus_id is None and self.issue_id is None:
            raise ValueError("node_id, casus_id of issue_id is verplicht")
        return self


class TaskCreate(TaskBase):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "title": "Analyseer impact nieuwe wetgeving",
                    "node_id": "00000000-0000-0000-0000-000000000001",
                    "assignee_id": "00000000-0000-0000-0000-000000000002",
                    "priority": "hoog",
                    "status": "open",
                }
            ]
        },
    )


class ReorderRequest(BaseModel):
    task_ids: list[UUID]


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    node_id: UUID | None = None
    casus_id: UUID | None = None
    issue_id: UUID | None = None
    assignee_id: UUID | None = None
    organisatie_eenheid_id: UUID | None = None
    parent_id: UUID | None = None
    parlementair_item_id: UUID | None = None
    opdracht_id: UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    deadline: date | None = Field(None, alias="due_date")
    work_type: str | None = Field(None, max_length=100)

    model_config = ConfigDict(populate_by_name=True)


class TaskAssigneeSummary(BaseModel):
    id: UUID
    naam: str
    is_agent: bool = False

    model_config = ConfigDict(from_attributes=True)


class TaskOrgEenheidSummary(BaseModel):
    id: UUID
    naam: str
    type: str

    model_config = ConfigDict(from_attributes=True)


class TaskNodeSummary(BaseModel):
    id: UUID
    title: str
    node_type: str

    model_config = ConfigDict(from_attributes=True)


class TaskOpdrachtSummary(BaseModel):
    id: UUID
    titel: str
    type: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class TaskSubtaskSummary(BaseModel):
    id: UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    assignee: TaskAssigneeSummary | None = None
    due_date: date | None = Field(None, validation_alias="deadline")
    order: int | None = None
    work_type: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskCasusSummary(BaseModel):
    id: UUID
    title: str
    fase: str
    # Het initiatief van de casus: de UI beperkt daarmee wie te kiezen is.
    initiatief_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class BacklogTask(BaseModel):
    """Eén taak in de backlog, als kaartje op het mini-kanban van zijn issue."""

    id: UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None = Field(None, validation_alias="deadline")
    order: int | None = None
    assignee_id: UUID | None = None
    assignee: TaskAssigneeSummary | None = None
    # Hoe besproken de taak is: het aantal opmerkingen, als getal op het kaartje.
    comment_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BacklogIssue(BaseModel):
    """Eén issue in de backlog van een initiatief, met de casus en zijn taken.

    Alleen hoofdtaken; hun subtaken hangen eronder.
    """

    id: UUID
    casus_id: UUID
    casus: TaskCasusSummary
    title: str
    status: str
    is_onderzoeksvraag: bool = True
    assignee_id: UUID | None = None
    assignee: TaskAssigneeSummary | None = None
    toelichting: str | None = None
    sort_order: int = 0
    dod_checked: list[str] = []
    tasks: list[BacklogTask] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BacklogResponse(BaseModel):
    issues: list[BacklogIssue]
    # Taken zonder issue, los op de casus, met hun casus erbij zodat ze
    # ergens onder te hangen zijn.
    losse_taken: list["BacklogLosseTaak"]


class BacklogLosseTaak(BacklogTask):
    casus_id: UUID
    casus: TaskCasusSummary


class TaskResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    node_id: UUID | None = None
    node: TaskNodeSummary | None = None
    casus_id: UUID | None = None
    casus: TaskCasusSummary | None = None
    issue_id: UUID | None = None
    assignee_id: UUID | None = None
    assignee: TaskAssigneeSummary | None = None
    organisatie_eenheid_id: UUID | None = None
    organisatie_eenheid: TaskOrgEenheidSummary | None = None
    parent_id: UUID | None = None
    parlementair_item_id: UUID | None = None
    opdracht_id: UUID | None = None
    opdracht: TaskOpdrachtSummary | None = None
    subtasks: list[TaskSubtaskSummary] = []
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None = Field(None, validation_alias="deadline")
    order: int | None = None
    work_type: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EenheidPersonTaskStats(BaseModel):
    person_id: UUID
    person_naam: str
    open_count: int = 0
    in_progress_count: int = 0
    done_count: int = 0
    overdue_count: int = 0


class EenheidSubeenheidStats(BaseModel):
    eenheid_id: UUID
    eenheid_naam: str
    eenheid_type: str
    open_count: int = 0
    in_progress_count: int = 0
    done_count: int = 0
    overdue_count: int = 0


class EenheidOverviewResponse(BaseModel):
    unassigned_count: int
    unassigned_no_unit: list[TaskResponse] = []
    unassigned_no_unit_count: int = 0
    unassigned_no_person: list[TaskResponse] = []
    unassigned_no_person_count: int = 0
    by_person: list[EenheidPersonTaskStats]
    by_subeenheid: list[EenheidSubeenheidStats]
    eenheid_type: str = ""
