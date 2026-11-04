"""Pydantic schemas for Lead funnel."""

import enum
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bouwmeester.schema.github_link import GitHubLinkResponse


class LeadStage(enum.StrEnum):
    """Default stage slugs.

    Stage waarden zijn niet langer beperkt tot deze enum: per-initiatief
    kunnen eigenaren eigen kolommen aanmaken via `lead_column`. De enum
    blijft als referentie voor de 7 default-kolommen (orphan-leads zonder
    initiatief, frontend fallback bij loading).
    """

    inbox = "inbox"
    verkennen = "verkennen"
    eerste_gesprek = "eerste_gesprek"
    interne_check = "interne_check"
    follow_up = "follow_up"
    in_the_pocket = "in_the_pocket"
    koelkast = "koelkast"


class LeadActivityType(enum.StrEnum):
    note = "note"
    stage_change = "stage_change"
    meeting = "meeting"
    call = "call"
    email = "email"
    evaluatie = "evaluatie"


class EngagementType(enum.StrEnum):
    intern_oppakken = "intern_oppakken"
    voorbereiden_eigen_team = "voorbereiden_eigen_team"
    betrokken_houden = "betrokken_houden"
    verkenning = "verkenning"
    nog_te_bepalen = "nog_te_bepalen"


# ---------------------------------------------------------------------------
# Lead base / create / update
# ---------------------------------------------------------------------------


class LeadBase(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    organization: str | None = Field(None, max_length=500)
    organisatie_eenheid_id: UUID | None = None
    stage: str = Field(default="inbox", min_length=1, max_length=120)
    assignee_id: UUID | None = None
    brought_by_id: UUID | None = None
    next_action: str | None = Field(None, max_length=5000)
    next_action_date: date | None = None
    raw_intake_text: str | None = Field(None, max_length=50000)
    initiatief_id: UUID | None = None
    engagement_type: EngagementType | None = None
    score_strategisch: int | None = Field(None, ge=1, le=5)
    score_politiek: int | None = Field(None, ge=1, le=5)
    score_positie: int | None = Field(None, ge=1, le=5)
    public_visible: bool = False
    public_title: str | None = Field(None, max_length=300)
    public_summary: str | None = Field(None, max_length=5000)


class LeadCreate(LeadBase):
    created_at: datetime | None = None  # Optional: backdate the lead


class LeadUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    organization: str | None = Field(None, max_length=500)
    organisatie_eenheid_id: UUID | None = None
    stage: str | None = Field(None, min_length=1, max_length=120)
    assignee_id: UUID | None = None
    brought_by_id: UUID | None = None
    next_action: str | None = Field(None, max_length=5000)
    next_action_date: date | None = None
    raw_intake_text: str | None = Field(None, max_length=50000)
    initiatief_id: UUID | None = None
    engagement_type: EngagementType | None = None
    score_strategisch: int | None = Field(None, ge=1, le=5)
    score_politiek: int | None = Field(None, ge=1, le=5)
    score_positie: int | None = Field(None, ge=1, le=5)
    public_visible: bool | None = None
    public_title: str | None = Field(None, max_length=300)
    public_summary: str | None = Field(None, max_length=5000)

    model_config = ConfigDict(populate_by_name=True)


class LeadMove(BaseModel):
    stage: str = Field(min_length=1, max_length=120)


class LeadReorder(BaseModel):
    lead_ids: list[UUID]
    stage: str = Field(min_length=1, max_length=120)


class LeadMergeRequest(BaseModel):
    source_id: UUID  # The lead to merge FROM (will be deleted)
    target_id: UUID  # The lead to merge INTO (will survive)


# ---------------------------------------------------------------------------
# Summary / nested response schemas
# ---------------------------------------------------------------------------


class LeadAssigneeSummary(BaseModel):
    id: UUID
    naam: str

    model_config = ConfigDict(from_attributes=True)


class LeadInitiatiefSummary(BaseModel):
    id: UUID
    naam: str
    kleur: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LeadOrganisatieSummary(BaseModel):
    id: UUID
    naam: str
    type: str | None = None
    afkorting: str | None = None
    bron: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LeadAttachmentResponse(BaseModel):
    id: UUID
    lead_id: UUID
    soort: str = "file"
    bestandsnaam: str | None = None
    content_type: str | None = None
    bestandsgrootte: int | None = None
    url: str | None = None
    source: str = "upload"
    source_ref: str | None = None
    bestand_beschikbaar: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadContactResponse(BaseModel):
    id: UUID
    person_id: UUID
    person_naam: str = ""
    person_functie: str | None = None
    person_expertise: str | None = None
    rol: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _extract_person_naam(cls, data: Any) -> Any:
        if hasattr(data, "person") and data.person:
            if not hasattr(data, "person_naam") or not data.person_naam:
                data.person_naam = data.person.naam
            if not getattr(data, "person_functie", None):
                data.person_functie = data.person.functie
            if not getattr(data, "person_expertise", None):
                data.person_expertise = data.person.expertise
        return data


class LeadNodeResponse(BaseModel):
    id: UUID
    node_id: UUID
    node_title: str = ""
    node_type: str = ""
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _extract_node_info(cls, data: Any) -> Any:
        if hasattr(data, "node") and data.node:
            if not hasattr(data, "node_title") or not data.node_title:
                data.node_title = data.node.title
            if not hasattr(data, "node_type") or not data.node_type:
                data.node_type = data.node.node_type
        return data


class LeadActivityResponse(BaseModel):
    id: UUID
    lead_id: UUID
    author_id: UUID | None = None
    author_naam: str | None = None
    content: str
    activity_type: LeadActivityType
    metadata_: dict = Field(default_factory=dict)
    uitkomst: str | None = None
    vervolgacties: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _fill_author_naam(cls, data: Any) -> Any:
        # Vul ``author_naam`` uit de relationship als die mee-geladen is.
        # Het ORM-object heeft geen `author_naam` kolom, dus zonder deze
        # validator blijft het veld in de response altijd None — een
        # latente bug die zichtbaar werd toen Mattermost-imports leidden
        # tot notes zonder zichtbare auteur.
        if hasattr(data, "author") and getattr(data, "author", None):
            if not getattr(data, "author_naam", None):
                # Pydantic v2 model_validator(before) geeft het ORM-object
                # zelf — we zetten een attribuut zodat from_attributes het
                # oppikt. Geen DB-write; deze instantie wordt na de
                # response weggegooid.
                try:
                    data.author_naam = data.author.naam
                except AttributeError:
                    pass
        return data


# ---------------------------------------------------------------------------
# Lead response (list) and detail response
# ---------------------------------------------------------------------------


class LeadResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    organization: str | None = None
    organisatie_eenheid_id: UUID | None = None
    organisatie_eenheid: LeadOrganisatieSummary | None = None
    stage: str
    assignee_id: UUID | None = None
    assignee: LeadAssigneeSummary | None = None
    brought_by_id: UUID | None = None
    brought_by: LeadAssigneeSummary | None = None
    initiatief_id: UUID | None = None
    initiatief: LeadInitiatiefSummary | None = None
    next_action: str | None = None
    next_action_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    sort_order: int = 0
    raw_intake_text: str | None = None
    engagement_type: EngagementType | None = None
    score_strategisch: int | None = None
    score_politiek: int | None = None
    score_positie: int | None = None
    public_visible: bool = False
    public_title: str | None = None
    public_summary: str | None = None
    attachment_count: int = 0
    contact_names: list[str] = Field(default_factory=list)
    # Gevuld als uit deze lead een casus is gestart; de lead is dan alleen-lezen.
    casus_id: UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _extract_tags(cls, data: object) -> object:
        """Populate tags from the lead_tags relationship if available."""
        # casus_id uit de relationship, maar alleen als die geladen is: een
        # lazy load vanuit een validator breekt in een async sessie.
        if hasattr(data, "__mapper__"):
            from sqlalchemy import inspect as sa_inspect

            if "casus" not in sa_inspect(data).unloaded:
                casus = getattr(data, "casus", None)
                object.__setattr__(data, "casus_id", casus.id if casus else None)
        if hasattr(data, "lead_tags"):
            lead_tags = data.lead_tags
            if lead_tags is not None:
                # Inject a 'tags' attribute onto the ORM object so
                # from_attributes picks it up as list[str].
                object.__setattr__(
                    data,
                    "tags",
                    [lt.tag.name for lt in lead_tags if lt.tag],
                )
        return data


class LeadDetailResponse(LeadResponse):
    activities: list[LeadActivityResponse] = Field(default_factory=list)
    attachments: list[LeadAttachmentResponse] = Field(default_factory=list)
    contacts: list[LeadContactResponse] = Field(default_factory=list)
    linked_nodes: list[LeadNodeResponse] = Field(default_factory=list)
    github_links: list[GitHubLinkResponse] = Field(default_factory=list)


class LeadMetricsResponse(BaseModel):
    total: int
    by_stage: dict[str, int]
    stale_count: int


# ---------------------------------------------------------------------------
# Activity / contact / node create schemas
# ---------------------------------------------------------------------------


class LeadActivityCreate(BaseModel):
    content: str = Field(min_length=1, max_length=50000)
    activity_type: LeadActivityType = LeadActivityType.note
    uitkomst: str | None = Field(None, max_length=10000)
    vervolgacties: str | None = Field(None, max_length=10000)


class LeadContactCreate(BaseModel):
    person_id: UUID
    rol: str = "contactpersoon"


class LeadNodeCreate(BaseModel):
    node_id: UUID


# ---------------------------------------------------------------------------
# AI parse result
# ---------------------------------------------------------------------------


class LeadParseResult(BaseModel):
    title: str | None = None
    organization: str | None = None
    description: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    original_date: str | None = None  # ISO date from the source message
    suggested_tags: list[str] = Field(default_factory=list)
    addressed_to: str | None = None


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


class LeadTimelineEvent(BaseModel):
    """A single event on the lead timeline."""

    id: str  # activity id or "created-{lead_id}"
    lead_id: UUID
    lead_title: str
    event_type: (
        str  # "created" | "stage_change" | "note" | "meeting" | "call" | "email"
    )
    timestamp: datetime
    actor_naam: str | None = None
    content: str | None = None  # activity content or creation description
    # Stage change specific
    from_stage: str | None = None
    to_stage: str | None = None
    # Lead metadata at time of event
    organization: str | None = None
    stage: str  # current stage of the lead
    assignee_naam: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LeadTimelineResponse(BaseModel):
    events: list[LeadTimelineEvent]
    total: int
    # Aggregates for the timeline header
    earliest: datetime | None = None
    latest: datetime | None = None
