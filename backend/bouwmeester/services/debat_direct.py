"""Read Debat Direct: which debates there are on a day, and who speaks when.

Debat Direct is the Tweede Kamer's livestream site. Its API is not
documented; what is here was read off its responses and its web app
(October 2026). It can change without notice, so everything is parsed
tolerantly and a debate that cannot be read is skipped, not fatal.

What it gives that the OData API does not: the room, the stream, and
`events`, a list of who got the floor at which moment. That list grows while
a debate runs, a speaker change showing up 5.8 to 8.7 seconds after it
happened (measured on 1 October 2026), and it stays available afterwards.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote

import httpx

from bouwmeester.services.tk_activiteit import Activiteit

logger = logging.getLogger(__name__)

DD_API_URL = "https://cdn.debatdirect.tweedekamer.nl/api"
DD_SITE_URL = "https://debatdirect.tweedekamer.nl"

# The widths of the columns an event is stored in.
EVENT_TYPE_MAX = 32
OBJECT_ID_MAX = 64

EVENT_SPEAKER = "speaker"
EVENT_INTERRUPTER = "interrupter"
EVENT_CHAIRMAN = "chairman"
EVENT_CHAIRMAN_CHANGE = "chairman_change"
EVENT_DEBATE_START = "debate_start"
EVENT_DEBATE_END = "debate_end"
EVENT_SUSPENDED = "suspended"
EVENT_CONTINUED = "continued"


class DebatDirectError(RuntimeError):
    """Debat Direct could not be read. Says nothing about the debate."""


@dataclass(frozen=True)
class DdEvent:
    start: datetime
    type: str
    object_id: str
    # The timestamp exactly as the API gave it. A link to this moment is
    # built from this string, and the site matches it literally.
    raw_start: str


@dataclass(frozen=True)
class DdDebat:
    id: str
    name: str
    slug: str
    debate_type: str | None
    debate_date: str | None
    starts_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    location_id: str | None
    location_name: str | None
    category_ids: tuple[str, ...]
    # Oldest first. Empty for a debate read from the agenda: only the
    # detail call carries events.
    events: tuple[DdEvent, ...] = ()
    # The playlist of the live stream, which names the subtitle track.
    stream_url: str | None = None
    # How much later than an event the sound of it is, as the feed says.
    stream_offset: timedelta = timedelta(0)
    # The playlist of the audio of the room alone, to tell voices apart.
    audio_url: str | None = None


@dataclass(frozen=True)
class Spreker:
    naam: str
    fractie: str | None = None
    titel: str | None = None

    @property
    def label(self) -> str:
        """`Kamerlid A (CDA)`, or the function for a minister.

        The party right behind the name, not in a column of its own.
        """
        if self.fractie:
            return f"{self.naam} ({self.fractie})"
        if self.titel and self.titel != "Tweede Kamerlid":
            return f"{self.naam} ({self.titel})"
        return self.naam


def _moment(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def parse_debate(raw: dict) -> DdDebat | None:
    """One debate from the agenda or the detail call; ``None`` without an id."""
    debate_id = _text(raw.get("id"))
    if not debate_id:
        return None
    events: list[DdEvent] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw.get("events") or []:
        if not isinstance(item, dict):
            continue
        raw_start = item.get("eventStart")
        start = _moment(raw_start)
        kind = _text(item.get("eventType"))
        if start is None or not kind:
            continue
        # Cut to what the database holds. Ids are 36 characters and
        # kinds a word, but this API is not ours: a value that does not
        # fit would make the row fail after the message was posted, and
        # the message would then be posted again on every tick.
        kind = kind[:EVENT_TYPE_MAX]
        object_id = _text(item.get("objectId"))[:OBJECT_ID_MAX]
        key = (raw_start, kind, object_id)
        if key in seen:
            continue
        seen.add(key)
        events.append(DdEvent(start, kind, object_id, raw_start))
    # The API returns newest first. Order by time and, within one second,
    # keep the order of things happening: a debate starts before someone
    # speaks in it.
    rank = {EVENT_DEBATE_START: 0, EVENT_CONTINUED: 0, EVENT_DEBATE_END: 9}
    events.sort(key=lambda e: (e.start, rank.get(e.type, 5)))

    categories = raw.get("categoryIds")
    video = raw.get("video") if isinstance(raw.get("video"), dict) else {}
    return DdDebat(
        id=debate_id,
        name=_text(raw.get("name")),
        slug=_text(raw.get("slug")),
        debate_type=_text(raw.get("debateType")) or None,
        debate_date=_text(raw.get("debateDate")) or None,
        starts_at=_moment(raw.get("startsAt")),
        started_at=_moment(raw.get("startedAt")),
        ended_at=_moment(raw.get("endedAt")),
        location_id=_text(raw.get("locationId")) or None,
        location_name=_text(raw.get("locationName")) or None,
        category_ids=tuple(
            c for c in (categories if isinstance(categories, list) else []) if c
        ),
        events=tuple(events),
        stream_url=_stream_url(video.get("url")),
        stream_offset=_offset(video.get("pdtOffset")),
        audio_url=_stream_url(video.get("audioUrl")),
    )


async def _get(client: httpx.AsyncClient, path: str, base_url: str) -> httpx.Response:
    try:
        return await client.get(
            f"{base_url}/{path}",
            # Without a browser-like agent the CDN answers 403.
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise DebatDirectError(f"Debat Direct onbereikbaar ({path})") from exc


async def fetch_agenda(
    client: httpx.AsyncClient, day: date, base_url: str = DD_API_URL
) -> list[DdDebat]:
    """The debates Debat Direct knows for this day."""
    response = await _get(client, f"agenda/{day.isoformat()}", base_url)
    try:
        response.raise_for_status()
        rows = response.json().get("debates", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise DebatDirectError(f"Agenda van {day} niet te lezen") from exc
    if not isinstance(rows, list):
        raise DebatDirectError(f"Agenda van {day} heeft een onverwachte vorm")
    debates = [parse_debate(row) for row in rows if isinstance(row, dict)]
    return [d for d in debates if d is not None]


async def fetch_debate(
    client: httpx.AsyncClient, debate_id: str, base_url: str = DD_API_URL
) -> DdDebat | None:
    """One debate with its events; ``None`` if Debat Direct does not know it."""
    response = await _get(client, f"debates/{quote(debate_id, safe='')}", base_url)
    if response.status_code == 404:
        return None
    try:
        response.raise_for_status()
        raw = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DebatDirectError(f"Debat {debate_id} niet te lezen") from exc
    if not isinstance(raw, dict):
        raise DebatDirectError(f"Debat {debate_id} heeft een onverwachte vorm")
    return parse_debate(raw)


async def fetch_sprekers(
    client: httpx.AsyncClient, day: date, base_url: str = DD_API_URL
) -> dict[str, Spreker]:
    """Everyone who can speak on this day, by the id the events carry.

    Members of parliament with their party, members of government with
    their function. This is what spares the speech recognition from telling
    speakers apart: the name comes from here, as a fact.
    """
    response = await _get(client, f"actors/{day.isoformat()}", base_url)
    try:
        response.raise_for_status()
        raw = response.json()
        politicians = raw.get("politicians") or []
        parties = raw.get("parties") or []
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise DebatDirectError(f"Sprekers van {day} niet te lezen") from exc

    fracties = {
        str(p.get("id")).lower(): _text(p.get("shorthand")) or _text(p.get("name"))
        for p in parties
        if isinstance(p, dict) and p.get("id")
    }
    sprekers: dict[str, Spreker] = {}
    for p in politicians:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        naam = _text(p.get("name")) or " ".join(
            x for x in (_text(p.get("firstName")), _text(p.get("lastName"))) if x
        )
        if not naam:
            continue
        sprekers[str(p["id"])] = Spreker(
            naam=naam,
            # Party ids differ in case between the two lists.
            fractie=fracties.get(str(p.get("partyId") or "").lower()) or None,
            titel=_text(p.get("title")) or None,
        )
    return sprekers


def debate_url(debat: DdDebat) -> str | None:
    """The page of this debate on Debat Direct, where the stream plays."""
    if not (debat.debate_date and debat.location_id and debat.slug):
        return None
    category = debat.category_ids[0] if debat.category_ids else "overig"
    return "/".join(
        [
            DD_SITE_URL,
            quote(debat.debate_date, safe=""),
            quote(category, safe=""),
            quote(debat.location_id, safe=""),
            quote(debat.slug, safe=""),
        ]
    )


def moment_url(debat: DdDebat, event: DdEvent) -> str | None:
    """A link that opens the broadcast at this event.

    The site reads `?event=<type><timestamp>` and seeks to it; that is how
    its own "spreekmomenten" link. The timestamp has to be the string the
    API gave, offset and all.
    """
    base = debate_url(debat)
    if base is None:
        return None
    return f"{base}?event={quote(f'{event.type}{event.raw_start}', safe='')}"


def _norm(tekst: str) -> str:
    plat = unicodedata.normalize("NFKD", tekst or "")
    plat = "".join(c for c in plat if not unicodedata.combining(c)).lower()
    plat = re.sub(r"\(.*?\)", " ", plat)
    plat = re.sub(r"\btweeminutendebat\b", " ", plat)
    plat = re.sub(r"[^a-z0-9 ]", " ", plat)
    return re.sub(r"\s+", " ", plat).strip()


def similarity(a: str, b: str) -> float:
    """How alike two subjects are, 0 to 1.

    Debat Direct often carries a shortened version of the OData subject, so
    one containing the other counts as nearly equal.
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    score = difflib.SequenceMatcher(None, na, nb).ratio()
    if na in nb or nb in na:
        score = max(score, 0.92)
    return score


# The thresholds the measurement used: over four days, 46 of 48 listenable
# debates matched on these and none was ambiguous.
MIN_SIMILARITY = 0.80
_MAX_START_DIFFERENCE = timedelta(minutes=90)


def _type_fits(activiteit_soort: str | None, debate_type: str | None) -> bool:
    """Same kind of meeting, as far as both sides say.

    OData says "Plenair debat (wetgeving)" where Debat Direct says "Plenair
    debat"; the part before the bracket is what they share. Without a kind
    on either side there is nothing to hold against the match.
    """
    if not activiteit_soort or not debate_type:
        return True
    a = _norm(activiteit_soort)
    b = _norm(debate_type)
    return a == b or a.startswith(b) or b.startswith(a)


PROCEDUREVERGADERING = "procedurevergadering"


def is_procedurevergadering(*kinds: str | None) -> bool:
    """Whether a meeting is a procedurevergadering, by any of what it is
    called: the `debateType` of Debat Direct, the `Soort` of the TK API,
    or a subject that starts with the word.
    """
    return any(_norm(kind or "").startswith(PROCEDUREVERGADERING) for kind in kinds)


# The kinds of meeting Debat Direct shows that are not a debate, as the
# noun with its article. Measured on the agenda of 4 November 2026.
_ARTICLE_HET = ("gesprek", "overleg", "verhoor")
_ARTICLE_DE = ("vergadering", "briefing")


def meeting_noun(debate_type: str | None) -> str:
    """The meeting as a noun: "Het debat", or what it is when not one.

    A procedurevergadering that "is begonnen" as a debate reads wrong to
    whoever knows the difference, and those are the people in the channel.
    A kind that is not known stays "het debat", as it always was.
    """
    kind = " ".join((debate_type or "").split()).lower()
    if not kind or "debat" in kind:
        return "Het debat"
    if kind.endswith(_ARTICLE_HET):
        return f"Het {kind}"
    if kind.endswith(_ARTICLE_DE):
        return f"De {kind}"
    return "Het debat"


def _stream_url(value: object) -> str | None:
    """Only an https address: it is fetched by the worker."""
    url = _text(value)
    return url if url.startswith("https://") else None


def _offset(value: object) -> timedelta:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return timedelta(0)
    if not 0 <= value <= 60_000:
        return timedelta(0)
    return timedelta(milliseconds=value)


def start_of(debat: DdDebat) -> datetime | None:
    """When a debate started, or is planned to if it has not yet."""
    return debat.started_at or debat.starts_at


# What tells a later part of one debate from another item of the agenda
# with the same name. Measured on the 21 days with an agenda between 31
# August and 6 October 2026 (357 debates, 280 activiteiten matched): 17
# activiteiten got more than one debate, 7 of them rightly. Those 7 were all
# a plenary debate cut around a break, and the next part started 0.6 to
# 63.4 minutes after the part before it ended.
#
# The other 10 are what these two rules keep out. Eight were items that are
# on the agenda several times a day under one name: "Stemmingen" three
# times (65, 106 and 692 minutes after the one before) and "Regeling van
# werkzaamheden" five times (3.5 to 53 minutes: no bound on the time tells
# those from a break, so they go by name). "Mededelingen" is the same kind
# of item, 13 times in these days, 49 to 423 minutes apart. The remaining
# two: the election of a chairman and that of a deputy 193 minutes later,
# and two meetings alike in name that ran at the same time in two rooms.
#
# Two hours is twice the longest break measured, and well under the
# shortest wrong pair that the names do not catch.
MAX_BREAK = timedelta(hours=2)
_RECURRING_ITEMS = frozenset(
    {"stemmingen", "regeling van werkzaamheden", "mededelingen"}
)


def _recurs(debat: DdDebat) -> bool:
    """An item that is on the agenda several times a day under one name."""
    return (
        _norm(debat.debate_type or "") in _RECURRING_ITEMS
        or _norm(debat.name) in _RECURRING_ITEMS
    )


def continues(previous: DdDebat, debat: DdDebat) -> bool:
    """Whether `debat` is the next part of the debate `previous` is a part of.

    Says nothing about the subject: the caller compares that. A part that
    has not ended has no next part yet. Debat Direct gives a debate its end
    at the moment of the event that ends it (170 of 170 debates), and a
    next part is looked for every five minutes, so it is found a round
    later at worst.
    """
    if _recurs(previous) or _recurs(debat):
        return False
    if (
        previous.location_id
        and debat.location_id
        and previous.location_id != debat.location_id
    ):
        # A debate goes on in the room it was in. Meetings of different
        # committees can carry almost the same name (procedurevergaderingen
        # scored 0.80 and more on each other on 2 July 2026) and follow
        # each other within the hour, in another room.
        return False
    start = start_of(debat)
    if start is None or previous.ended_at is None:
        return False
    return timedelta(0) <= start - previous.ended_at <= MAX_BREAK


def later_parts(
    onderwerp: str, known_ids: list[str], debates: list[DdDebat]
) -> list[DdDebat]:
    """Parts of a debate that came after the parts already known.

    Debat Direct cuts a plenary debate in two around a break, and the
    second part only appears when it starts. It is recognised by carrying
    the same subject and the same kind as a known part, and by starting
    within a break's length of where the last part ended; see `continues`.

    Deliberately not through `match_debates` again. That compares with the
    planned start of the activiteit, and once a debate has started Debat
    Direct overwrites its planned start with the real one: a debate that
    began two hours late would then no longer match itself, and its second
    part would never be found.
    """
    known = [debat for debat in debates if debat.id in known_ids]
    started = [debat for debat in known if start_of(debat) is not None]
    if not started:
        return []
    kinds = {debat.debate_type for debat in known}
    candidates = [
        debat
        for debat in debates
        if debat.id not in known_ids
        and debat.debate_type in kinds
        and similarity(onderwerp, debat.name) >= MIN_SIMILARITY
        and start_of(debat) is not None
    ]
    # A chain: a third part continues the second, not the first.
    last = max(started, key=_start_key)
    found: list[DdDebat] = []
    for debat in sorted(candidates, key=_start_key):
        if continues(last, debat):
            found.append(debat)
            last = debat
    return found


def _start_key(debat: DdDebat) -> float:
    start = start_of(debat)
    return start.timestamp() if start else 0.0


def _literal_likeness(a: str, b: str) -> float:
    """How alike two subjects are as they are written, brackets and all.

    `similarity` leaves out what is between brackets, and then "Regeling
    van werkzaamheden (stemmingen)" is "Regeling van werkzaamheden". Both
    are on the agenda within the hour, against one activiteit.
    """
    return difflib.SequenceMatcher(
        None, " ".join(a.lower().split()), " ".join(b.lower().split())
    ).ratio()


def match_debates(activiteit: Activiteit, debates: list[DdDebat]) -> list[DdDebat]:
    """The Debat Direct debates that are this activiteit, oldest first.

    There is no shared key, so this goes on subject, kind and start time.
    More than one is possible and correct: Debat Direct cuts a plenary
    debate in two around a break, against one activiteit.

    The start time only counts for one part. A second part starts hours
    after the activiteit does, and is recognised by carrying the same
    subject and following a part that did match on time; see `continues`.
    """
    alike = [
        debat
        for debat in debates
        if similarity(activiteit.onderwerp, debat.name) >= MIN_SIMILARITY
        and _type_fits(activiteit.soort, debat.debate_type)
    ]
    aanvang = activiteit.aanvang
    on_time = alike
    if aanvang is not None:
        on_time = [
            debat
            for debat in alike
            if (start := start_of(debat)) is not None
            and abs(start - aanvang) <= _MAX_START_DIFFERENCE
        ]
    if not on_time:
        return []

    def fit(debat: DdDebat) -> tuple[float, float, float]:
        start = start_of(debat)
        off = abs(start - aanvang).total_seconds() if start and aanvang else 0.0
        return (
            similarity(activiteit.onderwerp, debat.name),
            _literal_likeness(activiteit.onderwerp, debat.name),
            -off,
        )

    # Several can be on time without being parts of one debate: two items
    # of one name around the votes (5 of the 21 days), or two meetings
    # alike in name at the same hour (once). Then it is the one that fits
    # best, by subject before time: the item meant was once 35 minutes off
    # where the other was 19.
    parts = [max(on_time, key=fit)]
    ordered = sorted(alike, key=_start_key)
    # The parts before it and after it. Both ways, because a short first
    # part and its second can both be on time.
    for debat in reversed(ordered):
        if debat not in parts and continues(debat, parts[0]):
            parts.insert(0, debat)
    for debat in ordered:
        if debat not in parts and continues(parts[-1], debat):
            parts.append(debat)
    return parts
