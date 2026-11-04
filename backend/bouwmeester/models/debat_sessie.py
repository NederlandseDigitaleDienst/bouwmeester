"""The channel that was set up for one debate.

A row is the answer to "is there already a channel for this debate?", and
later the place where the listening worker finds what to listen to.

The key is the activiteit from the TK API, not a Debat Direct debate. A
convocatie arrives days to weeks ahead (median 20.5 days, measured over 80
convocaties), and Debat Direct does not know the debate until the day
itself. The activiteit already exists.

Own table, not a third scope on `mattermost_channel_link`: a linked channel
is read for leads and notes, and a debate channel must not be.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from bouwmeester.core.database import Base


class DebatSessie(Base):
    """One debate, in one team, with the channel that belongs to it."""

    __tablename__ = "debat_sessie"
    __table_args__ = (
        # One channel per debate per team. This constraint is also the
        # lock: the row is inserted before the channel is created, so two
        # people pressing start at the same moment cannot both get one.
        UniqueConstraint("activiteit_id", "team_id", name="uq_debat_sessie_activiteit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # `Id` of the Activiteit in the TK OData API. Of the meeting as it
    # stands: when the Kamer moves a meeting the new date is a new
    # activiteit, and the row follows it there the next time someone
    # presses start (see `DebatKanaalService._find`).
    activiteit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # `Nummer`, such as 2026A06386: what a human recognises and what the
    # page on tweedekamer.nl is keyed on.
    activiteit_nummer: Mapped[str | None] = mapped_column(String(32), nullable=True)
    onderwerp: Mapped[str] = mapped_column(Text, nullable=False)
    # As read when the channel was set up, or when start was pressed again
    # after the meeting changed. 10% of activiteiten is cancelled or moved
    # (25 of 250 measured), so whoever uses this on the day itself reads it
    # again.
    aanvang: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    team_id: Mapped[str] = mapped_column(String(26), nullable=False)
    # NULL while the channel is being created: the row is the claim, the
    # channel follows. A claim that stays NULL is a start that broke off
    # halfway, and may be taken over.
    channel_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True, unique=True
    )
    channel_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The pinned message with the agenda, so it can be updated in place
    # when the agenda changes.
    stukken_post_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    # The convocatie under which start was pressed.
    parlementair_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("parlementair_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_by_mattermost_user_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # The Debat Direct debates that are this activiteit, found on the day
    # itself. A list, because Debat Direct cuts a plenary debate in two
    # around a break against one activiteit.
    debat_direct_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Where the timeline stands: NULL (not yet found on Debat Direct),
    # gekoppeld, loopt, afgelopen or afgelast.
    tijdlijn_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # When the activiteit and the Debat Direct agenda were last read, so
    # that is not done on every tick.
    tijdlijn_gecontroleerd_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Per Debat Direct debate, where the reading of its subtitles stands:
    # {"<id>": {"url": playlist or "", "positie": iso, "offset_ms": int,
    # "audio": playlist of the audio of the room}}.
    ondertitels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Of a procedurevergadering only: where the overview of its decisions
    # stands (`debat_besluiten`). The message it is, how much of the text
    # was read for it, and whether the final overview is in the channel.
    besluiten: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


TIJDLIJN_GEKOPPELD = "gekoppeld"
TIJDLIJN_LOOPT = "loopt"
TIJDLIJN_AFGELOPEN = "afgelopen"
TIJDLIJN_AFGELAST = "afgelast"


class DebatSpreekbeurt(Base):
    """One event of a debate that the timeline has dealt with.

    The table is the memory of what was seen: an event that is in here is
    never posted again, also after a restart. `post_id` is the message it
    became, or NULL for an event that was deliberately not posted (the
    chairman giving the floor, or everything that happened before the
    timeline joined a running debate).

    Named after the spreekbeurt because that is what a row will grow into:
    the transcript is added to the same message later.
    """

    __tablename__ = "debat_spreekbeurt"
    __table_args__ = (
        UniqueConstraint(
            "sessie_id",
            "debat_direct_id",
            "event_type",
            "event_start",
            "object_id",
            name="uq_debat_spreekbeurt_event",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    sessie_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("debat_sessie.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    debat_direct_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # The politician for a speaker event, the debate itself for a start or
    # an end. Empty string, not NULL, so the unique key holds.
    object_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=""
    )
    post_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    # The kind of the turn this event went into, where that is not what the
    # event itself says. Someone who gets the floor is often entered as
    # interrupter and seconds later as speaker: one turn, of the kind that
    # came last. `event_type` stays what the feed said, because that is
    # what an event is recognised by. On every row of such a turn.
    beurt_soort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The first line of the message, kept so the message can be written
    # again with the text under it.
    kop: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What was said in this turn, as far as the subtitles have come. Derived:
    # the lines of `debat_ondertitel` that belong to this row, in order. Only
    # a row from before that table existed has text without lines.
    tekst: Mapped[str | None] = mapped_column(Text, nullable=True)
    # How much of the text of this turn is in the channel. Differs from the
    # length of the text when a message still has to be written.
    tekst_geplaatst: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # Which text that is: a digest of the text of the turn as it was written.
    # A line can move to another turn afterwards, and then the text of a turn
    # changes without only growing. NULL for a message written before this
    # column existed, which is taken at its length.
    tekst_geplaatst_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # The messages a long turn continues in, in order.
    vervolg_post_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # When this turn was read for questions to the bewindspersoon, with or
    # without a find. NULL is not yet: a turn is read once, when it is over
    # and its text is complete. Only on the row that carries the message.
    beoordeeld_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # How often reading this turn failed. Past a few times it is given up
    # on, so one turn the model cannot take does not hold up the debate.
    beoordeel_pogingen: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # For an answer of the bewindspersoon, which is read for toezeggingen a
    # window at a time: how many characters of its text were read and
    # stored. The next round goes on from here; what is in front of it is
    # never sent to the model again. NULL when nothing of it was read, and
    # for every other turn. For such a turn `beoordeel_pogingen` counts the
    # tries of the window that is next, and starts anew when this moves.
    antwoord_gelezen_tot: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


TOEWIJZING_TIJD = "tijd"
TOEWIJZING_STEM = "stem"


class DebatOndertitel(Base):
    """One line of subtitle, and the turn it belongs to.

    The subtitles say what was said and exactly when. Which turn a line
    belongs to is first decided by time, and around a change of speaker
    again by voice. Kept as rows so that a line can move: the text of a
    turn is its lines in order.
    """

    __tablename__ = "debat_ondertitel"
    __table_args__ = (
        # A line is in one file of the track only, so its moment names it.
        # Also what keeps two workers from keeping the same line twice.
        UniqueConstraint(
            "sessie_id", "debat_direct_id", "start", name="uq_debat_ondertitel_start"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    sessie_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("debat_sessie.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    debat_direct_id: Mapped[str] = mapped_column(String(36), nullable=False)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    einde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tekst: Mapped[str] = mapped_column(Text, nullable=False)
    spreekbeurt_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("debat_spreekbeurt.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # What decided the turn: `tijd` (the last event before the line) or
    # `stem` (whose voice it is). Not biometric: it says which of two turns,
    # nothing about a voice.
    toewijzing: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=TOEWIJZING_TIJD
    )
    # Whether the voices have had their say about this line, or never will.
    # A line that is not done is looked at again on a later round.
    stem_klaar: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
