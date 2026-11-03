"""TaskAttachment model - bijlagen op een taak, opgeslagen via core.storage."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from bouwmeester.core.database import Base


class TaskAttachment(Base):
    __tablename__ = "task_attachment"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bestandsnaam: Mapped[str] = mapped_column(nullable=False)
    content_type: Mapped[str | None] = mapped_column(nullable=True)
    bestandsgrootte: Mapped[int | None] = mapped_column(nullable=True)
    pad: Mapped[str] = mapped_column(nullable=False)
    # Wie de bijlage plaatste: die, of een beheerder, mag hem verwijderen.
    # Leeg als de persoon niet meer bestaat; dan alleen een beheerder.
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
