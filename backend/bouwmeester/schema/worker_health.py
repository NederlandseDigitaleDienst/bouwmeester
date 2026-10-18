"""Pydantic schemas for worker heartbeat/health endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WorkerHeartbeatResponse(BaseModel):
    """Status van één worker-loop, zoals getoond in Beheer > Systeem."""

    model_config = ConfigDict(from_attributes=True)

    loop_name: str
    status: str
    detail: str | None
    last_tick_at: datetime | None
    started_at: datetime | None
    seconds_since_last_tick: float | None
    health: str  # "healthy" | "stale" | "down" | "disabled"
    one_shot: bool = False
    """True voor entries die per ontwerp één keer ticken (worker_singleton).
    De UI toont de leeftijd dan als 'sinds', niet als achterstallige hartslag."""


class WorkerHealthResponse(BaseModel):
    """Aggregate response for ``GET /api/admin/workers``."""

    workers: list[WorkerHeartbeatResponse]
    server_now: datetime


class MattermostChannelOverview(BaseModel):
    """Eén gekoppeld kanaal in Beheer > Systeem."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: str
    channel_display_name: str
    channel_name: str
    team_id: str | None = None
    # Bij het tonen opgehaald, niet opgeslagen: een opgeslagen naam
    # veroudert zodra iemand het team hernoemt.
    team_name: str | None = None
    scope_type: str  # "lead" | "initiatief"
    scope_id: UUID
    scope_label: str | None
    auto_note_enabled: bool
    suggest_leads_enabled: bool
    parlementaire_alerts_enabled: bool
    nieuws_alerts_enabled: bool
    last_seen_post_at: datetime | None
    disabled_at: datetime | None
    created_at: datetime


class MattermostChannelRights(BaseModel):
    """Whether the bot may create channels in one team."""

    team_id: str
    team_name: str | None = None
    can_create_public_channel: bool
    can_create_private_channel: bool
