"""Pydantic schemas for Notification."""

import enum
import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationType(enum.StrEnum):
    task_assigned = "task_assigned"
    task_overdue = "task_overdue"
    task_completed = "task_completed"
    task_reassigned = "task_reassigned"
    node_updated = "node_updated"
    edge_created = "edge_created"
    coverage_needed = "coverage_needed"
    stakeholder_added = "stakeholder_added"
    stakeholder_role_changed = "stakeholder_role_changed"
    politieke_input_imported = "politieke_input_imported"
    direct_message = "direct_message"
    agent_prompt = "agent_prompt"
    mention = "mention"
    access_request = "access_request"
    placement_request = "placement_request"
    placement_approved = "placement_approved"
    placement_denied = "placement_denied"
    emoji_reaction = "emoji_reaction"
    opdracht_created = "opdracht_created"
    opdracht_status_changed = "opdracht_status_changed"
    lead_assigned = "lead_assigned"
    lead_stage_changed = "lead_stage_changed"
    lead_contact_added = "lead_contact_added"
    lead_activity_added = "lead_activity_added"
    task_comment_added = "task_comment_added"
    sync_alert = "sync_alert"


class NotificationBase(BaseModel):
    person_id: UUID
    type: NotificationType
    title: str = Field(max_length=500)
    message: str | None = Field(None, max_length=10000)
    sender_id: UUID | None = None
    related_node_id: UUID | None = None
    related_task_id: UUID | None = None
    related_lead_id: UUID | None = None
    parent_id: UUID | None = None
    thread_id: UUID | None = None


class NotificationCreate(NotificationBase):
    pass


class ReactionSummary(BaseModel):
    emoji: str
    count: int
    sender_names: list[str]
    reacted_by_me: bool = False


class NotificationResponse(NotificationBase):
    # Override fields without length constraints — response schemas must be
    # able to return data that already exists in the database.
    title: str
    message: str | None = None

    id: UUID
    is_read: bool = False
    created_at: datetime
    last_activity_at: datetime | None = None
    last_message: str | None = None
    sender_name: str | None = None
    reply_count: int = 0
    reactions: list[ReactionSummary] = []

    model_config = ConfigDict(from_attributes=True)


class SendMessageRequest(BaseModel):
    person_id: UUID
    sender_id: UUID
    message: str = Field(max_length=10000)


class ReplyRequest(BaseModel):
    sender_id: UUID
    message: str = Field(max_length=10000)


_EMOJI_RE = re.compile(
    r"^["
    r"\U0001f300-\U0001f9ff"  # Misc Symbols, Emoticons, Dingbats, etc.
    r"\U0001fa00-\U0001faff"  # Symbols & Pictographs Extended-A
    r"\U0001f1e0-\U0001f1ff"  # Regional Indicator Symbols (flags)
    r"\U00002600-\U000027bf"  # Misc Symbols, Dingbats
    r"\U0001f3fb-\U0001f3ff"  # Skin-tone modifiers
    r"\U0000fe0f"  # Variation Selector-16
    r"\U0000200d"  # Zero Width Joiner
    r"\U000020e3"  # Combining Enclosing Keycap
    r"]+$"
)


class ReactionRequest(BaseModel):
    sender_id: UUID
    emoji: str = Field(max_length=10)

    @field_validator("emoji")
    @classmethod
    def emoji_must_be_emoji(cls, v: str) -> str:
        if not _EMOJI_RE.match(v):
            raise ValueError("Alleen emoji-tekens zijn toegestaan")
        return v


class UnreadCountResponse(BaseModel):
    count: int


class DashboardStatsResponse(BaseModel):
    corpus_node_count: int
    open_task_count: int
    overdue_task_count: int
    active_opdracht_budget: float = 0
