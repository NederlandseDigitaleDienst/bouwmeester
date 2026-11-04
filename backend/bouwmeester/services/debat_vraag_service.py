"""Marking questions: what is the bewindspersoon asked in this debate.

When a turn at speaking is finished, the transcription hands it to
`DebatVraagService.beoordeel_beurt`. A model reads that one turn, with what
is known about the debate and the list of questions that are still open,
and says which questions to the bewindspersoon are in it. Each new question
is recorded, becomes a reply under the message of the turn, and shows up in
the status line of that message.

A question is a state, not an event. The model has no memory of the debate;
the table has. Every call gets the open questions of the speaker as a short
list, and a question they ask again becomes a vermelding on the row that is
there instead of a second thread.

Order of work, and why:

1. The answer of the model is stored in one commit, threads not yet posted.
   From then on the turn counts as judged: a second call for the same turn
   does not ask the model again, so it cannot mark other questions.
2. Each thread is posted while its row is locked, and the post id is
   committed before anything else happens. A post that fails leaves the row
   without a thread, and the next call tries it again.
3. The status line counts only questions that have a thread, and is written
   last. It is derived from the table, so writing it twice is harmless.

The service commits. It never rolls back: nothing is left half done between
two commits, and a rollback would expire what the caller holds.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from sqlalchemy import exists, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.debat_markering import (
    SLEUTEL_SLOTLIJST,
    SOORT_MOTIE,
    SOORT_TOEZEGGING,
    SOORT_VRAAG,
    STATUS_OPEN,
    STATUS_TOEGEWEZEN,
    STATUS_VERWORPEN,
    VERMELDING_ANTWOORD,
    VERMELDING_BEVESTIGING,
    VERMELDING_HERHALING,
    DebatMarkering,
    DebatMarkeringVermelding,
)
from bouwmeester.models.debat_sessie import DebatSessie, DebatSpreekbeurt
from bouwmeester.services import debat_direct as dd
from bouwmeester.services.debat_kanaal_service import AMSTERDAM
from bouwmeester.services.debat_motie import (
    VORM_AANGEKONDIGD,
    VORM_INGEDIEND,
    VORM_OVERWOGEN,
    Motie,
    dictum_without_close,
    find_moties,
    is_motion_text,
    motie_vorm,
)
from bouwmeester.services.debat_slotlijst import (
    is_listed_commitment,
    match_listed,
    opens_closing_list,
    promised_to,
)
from bouwmeester.services.debat_statusregel import (
    ICOON_MOTIE,
    ICOON_TOEZEGGING,
    ICOON_VRAAG,
    met_status,
    statusregel,
)
from bouwmeester.services.debat_toezegging import (
    AT_START,
    SAID_BEFORE,
    Interruption,
    commitment_passages,
    deadline_is_said,
    has_commitment_form,
    link_to_question,
    may_hold_commitment,
    shares_a_subject,
)
from bouwmeester.services.debat_transcript import _RUNS_ON, split_text
from bouwmeester.services.debat_vraag_brief import (
    PRODUCTS,
    PaperRequest,
    paper_request,
)
from bouwmeester.services.debat_vraag_moment import (
    SAFE_URL as _VEILIGE_URL,
)
from bouwmeester.services.debat_vraag_moment import (
    Line,
    moment_of_position,
    question_url,
)
from bouwmeester.services.debat_vraag_reacties import REACTIE_HINT, stand_marker
from bouwmeester.services.debat_vraag_vorm import has_question_form
from bouwmeester.services.llm.base import (
    DEBAT_VRAGEN_ONBEREIKBAAR,
    BaseLLMService,
    DebatToezegging,
    DebatVraag,
)
from bouwmeester.services.mattermost_service import (
    MattermostService,
    PostNotFoundError,
)
from bouwmeester.services.mattermost_utils import (
    escape_mattermost_prose as _escape,
)
from bouwmeester.services.tk_activiteit import (
    Activiteit,
    Bewindspersoon,
    Initiatiefnemer,
)

logger = logging.getLogger(__name__)

SOORT_SPEAKER = dd.EVENT_SPEAKER
SOORT_INTERRUPTER = dd.EVENT_INTERRUPTER
SOORT_CHAIRMAN = "chairman"
# Who a toezegging from the chairman's list stands under. The reply does
# not show it; the row has to name someone.
VOORZITTER = "de voorzitter"

# A turn shorter than this is not sent to the model: "Dank u wel,
# voorzitter." is not a question to anyone.
MIN_WOORDEN = 5
# How many of the speaker's own open questions the model gets, newest first.
MAX_OPENSTAAND = 20
# How often posting a thread is tried before it is left alone.
MAX_POST_POGINGEN = 3
MAX_CITAAT = 600
MAX_SAMENVATTING = 240
MAX_GERICHT_AAN = 80
MAX_TERMIJN = 80
# How many open questions the model gets next to an answer of the
# bewindspersoon, newest first. An answer comes after a whole term of
# questions: about 23 an hour were asked in the four debates of the gold
# set, so this is two to three hours of them.
MAX_VRAGEN_BIJ_ANTWOORD = 60
# How many of their own earlier toezeggingen, newest first: about 2 an hour
# were made in the gold set.
MAX_EERDERE_TOEZEGGINGEN = 30
# How many toezeggingen of the debate the model gets next to the list the
# chairman reads at the end, newest first: all of them, in any debate that
# is not a day long.
MAX_TOEZEGGINGEN_BIJ_LIJST = 60
# An answer of the bewindspersoon goes to the model in windows of about
# this many characters, each a call, cut where a sentence ends. The prompt
# keeps only the end of a long text (`MAX_BEURT_IN_PROMPT`), which is right
# for a question, asked at the end of an argument, and wrong for an answer:
# what is promised in the first ten minutes would never be read. And one
# call on a whole answer, with up to sixty open questions next to it, is
# the slowest call there is. In the gold set the 38 turns of a
# bewindspersoon have a median of 640 characters, a ninth decile of 5,214
# and a longest of 11,248; 5 are over 4,000 and none over 12,000.
ANTWOORD_VENSTER = 4000
# A window begins this many sentences before where the last one ended, so
# that a toezegging that was cut in two by the end of a window is seen
# whole. Not more than `MAX_OVERLAP` characters: a sentence without an end
# is not carried along whole.
OVERLAP_ZINNEN = 2
MAX_OVERLAP = 600
# What is left behind a window when it is less than this goes into that
# window: a last call on two sentences is a call for nothing.
MIN_STAART = 600
# No more of an answer than this is read: a turn of an hour is a transcript
# that lost its changes of speaker. It bounds the calls one turn can cost
# at twelve windows, twice that with the second try an unreadable reply
# gets.
MAX_ANTWOORD = 48000
# What is left of a rejected markering in the channel: one line.
MAX_VERWORPEN = 120
# A Mattermost username is at most 64 characters.
MAX_DOOR = 64

UITKOMST_OVERGESLAGEN = "overgeslagen"
# Why a turn is not read at all, for no kind of markering.
REDEN_VOORZITTER = "voorzitter"
REDEN_BEWINDSPERSOON = "bewindspersoon"
UITKOMST_AL_BEOORDEELD = "al_beoordeeld"
UITKOMST_GEEN_VRAAG = "geen_vraag"
# The same for a turn of the bewindspersoon: read, nothing promised.
UITKOMST_GEEN_TOEZEGGING = "geen_toezegging"
UITKOMST_GEMARKEERD = "gemarkeerd"
# Nothing was judged and nothing was stored: calling again later is useful.
UITKOMST_LLM_ONBEREIKBAAR = "llm_onbereikbaar"
# The model answered, but not with something readable. Not stored either;
# calling again will most likely give the same.
UITKOMST_LLM_ONBRUIKBAAR = "llm_onbruikbaar"

_TITEL_BEWINDSPERSOON = ("minister", "staatssecretaris")
# What `gericht_aan` has to name for a question to count. The model is asked
# for questions to the bewindspersoon only, and still hands in one to the
# initiatiefnemers now and then, honestly labelled as such.
_AAN_BEWINDSPERSOON = (
    "minister",
    "staatssecretaris",
    "kabinet",
    "regering",
    "bewindsperso",
    "premier",
)


def turn_sleutel(spreekbeurt_id: uuid.UUID) -> str:
    """What identifies the turn of a row in `debat_spreekbeurt`. See
    `Beurt.sleutel`."""
    return f"beurt:{spreekbeurt_id}"


@dataclass(frozen=True)
class Beurt:
    """One finished turn at speaking, as the transcription hands it over."""

    sessie_id: uuid.UUID
    # Row in `debat_spreekbeurt`, if known.
    spreekbeurt_id: uuid.UUID | None
    # The Mattermost message of this turn. The thread hangs under it.
    post_id: str | None
    channel_id: str
    # "speaker" | "interrupter" | "chairman"
    soort: str
    # Display label, such as "Kamerlid A (CDA)".
    spreker: str
    fractie: str | None
    # Start of the turn, timezone-aware.
    start: datetime
    # Link to this moment in the broadcast.
    moment_url: str | None
    tekst: str
    # A turn by the bewindspersoon holds answers, not questions. See
    # `is_bewindspersoon` for how to tell from a Debat Direct speaker.
    is_bewindspersoon: bool = False
    # For an interruption: the label of whoever had the floor, if known.
    # "Bent u het daarmee eens?" is a question to that person, and only a
    # question to the bewindspersoon when that person is the bewindspersoon.
    onderbroken: str | None = None
    onderbroken_is_bewindspersoon: bool = False
    # For a turn of the bewindspersoon: the label of the member whose
    # interruption came right before it, and what they said. The answer
    # that follows is to them, and "dat zeg ik toe" says what only with
    # their question next to it. Empty when the turn before was not an
    # interruption of a member.
    voorafgaand: str | None = None
    voorafgaand_tekst: str = ""
    # What identifies that interruption (its `sleutel`): the questions that
    # were marked in it are what the answer is to. ``None`` when not known;
    # the answer is then still to that member, without a question.
    voorafgaand_sleutel: str | None = None
    # For an answer of the bewindspersoon: how many characters of `tekst`
    # were read and stored by earlier calls (see `answer_window`). The
    # caller keeps it between calls; `Beoordeling.gelezen_tot` is what to
    # keep.
    gelezen_tot: int = 0
    # For an answer of the bewindspersoon that is still being given:
    # `tekst` is the part of the turn that is final, and more will follow.
    # It is read as far as `running_window` says, and never counts as done.
    loopt: bool = False
    # The messages a long turn continues in, after `post_id`, in order. A
    # toezegging hangs under the one that holds its quote (`post_holding`).
    vervolg_post_ids: tuple[str, ...] = ()
    # The subtitle lines `tekst` is made of, in order, each with the moment
    # it was spoken. Empty when they are not known; a question then gets
    # the time of the start of the turn.
    lines: tuple[Line, ...] = ()
    # The words of the chairman that are the list of toezeggingen read out
    # at the end of the debate (`debat_slotlijst.find_closing_list`). The
    # only words of a chairman that are ever read, and only for that.
    slotlijst: bool = False

    @property
    def sleutel(self) -> str:
        """What makes this turn this turn, for "was it judged already"."""
        if self.spreekbeurt_id is not None:
            eigen = turn_sleutel(self.spreekbeurt_id)
        elif self.post_id:
            eigen = f"post:{self.post_id}"
        else:
            eigen = f"tijd:{self.start.astimezone(UTC).isoformat()}|{self.spreker}"
        if self.slotlijst:
            # Its own key: the list can hang under a message that is also
            # a turn, and what is stored from it is told apart by this.
            eigen = f"{SLEUTEL_SLOTLIJST}{eigen}"
        return eigen[:255]


@dataclass(frozen=True)
class DebatContext:
    """What is known about a debate before it starts."""

    onderwerp: str
    # Kind of meeting: "Commissiedebat", "Notaoverleg", "Plenair debat".
    soort: str | None = None
    bewindspersonen: tuple[Bewindspersoon, ...] = ()
    # Titles of the agenda documents.
    stukken: tuple[str, ...] = ()
    # Whether members of parliament sit next to the bewindspersoon to
    # answer questions themselves: the debate is about their initiatiefnota
    # or initiatiefwet. Half of the questions then go to them.
    initiatiefnemers: bool = False
    # Who they are, when the TK API lists them; it does for about six in
    # ten of such debates (see `tk_activiteit`). Empty means not known,
    # and everything is then as it was before the names were read.
    initiatiefnemer_namen: tuple[Initiatiefnemer, ...] = ()
    # The subjects of the agendapunten, in order. What a procedurevergadering
    # goes through (`debat_besluiten`).
    agendapunten: tuple[str, ...] = ()
    # When this was read from the TK API. For whoever keeps it: the names
    # of the initiatiefnemers may be added on the day of the debate.
    gelezen_at: datetime | None = field(default=None, compare=False)

    @classmethod
    def from_activiteit(cls, activiteit: Activiteit) -> DebatContext:
        stukken: list[str] = []
        for punt in activiteit.agendapunten:
            titels = [d.onderwerp for d in punt.documenten if d.onderwerp]
            for titel in titels or [punt.onderwerp]:
                if titel and titel not in stukken:
                    stukken.append(titel)
        return cls(
            onderwerp=activiteit.onderwerp,
            soort=activiteit.soort,
            bewindspersonen=activiteit.bewindspersonen,
            stukken=tuple(stukken),
            initiatiefnemers=bool(activiteit.initiatiefnemers)
            or "initiatief" in activiteit.onderwerp.lower(),
            initiatiefnemer_namen=activiteit.initiatiefnemers,
            agendapunten=tuple(
                p.onderwerp for p in activiteit.agendapunten if p.onderwerp
            ),
        )


@dataclass(frozen=True)
class Beoordeling:
    """What became of one turn."""

    uitkomst: str
    # Why a turn was skipped.
    reden: str = ""
    # The markeringen of this turn, new or found from an earlier call.
    markering_ids: tuple[uuid.UUID, ...] = ()
    # Numbers of open questions this turn came back to.
    herhaald: tuple[int, ...] = ()
    # Threads posted by this call, backlog of earlier turns included.
    threads: int = 0
    # Answers of the model that were dropped: a quote that is not in the
    # turn, that holds no question, or that is the text of a motie.
    afgevallen: int = 0
    # How many moties this call stored. Those are found by rule, and are
    # stored whether or not the model could be asked.
    moties: int = 0
    # How many toezeggingen of the bewindspersoon this call stored.
    toezeggingen: int = 0
    # Numbers of the toezeggingen the chairman's list confirmed.
    bevestigd: tuple[int, ...] = ()
    # For an answer of the bewindspersoon: how many characters of it are
    # read and stored now, and whether there is more to read. With `meer`
    # the turn is not done: the same turn is handed in again, with this.
    gelezen_tot: int = 0
    meer: bool = False

    @property
    def opnieuw_proberen(self) -> bool:
        """Whether handing in the same turn again later can help."""
        return self.uitkomst == UITKOMST_LLM_ONBEREIKBAAR


def is_bewindspersoon(spreker: dd.Spreker) -> bool:
    """Whether a Debat Direct speaker is a member of government.

    They carry no party and a title that says what they are.
    """
    titel = (spreker.titel or "").lower()
    return not spreker.fractie and titel.startswith(_TITEL_BEWINDSPERSOON)


# --- the quote ---------------------------------------------------------

_WEGLATING = re.compile(r"\s*(?:\[\s*\.\.\.\s*\]|\(\s*\.\.\.\s*\)|\.\.\.|…)\s*")
_QUOTES = "\"'“”‘’„«»`"


def _plat(tekst: str) -> tuple[str, list[int]]:
    """Text flattened for comparison, with where each character came from.

    Lower case, whitespace as one space, quotation marks dropped. The model
    copies the quote, but not always its spacing or its quotation marks.
    """
    tekens: list[str] = []
    herkomst: list[int] = []
    for i, teken in enumerate(tekst):
        if teken in _QUOTES:
            continue
        if teken.isspace():
            if tekens and tekens[-1] != " ":
                tekens.append(" ")
                herkomst.append(i)
            continue
        laag = teken.lower()
        # One character can lower to two; keep the map one to one.
        for deel in laag:
            tekens.append(deel)
            herkomst.append(i)
    return "".join(tekens), herkomst


def vind_citaat(tekst: str, citaat: str) -> str | None:
    """The quote as it stands in the turn, or ``None`` if it is not there."""
    found = locate_citaat(tekst, citaat)
    return found[0] if found else None


def locate_citaat(tekst: str, citaat: str) -> tuple[str, int] | None:
    """The quote as it stands in the turn, and where in the turn it begins.

    What goes into a thread as "literally said" has to be in the
    transcript. A model that tidies up a sentence, or writes the question
    it thinks was meant, gives a quote nobody said. The return value is cut
    from the turn itself, never taken from the model.

    A model that was told to copy mistakes still repairs one now and then
    ("porgt" becomes "borgt"). The passage it meant is then looked up, and
    what comes back is how the transcript has it, mistake included.

    Where it begins is the place in `tekst` of its first character; for a
    quote in pieces, of its first piece. That is what says when the
    question was asked.
    """
    plat, herkomst = _plat(tekst)
    delen = [d for d in _WEGLATING.split(citaat) if d.strip()]
    # The whole quote first: the transcript has dots of its own.
    kandidaten = [[citaat]] + ([delen] if len(delen) > 1 else [])
    for stukken in kandidaten:
        gevonden: list[tuple[int, int]] = []
        vanaf = 0
        for stuk in stukken:
            zoek = _plat(stuk)[0].strip()
            if not zoek:
                break
            at = plat.find(zoek, vanaf)
            if at == -1:
                break
            gevonden.append((at, at + len(zoek) - 1))
            vanaf = at + len(zoek)
        else:
            if gevonden:
                return _met_plek(
                    " (...) ".join(
                        tekst[herkomst[a] : herkomst[b] + 1].strip()
                        for a, b in gevonden
                    ),
                    herkomst[gevonden[0][0]],
                )
    bijna = _vind_bijna(plat, _plat(citaat)[0].strip())
    if bijna is None:
        return None
    return _met_plek(
        tekst[herkomst[bijna[0]] : herkomst[bijna[1]] + 1].strip(),
        herkomst[bijna[0]],
    )


def _met_plek(citaat: str, plek: int) -> tuple[str, int] | None:
    gezegd = _zegt_iets(citaat)
    return (gezegd, plek) if gezegd is not None else None


def _zegt_iets(citaat: str) -> str | None:
    """A quote of a word or two stands in every turn and proves nothing."""
    return citaat if len(citaat) >= MIN_CITAAT else None


# The shortest quote that counts as a question that was really asked.
MIN_CITAAT = 12
# How much of a quote has to stand in the turn, in the same order, for the
# passage to count as the one the model meant.
_BIJNA_AANDEEL = 0.9
# Pieces shorter than this match anywhere and say nothing.
_BIJNA_MIN_STUK = 6


def _vind_bijna(plat: str, zoek: str) -> tuple[int, int] | None:
    """Where an almost literal quote stands in the flattened turn.

    The pieces the quote and the turn share, in order, have to cover nearly
    all of the quote and lie as close together as they do in the quote. A
    question the model wrote itself shares words with the turn, not
    sentences, and does not get there.
    """
    if len(zoek) < 3 * _BIJNA_MIN_STUK:
        return None
    blokken = [
        b
        for b in difflib.SequenceMatcher(
            None, plat, zoek, autojunk=False
        ).get_matching_blocks()
        if b.size >= _BIJNA_MIN_STUK
    ]
    if not blokken:
        return None
    gedekt = sum(b.size for b in blokken)
    begin, eind = blokken[0].a, blokken[-1].a + blokken[-1].size - 1
    if gedekt < _BIJNA_AANDEEL * len(zoek):
        return None
    if eind - begin + 1 > len(zoek) * (2 - _BIJNA_AANDEEL):
        return None
    # Whole words: a repaired first or last word is cut in half otherwise.
    while begin > 0 and plat[begin - 1] != " ":
        begin -= 1
    while eind + 1 < len(plat) and plat[eind + 1] != " ":
        eind += 1
    return begin, eind


def _kort(tekst: str, maximum: int) -> str:
    tekst = " ".join((tekst or "").split())
    if len(tekst) <= maximum:
        return tekst
    return tekst[: maximum - 1].rstrip() + "…"


# --- the thread --------------------------------------------------------

# Said once per thread, under the first reply that got into it.
NOOT_TRANSCRIPT = "Citaten komen letterlijk uit het automatische transcript."
# Behind a time that is not that of the question.
BEGIN_BEURT = "(begin van de spreekbeurt)"
ICOON_STUK = "📄"
# In front of what a question asks for on paper.
ICOON_OP_PAPIER = "✉️"
# The first line of a reply without a summary: this much of the quote.
MAX_KOP = 120
_EERSTE_ZIN = re.compile(r"[.?!…](?=\s|$)")


def _hhmm(moment: datetime) -> str:
    return moment.astimezone(AMSTERDAM).strftime("%H:%M")


def format_vraag_thread(
    *,
    volgnummer: int,
    gericht_aan: str,
    citaat: str,
    samenvatting: str,
    stuk: str | None,
    moment: datetime,
    moment_url: str | None,
    vraag_moment: datetime | None = None,
    first_in_thread: bool = True,
    status: str = STATUS_OPEN,
    door: str | None = None,
    vraagt_om: str | None = None,
    termijn: str | None = None,
    toegezegd: Sequence[int] = (),
    later_om: str | None = None,
    later_termijn: str | None = None,
) -> str:
    """The reply under the message of a turn that is the thread of a question.

        ❓ **<the question, in the words of the model>**
        Vraag 12 · aan de minister · [21:55](<link>)
        📄 <agenda document>
        > <the quote>

    A question that asks for something on paper, or that a toezegging was
    linked to, gets one short line more, under the line that was there:

        ❓ **<the question>**
        Vraag 12 · aan de minister · [21:55](<link>)
        ✉️ een overzicht, vóór de begrotingsbehandeling · 🤝 toezegging 15
        > <the quote>

    The second line stays what it was for every question, 34 characters
    with the time in a fixed place; with the request in it, it came to
    three lines on a phone. `vraagt_om` is what is asked for, the word
    the member used in a fixed spelling (`debat_vraag_brief.PRODUCTS`),
    and `termijn` by when, in the member's words. `later_om` and
    `later_termijn` are the same for a question that asked for nothing on
    paper when it was marked and was asked again later for a letter: the
    quote of this reply names no letter, so the line says it came later.
    `toegezegd` are the numbers of the toezeggingen that answer this
    question; their replies say "bij vraag 12", so the two read as a pair
    from either side. None of it says where the question stands: that is
    for the people who follow the debate.

    Who asks is not in it: the reply hangs under the message of the
    speaker. The number is the one of the markering in this debate, so
    people can say "vraag 12".

    Everything in it comes from outside: the quote from the transcript,
    the summary from a model that read the transcript. All of it is
    escaped; the bold and the link are ours.

    `moment` and `moment_url` are the start of the turn and the link to
    it. With `vraag_moment` the time shown is that of the question, and
    the link opens just before it. Without it, both are the turn's and the
    line says so.

    `status` is where the question stands and `door` who picked it up, as
    the reactions on the reply have it. The icon in front of the question
    becomes that of the status, and the words go into the line below, so
    the state of every question can be read down the left side of a
    thread. The reply is made from the row every time, never from what is
    in the channel: writing it twice gives the same text, and nothing in
    it can get lost.
    """
    # The dots of a subtitle line that runs on are taken out for reading,
    # as in the message of the turn. Only here, after the quote was found:
    # looking for it needs the text as it is.
    gezegd = _RUNS_ON.sub(" ", citaat)
    kop = _kop(samenvatting, gezegd)
    icoon, stand = stand_marker(status, _vrij(_kort(door or "", MAX_DOOR)))
    if status == STATUS_VERWORPEN:
        # One struck line instead of the whole reply struck through. In
        # Mattermost a strike does not carry over a line break or into a
        # quote, and what was not a question should not take up four
        # lines. The quote and the summary stay in the row, and taking the
        # reaction away brings the whole reply back.
        return f"{icoon} ~~Vraag {volgnummer} · {kop}~~ · {stand}"
    tijd = _tijd_met_link(moment, moment_url, vraag_moment)
    meta = [f"Vraag {volgnummer}", f"aan {aan_wie(gericht_aan)}", tijd]
    if stand:
        meta.insert(1, stand)
    regels = [f"{icoon or ICOON_VRAAG} **{kop}**", " · ".join(meta)]
    erbij = [
        deel
        for deel in (
            _op_papier(vraagt_om, termijn)
            or _op_papier(later_om, later_termijn, later=True),
            _toegezegd(toegezegd),
        )
        if deel
    ]
    if erbij:
        regels.append(" · ".join(erbij))
    if stuk:
        regels.append(f"{ICOON_STUK} {_vrij(_kort(stuk, 300))}")
    regels.append(f"> {_vrij(_kort(gezegd, MAX_CITAAT))}")
    if first_in_thread:
        # The empty line ends the quote; without it the note is part of it.
        regels.append("")
        regels.append(f"_{NOOT_TRANSCRIPT}_")
    return "\n".join(regels)


# How many toezeggingen on one question are named in its reply; the rest
# is counted behind them.
MAX_TOEGEZEGD = 2
# In front of what a question was asked for later, when it was asked again.
LATER_GEVRAAGD = "later gevraagd:"


def _op_papier(vraagt_om: str | None, termijn: str | None, later: bool = False) -> str:
    """What a question asks for on paper, for the line under its meta line.

    Only a product this code knows: the column is ours, but a row is not
    trusted to hold nothing else. The moment is the member's words from
    the transcript, so it is escaped and capped as the quote is.
    """
    if vraagt_om not in PRODUCTS:
        return ""
    wat = f"{LATER_GEVRAAGD} {vraagt_om}" if later else vraagt_om
    wanneer = _vrij(_kort(termijn or "", MAX_TERMIJN)).strip()
    return f"{ICOON_OP_PAPIER} {wat}" + (f", {wanneer}" if wanneer else "")


def _toegezegd(nummers: Sequence[int]) -> str:
    """The toezeggingen on a question, for the line under its meta line.

    The first `MAX_TOEGEZEGD` by number and how many more there are: a
    toezegging is never left out without the line saying so.
    """
    alle = [int(n) for n in nummers]
    if not alle:
        return ""
    genoemd = ", ".join(str(n) for n in alle[:MAX_TOEGEZEGD])
    meer = len(alle) - MAX_TOEGEZEGD
    return f"{ICOON_TOEZEGGING} toezegging {genoemd}" + (
        f" +{meer}" if meer > 0 else ""
    )


def _tijd_met_link(
    moment: datetime, moment_url: str | None, vraag_moment: datetime | None
) -> str:
    """The time in the line under a markering, as a link when there is one."""
    tijd = _hhmm(vraag_moment or moment)
    link = None
    if vraag_moment is not None:
        link = question_url(moment_url, vraag_moment, moment)
    if link is None and moment_url and _VEILIGE_URL.match(moment_url):
        # A link that cannot be moved to the question still opens the turn.
        link = moment_url
    if link:
        tijd = f"[{tijd}]({link})"
    if vraag_moment is None:
        tijd = f"{tijd} {BEGIN_BEURT}"
    return tijd


# What the first line of a motie says when it is not read out yet.
KOP_AANGEKONDIGD = "Kondigt een motie aan"
KOP_OVERWOGEN = "Overweegt een motie"
_VORM_WOORD = {
    VORM_INGEDIEND: "ingediend",
    VORM_AANGEKONDIGD: "aangekondigd",
    VORM_OVERWOGEN: "overwogen",
}
# The first line of a motie that is read out: this much of its dictum.
MAX_KOP_MOTIE = 160


def format_motie_thread(
    *,
    volgnummer: int,
    citaat: str,
    moment: datetime,
    moment_url: str | None,
    vraag_moment: datetime | None = None,
    first_in_thread: bool = True,
    status: str = STATUS_OPEN,
    door: str | None = None,
) -> str:
    """The reply under the message of a turn that is the thread of a motie.

        📜 **Verzoekt de regering om <the start of the dictum>…**
        Motie 12 · ingediend · [21:55](<link>)
        > <the dictum, and who signed it if that was read out>

    Laid out as a question is (`format_vraag_thread`), and for the same
    reasons: who submits it is not in it, because the reply hangs under
    the message of the speaker, and the number is that of the markering in
    this debate. It is not the number the chairman gives the motie.

    No model wrote any of this. The first line is the dictum as the
    transcript has it, cut short, or for an announcement a few words of
    ours; the whole of what was said is the quote. All of it is escaped
    all the same: the transcript comes from outside too.

    A motie is not answered. It gets an oordeel of the bewindspersoon, and
    that is not read from the debate yet, so the reactions say it in the
    words of a motie (see `stand_marker`).
    """
    gezegd = _RUNS_ON.sub(" ", citaat)
    vorm = motie_vorm(citaat)
    kop = _motie_kop(gezegd, vorm)
    icoon, stand = stand_marker(
        status, _vrij(_kort(door or "", MAX_DOOR)), soort=SOORT_MOTIE
    )
    if status == STATUS_VERWORPEN:
        return f"{icoon} ~~Motie {volgnummer} · {kop}~~ · {stand}"
    meta = [
        f"Motie {volgnummer}",
        _VORM_WOORD[vorm],
        _tijd_met_link(moment, moment_url, vraag_moment),
    ]
    if stand:
        meta.insert(1, stand)
    regels = [
        f"{icoon or ICOON_MOTIE} **{kop}**",
        " · ".join(meta),
        f"> {_vrij(_kort(gezegd, MAX_CITAAT))}",
    ]
    if first_in_thread:
        regels.append("")
        regels.append(f"_{NOOT_TRANSCRIPT}_")
    return "\n".join(regels)


def _motie_kop(gezegd: str, vorm: str) -> str:
    """What a motie asks, for the first line, ready to be made bold."""
    if vorm == VORM_OVERWOGEN:
        return KOP_OVERWOGEN
    if vorm == VORM_AANGEKONDIGD:
        return KOP_AANGEKONDIGD
    dictum = dictum_without_close(gezegd)
    kop = _vrij(_kort(dictum[:1].upper() + dictum[1:], MAX_KOP_MOTIE)).strip()
    return kop or "Motie"


KOP_TOEZEGGING = "Toezegging"
# What the reply of a toezegging says about the list the chairman reads at
# the end: that the chairman read it out too, or that it is known from
# that list only.
BEVESTIGD_DOOR_VOORZITTER = "bevestigd door de voorzitter"
UIT_LIJST_VAN_VOORZITTER = "uit de lijst van de voorzitter"
# Who the chairman names as who promised an item. Our own words go into
# the reply, never the transcript's; "hij" names nobody.
_BEWINDSPERSOON_IN_LIJST = re.compile(
    r"\bde (?:minister-president|staatssecretaris|minister)\b"
)


def format_toezegging_thread(
    *,
    volgnummer: int,
    aan: str,
    citaat: str,
    samenvatting: str,
    termijn: str | None,
    bij_volgnummer: int | None,
    moment: datetime,
    moment_url: str | None,
    vraag_moment: datetime | None = None,
    first_in_thread: bool = True,
    status: str = STATUS_OPEN,
    door: str | None = None,
    bevestigd: bool = False,
    uit_lijst: bool = False,
) -> str:
    """The reply under the message of a turn that is the thread of a toezegging.

        🤝 **<what is promised, in the words of the model>**
        Toezegging 7 · aan Kamerlid A (X) · voor het kerstreces · bij vraag 12
            · [21:55](<link>)
        > <the quote>

    Laid out as a question is (`format_vraag_thread`). Who promises is not
    in it: the reply hangs under the message of the bewindspersoon. `aan`
    is the member it was promised to, `termijn` by when, `bij_volgnummer`
    the question in this debate it answers; each is left out when it is
    not known.

    `bevestigd` says the chairman read this toezegging out in the list at
    the end of the debate. `uit_lijst` says it was not marked during the
    debate and is known from that list alone: its quote is then the
    chairman's wording, and its reply hangs under the chairman's message.

    The summary and the moment are the model's words, the member's name
    comes from Debat Direct and the quote from the transcript. All of it
    is escaped; the bold and the link are ours.
    """
    gezegd = _RUNS_ON.sub(" ", citaat)
    kop = _kop(samenvatting, gezegd, leeg=KOP_TOEZEGGING)
    icoon, stand = stand_marker(
        status, _vrij(_kort(door or "", MAX_DOOR)), soort=SOORT_TOEZEGGING
    )
    if status == STATUS_VERWORPEN:
        return f"{icoon} ~~Toezegging {volgnummer} · {kop}~~ · {stand}"
    meta = [f"Toezegging {volgnummer}"]
    if stand:
        meta.append(stand)
    if uit_lijst:
        meta.append(UIT_LIJST_VAN_VOORZITTER)
        # The reply hangs under the end of the debate and not under an
        # answer, so who promised is only known from what the chairman
        # read: "de minister zegt toe", "de staatssecretaris zal".
        wie_beloofde = _BEWINDSPERSOON_IN_LIJST.search(gezegd.lower())
        if wie_beloofde:
            meta.append(f"toegezegd door {wie_beloofde.group()}")
    elif bevestigd:
        meta.append(BEVESTIGD_DOOR_VOORZITTER)
    wie = _vrij(_kort(aan or "", MAX_GERICHT_AAN)).strip()
    if wie:
        meta.append(f"aan {wie}")
    wanneer = _vrij(_kort(termijn or "", MAX_TERMIJN)).strip()
    if wanneer:
        meta.append(wanneer)
    if bij_volgnummer is not None:
        meta.append(f"bij vraag {int(bij_volgnummer)}")
    meta.append(_tijd_met_link(moment, moment_url, vraag_moment))
    regels = [
        f"{icoon or ICOON_TOEZEGGING} **{kop}**",
        " · ".join(meta),
        f"> {_vrij(_kort(gezegd, MAX_CITAAT))}",
    ]
    if first_in_thread:
        regels.append("")
        regels.append(f"_{NOOT_TRANSCRIPT}_")
    return "\n".join(regels)


def format_thread(
    soort: str,
    *,
    volgnummer: int,
    gericht_aan: str,
    citaat: str,
    samenvatting: str,
    stuk: str | None,
    moment: datetime,
    moment_url: str | None,
    vraag_moment: datetime | None = None,
    first_in_thread: bool = True,
    status: str = STATUS_OPEN,
    door: str | None = None,
    termijn: str | None = None,
    bij_volgnummer: int | None = None,
    bevestigd: bool = False,
    uit_lijst: bool = False,
    vraagt_om: str | None = None,
    toegezegd: Sequence[int] = (),
    later_om: str | None = None,
    later_termijn: str | None = None,
) -> str:
    """The reply of a markering, whatever kind it is.

    For whoever writes a reply from a row: posting it, and writing it
    again when a reaction changed where it stands.
    """
    if soort == SOORT_TOEZEGGING:
        return format_toezegging_thread(
            volgnummer=volgnummer,
            # For a toezegging the column holds who it was promised to.
            aan=gericht_aan,
            citaat=citaat,
            samenvatting=samenvatting,
            termijn=termijn,
            bij_volgnummer=bij_volgnummer,
            moment=moment,
            moment_url=moment_url,
            vraag_moment=vraag_moment,
            first_in_thread=first_in_thread,
            status=status,
            door=door,
            bevestigd=bevestigd,
            uit_lijst=uit_lijst,
        )
    if soort == SOORT_MOTIE:
        return format_motie_thread(
            volgnummer=volgnummer,
            citaat=citaat,
            moment=moment,
            moment_url=moment_url,
            vraag_moment=vraag_moment,
            first_in_thread=first_in_thread,
            status=status,
            door=door,
        )
    return format_vraag_thread(
        volgnummer=volgnummer,
        gericht_aan=gericht_aan,
        citaat=citaat,
        samenvatting=samenvatting,
        stuk=stuk,
        moment=moment,
        moment_url=moment_url,
        vraag_moment=vraag_moment,
        first_in_thread=first_in_thread,
        status=status,
        door=door,
        vraagt_om=vraagt_om,
        # Of a question the column holds by when the member asks it.
        termijn=termijn,
        toegezegd=toegezegd,
        later_om=later_om,
        later_termijn=later_termijn,
    )


def _kop(samenvatting: str, citaat: str, leeg: str = "Vraag") -> str:
    """What the question is, for the first line, ready to be made bold.

    The summary of the model. A model that left it out, or wrote only
    what is taken out as unsafe, gets the first sentence of the quote: a
    first line that is empty would be four asterisks.
    """
    kop = _vrij(_kort(samenvatting, MAX_SAMENVATTING)).strip()
    if kop:
        return kop
    zin = _EERSTE_ZIN.search(citaat)
    eerste = citaat[: zin.end()] if zin else citaat
    return _vrij(_kort(eerste, MAX_KOP)).strip() or leeg


def _vrij(tekst: str) -> str:
    """Text a model wrote, or chose, made harmless for a message.

    Escaping alone is not enough: a model that writes a backslash before
    an at-sign gets the backslash escaped and the mention live. So no
    backslashes and no at-signs at all, and an address is broken up so it
    does not become a link.
    """
    tekst = tekst.replace("\\", "").replace("@", "")
    tekst = tekst.replace("://", ": //").replace("www.", "www ")
    return _escape(tekst)


def aan_wie(gericht_aan: str) -> str:
    """Who a question is put to, in our words and not the model's."""
    aan = gericht_aan.lower()
    if "staatssecretaris" in aan:
        return "de staatssecretaris"
    if "minister-president" in aan or "premier" in aan:
        return "de minister-president"
    if "minister" in aan:
        return "de minister"
    if "kabinet" in aan or "regering" in aan:
        return "het kabinet"
    return "de bewindspersoon"


# --- the answer of the model -------------------------------------------


@dataclass(frozen=True)
class _Nieuw:
    citaat: str
    gericht_aan: str
    samenvatting: str
    stuk: str | None
    # Where in the text of the turn the quote begins.
    plek: int = 0
    soort: str = SOORT_VRAAG
    # Of a toezegging: by when, and the number of the question it answers.
    # Of a question that asks for something on paper: by when it asks it.
    termijn: str | None = None
    bij_volgnummer: int | None = None
    # Of a question: what it asks for on paper, if anything.
    vraagt_om: str | None = None


@dataclass(frozen=True)
class _Herhaling:
    """A turn that comes back to a markering that is there."""

    volgnummer: int
    citaat: str
    # `herhaling`, `antwoord` for a toezegging on the question it answers,
    # or `bevestiging` for a toezegging the chairman's list reads out.
    soort: str = VERMELDING_HERHALING
    # Of a toezegging said again or read out: by when, if it was named
    # this time.
    termijn: str | None = None
    # Of a toezegging read out by the chairman: who it was promised to, if
    # the chairman said so.
    aan: str | None = None
    # Of a question asked again: whether it asks for something on paper
    # this time. What and by when is read from `citaat` when the reply of
    # the question is written (`later_op_papier`); this only says that
    # the reply has to be written again.
    op_papier: bool = False


def _woorden(tekst: str) -> list[str]:
    plat = unicodedata.normalize("NFKD", tekst.lower())
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", plat)


def stuk_blijkt_uit_citaat(citaat: str, titel: str, onderwerp: str) -> bool:
    """Whether the quote itself points at this agenda document.

    The model is asked for the document only when the speaker names it, and
    on a real debate it still picked one for half of the questions: every
    question in a debate is about the subject of the debate. So the choice
    is checked. What sets a document apart is in its title and not in the
    subject of the debate ("Reactie van het kabinet op ..."), and one of
    those words has to be in the quote ("uit de kabinetsreactie maak ik
    op"). A document whose title is the subject is never named: that a
    question is about it says nothing.
    """
    algemeen = set(_woorden(onderwerp))
    eigen = [w for w in _woorden(titel) if len(w) >= 5 and w not in algemeen]
    gezegd = " ".join(_woorden(citaat))
    return any(woord in gezegd for woord in eigen)


def lees_antwoord(
    vragen: Sequence[DebatVraag],
    tekst: str,
    stukken: Sequence[str],
    openstaand: set[int],
    onderwerp: str = "",
    *,
    moties: Sequence[Motie] = (),
    van_initiatiefnemer: bool = False,
) -> tuple[list[_Nieuw], list[_Herhaling], int]:
    """Sort what the model answered into new, repeated and dropped.

    Dropped: a question that is not to the bewindspersoon, a quote that is
    not in the turn, and a second answer with the same quote. A `hoort_bij`
    that is not an open question is a number the model made up; the question
    is then new. A `stuk` that is not on the agenda, or that the quote does
    not point at, is left out.

    Dropped as well, whatever the model says about it, because on four
    real debates a paragraph in the prompt did not stop the model:

    * a quote that is the text of a motie, or stands inside one that is
      read out in this turn (`moties`). A dictum asks the cabinet something
      in form; it is marked as a motie, once;
    * a quote without the form of a question or a request
      (`has_question_form`): a statement the model made a question of.
      A quote that asks for something on paper (`paper_request`) is a
      request whatever its form;
    * in a turn of an initiatiefnemer (`van_initiatiefnemer`), a quote that
      does not name the bewindspersoon. They sit at the table to answer,
      and a question in their turn is one they repeat or put to the room.

    Measured on the three debates these were made on, over five runs: the
    checks took away 12 to 21 of the 26 to 43 wrong markings per run and
    not one question the labeller was sure of.

    A question that is kept is looked at once more, by rule: whether it
    asks for something on paper, and by when (`paper_request`). That adds
    a property to the question and never drops or adds one.

    A member who comes back to a question that got no answer often asks
    for a letter then ("Kan de minister dat overzicht dan naar de Kamer
    sturen?"), and the model files that under the question that is open:
    one of the two requests that were missed in the first run on the gold
    set. The property is not put on that question: its quote names no
    letter, and what a rule got wrong there would stay for good. The
    later turn is a vermelding with its own quote, and the reply of the
    question says what was asked for later, read from that quote each
    time the reply is written.
    """
    nieuw: list[_Nieuw] = []
    herhaald: list[_Herhaling] = []
    afgevallen = 0
    gezien: set[str] = set()
    for vraag in vragen:
        aan = vraag.gericht_aan.lower()
        if not any(woord in aan for woord in _AAN_BEWINDSPERSOON):
            afgevallen += 1
            logger.info("Vraag aan %r is niet aan de bewindspersoon", aan[:60])
            continue
        gevonden = locate_citaat(tekst, vraag.citaat)
        if gevonden is None:
            afgevallen += 1
            logger.info(
                "Citaat staat niet in de spreekbeurt, vraag valt af: %s",
                vraag.citaat[:120],
            )
            continue
        citaat, plek = gevonden
        sleutel = _plat(citaat)[0]
        if sleutel in gezien:
            afgevallen += 1
            continue
        gezien.add(sleutel)
        waarom = _geen_vraag(citaat, plek, moties, van_initiatiefnemer)
        if waarom:
            afgevallen += 1
            logger.info("Citaat valt af als vraag, %s: %s", waarom, citaat[:120])
            continue
        op_papier = paper_request(citaat)
        vraagt_om = op_papier.product if op_papier else None
        termijn = (
            _kort(op_papier.moment, MAX_TERMIJN)
            if op_papier and op_papier.moment
            else None
        )
        if vraag.hoort_bij is not None and vraag.hoort_bij in openstaand:
            if all(h.volgnummer != vraag.hoort_bij for h in herhaald):
                herhaald.append(
                    _Herhaling(vraag.hoort_bij, citaat, op_papier=bool(vraagt_om))
                )
            continue
        stuk = None
        if vraag.stuk is not None and 1 <= vraag.stuk <= len(stukken):
            titel = stukken[vraag.stuk - 1]
            if stuk_blijkt_uit_citaat(citaat, titel, onderwerp):
                stuk = titel
        nieuw.append(
            _Nieuw(
                citaat=citaat,
                gericht_aan=_kort(vraag.gericht_aan, MAX_GERICHT_AAN),
                samenvatting=_kort(vraag.samenvatting, MAX_SAMENVATTING),
                stuk=stuk,
                plek=plek,
                vraagt_om=vraagt_om,
                termijn=termijn,
            )
        )
    return nieuw, herhaald, afgevallen


def _geen_vraag(
    citaat: str, plek: int, moties: Sequence[Motie], van_initiatiefnemer: bool
) -> str:
    """Why a quote that stands in the turn is no question, or an empty string."""
    eind = plek + len(citaat)
    # Inside a motie that was found in this turn: at least half of the
    # quote. A question that ends where a motie begins is still a question.
    if is_motion_text(citaat) or any(
        motie.vorm == VORM_INGEDIEND
        and 2 * (min(eind, motie.end) - max(plek, motie.start)) >= len(citaat)
        for motie in moties
    ):
        return "tekst van een motie"
    # A request for something on paper is a request, also in a wording
    # the check for questions does not know ("Ik zou graag vóór de
    # begrotingsbehandeling een brief van de minister ontvangen", from the
    # made-up debate). The form check dropped 2 of the 6 requests the
    # labeller was sure of. Only a wording of asking counts for this
    # (`paper_request`): a statement with a letter and a verb of sending in
    # it ("de wethouder stuurt ouders een brief") is dropped as before.
    if not has_question_form(citaat) and paper_request(citaat) is None:
        return "geen vorm van een vraag"
    if van_initiatiefnemer and not _noemt_bewindspersoon(citaat):
        return "initiatiefnemer noemt de bewindspersoon niet"
    return ""


def lees_toezeggingen(
    toezeggingen: Sequence[DebatToezegging],
    tekst: str,
    vragen: Mapping[int, str],
    eerdere: dict[int, str],
    onderwerp: str = "",
    *,
    vragenstellers: Mapping[int, str] | None = None,
    interruptie: Interruption | None = None,
) -> tuple[list[_Nieuw], list[_Herhaling], int]:
    """Sort what the model found in an answer into new, repeated and dropped.

    As strict as `lees_antwoord` is for a question. Dropped: a quote that
    is not in the turn, a second answer with the same quote, and a quote
    without the form of a commitment (`has_commitment_form`): work that is
    going on, what someone else promised, a refusal, "daar kom ik zo op
    terug".

    A `hoort_bij` that is one of `eerdere`, the toezeggingen this
    bewindspersoon made before by number with what each promised, makes it
    a herhaling on that one and not a second toezegging, when the two share
    a subject by their words (`shares_a_subject`). A moment that is named
    with the herhaling goes along, for the first one if it had none.

    Which question a toezegging answers and who it was promised to is
    decided by `link_to_question`: by where the toezegging stands first,
    with the model's `bij_vraag` as confirmation. `vragen` are the open
    questions by number with what each asks, `vragenstellers` who asked
    each, `interruptie` the turn of a member right before this answer. A
    number the model made up, or a question that is only near it, is left
    out, and then nobody is named either unless the answer is to an
    interruption. A `termijn` the quote does not name is left out too: it
    is shown as what was said.
    """
    nieuw: list[_Nieuw] = []
    herhaald: list[_Herhaling] = []
    afgevallen = 0
    gezien: set[str] = set()
    for toezegging in toezeggingen:
        gevonden = locate_citaat(tekst, toezegging.citaat)
        if gevonden is None:
            afgevallen += 1
            logger.info(
                "Citaat staat niet in de spreekbeurt, toezegging valt af: %s",
                toezegging.citaat[:120],
            )
            continue
        citaat, plek = gevonden
        sleutel = _plat(citaat)[0]
        if sleutel in gezien:
            afgevallen += 1
            continue
        gezien.add(sleutel)
        if not has_commitment_form(citaat):
            afgevallen += 1
            logger.info("Citaat is geen toezegging naar de vorm: %s", citaat[:120])
            continue
        termijn = _kort(toezegging.termijn or "", MAX_TERMIJN)
        termijn = termijn if termijn and deadline_is_said(termijn, citaat) else ""
        samenvatting = _kort(toezegging.samenvatting, MAX_SAMENVATTING)
        # "Said again" is the model's word, and a herhaling leaves nothing
        # in the channel. So it is believed only when the two are about
        # the same thing by their words; another promise the model filed
        # under an earlier one is stored as new.
        if toezegging.hoort_bij in eerdere and shares_a_subject(
            f"{samenvatting} {citaat}", eerdere[toezegging.hoort_bij], onderwerp
        ):
            if all(h.volgnummer != toezegging.hoort_bij for h in herhaald):
                herhaald.append(
                    _Herhaling(toezegging.hoort_bij, citaat, termijn=termijn or None)
                )
            continue
        link = link_to_question(
            quote=citaat,
            said_before=tekst[max(0, plek - SAID_BEFORE) : plek],
            summary=samenvatting,
            named=toezegging.bij_vraag,
            questions=vragen,
            askers=vragenstellers or {},
            onderwerp=onderwerp,
            interruption=interruptie,
            at_start=plek < AT_START,
        )
        if toezegging.bij_vraag is not None and link.vraag != toezegging.bij_vraag:
            logger.info(
                "Toezegging hoort niet aantoonbaar bij vraag %s, wel bij %s",
                toezegging.bij_vraag,
                link.vraag,
            )
        nieuw.append(
            _Nieuw(
                citaat=citaat,
                # Who it was promised to is not the model's to say.
                gericht_aan=_kort(link.aan, MAX_GERICHT_AAN),
                samenvatting=samenvatting,
                stuk=None,
                plek=plek,
                soort=SOORT_TOEZEGGING,
                termijn=termijn or None,
                bij_volgnummer=link.vraag,
            )
        )
    return nieuw, herhaald, afgevallen


def lees_slotlijst(
    toezeggingen: Sequence[DebatToezegging],
    tekst: str,
    eerdere: Mapping[int, str],
    onderwerp: str = "",
    leden: Sequence[str] = (),
) -> tuple[list[_Nieuw], list[_Herhaling], int]:
    """Sort what the model found in the chairman's list into new, confirmed
    and dropped.

    Dropped: a quote that is not in the list, a second answer with the
    same quote or one that begins inside another, and a quote without the
    form of an item (`is_listed_commitment`): the opening of the list, a
    word of thanks, the announcement of a tweeminutendebat.

    An item is a toezegging of `eerdere`, the ones that were marked during
    the debate by number with what each promised, when the model names it
    in `hoort_bij` and the code finds it so by their words
    (`match_listed`): both, never one of the two. That one is confirmed,
    and gets the moment and the member the chairman names if it had none.
    Every other item is new: a toezegging that was missed during the
    debate, with the chairman's wording as its quote. An item that was
    marked and is not matched is there twice; that is the cheaper mistake.

    Who an item was promised to is the member the chairman names right
    behind it, when that is one of `leden` (`promised_to`). Right behind
    it: up to the next thing the model quoted, also when that quote is
    dropped here.
    """
    afgevallen = 0
    grenzen: list[int] = []
    items: list[tuple[int, str, DebatToezegging]] = []
    for toezegging in toezeggingen:
        gevonden = locate_citaat(tekst, toezegging.citaat)
        if gevonden is None:
            afgevallen += 1
            logger.info(
                "Citaat staat niet in de slotlijst, toezegging valt af: %s",
                toezegging.citaat[:120],
            )
            continue
        citaat, plek = gevonden
        # Where anything the model quoted begins, kept or not: the member
        # named behind a quote that is dropped is not the member of the
        # item before it.
        grenzen.append(plek)
        if not is_listed_commitment(citaat):
            afgevallen += 1
            logger.info("Citaat uit de slotlijst is geen toezegging: %s", citaat[:120])
            continue
        items.append((plek, citaat, toezegging))
    items.sort(key=lambda item: item[0])

    nieuw: list[_Nieuw] = []
    bevestigd: list[_Herhaling] = []
    vergeven: set[int] = set()
    einde_vorige = 0
    for plek, citaat, toezegging in items:
        if plek < einde_vorige:
            # The same item twice, whether or not it is cut the same way.
            afgevallen += 1
            continue
        einde_vorige = plek + len(citaat)
        volgende = min((g for g in grenzen if g >= einde_vorige), default=len(tekst))
        aan = promised_to(tekst[einde_vorige:volgende], leden)
        termijn = _kort(toezegging.termijn or "", MAX_TERMIJN)
        termijn = termijn if termijn and deadline_is_said(termijn, citaat) else ""
        samenvatting = _kort(toezegging.samenvatting, MAX_SAMENVATTING)
        nummer = match_listed(
            f"{samenvatting} {citaat}",
            toezegging.hoort_bij,
            eerdere,
            onderwerp,
            vergeven,
        )
        if nummer is not None:
            vergeven.add(nummer)
            bevestigd.append(
                _Herhaling(
                    nummer,
                    citaat,
                    VERMELDING_BEVESTIGING,
                    termijn=termijn or None,
                    aan=_kort(aan, MAX_GERICHT_AAN) or None,
                )
            )
            continue
        nieuw.append(
            _Nieuw(
                citaat=citaat,
                gericht_aan=_kort(aan, MAX_GERICHT_AAN),
                samenvatting=samenvatting,
                stuk=None,
                plek=plek,
                soort=SOORT_TOEZEGGING,
                termijn=termijn or None,
            )
        )
    return nieuw, bevestigd, afgevallen


# Where a sentence ends: not at the three dots of a line that runs on.
_ZIN_EINDE = re.compile(r"(?<!\.\.)[.?!](?=\s)")


def answer_window(tekst: str, vanaf: int) -> tuple[int, int] | None:
    """The next window of an answer to ask the model about, as (begin, end).

    `vanaf` is how far the answer was read. The window ends where a
    sentence ends, about `ANTWOORD_VENSTER` further, and begins a sentence
    or two before `vanaf`: what stands between `begin` and `vanaf` was read
    before and goes along so that nothing on the boundary is read in
    halves. ``None`` when nothing is left to read.

    Where a window ends depends only on the text from `vanaf` on, so a
    text that is the same gives the same windows on every call.
    """
    lengte = min(len(tekst), MAX_ANTWOORD)
    if vanaf < 0 or vanaf >= lengte or not tekst[vanaf:lengte].strip():
        return None
    rest = tekst[vanaf:lengte]
    if len(rest) <= ANTWOORD_VENSTER + MIN_STAART:
        einde = lengte
    else:
        stuk = split_text(rest, limit=ANTWOORD_VENSTER, minimum=ANTWOORD_VENSTER // 2)[
            0
        ]
        einde = vanaf + rest.index(stuk) + len(stuk)
    begin = vanaf
    terug = max(0, vanaf - MAX_OVERLAP)
    ervoor = tekst[terug:vanaf].rstrip()
    # Where the sentences in front of `vanaf` begin, the last one first.
    starts = [found.end() for found in _ZIN_EINDE.finditer(ervoor)][::-1]
    starts = [start for start in starts if ervoor[start:].strip()]
    if starts:
        begin = terug + starts[min(OVERLAP_ZINNEN, len(starts)) - 1]
        while begin < vanaf and tekst[begin].isspace():
            begin += 1
    return begin, einde


def next_window(tekst: str, vanaf: int) -> tuple[int, int, int] | None:
    """The next window that is worth a call, as (read up to, begin, end).

    Windows in which the words of a commitment stand nowhere are passed
    over (`may_hold_commitment`): they cost a call and can mark nothing.
    That is decided per window, on what is new in it, and it errs to
    asking. `read up to` is where the passing over stopped: what is in
    front of it needs no model. ``None`` when no window is left that does.
    """
    while (venster := answer_window(tekst, vanaf)) is not None:
        begin, einde = venster
        if may_hold_commitment(tekst[vanaf:einde]):
            return vanaf, begin, einde
        vanaf = einde
    return None


def skip_window(tekst: str, vanaf: int) -> int:
    """Where an answer is read up to when the window at `vanaf` is given up on."""
    venster = next_window(tekst, vanaf)
    return len(tekst) if venster is None else venster[2]


# --- an answer that is still being given --------------------------------
#
# A turn of the bewindspersoon is read while it goes on, so that a
# toezegging is in the channel a minute after it was said and not when the
# turn is over: in the gold set that was a median of 74 seconds later and a
# ninth decile of 429. What is read is the part of the turn that is final
# (the worker decides which lines those are), up to the last sentence of it
# that is complete. Every round of a quarter of a minute brings a sentence
# or two, and a call per round would be 240 calls an hour, so a window is
# only asked about when one of these holds:
#
# * it is full: more than a window of final text is waiting, as in a turn
#   that is over;
# * a sentence in it looks like a toezegging (`commitment_passages`) and
#   the sentence after it is there. The sentence after it, because that is
#   where the moment is named ("Dat zeg ik toe. Die brief komt voor de
#   zomer."), and a quote stored without it is not stored again with it;
# * the words of a commitment stand somewhere in it and this much has been
#   said since the last window: `MEELEES_VENSTER`.
#
# Everything else waits for more text or for the end of the turn, where
# what is left is read as before.
MEELEES_VENSTER = 1500


def final_end(tekst: str) -> int:
    """Where the last complete sentence of a text ends.

    For the final part of a turn that goes on: what stands behind this is
    a sentence the speaker has not finished, or one the next subtitle line
    goes on with. The end of the text counts when it is a full stop: the
    next line starts a new sentence. Not the three dots of a line that
    runs on.
    """
    kaal = tekst.rstrip()
    if kaal and kaal[-1] in ".?!" and not kaal.endswith(".."):
        return len(kaal)
    einden = [found.end() for found in _ZIN_EINDE.finditer(tekst)]
    return einden[-1] if einden else 0


def _zinnen(tekst: str, vanaf: int, tot: int) -> list[tuple[int, int]]:
    """The sentences of `tekst[vanaf:tot]`, each as (begin, end)."""
    grenzen = [vanaf + found.end() for found in _ZIN_EINDE.finditer(tekst[vanaf:tot])]
    if not grenzen or grenzen[-1] < tot:
        grenzen.append(tot)
    zinnen: list[tuple[int, int]] = []
    begin = vanaf
    for einde in grenzen:
        if tekst[begin:einde].strip():
            zinnen.append((begin, einde))
        begin = einde
    return zinnen


def running_window(
    tekst: str, vanaf: int, venster: int | None = None
) -> tuple[int, int, int] | None:
    """The window of an answer that goes on that is worth a call now, as
    (read up to, begin, end); ``None`` when there is none yet.

    `tekst` is the final part of the turn, `vanaf` how far it was read.
    The window ends where a sentence ends that is complete, and never
    behind the last such sentence: the tail that is still coming is left
    for a later round. See above for when a window is asked about.
    `venster` is `MEELEES_VENSTER` when not given.

    As for a turn that is over (`next_window`), a full window without the
    words of a commitment is passed over, and `read up to` is where the
    passing over stopped.
    """
    drempel = MEELEES_VENSTER if venster is None else venster
    vast = tekst[: final_end(tekst)]
    while (gevonden := answer_window(vast, vanaf)) is not None:
        begin, einde = gevonden
        if einde < len(vast):
            # Full: cut by its size, with more final text behind it.
            if may_hold_commitment(vast[vanaf:einde]):
                return vanaf, begin, einde
            vanaf = einde
            continue
        # The last of what is final. A sentence that looks like a
        # toezegging at its very end waits for the sentence after it.
        zinnen = _zinnen(vast, vanaf, einde)
        lijkt = [bool(commitment_passages(vast[a:b])) for a, b in zinnen]
        while lijkt and lijkt[-1]:
            lijkt.pop()
        if not lijkt:
            return None
        einde = zinnen[len(lijkt) - 1][1]
        nieuw = vast[vanaf:einde]
        if any(lijkt) or (len(nieuw) >= drempel and may_hold_commitment(nieuw)):
            return vanaf, begin, einde
        return None
    return None


def post_holding(
    tekst: str, plek: int, post_id: str | None, vervolg: Sequence[str]
) -> str | None:
    """The message of a turn that holds the character at `plek` of its text.

    A long turn is cut over several messages (`split_text`): the first,
    and the ones in `vervolg`. A cut depends only on the text in front of
    it, so for a place in text that is final this is the message it stays
    in, however the turn goes on. A piece for which there is no message
    was put into the last one there is (`fit_messages`).
    """
    if post_id is None or not vervolg:
        return post_id
    einde = 0
    nummer = 0
    for nummer, stuk in enumerate(split_text(tekst)):
        einde = tekst.index(stuk, einde) + len(stuk)
        if plek < einde:
            break
    nummer = min(nummer, len(vervolg))
    return post_id if nummer == 0 else vervolg[nummer - 1]


def rol_van(spreker: str) -> str | None:
    """Whether a bewindspersoon is a minister or a staatssecretaris.

    From the label Debat Direct gives ("Naam (Staatssecretaris van ...)").
    ``None`` when it says neither.
    """
    label = spreker.lower()
    if "staatssecretaris" in label:
        return "de staatssecretaris"
    if "minister" in label:
        return "de minister"
    return None


# --- the service -------------------------------------------------------


async def statusblok_voor_post(session: AsyncSession, post_id: str) -> str:
    """The status block that belongs under the message of a turn.

    For whoever rewrites that message from scratch. Only markeringen with a
    thread count: a question whose thread could not be posted is not shown
    as marked.
    """
    rows = (
        await session.execute(
            select(DebatMarkering.soort, DebatMarkering.status)
            .where(
                DebatMarkering.beurt_post_id == post_id,
                DebatMarkering.thread_post_id.is_not(None),
            )
            .order_by(DebatMarkering.volgnummer)
        )
    ).all()
    return statusregel([(r[0], r[1]) for r in rows])


# Which markeringen can be put in the channel: those of a turn that has a
# message, and those from the chairman's list, which go in by themselves
# when the end of the debate has none.
_HEEFT_EEN_PLEK = or_(
    DebatMarkering.beurt_post_id.is_not(None),
    DebatMarkering.beurt_sleutel.like(f"{SLEUTEL_SLOTLIJST}%"),
)


def komt_uit_slotlijst(beurt_sleutel: str) -> bool:
    """Whether a markering was taken from the list the chairman reads at
    the end of the debate, by the key of its turn."""
    return beurt_sleutel.startswith(SLEUTEL_SLOTLIJST)


async def is_bevestigd(session: AsyncSession, markering_id: uuid.UUID) -> bool:
    """Whether the chairman read this toezegging out in the list at the end.

    For whoever writes the reply of a markering from its row.
    """
    return bool(
        await session.scalar(
            select(
                exists().where(
                    DebatMarkeringVermelding.markering_id == markering_id,
                    DebatMarkeringVermelding.soort == VERMELDING_BEVESTIGING,
                )
            )
        )
    )


async def toezeggingen_bij(
    session: AsyncSession, sessie_id: uuid.UUID, volgnummer: int
) -> tuple[int, ...]:
    """The numbers of the toezeggingen that answer a question of a debate.

    For whoever writes the reply of a question from its row. One that was
    rejected as no toezegging is not named: it promised nothing. Neither
    is one whose own reply is not in the channel: "toezegging 15" would
    point at nothing anyone can find.
    """
    return tuple(
        (
            await session.execute(
                select(DebatMarkering.volgnummer)
                .where(
                    DebatMarkering.sessie_id == sessie_id,
                    DebatMarkering.soort == SOORT_TOEZEGGING,
                    DebatMarkering.bij_volgnummer == volgnummer,
                    DebatMarkering.status != STATUS_VERWORPEN,
                    DebatMarkering.thread_post_id.is_not(None),
                )
                .order_by(DebatMarkering.volgnummer)
            )
        )
        .scalars()
        .all()
    )


async def later_op_papier(
    session: AsyncSession, markering_id: uuid.UUID
) -> PaperRequest | None:
    """What a question was asked for on paper when it was asked again.

    The first of the later turns that asks for something, by the rule on
    its own quote. Not kept on the row: read each time the reply is
    written, so what the rule says of that quote is what the reply shows.
    """
    citaten = (
        (
            await session.execute(
                select(DebatMarkeringVermelding.citaat)
                .where(
                    DebatMarkeringVermelding.markering_id == markering_id,
                    DebatMarkeringVermelding.soort == VERMELDING_HERHALING,
                )
                .order_by(
                    DebatMarkeringVermelding.created_at, DebatMarkeringVermelding.id
                )
            )
        )
        .scalars()
        .all()
    )
    for citaat in citaten:
        found = paper_request(citaat)
        if found is not None:
            return found
    return None


async def schrijf_statusregel(
    session: AsyncSession,
    mattermost: MattermostService,
    post_id: str,
    sessie_id: uuid.UUID | None = None,
) -> bool | None:
    """Put the status block under a message that nobody else writes.

    ``None`` for a message the transcription writes: the message of a
    turn, or one it continues in. That has one writer, and this is not
    it: a message read here and written back a moment later can be lines
    behind what the transcription put there in between. Whoever calls
    leaves the row without `statusregel_at`, and the transcription
    writes the message again, with the count
    (`DebatTranscript.write_counts`).

    For any other message (the end of a debate without words of the
    chairman, a message that is not in the table): reads it first and
    replaces only the status block. ``True`` when the line is as it
    should be, or never will be because the message is gone.
    """
    # Imported here: the transcription imports this module.
    from bouwmeester.services.debat_transcript_service import turn_of_message

    if await turn_of_message(session, post_id, sessie_id) is not None:
        return None
    return await vervang_statusblok(session, mattermost, post_id)


async def vervang_statusblok(
    session: AsyncSession, mattermost: MattermostService, post_id: str
) -> bool:
    """Replace the status block of a message and leave its text as it is.

    Read, and written back with another block. ``True`` when the line is
    as it should be, or never will be because the message is gone. Only
    for whoever is sure nothing writes the message in between: the
    timeline for any message (`DebatTranscript.write_counts`), the
    marking for a message that is not a turn's (`schrijf_statusregel`).
    """
    blok = await statusblok_voor_post(session, post_id)
    try:
        post = await mattermost.get_post(post_id)
    except PostNotFoundError:
        logger.info("Bericht %s is weg; geen statusregel", post_id)
        return True
    except Exception as exc:
        # One line and what kind of error: this is tried again, by a round
        # that comes every few seconds.
        logger.warning(
            "Bericht %s niet te lezen voor de statusregel (%s)",
            post_id,
            type(exc).__name__,
        )
        return False
    if not post:
        return False
    huidig = str(post.get("message") or "")
    nieuw = met_status(huidig, blok)
    if nieuw == huidig:
        return True
    try:
        # The props go back as they came: an update without them is an
        # update that clears them.
        return bool(
            await mattermost.update_post(post_id, nieuw, post.get("props") or None)
        )
    except Exception as exc:
        logger.warning(
            "Statusregel op bericht %s niet geschreven (%s)",
            post_id,
            type(exc).__name__,
        )
        return False


class DebatVraagService:
    def __init__(
        self,
        session: AsyncSession,
        mattermost: MattermostService,
        llm: BaseLLMService,
    ) -> None:
        self.session = session
        self.mattermost = mattermost
        self.llm = llm
        self._ingehaald: set[uuid.UUID] = set()
        # How often the model was asked, for whoever bounds that.
        self.aanroepen = 0

    @classmethod
    async def create(
        cls, session: AsyncSession, mattermost: MattermostService | None = None
    ) -> DebatVraagService | None:
        """A service on the configured model, or ``None`` if there is none.

        A debate is public and broadcast, so any provider may read it.
        """
        from bouwmeester.services.llm import get_llm_service

        llm = await get_llm_service(session)
        if llm is None:
            return None
        return cls(session, mattermost or MattermostService(session), llm)

    def nieuwe_ronde(self) -> None:
        """For whoever keeps one service over several rounds."""
        self._ingehaald.clear()

    async def beoordeel_beurt(self, beurt: Beurt, context: DebatContext) -> Beoordeling:
        """Judge one finished turn, and post what it holds.

        Safe to call again for the same turn: the model is asked once, and
        a thread is posted once.
        """
        # Threads and status lines of earlier turns that did not make it.
        # Once per debate for as long as this service lives, which is one
        # round: tried with every turn, a Mattermost that is down for a
        # moment would use up all attempts within that one round.
        threads = 0
        if beurt.sessie_id not in self._ingehaald:
            self._ingehaald.add(beurt.sessie_id)
            threads = await self._haal_achterstand_in(beurt.sessie_id)

        if beurt.slotlijst:
            return await self._beoordeel_slotlijst(beurt, context, threads)
        reden = self._overslaan(beurt, context)
        if reden == REDEN_BEWINDSPERSOON:
            # An answer holds no questions and no moties. It is read for
            # one thing only: what the bewindspersoon promises in it.
            return await self._beoordeel_antwoord(beurt, context, threads)
        # A motie is looked for in every turn of a member, also in the ones
        # the model is not asked about: an interruption of a colleague is
        # where "ik dien hier een motie over in" is said. Not in a turn of
        # the chairman, who reads nothing out, and not in one of the
        # bewindspersoon, who repeats the words of a motie to judge it.
        moties: list[Motie] = []
        if reden not in (REDEN_VOORZITTER, REDEN_BEWINDSPERSOON):
            moties = find_moties(beurt.tekst)
        if reden and not moties:
            return Beoordeling(UITKOMST_OVERGESLAGEN, reden=reden, threads=threads)

        # Was this turn read before? For a turn the model is asked about,
        # that is when the model's answer was stored: its moties alone say
        # nothing, they are also stored when the model could not be asked.
        gelezen = await self._eerder_beoordeeld(
            beurt.sessie_id, beurt.sleutel, door_model=not reden
        )
        if gelezen is not None:
            alles = await self._eerder_beoordeeld(beurt.sessie_id, beurt.sleutel)
            return Beoordeling(
                UITKOMST_AL_BEOORDEELD, markering_ids=alles or (), threads=threads
            )

        gevonden = [
            _Nieuw(
                citaat=motie.citaat,
                gericht_aan="",
                samenvatting="",
                stuk=None,
                plek=motie.plek,
                soort=SOORT_MOTIE,
            )
            for motie in moties
        ]
        if reden:
            # Only the moties: the rest of this turn is not for the model.
            return await self._markeer(beurt, gevonden, [], {}, threads, 0)

        open_ids = await self._openstaand(beurt.sessie_id, beurt.spreker)
        openstaand = [(nummer, wie, wat) for nummer, wie, wat, _ in open_ids]
        van_initiatiefnemer = _is_initiatiefnemer(beurt, context)
        result = await self.llm.markeer_debat_vragen(
            onderwerp=context.onderwerp,
            soort_vergadering=context.soort,
            bewindspersonen=[
                f"{b.functie}: {b.naam}" if b.functie else b.naam
                for b in context.bewindspersonen
            ],
            stukken=list(context.stukken),
            openstaand=openstaand,
            spreker=beurt.spreker,
            interruptie=beurt.soort == SOORT_INTERRUPTER,
            tekst=beurt.tekst,
            onderbroken=beurt.onderbroken,
            initiatiefnemers=context.initiatiefnemers,
            initiatiefnemer_namen=[
                f"{i.naam} ({i.fractie})" if i.fractie else i.naam
                for i in context.initiatiefnemer_namen
            ],
            spreker_is_initiatiefnemer=van_initiatiefnemer,
        )
        if result.fout and gevonden:
            # The moties of this turn are a rule and do not wait for the
            # model. Stored now, a model that stays away loses none; the
            # turn still counts as not read, so its questions are asked
            # for again, and a motie that is there is not stored twice.
            logger.warning(
                "Spreekbeurt van %s in sessie %s: model %s, alleen de moties",
                _hhmm(beurt.start),
                beurt.sessie_id,
                result.fout,
            )
            opgeslagen = await self._markeer(beurt, gevonden, [], {}, threads, 0)
            if result.fout == DEBAT_VRAGEN_ONBEREIKBAAR:
                return replace(opgeslagen, uitkomst=UITKOMST_LLM_ONBEREIKBAAR)
            return opgeslagen
        if result.fout:
            logger.warning(
                "Spreekbeurt van %s in sessie %s niet beoordeeld: model %s",
                _hhmm(beurt.start),
                beurt.sessie_id,
                result.fout,
            )
            return Beoordeling(
                UITKOMST_LLM_ONBEREIKBAAR
                if result.fout == DEBAT_VRAGEN_ONBEREIKBAAR
                else UITKOMST_LLM_ONBRUIKBAAR,
                threads=threads,
            )

        nieuw, herhaald, afgevallen = lees_antwoord(
            result.vragen,
            beurt.tekst,
            context.stukken,
            {nummer for nummer, _, _ in openstaand},
            context.onderwerp,
            moties=moties,
            van_initiatiefnemer=van_initiatiefnemer,
        )
        if not nieuw and not herhaald and not gevonden:
            return Beoordeling(
                UITKOMST_GEEN_VRAAG, threads=threads, afgevallen=afgevallen
            )
        return await self._markeer(
            beurt,
            # Numbered in the order they were said.
            sorted([*nieuw, *gevonden], key=lambda n: n.plek),
            herhaald,
            {nummer: id_ for nummer, _, _, id_ in open_ids},
            threads,
            afgevallen,
        )

    async def _beoordeel_antwoord(
        self, beurt: Beurt, context: DebatContext, threads: int
    ) -> Beoordeling:
        """Read a turn of the bewindspersoon for toezeggingen.

        Whether a sentence commits to anything is for the model. Before it
        is asked, the code looks whether the words of a commitment are in
        the window at all (`next_window`). After it answered, each quote
        has to stand in the turn and have the form of a commitment
        (`lees_toezeggingen`).
        """
        if len(beurt.tekst.split()) < MIN_WOORDEN:
            return Beoordeling(
                UITKOMST_OVERGESLAGEN, reden=REDEN_BEWINDSPERSOON, threads=threads
            )
        tekst = beurt.tekst
        gelezen = min(max(0, beurt.gelezen_tot), len(tekst))
        if beurt.loopt:
            # The turn goes on: only what `running_window` says is worth a
            # call now, and whatever comes of it there is more to read.
            venster = running_window(tekst, gelezen)
            if venster is None:
                return Beoordeling(
                    UITKOMST_GEEN_TOEZEGGING,
                    threads=threads,
                    gelezen_tot=gelezen,
                    meer=True,
                )
        else:
            if gelezen == 0 and not may_hold_commitment(tekst):
                return Beoordeling(
                    UITKOMST_OVERGESLAGEN,
                    reden=REDEN_BEWINDSPERSOON,
                    threads=threads,
                    gelezen_tot=len(tekst),
                )
            # One window per call. An answer of ten minutes is three
            # windows, each a model call of its own, and a caller that
            # waits for all of them waits longer than a turn may take. What
            # a window holds is stored before the call returns, so a window
            # that was read is never asked about again, whatever becomes of
            # the next.
            venster = next_window(tekst, gelezen)
            if venster is None:
                return Beoordeling(
                    UITKOMST_AL_BEOORDEELD if gelezen else UITKOMST_GEEN_TOEZEGGING,
                    threads=threads,
                    gelezen_tot=len(tekst),
                )
        vanaf, begin, einde = venster
        heel = (
            not beurt.loopt
            and gelezen == 0
            and begin == 0
            and next_window(tekst, einde) is None
        )
        if heel:
            # The whole answer is one window: stored once, as a turn of a
            # member is, and a second call for it asks nothing.
            eerder = await self._eerder_beoordeeld(beurt.sessie_id, beurt.sleutel)
            if eerder is not None:
                return Beoordeling(
                    UITKOMST_AL_BEOORDEELD,
                    markering_ids=eerder,
                    threads=threads,
                    gelezen_tot=len(tekst),
                )
        deel = tekst[begin:einde]
        # With no window behind this one that needs the model, the answer
        # is read to its end. Not one that goes on: it is read as far as
        # this window, and its end is not there yet.
        meer = beurt.loopt or next_window(tekst, einde) is not None
        tot = einde if meer else len(tekst)

        vragen = await self._vragen_aan(beurt.sessie_id, beurt.spreker, beurt.start)
        # With what earlier windows of this same answer promised: those
        # are rows by now, so one said again further on is a herhaling.
        eerdere = await self._toezeggingen_van(beurt.sessie_id, beurt.spreker)
        self.aanroepen += 1
        result = await self.llm.markeer_debat_toezeggingen(
            onderwerp=context.onderwerp,
            soort_vergadering=context.soort,
            bewindspersonen=[
                f"{b.functie}: {b.naam}" if b.functie else b.naam
                for b in context.bewindspersonen
            ],
            spreker=beurt.spreker,
            tekst=deel,
            vragen=[(nummer, wie, wat) for nummer, wie, wat, _, _ in vragen],
            eerdere=[(nummer, wat) for nummer, wat, _, _ in eerdere],
            voorafgaand=beurt.voorafgaand,
            voorafgaand_tekst=beurt.voorafgaand_tekst,
            # Of what is new in the window: the sentences in front of it
            # were pointed at the last time.
            passages=commitment_passages(tekst[vanaf:einde]),
        )
        if result.fout == DEBAT_VRAGEN_ONBEREIKBAAR:
            # Not read: the same window is asked about again later. What
            # earlier windows held stays stored.
            logger.warning(
                "Antwoord van %s in sessie %s, vanaf teken %d: model onbereikbaar",
                _hhmm(beurt.start),
                beurt.sessie_id,
                vanaf,
            )
            return Beoordeling(
                UITKOMST_LLM_ONBEREIKBAAR,
                threads=threads,
                gelezen_tot=vanaf,
                meer=True,
            )
        if result.fout:
            # The model answered twice with something unreadable. Asking a
            # third time gives the same; this window counts as read, and
            # the windows after it are still read.
            logger.warning(
                "Antwoord van %s in sessie %s, vanaf teken %d: model %s",
                _hhmm(beurt.start),
                beurt.sessie_id,
                vanaf,
                result.fout,
            )
            return Beoordeling(
                UITKOMST_LLM_ONBRUIKBAAR,
                threads=threads,
                gelezen_tot=tot,
                meer=meer,
            )

        interruptie = None
        if beurt.voorafgaand:
            interruptie = Interruption(
                spreker=_kort(beurt.voorafgaand, MAX_GERICHT_AAN),
                tekst=beurt.voorafgaand_tekst,
                vragen=await self._vragen_in(
                    beurt.sessie_id, beurt.voorafgaand_sleutel
                ),
            )
        nieuw, herhaald, afgevallen = lees_toezeggingen(
            result.toezeggingen,
            beurt.tekst,
            {nummer: waarover for nummer, _, _, _, waarover in vragen},
            {nummer: waarover for nummer, _, _, waarover in eerdere},
            context.onderwerp,
            vragenstellers={nummer: wie for nummer, wie, _, _, _ in vragen},
            interruptie=interruptie,
        )
        if not nieuw and not herhaald:
            return Beoordeling(
                UITKOMST_GEEN_TOEZEGGING,
                threads=threads,
                afgevallen=afgevallen,
                gelezen_tot=tot,
                meer=meer,
            )
        nieuw = sorted(nieuw, key=lambda n: n.plek)
        # On the question a toezegging answers, a vermelding that says so.
        # Where the question stands is not touched: whether a promise is an
        # answer is for the people who follow the debate to say.
        antwoorden = [
            _Herhaling(n.bij_volgnummer, n.citaat, VERMELDING_ANTWOORD)
            for n in nieuw
            if n.bij_volgnummer is not None
        ]
        stored = await self._markeer(
            beurt,
            nieuw,
            [*herhaald, *antwoorden],
            {
                **{nummer: id_ for nummer, _, _, id_, _ in vragen},
                **{nummer: id_ for nummer, _, id_, _ in eerdere},
            },
            threads,
            afgevallen,
            # Of a longer answer every window adds to what is there.
            aanvullen=not heel,
            # While the turn goes on, how far it was read is kept with what
            # was found: see `_leg_vast`.
            gelezen_tot=tot if beurt.loopt else None,
        )
        return replace(stored, gelezen_tot=tot, meer=meer)

    async def _beoordeel_slotlijst(
        self, beurt: Beurt, context: DebatContext, threads: int
    ) -> Beoordeling:
        """Read the list of toezeggingen the chairman reads out at the end.

        Read once: what it held is stored under the key of the list, and a
        second call asks nothing. A turn of the chairman that does not
        open such a list is not read, whoever hands it in
        (`opens_closing_list`).

        An item that is a toezegging of this debate leaves a vermelding on
        it, and its reply is written again from the row, by the round of
        the reactions, to say that the chairman confirmed it. An item that
        was not marked is stored as a toezegging of its own, under the
        message of the chairman.
        """
        if beurt.soort != SOORT_CHAIRMAN or not opens_closing_list(beurt.tekst):
            return Beoordeling(
                UITKOMST_OVERGESLAGEN, reden=REDEN_VOORZITTER, threads=threads
            )
        eerder = await self._eerder_beoordeeld(beurt.sessie_id, beurt.sleutel)
        if eerder is not None:
            return Beoordeling(
                UITKOMST_AL_BEOORDEELD, markering_ids=eerder, threads=threads
            )
        gemarkeerd = await self._toezeggingen_in(beurt.sessie_id)
        result = await self.llm.markeer_debat_slotlijst(
            onderwerp=context.onderwerp,
            soort_vergadering=context.soort,
            tekst=beurt.tekst,
            eerdere=[(nummer, wie, wat) for nummer, wie, wat, _, _ in gemarkeerd],
        )
        if result.fout:
            logger.warning(
                "Slotlijst van %s in sessie %s niet gelezen: model %s",
                _hhmm(beurt.start),
                beurt.sessie_id,
                result.fout,
            )
            return Beoordeling(
                UITKOMST_LLM_ONBEREIKBAAR
                if result.fout == DEBAT_VRAGEN_ONBEREIKBAAR
                else UITKOMST_LLM_ONBRUIKBAAR,
                threads=threads,
            )
        nieuw, bevestigd, afgevallen = lees_slotlijst(
            result.toezeggingen,
            beurt.tekst,
            {nummer: waarover for nummer, _, _, _, waarover in gemarkeerd},
            context.onderwerp,
            await self._leden(beurt.sessie_id),
        )
        if not nieuw and not bevestigd:
            return Beoordeling(
                UITKOMST_GEEN_TOEZEGGING, threads=threads, afgevallen=afgevallen
            )
        stored = await self._markeer(
            beurt,
            nieuw,
            bevestigd,
            {nummer: id_ for nummer, _, _, id_, _ in gemarkeerd},
            threads,
            afgevallen,
        )
        return replace(stored, bevestigd=tuple(h.volgnummer for h in bevestigd))

    async def _toezeggingen_in(
        self, sessie_id: uuid.UUID
    ) -> list[tuple[int, str, str, uuid.UUID, str]]:
        """The toezeggingen that were marked in this debate, as (number, who
        promised, summary, id, summary and quote together).

        Of every bewindspersoon, and whatever became of them. Also the
        ones a reader rejected: when the chairman reads one out it was a
        toezegging, and the rejection was of its wording or of the
        marking. It is matched, so that the item is not posted next to it
        as a new one; where it stands is left to who rejected it. Not the
        ones that came from a list themselves: a list confirms what was
        said in the debate.
        """
        rows = (
            await self.session.execute(
                select(
                    DebatMarkering.volgnummer,
                    DebatMarkering.spreker,
                    DebatMarkering.samenvatting,
                    DebatMarkering.citaat,
                    DebatMarkering.id,
                )
                .where(
                    DebatMarkering.sessie_id == sessie_id,
                    DebatMarkering.soort == SOORT_TOEZEGGING,
                    DebatMarkering.beurt_sleutel.not_like(f"{SLEUTEL_SLOTLIJST}%"),
                )
                .order_by(DebatMarkering.volgnummer.desc())
                .limit(MAX_TOEZEGGINGEN_BIJ_LIJST)
            )
        ).all()
        return [
            (
                r[0],
                _kort(r[1], MAX_GERICHT_AAN),
                _kort(r[2] or r[3], MAX_SAMENVATTING),
                r[4],
                f"{r[2]} {r[3]}",
            )
            for r in sorted(rows, key=lambda r: r[0])
        ]

    async def _leden(self, sessie_id: uuid.UUID) -> list[str]:
        """The members of whom something was marked in this debate, by their
        label: who the chairman can name as who a toezegging was made to."""
        return list(
            (
                await self.session.execute(
                    select(DebatMarkering.spreker)
                    .where(
                        DebatMarkering.sessie_id == sessie_id,
                        DebatMarkering.fractie.is_not(None),
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

    async def _vragen_aan(
        self, sessie_id: uuid.UUID, spreker: str, voor: datetime
    ) -> list[tuple[int, str, str, uuid.UUID, str]]:
        """The open questions put to this bewindspersoon, as (number, who
        asked, summary, id, summary and quote together).

        Everyone's, unlike `_openstaand`: an answer is to whoever asked.
        With two bewindspersonen at the table a question put to "de
        staatssecretaris" is not one the minister answers, so a question
        that names the other of the two is left out. One to "het kabinet",
        or to nobody in particular, stays.

        Only what was asked before this turn began (`voor`). The turns of
        members are read first in a round, so a question from after the
        answer can be stored before the answer is read; a toezegging does
        not answer what was not asked yet.

        The most recent `MAX_VRAGEN_BIJ_ANTWOORD`, in the order they were
        asked.
        """
        rows = (
            await self.session.execute(
                select(
                    DebatMarkering.volgnummer,
                    DebatMarkering.spreker,
                    DebatMarkering.samenvatting,
                    DebatMarkering.citaat,
                    DebatMarkering.id,
                    DebatMarkering.gericht_aan,
                )
                .where(
                    DebatMarkering.sessie_id == sessie_id,
                    DebatMarkering.soort == SOORT_VRAAG,
                    DebatMarkering.status.in_((STATUS_OPEN, STATUS_TOEGEWEZEN)),
                    DebatMarkering.moment <= voor,
                )
                .order_by(DebatMarkering.volgnummer.desc())
            )
        ).all()
        rol = rol_van(spreker)
        ander = {"de minister", "de staatssecretaris"} - {rol} if rol else set()
        aan_deze = [r for r in rows if aan_wie(r[5]) not in ander]
        return [
            (
                r[0],
                _kort(r[1], MAX_GERICHT_AAN),
                _kort(r[2] or r[3], MAX_SAMENVATTING),
                r[4],
                f"{r[2]} {r[3]}",
            )
            for r in sorted(aan_deze[:MAX_VRAGEN_BIJ_ANTWOORD], key=lambda r: r[0])
        ]

    async def _vragen_in(
        self, sessie_id: uuid.UUID, sleutel: str | None
    ) -> tuple[int, ...]:
        """The numbers of the questions that were marked in one turn: asked
        in it, or asked again in it.

        For the interruption right before an answer. A member who
        interrupts mostly comes back to a question from their first term,
        and that is stored as a vermelding on the question that is there:
        in the gold set the one interruption with a link was that in every
        run. Whether a question is still open, and put to this
        bewindspersoon, is for whoever uses the numbers.
        """
        if not sleutel:
            return ()
        asked = (
            (
                await self.session.execute(
                    select(DebatMarkering.volgnummer).where(
                        DebatMarkering.sessie_id == sessie_id,
                        DebatMarkering.beurt_sleutel == sleutel,
                        DebatMarkering.soort == SOORT_VRAAG,
                    )
                )
            )
            .scalars()
            .all()
        )
        again = (
            (
                await self.session.execute(
                    select(DebatMarkering.volgnummer)
                    .join(
                        DebatMarkeringVermelding,
                        DebatMarkeringVermelding.markering_id == DebatMarkering.id,
                    )
                    .where(
                        DebatMarkeringVermelding.sessie_id == sessie_id,
                        DebatMarkeringVermelding.beurt_sleutel == sleutel,
                        DebatMarkeringVermelding.soort == VERMELDING_HERHALING,
                        DebatMarkering.soort == SOORT_VRAAG,
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(sorted({*asked, *again}))

    async def _toezeggingen_van(
        self, sessie_id: uuid.UUID, spreker: str
    ) -> list[tuple[int, str, uuid.UUID, str]]:
        """What this bewindspersoon promised before, as (number, summary, id,
        summary and quote together).

        Whatever became of it, as long as it was not rejected: a toezegging
        that someone ticked off as kept and is then said again is still
        the same one, and not a second thread.
        """
        rows = (
            await self.session.execute(
                select(
                    DebatMarkering.volgnummer,
                    DebatMarkering.samenvatting,
                    DebatMarkering.citaat,
                    DebatMarkering.id,
                )
                .where(
                    DebatMarkering.sessie_id == sessie_id,
                    DebatMarkering.soort == SOORT_TOEZEGGING,
                    DebatMarkering.status != STATUS_VERWORPEN,
                    DebatMarkering.spreker == spreker,
                )
                .order_by(DebatMarkering.volgnummer.desc())
                .limit(MAX_EERDERE_TOEZEGGINGEN)
            )
        ).all()
        return [
            (r[0], _kort(r[1] or r[2], MAX_SAMENVATTING), r[3], f"{r[1]} {r[2]}")
            for r in sorted(rows, key=lambda r: r[0])
        ]

    async def _markeer(
        self,
        beurt: Beurt,
        nieuw: list[_Nieuw],
        herhaald: list[_Herhaling],
        open_ids: dict[int, uuid.UUID],
        threads: int,
        afgevallen: int,
        *,
        aanvullen: bool = False,
        gelezen_tot: int | None = None,
    ) -> Beoordeling:
        """Store what was found in a turn and put it in the channel."""
        opgeslagen = await self._leg_vast(
            beurt,
            nieuw,
            herhaald,
            open_ids,
            aanvullen=aanvullen,
            gelezen_tot=gelezen_tot,
        )
        if opgeslagen is None:
            # Someone else stored this turn while the model was reading.
            eerder = await self._eerder_beoordeeld(beurt.sessie_id, beurt.sleutel)
            return Beoordeling(
                UITKOMST_AL_BEOORDEELD, markering_ids=eerder or (), threads=threads
            )

        ids, aantal = opgeslagen
        for markering_id in ids:
            if await self._post_thread(markering_id):
                threads += 1
        await self._werk_statusregels_bij(beurt.sessie_id)
        opnieuw = tuple(
            h.volgnummer for h in herhaald if h.soort == VERMELDING_HERHALING
        )
        logger.info(
            "Spreekbeurt van %s: %d vragen, %d moties, %d toezeggingen, %d herhaald",
            _hhmm(beurt.start),
            aantal.get(SOORT_VRAAG, 0),
            aantal.get(SOORT_MOTIE, 0),
            aantal.get(SOORT_TOEZEGGING, 0),
            len(opnieuw),
        )
        return Beoordeling(
            UITKOMST_GEMARKEERD,
            markering_ids=ids,
            herhaald=opnieuw,
            threads=threads,
            afgevallen=afgevallen,
            moties=aantal.get(SOORT_MOTIE, 0),
            toezeggingen=aantal.get(SOORT_TOEZEGGING, 0),
        )

    def _overslaan(self, beurt: Beurt, context: DebatContext) -> str:
        """Why this turn is not sent to the model, or an empty string."""
        if beurt.soort == SOORT_CHAIRMAN:
            # The chairman gives the floor and keeps order.
            return REDEN_VOORZITTER
        if beurt.is_bewindspersoon or _is_aan_tafel(beurt, context):
            # An answer, not a question.
            return REDEN_BEWINDSPERSOON
        if len(beurt.tekst.split()) < MIN_WOORDEN:
            return "te kort"
        if (
            beurt.soort == SOORT_INTERRUPTER
            and not beurt.onderbroken_is_bewindspersoon
            and not _noemt_bewindspersoon(beurt.tekst)
        ):
            # "Bent u het daarmee eens?" in an interruption is a question
            # to whoever is interrupted. On a real debate the model read
            # that as a question to the minister in two runs out of three,
            # so it is not left to the model: an interruption of someone
            # else only counts when it names the bewindspersoon.
            return "interruptie van een ander"
        return ""

    async def _eerder_beoordeeld(
        self, sessie_id: uuid.UUID, sleutel: str, *, door_model: bool = False
    ) -> tuple[uuid.UUID, ...] | None:
        """The markeringen of a turn that was stored before, or ``None``.

        A turn that held nothing is not stored, so it is ``None`` here and
        is read again. That costs a call and changes nothing.

        With `door_model` only what an answer of the model left behind
        counts: a question, or a question asked again. A turn of which only
        the moties are stored was not read by the model yet, or held no
        question when it was; either way it is ``None`` and is read again.
        """
        stmt = select(DebatMarkering.id).where(
            DebatMarkering.sessie_id == sessie_id,
            DebatMarkering.beurt_sleutel == sleutel,
        )
        if door_model:
            stmt = stmt.where(DebatMarkering.soort != SOORT_MOTIE)
        ids = (
            (await self.session.execute(stmt.order_by(DebatMarkering.volgnummer)))
            .scalars()
            .all()
        )
        if ids:
            return tuple(ids)
        vermelding = (
            await self.session.execute(
                select(DebatMarkeringVermelding.id)
                .where(
                    DebatMarkeringVermelding.sessie_id == sessie_id,
                    DebatMarkeringVermelding.beurt_sleutel == sleutel,
                )
                .limit(1)
            )
        ).first()
        return () if vermelding is not None else None

    async def _openstaand(
        self, sessie_id: uuid.UUID, spreker: str
    ) -> list[tuple[int, str, str, uuid.UUID]]:
        """The open questions of this speaker, as (number, who, summary, id).

        A question someone picked up is still waiting for its answer, so it
        is in the list: asked again, it is the same question and not a
        second thread.

        Only their own. A question is the same question when the same
        member asks it again; two members who ask about the same thing each
        expect an answer. On a real debate the model, given everyone's open
        questions, filed new questions of one member under a question of
        another because they shared a subject, and a question that is filed
        gets no thread.

        The most recent `MAX_OPENSTAAND`, in the order they were asked.
        """
        rows = (
            await self.session.execute(
                select(
                    DebatMarkering.volgnummer,
                    DebatMarkering.spreker,
                    DebatMarkering.samenvatting,
                    DebatMarkering.citaat,
                    DebatMarkering.id,
                )
                .where(
                    DebatMarkering.sessie_id == sessie_id,
                    DebatMarkering.soort == SOORT_VRAAG,
                    DebatMarkering.status.in_((STATUS_OPEN, STATUS_TOEGEWEZEN)),
                    DebatMarkering.spreker == spreker,
                )
                .order_by(DebatMarkering.volgnummer.desc())
                .limit(MAX_OPENSTAAND)
            )
        ).all()
        return [
            (r[0], _kort(r[1], 80), _kort(r[2] or r[3], MAX_SAMENVATTING), r[4])
            for r in sorted(rows, key=lambda r: r[0])
        ]

    async def _leg_vast(
        self,
        beurt: Beurt,
        nieuw: list[_Nieuw],
        herhaald: list[_Herhaling],
        open_ids: dict[int, uuid.UUID],
        *,
        aanvullen: bool = False,
        gelezen_tot: int | None = None,
    ) -> tuple[tuple[uuid.UUID, ...], dict[str, int]] | None:
        """Store what was found in this turn, in one commit.

        ``None`` if the answer of the model for this turn was stored in the
        meantime, or the debate is gone. The lock on the sessie makes two
        calls for the same debate take turns here: the second sees what the
        first stored, and the numbers are handed out once.

        A motie of this turn that is there already is not stored again: the
        moties of a turn can be stored before its questions, when the model
        could not be asked. Returns the markeringen of the turn that are
        new or were moties already, and how many of each kind were added.

        `herhaald` are the markeringen of before this turn comes back to,
        each by its number in `open_ids`: a question asked again, a
        toezegging said again, the question a toezegging answers, or a
        toezegging the chairman's list reads out. That last one is written
        once per toezegging, whatever list it is read from.

        With `aanvullen` the turn is a long answer that is stored window
        by window: what is there stays, and only what is not there yet is
        added. Two windows share a sentence or two, and a window can be
        handed in twice, after a restart between storing it and noting how
        far the answer was read. Neither leaves anything a second time: a
        toezegging whose quote overlaps one of this turn is the same one,
        and a vermelding is written once per markering and kind.

        `gelezen_tot` is for an answer that is read while it goes on: how
        far the turn is read with this window, kept on its row in the same
        commit as what the window held. When that turn is over, a read
        position of nothing has to mean that nothing of it was stored: a
        short answer is then read in one call and counts as read when
        anything of it is there. Kept apart, a restart between the two
        would leave the first sentences stored and the rest never read.
        """
        locked = (
            await self.session.execute(
                select(DebatSessie.id)
                .where(DebatSessie.id == beurt.sessie_id)
                .with_for_update()
            )
        ).first()
        if locked is None:
            await self.session.commit()
            return None
        gelezen = await self._eerder_beoordeeld(
            beurt.sessie_id, beurt.sleutel, door_model=True
        )
        if gelezen is not None and not aanvullen:
            await self.session.commit()
            return None
        if aanvullen:
            nieuw, herhaald = await self._nog_niet_opgeslagen(
                beurt, nieuw, herhaald, open_ids
            )
        er_al = {
            citaat: id_
            for id_, citaat in (
                await self.session.execute(
                    select(DebatMarkering.id, DebatMarkering.citaat)
                    .where(
                        DebatMarkering.sessie_id == beurt.sessie_id,
                        DebatMarkering.beurt_sleutel == beurt.sleutel,
                        DebatMarkering.soort == SOORT_MOTIE,
                    )
                    .order_by(DebatMarkering.volgnummer)
                )
            ).all()
        }
        nieuw = [n for n in nieuw if not (n.soort == SOORT_MOTIE and n.citaat in er_al)]

        hoogste = (
            await self.session.execute(
                select(func.max(DebatMarkering.volgnummer)).where(
                    DebatMarkering.sessie_id == beurt.sessie_id
                )
            )
        ).scalar() or 0
        ids: list[uuid.UUID] = []
        for i, vraag in enumerate(nieuw, start=1):
            ids.append(
                (
                    await self.session.execute(
                        insert(DebatMarkering)
                        .values(
                            sessie_id=beurt.sessie_id,
                            spreekbeurt_id=beurt.spreekbeurt_id,
                            beurt_sleutel=beurt.sleutel,
                            volgnummer=hoogste + i,
                            soort=vraag.soort,
                            status=STATUS_OPEN,
                            channel_id=beurt.channel_id,
                            beurt_post_id=self._post_van(beurt, vraag),
                            spreker=beurt.spreker,
                            fractie=beurt.fractie,
                            gericht_aan=vraag.gericht_aan,
                            citaat=vraag.citaat,
                            samenvatting=vraag.samenvatting,
                            stuk=vraag.stuk,
                            moment=beurt.start,
                            moment_url=beurt.moment_url,
                            vraag_moment=_vraag_moment(beurt, vraag.plek),
                            termijn=vraag.termijn,
                            bij_volgnummer=vraag.bij_volgnummer,
                            vraagt_om=vraag.vraagt_om,
                        )
                        .returning(DebatMarkering.id)
                    )
                ).scalar_one()
            )
        for herhaling in herhaald:
            if herhaling.soort == VERMELDING_BEVESTIGING and await is_bevestigd(
                self.session, open_ids[herhaling.volgnummer]
            ):
                continue
            await self.session.execute(
                insert(DebatMarkeringVermelding).values(
                    # The number came from this list, so it is in it.
                    markering_id=open_ids[herhaling.volgnummer],
                    sessie_id=beurt.sessie_id,
                    spreekbeurt_id=beurt.spreekbeurt_id,
                    beurt_sleutel=beurt.sleutel,
                    soort=herhaling.soort,
                    beurt_post_id=beurt.post_id,
                    spreker=beurt.spreker,
                    fractie=beurt.fractie,
                    citaat=herhaling.citaat,
                    moment=beurt.start,
                    moment_url=beurt.moment_url,
                )
            )
            if herhaling.op_papier and herhaling.soort == VERMELDING_HERHALING:
                # A question that is asked again, now for something on
                # paper: its reply says so, from the quote of this turn.
                # The row of the question keeps what it was marked with.
                # Marked the way a reaction marks it, so that the round of
                # the reactions writes its reply again.
                await self.session.execute(
                    update(DebatMarkering)
                    .where(
                        DebatMarkering.id == open_ids[herhaling.volgnummer],
                        DebatMarkering.soort == SOORT_VRAAG,
                    )
                    .values(reacties_gewijzigd_at=datetime.now(UTC))
                )
            if herhaling.termijn and herhaling.soort == VERMELDING_HERHALING:
                # A toezegging that is made more precise: the first time
                # without a moment, now with one. The row gets it, and is
                # marked the way a reaction marks it, so that the round of
                # the reactions writes its reply again from the row.
                await self.session.execute(
                    update(DebatMarkering)
                    .where(
                        DebatMarkering.id == open_ids[herhaling.volgnummer],
                        DebatMarkering.soort == SOORT_TOEZEGGING,
                        DebatMarkering.termijn.is_(None),
                    )
                    .values(
                        termijn=herhaling.termijn,
                        reacties_gewijzigd_at=datetime.now(UTC),
                    )
                )
            if herhaling.soort == VERMELDING_BEVESTIGING:
                # Read out by the chairman: the reply has to say so. Marked
                # the way a reaction marks it, so that the round of the
                # reactions writes the reply again from the row. The list
                # is what the griffier registers, so the moment and the
                # member it names fill in what the row did not have; what
                # the row has is what was said, and stays.
                eigen = (
                    DebatMarkering.id == open_ids[herhaling.volgnummer],
                    DebatMarkering.soort == SOORT_TOEZEGGING,
                )
                await self.session.execute(
                    update(DebatMarkering)
                    .where(*eigen)
                    .values(reacties_gewijzigd_at=datetime.now(UTC))
                )
                if herhaling.termijn:
                    await self.session.execute(
                        update(DebatMarkering)
                        .where(*eigen, DebatMarkering.termijn.is_(None))
                        .values(termijn=herhaling.termijn)
                    )
                if herhaling.aan:
                    await self.session.execute(
                        update(DebatMarkering)
                        .where(*eigen, DebatMarkering.gericht_aan == "")
                        .values(gericht_aan=herhaling.aan)
                    )
        if gelezen_tot is not None and beurt.spreekbeurt_id is not None:
            await self.session.execute(
                update(DebatSpreekbeurt)
                .where(DebatSpreekbeurt.id == beurt.spreekbeurt_id)
                .values(antwoord_gelezen_tot=gelezen_tot, beoordeel_pogingen=0)
            )
        await self.session.commit()
        aantal: dict[str, int] = {}
        for n in nieuw:
            aantal[n.soort] = aantal.get(n.soort, 0) + 1
        return (*er_al.values(), *ids), aantal

    @staticmethod
    def _post_van(beurt: Beurt, gevonden: _Nieuw) -> str | None:
        """The message a markering hangs under.

        A toezegging hangs under the message of the turn that holds its
        quote: an answer of ten minutes is five messages, and a reply
        under the first is four screens above what it is about. That is
        safe for an answer because what is read of it is final: the text
        in front of the quote does not change any more, so the quote stays
        in the message it is in. A question and a motie hang under the
        first message, as they did: the turn of a member is read when it
        is over, and nothing was measured that says they should move.
        """
        if gevonden.soort != SOORT_TOEZEGGING or beurt.slotlijst:
            return beurt.post_id
        return post_holding(
            beurt.tekst, gevonden.plek, beurt.post_id, beurt.vervolg_post_ids
        )

    async def _nog_niet_opgeslagen(
        self,
        beurt: Beurt,
        nieuw: list[_Nieuw],
        herhaald: list[_Herhaling],
        open_ids: dict[int, uuid.UUID],
    ) -> tuple[list[_Nieuw], list[_Herhaling]]:
        """What of a window of a long answer is not stored for its turn yet."""
        spans: list[tuple[int, int]] = []
        for (citaat,) in (
            await self.session.execute(
                select(DebatMarkering.citaat).where(
                    DebatMarkering.sessie_id == beurt.sessie_id,
                    DebatMarkering.beurt_sleutel == beurt.sleutel,
                )
            )
        ).all():
            found = locate_citaat(beurt.tekst, citaat)
            if found is not None:
                spans.append((found[1], found[1] + len(found[0])))
        vermeld = {
            (row[0], row[1])
            for row in (
                await self.session.execute(
                    select(
                        DebatMarkeringVermelding.markering_id,
                        DebatMarkeringVermelding.soort,
                    ).where(
                        DebatMarkeringVermelding.sessie_id == beurt.sessie_id,
                        DebatMarkeringVermelding.beurt_sleutel == beurt.sleutel,
                    )
                )
            ).all()
        }

        def overlaps(n: _Nieuw) -> bool:
            eind = n.plek + len(n.citaat)
            return any(
                2 * (min(eind, b) - max(n.plek, a)) >= min(len(n.citaat), b - a)
                for a, b in spans
            )

        def stored(citaat: str) -> bool:
            found = locate_citaat(beurt.tekst, citaat)
            return found is not None and overlaps(
                _Nieuw(
                    citaat=found[0],
                    gericht_aan="",
                    samenvatting="",
                    stuk=None,
                    plek=found[1],
                )
            )

        over = [n for n in nieuw if not overlaps(n)]
        # The link of a toezegging that is there already was written with
        # it. And a toezegging in the sentences two windows share is not
        # "said again": the model saw the same sentence twice.
        citaten = {n.citaat for n in over}
        return over, [
            h
            for h in herhaald
            if (open_ids[h.volgnummer], h.soort) not in vermeld
            and (h.soort != VERMELDING_ANTWOORD or h.citaat in citaten)
            and (h.soort != VERMELDING_HERHALING or not stored(h.citaat))
        ]

    async def _post_thread(self, markering_id: uuid.UUID) -> bool:
        """Post the thread of one markering, if it has none yet.

        The row is locked from the look until the post id is committed, so
        two workers cannot both post it: the second skips a locked row. A
        post that fails counts as an attempt and leaves the row without a
        thread. Whether it is tried again is for the backlog to decide.

        The first reply that gets into a thread carries the note about the
        transcript. Which reply that is, is read from the table at the
        moment of posting, with the message of the turn held for as long.
        """
        row = (
            await self.session.execute(
                select(
                    DebatMarkering.channel_id,
                    DebatMarkering.beurt_post_id,
                    DebatMarkering.volgnummer,
                    DebatMarkering.gericht_aan,
                    DebatMarkering.citaat,
                    DebatMarkering.samenvatting,
                    DebatMarkering.stuk,
                    DebatMarkering.moment,
                    DebatMarkering.moment_url,
                    DebatMarkering.vraag_moment,
                    DebatMarkering.soort,
                    DebatMarkering.termijn,
                    DebatMarkering.bij_volgnummer,
                    DebatMarkering.beurt_sleutel,
                    DebatMarkering.vraagt_om,
                    DebatMarkering.sessie_id,
                )
                .where(
                    DebatMarkering.id == markering_id,
                    DebatMarkering.thread_post_id.is_(None),
                    _HEEFT_EEN_PLEK,
                )
                .with_for_update(skip_locked=True)
            )
        ).first()
        if row is None:
            await self.session.commit()
            return False
        # One reply at a time under one message, so that "the first reply
        # of this thread" is one reply. Not waited for, like the row: a
        # worker that is posting under this message right now holds it, and
        # this markering is tried again with the backlog.
        alone = await self.session.scalar(
            select(
                func.pg_try_advisory_xact_lock(
                    func.hashtextextended(literal(f"debat-thread:{row[1]}"), 0)
                )
            )
        )
        if not alone:
            await self.session.commit()
            return False
        # The first is the first that got into the channel, not the first
        # question: a post that failed left no reply, and the note that
        # goes under the first reply has to be in the thread exactly once.
        first = not await self.session.scalar(
            select(
                exists().where(
                    DebatMarkering.beurt_post_id == row[1],
                    DebatMarkering.thread_post_id.is_not(None),
                )
            )
        )

        later = (
            await later_op_papier(self.session, markering_id)
            if row[10] == SOORT_VRAAG and row[14] is None
            else None
        )
        tekst = format_thread(
            row[10],
            volgnummer=row[2],
            gericht_aan=row[3],
            citaat=row[4],
            samenvatting=row[5],
            stuk=row[6],
            moment=row[7],
            moment_url=row[8],
            vraag_moment=row[9],
            first_in_thread=first,
            termijn=row[11],
            bij_volgnummer=row[12],
            # A thread that is posted late can be of a toezegging the
            # chairman read out in the meantime.
            bevestigd=await is_bevestigd(self.session, markering_id),
            uit_lijst=komt_uit_slotlijst(row[13]),
            vraagt_om=row[14],
            # A question that is posted late can have its toezegging by
            # now, and can have been asked again.
            toegezegd=(
                await toezeggingen_bij(self.session, row[15], row[2])
                if row[10] == SOORT_VRAAG
                else ()
            ),
            later_om=later.product if later else None,
            later_termijn=later.moment if later else None,
        )
        post_id = None
        if row[1] is not None:
            try:
                post_id = await self.mattermost.send_channel_message(
                    row[0], tekst, root_id=row[1]
                )
            except Exception:
                logger.exception(
                    "Thread voor markering %s niet geplaatst", markering_id
                )
        if (
            not post_id
            and komt_uit_slotlijst(row[13])
            and (row[1] is None or await self._is_weg(row[1]))
        ):
            # A toezegging from the chairman's list hangs under the message
            # of the end of the debate. Without that message, or with one
            # somebody deleted, it would be stored and seen by nobody: it
            # goes into the channel as a message of its own.
            try:
                post_id = await self.mattermost.send_channel_message(row[0], tekst)
            except Exception:
                logger.exception(
                    "Toezegging %s uit de slotlijst niet geplaatst", markering_id
                )

        if post_id:
            # Before anything else: a thread that is in the channel has to
            # be in the database, or the next call posts it a second time.
            await self.session.execute(
                update(DebatMarkering)
                .where(DebatMarkering.id == markering_id)
                .values(thread_post_id=post_id, met_noot=first)
            )
            if row[10] == SOORT_TOEZEGGING and row[12] is not None:
                # A toezegging that answers a question is in the channel
                # now: the reply of that question names it ("toezegging
                # 15"), as this reply names the question. Here and not
                # where the toezegging is stored: one that never got a
                # reply is not named, and every toezegging on a question
                # marks it, also the second one in a later window of the
                # same answer. The question is marked the way a reaction
                # marks it, in the commit that makes this reply known, and
                # the round of the reactions writes its reply again from
                # the row: one builder and one writer for a reply, whoever
                # changed the row. Where the question stands is not
                # touched.
                await self.session.execute(
                    update(DebatMarkering)
                    .where(
                        DebatMarkering.sessie_id == row[15],
                        DebatMarkering.volgnummer == row[12],
                        DebatMarkering.soort == SOORT_VRAAG,
                    )
                    .values(reacties_gewijzigd_at=datetime.now(UTC))
                )
        else:
            logger.warning("Thread voor markering %s niet geplaatst", markering_id)
            await self.session.execute(
                update(DebatMarkering)
                .where(DebatMarkering.id == markering_id)
                .values(post_pogingen=DebatMarkering.post_pogingen + 1)
            )
        await self.session.commit()
        if post_id:
            await self._zet_hint(post_id)
        return bool(post_id)

    async def _is_weg(self, post_id: str) -> bool:
        """Whether a message is known to be gone. Not when it cannot be
        read for another reason: then it may come back."""
        try:
            await self.mattermost.get_post(post_id)
        except PostNotFoundError:
            return True
        except Exception:
            return False
        return False

    async def _zet_hint(self, post_id: str) -> None:
        """Put one reaction under a new reply, as something to click.

        One, not the four that mean something: four under every reply is
        more bot than debate, and the pinned message of the channel lists
        them. After the commit and never retried: a reply without it is
        still a reply, and people can pick the reaction themselves.
        """
        try:
            await self.mattermost.add_reaction(post_id, REACTIE_HINT)
        except Exception:
            logger.warning("Reactie onder thread %s niet gezet", post_id, exc_info=True)

    async def _haal_achterstand_in(self, sessie_id: uuid.UUID) -> int:
        """Try again what an earlier call could not put in the channel."""
        ids = (
            (
                await self.session.execute(
                    select(DebatMarkering.id)
                    .where(
                        DebatMarkering.sessie_id == sessie_id,
                        DebatMarkering.thread_post_id.is_(None),
                        _HEEFT_EEN_PLEK,
                        DebatMarkering.post_pogingen < MAX_POST_POGINGEN,
                    )
                    .order_by(DebatMarkering.volgnummer)
                )
            )
            .scalars()
            .all()
        )
        threads = 0
        for markering_id in ids:
            if await self._post_thread(markering_id):
                threads += 1
        await self._werk_statusregels_bij(sessie_id)
        return threads

    async def _werk_statusregels_bij(self, sessie_id: uuid.UUID) -> None:
        """Write the status line of every turn whose line is out of date."""
        post_ids = (
            (
                await self.session.execute(
                    select(DebatMarkering.beurt_post_id)
                    .where(
                        DebatMarkering.sessie_id == sessie_id,
                        DebatMarkering.thread_post_id.is_not(None),
                        DebatMarkering.statusregel_at.is_(None),
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        for post_id in post_ids:
            # Only `True`: a message of the transcription stays out of
            # date here, and the transcription writes it.
            if post_id and await self._schrijf_statusregel(post_id, sessie_id) is True:
                await self.session.execute(
                    update(DebatMarkering)
                    .where(
                        DebatMarkering.beurt_post_id == post_id,
                        DebatMarkering.thread_post_id.is_not(None),
                    )
                    .values(statusregel_at=datetime.now(UTC))
                )
                await self.session.commit()

    async def _schrijf_statusregel(
        self, post_id: str, sessie_id: uuid.UUID | None = None
    ) -> bool | None:
        return await schrijf_statusregel(
            self.session, self.mattermost, post_id, sessie_id
        )


def _vraag_moment(beurt: Beurt, plek: int) -> datetime | None:
    """When the question that begins at `plek` of the turn was asked.

    ``None`` when the lines do not say. Never before the turn began: the
    voices can give a turn a line from just before its event, and a
    question is shown under the message of its turn.
    """
    found = moment_of_position(beurt.lines, beurt.tekst, plek)
    return max(found, beurt.start) if found is not None else None


# The bewindspersoon in the words of a transcript, also the ways it gets
# them wrong: one s in "staatsecretaris", "minster", "bewindsman".
_BEWINDSPERSOON_GEZEGD = re.compile(
    r"mini?ster|staats*ecreta|kabinet|regering|bewinds|premier"
)


def _noemt_bewindspersoon(tekst: str) -> bool:
    """Whether a text names a bewindspersoon, misheard or not.

    By title only. "Kan hij dat toezeggen" names nobody, and in a turn of
    an initiatiefnemer or an interruption of a colleague "hij" is as often
    someone else.
    """
    return bool(_BEWINDSPERSOON_GEZEGD.search(tekst.lower()))


def _is_initiatiefnemer(beurt: Beurt, context: DebatContext) -> bool:
    """Whether the speaker is one of the initiatiefnemers of this debate.

    On the surname and the party together: the TK API writes initials
    ("A.B. Voorbeeld") where Debat Direct writes a first name, and two
    members can share a surname. Without a party on either side nothing
    is concluded.
    """
    fractie = (beurt.fractie or "").strip().lower()
    if not fractie:
        return False
    woorden = set(re.findall(r"[\w-]+", beurt.spreker.lower()))
    for initiatiefnemer in context.initiatiefnemer_namen:
        if (initiatiefnemer.fractie or "").strip().lower() != fractie:
            continue
        delen = re.findall(r"[\w-]+", initiatiefnemer.naam.lower())
        if delen and len(delen[-1]) >= 3 and delen[-1] in woorden:
            return True
    return False


def _is_aan_tafel(beurt: Beurt, context: DebatContext) -> bool:
    """Whether the speaker is one of the bewindspersonen of this debate.

    A safety net for a caller that did not set `is_bewindspersoon`. On the
    surname, because the TK API writes initials where Debat Direct writes a
    first name. Someone with a party is a member of parliament, whatever
    they are called.
    """
    if beurt.fractie:
        return False
    woorden = set(re.findall(r"\w+", beurt.spreker.lower()))
    for bewindspersoon in context.bewindspersonen:
        delen = re.findall(r"\w+", bewindspersoon.naam.lower())
        if delen and len(delen[-1]) >= 4 and delen[-1] in woorden:
            return True
    return False
