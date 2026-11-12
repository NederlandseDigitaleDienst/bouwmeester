"""The outcome of the votes on a bill, in the channel of its debate.

A debate on a bill ends without a decision: amendementen, moties and the
bill itself are voted on later, often days later, in a block of votes on
the agenda of its own. Whoever followed the debate in the channel wants to
know how it ended without looking it up.

Two sources, because neither is enough on its own:

* Debat Direct has the votes as they are cast: per voting round the result
  and the vote of every fractie (or of every member, when the vote is
  hoofdelijk), with the time to the second. It names the zaak only in the
  title of the round, "de motie-X over ... (37022, nr. 45)", and that is
  how it is matched. A title can lack the number ("nr. ??") or be cut off,
  and then the round is matched in another way or not at all.
* The TK API has every vote as a `Besluit` on the `Zaak`, with a link to
  the document. Measured on the votes of 3 and 10 November 2026: the
  besluit is there within 0 to 20 minutes of the vote, the votes per
  fractie only the next morning, between 9 and 13 o'clock.

A zaak that is in both is shown once: the besluit from the TK API, the
votes from whichever has them. Debat Direct is the extra: when it cannot be
read, what the TK API has is posted all the same, but never in a way that
drops a line that is already in the channel.

Which votes belong to a debate: those on a zaak in the kamerstukdossier of
a bill on its agenda, held on or after the day of the debate. Only for a
debate on a bill. Such a dossier holds that bill with its own amendementen
and moties and nothing else. The dossier of a commissiedebat is a theme
that gathers years of moties of other debates, and is left alone here. A
dossier is its number with its toevoeging: the begrotingen of one year all
share a number and differ in the toevoeging only (37020-XVI).

One message per day of votes, pinned, and remembered on the sessie
(`DebatSessie.stemmingen`) the moment it exists, so a restart does not post
it twice. A message someone took away is not posted again.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.debat_sessie import DebatSessie
from bouwmeester.services import debat_direct as dd
from bouwmeester.services.debat_kanaal_service import (
    AMSTERDAM,
    MESSAGE_MAX,
    document_url,
    format_day,
)
from bouwmeester.services.kamerstuk_soort import TK_BASE_URL
from bouwmeester.services.mattermost_service import (
    MattermostService,
    PostNotFoundError,
)
from bouwmeester.services.mattermost_utils import (
    escape_mattermost_md,
    escape_mattermost_prose,
)

logger = logging.getLogger(__name__)

# How long after a debate its votes are looked for. The votes on a bill are
# usually the Tuesday after the debate, the votes per fractie in the TK API
# the morning after that; a debate that is suspended can take longer.
FOLLOW = timedelta(days=21)
# How often the sources are asked, per debate. Debat Direct is a CDN.
EVERY = timedelta(minutes=2)
# When the TK API could not be read: wait this long before the next try.
AFTER_ERROR = timedelta(minutes=5)
# An agenda without a bill is asked again this often, as many times: the
# TK API can link the zaak to the agendapunt after the debate began.
DOSSIERS_AGAIN = timedelta(hours=1)
DOSSIERS_TRIES = 4
# The subject of a zaak can run to several lines.
ONDERWERP_MAX = 160

_HTTP_TIMEOUT = 30.0

SOORT_WETGEVING = "Wetgeving"
SOORT_AMENDEMENT = "Amendement"
SOORT_MOTIE = "Motie"
SOORT_OVERIG = "Overig"
# The zaak of a bill in the TK API: of the government, or of members.
_BILL_KINDS = frozenset({"Wetgeving", "Initiatiefwetgeving"})

OUTCOME_AANGENOMEN = "aangenomen"
OUTCOME_VERWORPEN = "verworpen"
OUTCOME_STAKEN = "staken"
OUTCOME_AANGEHOUDEN = "aangehouden"
OUTCOME_INGETROKKEN = "ingetrokken"
_OUTCOMES = (
    OUTCOME_AANGENOMEN,
    OUTCOME_VERWORPEN,
    OUTCOME_STAKEN,
    OUTCOME_AANGEHOUDEN,
    OUTCOME_INGETROKKEN,
)

VOTE_VOOR = "Voor"
VOTE_TEGEN = "Tegen"

SOURCE_TK = "tk"
SOURCE_DD = "dd"


class SourceError(RuntimeError):
    """A source could not be read. Says nothing about the votes."""


@dataclass(frozen=True)
class Fractiestem:
    """How one fractie voted, or the members of it that voted alike."""

    fractie: str
    soort: str
    # Seats with a vote per fractie, members with a hoofdelijke stemming.
    count: int


@dataclass(frozen=True)
class Uitslag:
    """One outcome on one zaak on one day."""

    source: str
    zaak_soort: str
    onderwerp: str
    # "37022", or "37020-XVI" with a toevoeging.
    dossier: str | None
    volgnummer: int | None
    outcome: str
    # Shown for what is not one of the known outcomes.
    besluit_tekst: str
    hoofdelijk: bool
    moment: datetime | None
    zaak_nummer: str | None = None
    document_nummer: str | None = None
    changed_at: str = ""
    votes: tuple[Fractiestem, ...] = field(default=())
    # Of a changed motie or amendement: the number of the one it replaces.
    # Debat Direct can know a changed motie before it has a number of its
    # own ("nr. ??, was nr. 36"); this is what it is matched by then.
    replaces: int | None = None

    @property
    def key(self) -> tuple:
        """What tells one zaak from another across the two sources."""
        if self.zaak_soort == SOORT_WETGEVING and self.dossier:
            return (self.dossier, "wet")
        if self.dossier and self.volgnummer:
            return (self.dossier, self.volgnummer)
        return ("onderwerp", self.onderwerp.lower())

    @property
    def day(self) -> date | None:
        return self.moment.astimezone(AMSTERDAM).date() if self.moment else None

    def total(self, soort: str) -> int:
        return sum(v.count for v in self.votes if v.soort == soort)

    def fracties(self, soort: str) -> list[str]:
        """The fracties that voted `soort`, largest first.

        With a hoofdelijke stemming a fractie can be split: then its share
        is said ("Partij A 12 van 22").
        """
        per: dict[str, dict[str, int]] = defaultdict(dict)
        for v in self.votes:
            per[v.fractie][v.soort] = per[v.fractie].get(v.soort, 0) + v.count
        names: list[tuple[int, str]] = []
        for fractie, counts in per.items():
            mine = counts.get(soort, 0)
            if not mine:
                continue
            total = sum(counts.values())
            label = fractie if mine == total else f"{fractie} {mine} van {total}"
            names.append((mine, label))
        return [label for _, label in sorted(names, key=lambda n: (-n[0], n[1]))]


def _outcome(text: str) -> str:
    """`aangenomen`, `verworpen`, ... from "Stemmen - aangenomen" or "Aangenomen"."""
    rest = text.split(" - ", 1)[-1].strip().lower()
    for outcome in _OUTCOMES:
        if rest.startswith(outcome):
            return outcome
    return rest


def _rows(value: object) -> list[dict]:
    """A list of live objects: no deleted rows, nothing that is not a dict."""
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict) and not row.get("Verwijderd")]


def dossier_key(nummer: object, toevoeging: object) -> str | None:
    if not isinstance(nummer, int):
        return None
    if isinstance(toevoeging, str) and toevoeging.strip():
        return f"{nummer}-{toevoeging.strip()}"
    return str(nummer)


# --- The TK API -------------------------------------------------------------


async def _get_tk(client: httpx.AsyncClient, url: str, params: dict) -> list[dict]:
    rows: list[dict] = []
    next_url: str | None = url
    next_params: dict | None = params
    # A dossier of a large bill holds well under a thousand besluiten; the
    # bound is against a server that keeps pointing at a next page.
    for _ in range(10):
        if next_url is None:
            break
        try:
            response = await client.get(next_url, params=next_params)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(str(exc) or type(exc).__name__) from exc
        if not isinstance(body, dict):
            raise SourceError("geen object")
        rows += [r for r in body.get("value") or [] if isinstance(r, dict)]
        next_url, next_params = body.get("@odata.nextLink"), None
    return rows


async def fetch_dossiers(
    activiteit_id: str, client: httpx.AsyncClient, base_url: str = TK_BASE_URL
) -> list[str]:
    """The kamerstukdossiers of the bills on the agenda of an activiteit."""
    rows = await _get_tk(
        client,
        f"{base_url}/Agendapunt",
        {
            "$filter": f"Activiteit_Id eq {uuid.UUID(activiteit_id)} "
            "and Verwijderd eq false",
            "$select": "Id",
            "$expand": (
                "Zaak($select=Soort,Verwijderd;"
                "$expand=Kamerstukdossier($select=Nummer,Toevoeging,Verwijderd))"
            ),
        },
    )
    dossiers: set[str] = set()
    for agendapunt in rows:
        for zaak in _rows(agendapunt.get("Zaak")):
            if zaak.get("Soort") not in _BILL_KINDS:
                continue
            for dossier in _rows(zaak.get("Kamerstukdossier")):
                key = dossier_key(dossier.get("Nummer"), dossier.get("Toevoeging"))
                if key:
                    dossiers.add(key)
    return sorted(dossiers)


def dossier_filter(dossiers: list[str]) -> str:
    """The OData condition on a `Kamerstukdossier` `k` for these dossiers."""
    parts = []
    for key in dossiers:
        nummer, _, toevoeging = key.partition("-")
        if not nummer.isdigit():
            continue
        if toevoeging:
            safe = toevoeging.replace("'", "''")
            parts.append(f"(k/Nummer eq {nummer} and k/Toevoeging eq '{safe}')")
        else:
            parts.append(f"(k/Nummer eq {nummer} and k/Toevoeging eq null)")
    return " or ".join(parts)


_BESLUIT_SELECT = "Id,BesluitSoort,BesluitTekst,StemmingsSoort,GewijzigdOp,Verwijderd"
_BESLUIT_EXPAND = (
    "Stemming($select=Soort,FractieGrootte,ActorFractie,ActorNaam,Persoon_Id,"
    "Verwijderd),"
    "Zaak($select=Nummer,Soort,Onderwerp,Volgnummer,Verwijderd;"
    "$expand=Kamerstukdossier($select=Nummer,Toevoeging,Verwijderd),"
    "Document($select=DocumentNummer,Volgnummer,Verwijderd)),"
    "Agendapunt($select=Id;$expand=Activiteit($select=Id,Datum,Aanvangstijd))"
)


async def fetch_tk_uitslagen(
    dossiers: list[str],
    since: date,
    client: httpx.AsyncClient,
    base_url: str = TK_BASE_URL,
) -> list[Uitslag]:
    """The besluiten on zaken in these dossiers, in votes from `since`."""
    in_dossier = dossier_filter(dossiers)
    if not in_dossier:
        return []
    rows = await _get_tk(
        client,
        f"{base_url}/Besluit",
        {
            # A bare date against the DateTimeOffset `Datum`: the TK API
            # takes it (checked on 12 November 2026).
            "$filter": (
                "Verwijderd eq false and startswith(BesluitSoort,'Stemmen - ') "
                f"and Agendapunt/Activiteit/Datum ge {since.isoformat()} "
                f"and Zaak/any(z: z/Kamerstukdossier/any(k: {in_dossier}))"
            ),
            "$select": _BESLUIT_SELECT,
            "$expand": _BESLUIT_EXPAND,
            "$top": "250",
        },
    )
    return parse_tk_uitslagen(rows, set(dossiers))


def _tk_votes(rows: list[dict]) -> tuple[Fractiestem, ...]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        fractie = row.get("ActorFractie") or row.get("ActorNaam")
        soort = row.get("Soort")
        if not isinstance(fractie, str) or soort not in (VOTE_VOOR, VOTE_TEGEN):
            continue
        if row.get("Persoon_Id"):
            # A hoofdelijke stemming: one row per member.
            counts[(fractie, soort)] += 1
        else:
            size = row.get("FractieGrootte")
            counts[(fractie, soort)] += size if isinstance(size, int) else 0
    return tuple(
        Fractiestem(fractie=f, soort=s, count=n) for (f, s), n in sorted(counts.items())
    )


# "ter vervanging van nr. 36", or "(t.v.v. 37020-VII-42)" at the end.
_TER_VERVANGING = re.compile(
    r"\bter vervanging van nr\.\s*(\d+)|\bt\.v\.v\.\s*\d+(?:-[A-Z0-9]+)?-(\d+)",
    re.IGNORECASE,
)


def _replaces(onderwerp: str) -> int | None:
    found = _TER_VERVANGING.search(onderwerp)
    if not found:
        return None
    return int(found.group(1) or found.group(2))


def parse_tk_uitslagen(rows: list[dict], dossiers: set[str]) -> list[Uitslag]:
    """Read the besluiten, the latest per zaak per day.

    A zaak that was voted on twice on one day (a vote done again, a besluit
    corrected) keeps the besluit that was changed last.
    """
    latest: dict[tuple, Uitslag] = {}
    for row in _rows(rows):
        agendapunt = row.get("Agendapunt")
        activiteit = (
            agendapunt.get("Activiteit") if isinstance(agendapunt, dict) else None
        )
        if not isinstance(activiteit, dict):
            continue
        zaken = _rows(row.get("Zaak"))
        if not zaken or not isinstance(zaken[0].get("Nummer"), str):
            continue
        zaak = zaken[0]
        in_dossiers = [
            dossier_key(d.get("Nummer"), d.get("Toevoeging"))
            for d in _rows(zaak.get("Kamerstukdossier"))
        ]
        dossier = next((d for d in in_dossiers if d in dossiers), None)
        raw_volgnummer = zaak.get("Volgnummer")
        volgnummer = raw_volgnummer if isinstance(raw_volgnummer, int) else None
        documents = _rows(zaak.get("Document"))
        document = next(
            (d for d in documents if d.get("Volgnummer") == volgnummer), None
        ) or (documents[0] if documents else None)
        soort = str(zaak.get("Soort") or "")
        if soort in _BILL_KINDS:
            soort = SOORT_WETGEVING
        elif soort not in (SOORT_AMENDEMENT, SOORT_MOTIE):
            soort = SOORT_OVERIG
        uitslag = Uitslag(
            source=SOURCE_TK,
            zaak_soort=soort,
            onderwerp=" ".join(str(zaak.get("Onderwerp") or "").split()),
            dossier=dossier,
            volgnummer=volgnummer,
            outcome=_outcome(str(row.get("BesluitSoort") or "")),
            besluit_tekst=" ".join(str(row.get("BesluitTekst") or "").split()),
            hoofdelijk=str(row.get("StemmingsSoort") or "").lower() == "hoofdelijk",
            moment=dd.parse_moment(activiteit.get("Aanvangstijd"))
            or dd.parse_moment(activiteit.get("Datum")),
            zaak_nummer=zaak["Nummer"],
            document_nummer=(document or {}).get("DocumentNummer"),
            changed_at=str(row.get("GewijzigdOp") or ""),
            votes=_tk_votes(_rows(row.get("Stemming"))),
            replaces=_replaces(str(zaak.get("Onderwerp") or "")),
        )
        key = (uitslag.day, uitslag.key)
        known = latest.get(key)
        if known is None or uitslag.changed_at >= known.changed_at:
            latest[key] = uitslag
    return list(latest.values())


# --- Debat Direct -----------------------------------------------------------

# "(37022, nr. 45)", "(37020-XVI, nr. 91)", "(37022)", and "(37020-XXIII,
# nr. ??, was nr. 36)" for a changed motie that has no number yet.
_KENMERK = re.compile(r"\((\d{5})(?:-([A-Z0-9]+))?(?:,\s*nr\.\s*(\d+|\?\?)[^)]*)?\)")
_WAS = re.compile(r"\bwas nr\.\s*(\d+)")
_ARTICLE = re.compile(r"^(?:de|het)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class DdTitle:
    zaak_soort: str
    dossier: str | None
    volgnummer: int | None
    onderwerp: str
    replaces: int | None


def parse_dd_title(title: str) -> DdTitle:
    """The kind of zaak, its dossier and number, and the title without them.

    The last kenmerk in the title counts: a title can mention another
    document before it.
    """
    matches = list(_KENMERK.finditer(title))
    dossier: str | None = None
    volgnummer: int | None = None
    replaces: int | None = None
    remainder = title
    if matches:
        m = matches[-1]
        dossier = m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
        if m.group(3) and m.group(3).isdigit():
            volgnummer = int(m.group(3))
        was = _WAS.search(m.group(0))
        replaces = int(was.group(1)) if was else None
        remainder = (title[: m.start()] + title[m.end() :]).strip()
    opening = remainder.lower()[:40]
    if "amendement" in opening:
        soort = SOORT_AMENDEMENT
    elif "motie" in opening:
        soort = SOORT_MOTIE
    elif "wetsvoorstel" in opening or "wetvoorstel" in opening:
        # Also "het initiatiefwetsvoorstel".
        soort = SOORT_WETGEVING
    else:
        soort = SOORT_OVERIG
    remainder = _ARTICLE.sub("", " ".join(remainder.split()))
    return DdTitle(
        zaak_soort=soort,
        dossier=dossier,
        volgnummer=volgnummer,
        onderwerp=remainder[:1].upper() + remainder[1:],
        replaces=replaces,
    )


def is_stemmingen(debat: dd.DdDebat) -> bool:
    name = f"{debat.debate_type or ''} {debat.name or ''}".lower()
    return "stemming" in name


@dataclass(frozen=True)
class DdActors:
    # Party id to its short name.
    parties: dict[str, str]
    # Member id to party id. Members of government carry no party.
    members: dict[str, str]

    def seats(self, party_id: str) -> int:
        return sum(1 for p in self.members.values() if p == party_id)


def parse_dd_actors(raw: object) -> DdActors:
    if not isinstance(raw, dict):
        return DdActors({}, {})
    parties_raw = raw.get("parties")
    politicians_raw = raw.get("politicians")
    parties = {
        str(p["id"]).lower(): str(p.get("shorthand") or p.get("name") or "")
        for p in (parties_raw if isinstance(parties_raw, list) else [])
        if isinstance(p, dict) and p.get("id")
    }
    members = {
        str(p["id"]).lower(): str(p["partyId"]).lower()
        for p in (politicians_raw if isinstance(politicians_raw, list) else [])
        if isinstance(p, dict) and p.get("id") and p.get("partyId")
    }
    return DdActors(parties=parties, members=members)


def _is_hoofdelijk(voting_round: dict) -> bool:
    return str(voting_round.get("type") or "").lower().startswith("hoofd")


def _dd_votes(voting_round: dict, actors: DdActors) -> tuple[Fractiestem, ...]:
    hoofdelijk = _is_hoofdelijk(voting_round)
    raw_votes = voting_round.get("votes")
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for vote in raw_votes if isinstance(raw_votes, list) else []:
        if not isinstance(vote, list) or len(vote) != 2:
            continue
        actor, soort = str(vote[0]).lower(), vote[1]
        if soort not in (VOTE_VOOR, VOTE_TEGEN):
            # "Onbekend" and the like: not there, or did not take part.
            continue
        if hoofdelijk:
            party = actors.members.get(actor)
            if party is None:
                continue
            counts[(actors.parties.get(party, "?"), soort)] += 1
        else:
            name = actors.parties.get(actor)
            if name is None:
                continue
            counts[(name, soort)] += actors.seats(actor)
    return tuple(
        Fractiestem(fractie=f, soort=s, count=n) for (f, s), n in sorted(counts.items())
    )


def parse_dd_votings(
    raw: object, actors: DdActors, dossiers: set[str]
) -> list[Uitslag]:
    """The voting rounds of one block of votes on zaken in these dossiers.

    A zaak voted on twice (the votes were equal, then a hoofdelijke
    stemming) keeps the round that started last.
    """
    if not isinstance(raw, dict):
        return []
    latest: dict[tuple, tuple[datetime | None, Uitslag]] = {}
    votings = raw.get("votings")
    for voting in votings if isinstance(votings, list) else []:
        if not isinstance(voting, dict):
            continue
        rounds = voting.get("votingRounds")
        for voting_round in rounds if isinstance(rounds, list) else []:
            if not isinstance(voting_round, dict) or not voting_round.get("result"):
                continue
            title = parse_dd_title(
                " ".join(str(voting_round.get("title") or "").split())
            )
            dossier = title.dossier
            if dossier is None:
                # A cut-off title: the dossier may be in the subject.
                dossier = parse_dd_title(str(voting.get("subject") or "")).dossier
            if dossier not in dossiers:
                continue
            started = dd.parse_moment(voting_round.get("startedAt"))
            uitslag = Uitslag(
                source=SOURCE_DD,
                zaak_soort=title.zaak_soort,
                onderwerp=title.onderwerp,
                dossier=dossier,
                volgnummer=title.volgnummer,
                outcome=_outcome(str(voting_round["result"])),
                besluit_tekst=str(voting_round["result"]),
                hoofdelijk=_is_hoofdelijk(voting_round),
                moment=started or dd.parse_moment(voting.get("startsAt")),
                votes=_dd_votes(voting_round, actors),
                replaces=title.replaces,
            )
            known = latest.get(uitslag.key)
            if known is None or (started and (known[0] is None or started >= known[0])):
                latest[uitslag.key] = (started, uitslag)
    return [u for _, u in latest.values()]


class DebatDirectSource:
    """The blocks of votes of Debat Direct, read once per round of the worker."""

    def __init__(self, client: httpx.AsyncClient, base_url: str = dd.DD_API_URL):
        self.client = client
        self.base_url = base_url
        self._days: dict[date, tuple[list[dict], DdActors]] = {}
        self._failed: dict[date, SourceError] = {}

    async def blocks(self, day: date) -> tuple[list[dict], DdActors]:
        if day in self._failed:
            # Failed earlier in this round: not asked again for every debate.
            raise self._failed[day]
        if day in self._days:
            return self._days[day]
        try:
            agenda = await dd.fetch_agenda(self.client, day, self.base_url)
            raws = [
                await dd.fetch_debate_json(self.client, debat.id, self.base_url)
                for debat in agenda
                if is_stemmingen(debat) and debat.started_at is not None
            ]
            actors = DdActors({}, {})
            if raws:
                actors = parse_dd_actors(
                    await dd.fetch_actors_json(self.client, day, self.base_url)
                )
        except dd.DebatDirectError as exc:
            error = SourceError(str(exc) or type(exc).__name__)
            self._failed[day] = error
            raise error from exc
        self._days[day] = (raws, actors)
        return raws, actors

    async def uitslagen(self, dossiers: list[str], days: list[date]) -> list[Uitslag]:
        found: list[Uitslag] = []
        for day in days:
            raws, actors = await self.blocks(day)
            for raw in raws:
                found += parse_dd_votings(raw, actors, set(dossiers))
        return found


def _about(onderwerp: str) -> str:
    """What a motie is about: the words after "over", as they compare."""
    _, sep, rest = onderwerp.partition(" over ")
    rest = re.sub(r"\(.*?\)", " ", rest)
    return " ".join(rest.lower().split()) if sep else ""


def merge(tk: list[Uitslag], live: list[Uitslag]) -> list[Uitslag]:
    """One outcome per zaak per day: the TK API's besluit, the votes of either.

    Debat Direct alone for what the TK API does not have yet. A round of
    Debat Direct without a number of its own (a changed motie, "nr. ??") is
    matched by the number it replaces, or else by what it is about: the TK
    API does not always say what a changed motie replaces, and names the
    members where Debat Direct writes "c.s.". One that still does not match
    is shown only until the TK API has besluiten in its dossier that day.
    From then on it would be the same motie twice, under two names.
    """
    merged: dict[tuple, Uitslag] = {(u.day, u.key): u for u in tk}
    by_replaces = {
        (u.day, u.dossier, u.replaces): (u.day, u.key) for u in tk if u.replaces
    }
    by_about = {
        (u.day, u.dossier, _about(u.onderwerp)): (u.day, u.key)
        for u in tk
        if _about(u.onderwerp)
    }
    tk_dossiers = {(u.day, u.dossier) for u in tk}
    for u in live:
        key = (u.day, u.key)
        if u.volgnummer is None and u.zaak_soort != SOORT_WETGEVING:
            key = by_replaces.get(
                (u.day, u.dossier, u.replaces),
                by_about.get((u.day, u.dossier, _about(u.onderwerp)), key),
            )
            if key not in merged and (u.day, u.dossier) in tk_dossiers:
                continue
        known = merged.get(key)
        if known is None:
            merged[key] = u
        elif not known.votes and u.votes:
            merged[key] = replace(known, votes=u.votes, hoofdelijk=u.hoofdelijk)
    return list(merged.values())


# --- The message ------------------------------------------------------------

_ORDER = {SOORT_WETGEVING: 0, SOORT_AMENDEMENT: 1, SOORT_MOTIE: 2, SOORT_OVERIG: 3}
_HEADINGS = {
    SOORT_WETGEVING: "Wetsvoorstellen",
    SOORT_AMENDEMENT: "Amendementen",
    SOORT_MOTIE: "Moties",
    SOORT_OVERIG: "Overig",
}
_LABELS = {
    OUTCOME_AANGENOMEN: "✅ **Aangenomen**",
    OUTCOME_VERWORPEN: "❌ **Verworpen**",
    OUTCOME_STAKEN: "⚖️ Stemmen staken",
    OUTCOME_AANGEHOUDEN: "⏸️ Aangehouden",
    OUTCOME_INGETROKKEN: "↩️ Ingetrokken",
}


def _hhmm(moment: datetime) -> str:
    return moment.astimezone(AMSTERDAM).strftime("%H:%M")


def _short(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _sort_key(u: Uitslag) -> tuple:
    return (
        _ORDER.get(u.zaak_soort, 3),
        u.dossier or "",
        u.volgnummer or 0,
        u.onderwerp,
    )


def _votes_line(u: Uitslag) -> str:
    """The count and who voted for, when the votes are known."""
    if not u.votes:
        return ""
    line = f"voor {u.total(VOTE_VOOR)}, tegen {u.total(VOTE_TEGEN)}"
    if u.hoofdelijk:
        line += " (hoofdelijk)"
    fracties = ", ".join(escape_mattermost_prose(f) for f in u.fracties(VOTE_VOOR))
    return f"{line} · voor: {fracties}" if fracties else line


def render_uitslag(u: Uitslag) -> str:
    """One item: the outcome, the zaak with a link, who voted for."""
    label = _LABELS.get(u.outcome, escape_mattermost_prose(u.besluit_tekst))
    if u.dossier and u.volgnummer:
        kenmerk = f"{u.dossier}, nr. {u.volgnummer}"
    else:
        kenmerk = u.dossier or u.zaak_nummer or ""
    kenmerk = escape_mattermost_md(kenmerk)
    if kenmerk and u.document_nummer:
        kenmerk = f"[{kenmerk}]({document_url(u.zaak_nummer, u.document_nummer)})"
    parts = [label]
    if kenmerk:
        parts.append(kenmerk)
    parts.append(escape_mattermost_prose(_short(u.onderwerp, ONDERWERP_MAX)))
    line = "- " + " · ".join(parts)
    votes = _votes_line(u)
    return f"{line}\n  {votes}" if votes else line


def render_day(
    day: date, uitslagen: list[Uitslag], *, updated_at: datetime | None = None
) -> list[str]:
    """The messages for one day of votes. One, unless it is too long."""
    if not uitslagen:
        return []
    title = f"🗳️ **Stemmingen van {format_day(day)}**"
    counts: dict[str, int] = defaultdict(int)
    for u in uitslagen:
        counts[u.outcome] += 1
    summary = ", ".join(f"{counts[k]} {k}" for k in _OUTCOMES if counts[k])
    head = f"{title}\n{summary}" if summary else title

    sources = frozenset(u.source for u in uitslagen)
    footer = "_Uit " + {
        frozenset({SOURCE_TK}): "de TK-API",
        frozenset({SOURCE_DD}): "Debat Direct",
    }.get(sources, "de TK-API en Debat Direct")
    if updated_at is not None:
        footer += f", bijgewerkt om {_hhmm(updated_at)}"
    footer += "."
    if any(
        not u.votes
        for u in uitslagen
        if u.outcome in (OUTCOME_AANGENOMEN, OUTCOME_VERWORPEN)
    ):
        footer += " Waar de stemmen per fractie ontbreken, volgen die later."
    footer += "_"

    by_kind: dict[str, list[Uitslag]] = defaultdict(list)
    for u in sorted(uitslagen, key=_sort_key):
        by_kind[u.zaak_soort].append(u)

    # Packed into messages, an item at a time, each under the limit.
    messages: list[str] = []
    current = head
    for kind in sorted(by_kind, key=lambda k: _ORDER.get(k, 3)):
        heading = f"**{_HEADINGS.get(kind, kind)}**"
        pending: str | None = heading
        for u in by_kind[kind]:
            item = render_uitslag(u)
            addition = f"\n\n{pending}\n{item}" if pending else f"\n{item}"
            if len(current) + len(addition) + len(footer) + 2 > MESSAGE_MAX:
                messages.append(current)
                current = f"{title} (vervolg)"
                addition = f"\n\n{heading}\n{item}"
            current += addition
            pending = None
    messages.append(f"{current}\n\n{footer}")
    return messages


# --- In the channel ---------------------------------------------------------


@dataclass
class StemmingenTickResult:
    sessions: int = 0
    fetched: int = 0
    posted: int = 0
    updated: int = 0
    errors: int = 0

    def summary(self) -> str:
        return (
            f"{self.sessions} debatten, {self.fetched} keer gevraagd, "
            f"{self.posted} geplaatst, {self.updated} bijgewerkt, "
            f"{self.errors} fouten"
        )


def _hash(messages: list[str]) -> str:
    return hashlib.sha256("\x00".join(messages).encode()).hexdigest()[:16]


class DebatStemmingsuitslag:
    """Keeps the outcome of the votes in the channel of each bill's debate.

    What is kept on the sessie (`DebatSessie.stemmingen`):

    * ``dossiers``: the dossiers of the bills on its agenda, and
      ``dossier_tries`` while that list came back empty;
    * ``niet_voor``: not asked again before this moment;
    * ``dagen``: per day of votes, ``posts`` (the messages in the channel),
      ``hash`` (of what they say), ``items`` (how many lines), ``pinned``,
      and ``weg`` when someone took the message away.
    """

    def __init__(
        self,
        session: AsyncSession,
        mattermost: MattermostService | None = None,
        tk_base_url: str = TK_BASE_URL,
        dd_base_url: str = dd.DD_API_URL,
    ) -> None:
        self.session = session
        self.mattermost = mattermost or MattermostService(session)
        self.tk_base_url = tk_base_url
        self.dd_base_url = dd_base_url

    async def close(self) -> None:
        await self.mattermost.close()

    async def tick(
        self, now: datetime, client: httpx.AsyncClient | None = None
    ) -> StemmingenTickResult:
        result = StemmingenTickResult()
        stmt = select(DebatSessie.id).where(
            DebatSessie.channel_id.is_not(None),
            DebatSessie.aanvang.is_not(None),
            DebatSessie.aanvang <= now,
            DebatSessie.aanvang >= now - FOLLOW,
        )
        sessie_ids = list((await self.session.execute(stmt)).scalars().all())
        if not sessie_ids:
            return result
        if not await self.mattermost.is_enabled():
            return result
        own = client is None
        client = client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        source = DebatDirectSource(client, self.dd_base_url)
        try:
            for sessie_id in sessie_ids:
                result.sessions += 1
                try:
                    await self.update(sessie_id, now, client, source, result)
                except Exception:
                    # One debate that breaks must not stop the others.
                    await self.session.rollback()
                    result.errors += 1
                    logger.exception("Stemmingen van sessie %s liepen vast", sessie_id)
        finally:
            if own:
                await client.aclose()
        return result

    async def update(
        self,
        sessie_id: uuid.UUID,
        now: datetime,
        client: httpx.AsyncClient,
        source: DebatDirectSource,
        result: StemmingenTickResult,
    ) -> None:
        sessie = await self.session.get(DebatSessie, sessie_id, populate_existing=True)
        if sessie is None or sessie.channel_id is None or sessie.aanvang is None:
            return
        state = dict(sessie.stemmingen or {})
        not_before = dd.parse_moment(state.get("niet_voor"))
        if not_before is not None and now < not_before:
            return

        since = sessie.aanvang.astimezone(AMSTERDAM).date()
        today = now.astimezone(AMSTERDAM).date()
        try:
            dossiers = await self._dossiers(sessie, state, now, client)
            if not dossiers:
                await self._keep(sessie, state)
                return
            result.fetched += 1
            tk = await fetch_tk_uitslagen(dossiers, since, client, self.tk_base_url)
        except SourceError as exc:
            logger.warning("Stemmingen van sessie %s niet te lezen: %s", sessie_id, exc)
            result.errors += 1
            state["niet_voor"] = (now + AFTER_ERROR).isoformat()
            await self._keep(sessie, state)
            return

        # Debat Direct for today and yesterday only: by then the TK API has
        # the votes per fractie as well.
        live_days = [d for d in (today - timedelta(days=1), today) if d >= since]
        live_ok = True
        try:
            live = await source.uitslagen(dossiers, live_days)
        except SourceError as exc:
            logger.warning(
                "Debat Direct niet te lezen voor sessie %s: %s", sessie_id, exc
            )
            result.errors += 1
            live, live_ok = [], False

        state["niet_voor"] = (now + EVERY).isoformat()
        by_day: dict[date, list[Uitslag]] = defaultdict(list)
        for u in merge(tk, live):
            if u.day is not None:
                by_day[u.day].append(u)
        days = dict(state.get("dagen") or {})
        for day in sorted(by_day):
            items = by_day[day]
            entry = dict(days.get(day.isoformat()) or {})
            if entry.get("weg"):
                continue
            if not live_ok and day in live_days and len(items) < entry.get("items", 0):
                # Without Debat Direct some lines would go that are in the
                # channel already. Kept as it is until it can be read again.
                continue
            await self._pin(entry)
            # The time of the update only in what is posted, not in what is
            # compared: otherwise every round writes the message again.
            content = _hash(render_day(day, items))
            if entry.get("hash") == content:
                days[day.isoformat()] = entry
                continue
            messages = render_day(day, items, updated_at=now)
            entry, complete = await self._write(
                sessie, state, days, day.isoformat(), entry, messages, result
            )
            if complete:
                entry.update(hash=content, items=len(items))
            days[day.isoformat()] = entry
        state["dagen"] = days
        await self._keep(sessie, state)

    async def _dossiers(
        self,
        sessie: DebatSessie,
        state: dict,
        now: datetime,
        client: httpx.AsyncClient,
    ) -> list[str]:
        """The dossiers of the bills on the agenda; empty when there is none.

        An empty agenda is asked again a few times before it counts: the TK
        API can link the zaak to the agendapunt late.
        """
        known = [d for d in state.get("dossiers") or [] if isinstance(d, str)]
        if known:
            return known
        tries = int(state.get("dossier_tries") or 0)
        if tries >= DOSSIERS_TRIES:
            state["niet_voor"] = (sessie.aanvang + FOLLOW).isoformat()
            return []
        found = await fetch_dossiers(sessie.activiteit_id, client, self.tk_base_url)
        state["dossiers"] = found
        if found:
            state.pop("dossier_tries", None)
            return found
        state["dossier_tries"] = tries + 1
        state["niet_voor"] = (
            (now + DOSSIERS_AGAIN).isoformat()
            if tries + 1 < DOSSIERS_TRIES
            else (sessie.aanvang + FOLLOW).isoformat()
        )
        return []

    async def _pin(self, entry: dict) -> None:
        """Pin the first message, again if that failed before."""
        posts = entry.get("posts") or []
        if posts and not entry.get("pinned"):
            if await self.mattermost.pin_post(posts[0]):
                entry["pinned"] = True

    async def _write(
        self,
        sessie: DebatSessie,
        state: dict,
        days: dict,
        key: str,
        entry: dict,
        messages: list[str],
        result: StemmingenTickResult,
    ) -> tuple[dict, bool]:
        """Write the messages of one day. ``True`` when all of them are there."""
        posts = list(entry.get("posts") or [])
        for i, message in enumerate(messages):
            if i < len(posts):
                if await self.mattermost.update_post(posts[i], message):
                    result.updated += 1
                    continue
                try:
                    await self.mattermost.get_post(posts[i])
                except PostNotFoundError:
                    # Someone took it away: not posted again.
                    return {**entry, "posts": posts, "weg": True}, True
                # Mattermost could not be reached: the next round tries again.
                return {**entry, "posts": posts}, False
            post_id = await self.mattermost.send_channel_message(
                sessie.channel_id, message
            )
            if not post_id:
                return {**entry, "posts": posts}, False
            posts.append(post_id)
            result.posted += 1
            # At once: a message that exists has to be known, or a restart
            # posts it a second time.
            days[key] = {**entry, "posts": posts}
            await self._keep(sessie, {**state, "dagen": days})
            if i == 0:
                entry = {**entry, "posts": posts, "pinned": False}
                await self._pin(entry)
        # Fewer messages than before: the ones left over go. One that does
        # not go stays on the list, and the next round tries again.
        left: list[str] = []
        for post_id in posts[len(messages) :]:
            if not await self._remove(post_id):
                left.append(post_id)
        return {**entry, "posts": posts[: len(messages)] + left}, not left

    async def _remove(self, post_id: str) -> bool:
        """Take a message away. ``True`` also when it was gone already."""
        if await self.mattermost.delete_post(post_id):
            return True
        try:
            await self.mattermost.get_post(post_id)
        except PostNotFoundError:
            return True
        return False

    async def _keep(self, sessie: DebatSessie, state: dict) -> None:
        # A deep copy: a JSON column only notices a value that is replaced,
        # and compares with what it holds. A nested dict that was handed in
        # before and changed since would compare equal and not be written.
        sessie.stemmingen = copy.deepcopy(state)
        await self.session.commit()
