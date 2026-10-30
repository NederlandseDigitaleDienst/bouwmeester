"""Issue model - de laag tussen casus en taak.

Werkproces: casus > issue > taak > subtaken. Er is geen story-laag.
Een issue is een onderzoeksvraag of niet (is_onderzoeksvraag); andere
categorieën bleken geen betekenis te hebben. Een issue heeft een eigenaar
(assignee). De status volgt de taken eronder (repositories/issue.py,
sync_status), maar is ook met de hand te zetten. Afgerond wordt een issue
alleen met de hand, na de Definition of Done (dod_checked). De backlog van een
initiatief is de lijst issues over alle casussen heen, met de taken eronder.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.casus import Casus
    from bouwmeester.models.person import Person
    from bouwmeester.models.task import Task


class Issue(Base):
    __tablename__ = "issue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    casus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("casus.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(nullable=False)
    toelichting: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_onderzoeksvraag: Mapped[bool] = mapped_column(
        default=True, server_default="true"
    )
    # Wie het issue trekt. Lid van het initiatief, zoals bij taken.
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        default="open",
        server_default="open",
        comment="open|in_progress|done",
    )
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    # Welke DoD-eisen zijn afgevinkt bij het afronden (tekst van de eis).
    dod_checked: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    casus: Mapped["Casus"] = relationship("Casus", back_populates="issues")
    assignee: Mapped[Optional["Person"]] = relationship("Person")
    # De taken onder het issue. Subtaken hangen aan hun hoofdtaak.
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="issue",
        order_by="Task.order.asc(), Task.created_at.asc()",
    )
