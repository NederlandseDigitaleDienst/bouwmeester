"""Issue model - de laag tussen casus en taak.

Een issue hoort altijd bij een initiatief (initiatief_id) en meestal bij een
casus. Zonder casus is het een vraag van het initiatief zelf; de taken eronder
hangen dan alleen aan de vraag (task.issue_id, task.casus_id leeg) en volgen
de rechten van het initiatief.

Werkproces: casus > issue > taak > subtaken. Er is geen story-laag.
Een issue is een onderzoeksvraag of niet (is_onderzoeksvraag); andere
categorieën bleken geen betekenis te hebben. Een issue heeft een eigenaar
(assignee). De status volgt de taken eronder (repositories/issue.py,
sync_status), maar is ook met de hand te zetten. Afgerond wordt een issue
alleen met de hand, na de Definition of Done (dod_checked). De backlog van een
initiatief is de lijst issues over alle casussen heen, met de taken eronder.

Naar buiten: een afgeronde onderzoeksvraag kan iemand vrijgeven met een
publieke vraag en een kort antwoord (public_title, public_answer). Alleen die
twee teksten gaan ooit naar buiten, op de publieke pagina en in de mailbrief
van een update; titel, toelichting en casus blijven binnen. Wordt de vraag
weer open gezet, dan is hij niet meer vrijgegeven (published_at leeg).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.casus import Casus
    from bouwmeester.models.onderzoeksverslag import Onderzoeksverslag
    from bouwmeester.models.person import Person
    from bouwmeester.models.task import Task


class Issue(Base):
    __tablename__ = "issue"
    __table_args__ = (
        CheckConstraint(
            "casus_id IS NOT NULL OR initiatief_id IS NOT NULL", name="ck_issue_plek"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # Leeg: een vraag van het initiatief, zonder casus.
    casus_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("casus.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Het initiatief waar de vraag bij hoort; bij een casusvraag dat van de
    # casus. Bepaalt wie de vraag ziet als er geen casus is.
    initiatief_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief.id", ondelete="CASCADE", name="fk_issue_initiatief"),
        nullable=True,
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
    # Het antwoord, interne versie: voor het team, mag namen en details
    # bevatten. De externe versie is public_title en public_answer.
    antwoord: Mapped[str | None] = mapped_column(Text, nullable=True)
    # De vraag zoals buiten hem leest, en het antwoord. Blijven bewaard als de
    # vraag wordt ingetrokken, zodat opnieuw vrijgeven geen typwerk is.
    public_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Wanneer vrijgegeven voor buiten; leeg is niet vrijgegeven.
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    casus: Mapped[Optional["Casus"]] = relationship("Casus", back_populates="issues")
    assignee: Mapped[Optional["Person"]] = relationship("Person")
    # Het onderzoeksverslag, als er een is. De database ruimt het op met de
    # vraag (CASCADE); laden gebeurt alleen waar het nodig is.
    verslag: Mapped[Optional["Onderzoeksverslag"]] = relationship(
        "Onderzoeksverslag",
        back_populates="issue",
        uselist=False,
        passive_deletes=True,
    )
    # De taken onder het issue. Subtaken hangen aan hun hoofdtaak.
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="issue",
        order_by="Task.order.asc(), Task.created_at.asc()",
    )
