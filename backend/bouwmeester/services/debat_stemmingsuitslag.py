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
  and then the round is not matched.
* The TK API has every vote as a `Besluit` on the `Zaak`, with a link to
  the document. Measured on the votes of 3 and 10 November 2026: the
  besluit is there within 0 to 20 minutes of the vote, the votes per
  fractie only the next morning, between 9 and 13 o'clock.

A zaak that is in both is shown once: the besluit from the TK API, the
votes from whichever has them.

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
from bouwmeester.services.debat_kanaal_service import AMSTERDAM, document_url
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
# When a source could not be read: wait this long before the next try.
AFTER_ERROR = timedelta(minutes=5)
# Room in one Mattermost message (the limit is 16383 characters).
MESSAGE_MAX = 15000
# The subject of a zaak can run to several lines.
ONDERWERP_MAX = 160

_HTTP_TIMEOUT = 30.0

SOORT_WETGEVING = "Wetgeving"
SOORT_AMENDEMENT = "Amendement"
SOORT_MOTIE = "Motie"
SOORT_OVERIG = "Overig"

UITKOMST_AANGENOMEN = "aangenomen"
UITKOMST_VERWORPEN = "verworpen"
UITKOMST_STAKEN = "staken"
UITKOMST_AANGEHOUDEN = "aangehouden"
UITKOMST_INGETROKKEN = "ingetrokken"
_UITKOMSTEN = (
    UITKOMST_AANGENOMEN,
    UITKOMST_VERWORPEN,
    UITKOMST_STAKEN,
    UITKOMST_AANGEHOUDEN,
    UITKOMST_INGETROKKEN,
)

STEM_VOOR = "Voor"
STEM_TEGEN = "Tegen"

BRON_TK = "tk"
BRON_DD = "dd"


class StemmingBronError(RuntimeError):
    """A source could not be read. Says nothing about the votes."""


@dataclass(frozen=True)
class Fractiestem:
    """How one fractie voted, or the members of it that voted alike."""

    fractie: str
    soort: str
    # Seats with a vote per fractie, members with a hoofdelijke stemming.
    aantal: int


@dataclass(frozen=True)
class Uitslag:
    """One outcome on one zaak on one day."""

    bron: str
    zaak_soort: str
    onderwerp: str
    # "37022", or "37020-XVI" with a toevoeging.
    dossier: str | None
    volgnummer: int | None
    uitkomst: str
    # Fallback for what is not one of the known outcomes.
    besluit_tekst: str
    hoofdelijk: bool
    moment: datetime | None
    zaak_nummer: str | None = None
    document_nummer: str | None = None
    gewijzigd_op: str = ""
    stemmen: tuple[Fractiestem, ...] = field(default=())
    # Of a changed motie or amendement: the number of the one it replaces.
    # Debat Direct can know a changed motie before it has a number of its
    # own ("nr. ??, was nr. 36"); this is what it is matched by then.
    vervangt: int | None = None

    @property
    def key(self) -> tuple:
        """What tells one zaak from another across the two sources."""
        if self.zaak_soort == SOORT_WETGEVING and self.dossier:
            return (self.dossier, "wet")
        if self.dossier and self.volgnummer:
            return (self.dossier, self.volgnummer)
        return ("onderwerp", self.onderwerp.lower())

    @property
    def dag(self) -> date | None:
        return self.moment.astimezone(AMSTERDAM).date() if self.moment else None

    def totaal(self, soort: str) -> int:
        return sum(s.aantal for s in self.stemmen if s.soort == soort)

    def fracties(self, soort: str) -> list[str]:
        """The fracties that voted `soort`, largest first.

        With a hoofdelijke stemming a fractie can be split: then its share
        is said ("Partij A 12 van 22").
        """
        per: dict[str, dict[str, int]] = defaultdict(dict)
        for s in self.stemmen:
            per[s.fractie][s.soort] = per[s.fractie].get(s.soort, 0) + s.aantal
        names: list[tuple[int, str]] = []
        for fractie, counts in per.items():
            mine = counts.get(soort, 0)
            if not mine:
                continue
            total = sum(counts.values())
            label = fractie if mine == total else f"{fractie} {mine} van {total}"
            names.append((mine, label))
        return [label for _, label in sorted(names, key=lambda n: (-n[0], n[1]))]


def _uitkomst(text: str) -> str:
    """`aangenomen`, `verworpen`, ... from "Stemmen - aangenomen" or "Aangenomen"."""
    rest = text.split(" - ", 1)[-1].strip().lower()
    for uitkomst in _UITKOMSTEN:
        if rest.startswith(uitkomst):
            return uitkomst
    return rest


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        try:
            # Debat Direct writes the offset without a colon: +0100.
            moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
    return moment if moment.tzinfo else None


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
            raise StemmingBronError(str(exc) or type(exc).__name__) from exc
        if not isinstance(body, dict):
            raise StemmingBronError("geen object")
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
            if zaak.get("Soort") != SOORT_WETGEVING:
                continue
            for dossier in _rows(zaak.get("Kamerstukdossier")):
                key = dossier_key(dossier.get("Nummer"), dossier.get("Toevoeging"))
                if key:
                    dossiers.add(key)
    return sorted(dossiers)


def _dossier_filter(dossiers: list[str]) -> str:
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
    in_dossier = _dossier_filter(dossiers)
    if not in_dossier:
        return []
    rows = await _get_tk(
        client,
        f"{base_url}/Besluit",
        {
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


def _tk_stemmen(rows: list[dict]) -> tuple[Fractiestem, ...]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        fractie = row.get("ActorFractie") or row.get("ActorNaam")
        soort = row.get("Soort")
        if not isinstance(fractie, str) or soort not in (STEM_VOOR, STEM_TEGEN):
            continue
        if row.get("Persoon_Id"):
            # A hoofdelijke stemming: one row per member.
            counts[(fractie, soort)] += 1
        else:
            grootte = row.get("FractieGrootte")
            counts[(fractie, soort)] += grootte if isinstance(grootte, int) else 0
    return tuple(
        Fractiestem(fractie=f, soort=s, aantal=n)
        for (f, s), n in sorted(counts.items())
    )


def _vervangt(onderwerp: str) -> int | None:
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
        documenten = _rows(zaak.get("Document"))
        document = next(
            (d for d in documenten if d.get("Volgnummer") == volgnummer), None
        ) or (documenten[0] if documenten else None)
        soort = str(zaak.get("Soort") or "")
        uitslag = Uitslag(
            bron=BRON_TK,
            zaak_soort=soort
            if soort in (SOORT_WETGEVING, SOORT_AMENDEMENT, SOORT_MOTIE)
            else SOORT_OVERIG,
            onderwerp=" ".join(str(zaak.get("Onderwerp") or "").split()),
            dossier=dossier,
            volgnummer=volgnummer,
            uitkomst=_uitkomst(str(row.get("BesluitSoort") or "")),
            besluit_tekst=" ".join(str(row.get("BesluitTekst") or "").split()),
            hoofdelijk=str(row.get("StemmingsSoort") or "").lower() == "hoofdelijk",
            moment=_moment(activiteit.get("Aanvangstijd"))
            or _moment(activiteit.get("Datum")),
            zaak_nummer=zaak["Nummer"],
            document_nummer=(document or {}).get("DocumentNummer"),
            gewijzigd_op=str(row.get("GewijzigdOp") or ""),
            stemmen=_tk_stemmen(_rows(row.get("Stemming"))),
            vervangt=_vervangt(str(zaak.get("Onderwerp") or "")),
        )
        key = (uitslag.dag, uitslag.key)
        known = latest.get(key)
        if known is None or uitslag.gewijzigd_op >= known.gewijzigd_op:
            latest[key] = uitslag
    return list(latest.values())


# --- Debat Direct -----------------------------------------------------------

# "(37022, nr. 45)", "(37020-XVI, nr. 91)", "(37022)", and "(37020-XXIII,
# nr. ??, was nr. 36)" for a changed motie that has no number yet.
_KENMERK = re.compile(r"\((\d{5})(?:-([A-Z0-9]+))?(?:,\s*nr\.\s*(\d+|\?\?)[^)]*)?\)")
_WAS = re.compile(r"\bwas nr\.\s*(\d+)")
# "ter vervanging van nr. 36", or "(t.v.v. 37020-VII-42)" at the end.
_TER_VERVANGING = re.compile(
    r"\bter vervanging van nr\.\s*(\d+)|\bt\.v\.v\.\s*\d+(?:-[A-Z0-9]+)?-(\d+)",
    re.IGNORECASE,
)
_LIDWOORD = re.compile(r"^(?:de|het)\s+", re.IGNORECASE)


def parse_dd_titel(
    titel: str,
) -> tuple[str, str | None, int | None, str, int | None]:
    """The kind of zaak, its dossier, its number, and the title without them.

    The last kenmerk in the title counts: a title can mention another
    document before it.
    """
    gevonden = list(_KENMERK.finditer(titel))
    dossier: str | None = None
    volgnummer: int | None = None
    rest = titel
    vervangt: int | None = None
    if gevonden:
        m = gevonden[-1]
        dossier = m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
        if m.group(3) and m.group(3).isdigit():
            volgnummer = int(m.group(3))
        was = _WAS.search(m.group(0))
        vervangt = int(was.group(1)) if was else None
        rest = (titel[: m.start()] + titel[m.end() :]).strip()
    begin = rest.lower()[:40]
    if "amendement" in begin:
        soort = SOORT_AMENDEMENT
    elif "motie" in begin:
        soort = SOORT_MOTIE
    elif "wetsvoorstel" in begin or "wetvoorstel" in begin:
        soort = SOORT_WETGEVING
    else:
        soort = SOORT_OVERIG
    rest = _LIDWOORD.sub("", " ".join(rest.split()))
    return soort, dossier, volgnummer, rest[:1].upper() + rest[1:], vervangt


def is_stemmingen(debat: dd.DdDebat) -> bool:
    naam = f"{debat.debate_type or ''} {debat.name or ''}".lower()
    return "stemming" in naam


@dataclass(frozen=True)
class DdActors:
    # Party id to its short name.
    partijen: dict[str, str]
    # Member id to party id.
    leden: dict[str, str]

    def zetels(self, partij_id: str) -> int:
        return sum(1 for p in self.leden.values() if p == partij_id)


def parse_dd_actors(raw: dict) -> DdActors:
    partijen = {
        str(p["id"]).lower(): str(p.get("shorthand") or p.get("name") or "")
        for p in raw.get("parties") or []
        if isinstance(p, dict) and p.get("id")
    }
    leden = {
        str(p["id"]).lower(): str(p["partyId"]).lower()
        for p in raw.get("politicians") or []
        if isinstance(p, dict) and p.get("id") and p.get("partyId")
    }
    return DdActors(partijen=partijen, leden=leden)


def _dd_stemmen(ronde: dict, actors: DdActors) -> tuple[Fractiestem, ...]:
    hoofdelijk = str(ronde.get("type") or "").lower().startswith("hoofd")
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for vote in ronde.get("votes") or []:
        if not isinstance(vote, list) or len(vote) != 2:
            continue
        actor, soort = str(vote[0]).lower(), vote[1]
        if soort not in (STEM_VOOR, STEM_TEGEN):
            # "Onbekend" and the like: not there, or did not take part.
            continue
        if hoofdelijk:
            partij = actors.leden.get(actor)
            if partij is None:
                continue
            counts[(actors.partijen.get(partij, "?"), soort)] += 1
        else:
            naam = actors.partijen.get(actor)
            if naam is None:
                continue
            counts[(naam, soort)] += actors.zetels(actor)
    return tuple(
        Fractiestem(fractie=f, soort=s, aantal=n)
        for (f, s), n in sorted(counts.items())
    )


def parse_dd_votings(raw: dict, actors: DdActors, dossiers: set[str]) -> list[Uitslag]:
    """The voting rounds of one block of votes on zaken in these dossiers.

    A zaak voted on twice (the votes were equal, then a hoofdelijke
    stemming) keeps the round that started last.
    """
    latest: dict[tuple, tuple[datetime | None, Uitslag]] = {}
    for voting in raw.get("votings") or []:
        if not isinstance(voting, dict):
            continue
        for ronde in voting.get("votingRounds") or []:
            if not isinstance(ronde, dict) or not ronde.get("result"):
                continue
            titel = " ".join(str(ronde.get("title") or "").split())
            soort, dossier, volgnummer, onderwerp, vervangt = parse_dd_titel(titel)
            if dossier is None:
                # A cut-off title: the dossier may be in the subject.
                dossier = parse_dd_titel(str(voting.get("subject") or ""))[1]
            if dossier not in dossiers:
                continue
            started = _moment(ronde.get("startedAt"))
            uitslag = Uitslag(
                bron=BRON_DD,
                zaak_soort=soort,
                onderwerp=onderwerp,
                dossier=dossier,
                volgnummer=volgnummer,
                uitkomst=_uitkomst(str(ronde["result"])),
                besluit_tekst=str(ronde["result"]),
                hoofdelijk=str(ronde.get("type") or "").lower().startswith("hoofd"),
                moment=started or _moment(voting.get("startsAt")),
                stemmen=_dd_stemmen(ronde, actors),
                vervangt=vervangt,
            )
            known = latest.get(uitslag.key)
            if known is None or (started and (known[0] is None or started >= known[0])):
                latest[uitslag.key] = (started, uitslag)
    return [u for _, u in latest.values()]


class DdBron:
    """The blocks of votes of Debat Direct, read once per round of the worker."""

    def __init__(self, client: httpx.AsyncClient, base_url: str = dd.DD_API_URL):
        self.client = client
        self.base_url = base_url
        self._days: dict[date, tuple[list[dict], DdActors]] = {}

    async def blocks(self, day: date) -> tuple[list[dict], DdActors]:
        if day in self._days:
            return self._days[day]
        try:
            agenda = await dd.fetch_agenda(self.client, day, self.base_url)
            raws: list[dict] = []
            for debat in agenda:
                if not is_stemmingen(debat) or debat.started_at is None:
                    continue
                response = await dd._get(
                    self.client, f"debates/{debat.id}", self.base_url
                )
                response.raise_for_status()
                raw = response.json()
                if isinstance(raw, dict):
                    raws.append(raw)
            actors = DdActors({}, {})
            if raws:
                response = await dd._get(
                    self.client, f"actors/{day.isoformat()}", self.base_url
                )
                response.raise_for_status()
                actors = parse_dd_actors(response.json())
        except (dd.DebatDirectError, httpx.HTTPError, ValueError) as exc:
            raise StemmingBronError(str(exc) or type(exc).__name__) from exc
        self._days[day] = (raws, actors)
        return raws, actors

    async def uitslagen(self, dossiers: list[str], days: list[date]) -> list[Uitslag]:
        found: list[Uitslag] = []
        for day in days:
            raws, actors = await self.blocks(day)
            for raw in raws:
                found += parse_dd_votings(raw, actors, set(dossiers))
        return found


def _over(onderwerp: str) -> str:
    """What a motie is about: the words after "over", as they compare."""
    _, sep, rest = onderwerp.partition(" over ")
    rest = re.sub(r"\(.*?\)", " ", rest)
    return " ".join(rest.lower().split()) if sep else ""


def merge(tk: list[Uitslag], dd_uitslagen: list[Uitslag]) -> list[Uitslag]:
    """One outcome per zaak per day: the TK API's besluit, the votes of either.

    Debat Direct alone for what the TK API does not have yet.
    """
    merged: dict[tuple, Uitslag] = {(u.dag, u.key): u for u in tk}
    # A changed motie that has no number of its own in Debat Direct yet: by
    # the number it replaces, or else by what it is about. The TK API does
    # not always say what a changed motie replaces, and names the members
    # where Debat Direct writes "c.s.", so only the part after "over".
    by_vervangt = {
        (u.dag, u.dossier, u.vervangt): (u.dag, u.key) for u in tk if u.vervangt
    }
    by_over = {
        (u.dag, u.dossier, _over(u.onderwerp)): (u.dag, u.key)
        for u in tk
        if _over(u.onderwerp)
    }
    for u in dd_uitslagen:
        key = (u.dag, u.key)
        if u.volgnummer is None:
            key = by_vervangt.get(
                (u.dag, u.dossier, u.vervangt),
                by_over.get((u.dag, u.dossier, _over(u.onderwerp)), key),
            )
        known = merged.get(key)
        if known is None:
            merged[key] = u
        elif not known.stemmen and u.stemmen:
            merged[key] = replace(known, stemmen=u.stemmen, hoofdelijk=u.hoofdelijk)
    return list(merged.values())


# --- The message ------------------------------------------------------------

_ORDER = {SOORT_WETGEVING: 0, SOORT_AMENDEMENT: 1, SOORT_MOTIE: 2, SOORT_OVERIG: 3}
_KOPJES = {
    SOORT_WETGEVING: "Wetsvoorstellen",
    SOORT_AMENDEMENT: "Amendementen",
    SOORT_MOTIE: "Moties",
    SOORT_OVERIG: "Overig",
}
_LABEL = {
    UITKOMST_AANGENOMEN: "✅ **Aangenomen**",
    UITKOMST_VERWORPEN: "❌ **Verworpen**",
    UITKOMST_STAKEN: "⚖️ Stemmen staken",
    UITKOMST_AANGEHOUDEN: "⏸️ Aangehouden",
    UITKOMST_INGETROKKEN: "↩️ Ingetrokken",
}
_DAGEN = (
    "maandag",
    "dinsdag",
    "woensdag",
    "donderdag",
    "vrijdag",
    "zaterdag",
    "zondag",
)
_MAANDEN = (
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)


def _dag(day: date) -> str:
    return f"{_DAGEN[day.weekday()]} {day.day} {_MAANDEN[day.month - 1]}"


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


def _stemregel(u: Uitslag) -> str:
    """The count and who voted for, when the votes are known."""
    if not u.stemmen:
        return ""
    voor, tegen = u.totaal(STEM_VOOR), u.totaal(STEM_TEGEN)
    regel = f"voor {voor}, tegen {tegen}"
    if u.hoofdelijk:
        regel += " (hoofdelijk)"
    fracties = ", ".join(escape_mattermost_prose(f) for f in u.fracties(STEM_VOOR))
    return f"{regel} · voor: {fracties}" if fracties else regel


def render_uitslag(u: Uitslag) -> str:
    """One item: the outcome, the zaak with a link, who voted for."""
    label = _LABEL.get(u.uitkomst, escape_mattermost_prose(u.besluit_tekst))
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
    stem = _stemregel(u)
    return f"{line}\n  {stem}" if stem else line


def render_dag(
    day: date, uitslagen: list[Uitslag], *, bijgewerkt: datetime | None = None
) -> list[str]:
    """The messages for one day of votes. One, unless it is too long."""
    if not uitslagen:
        return []
    titel = f"🗳️ **Stemmingen van {_dag(day)}**"
    tellingen: dict[str, int] = defaultdict(int)
    for u in uitslagen:
        tellingen[u.uitkomst] += 1
    samen = ", ".join(f"{tellingen[k]} {k}" for k in _UITKOMSTEN if tellingen[k])
    head = f"{titel}\n{samen}" if samen else titel

    bronnen = {u.bron for u in uitslagen}
    footer = "_Uit "
    footer += {
        frozenset({BRON_TK}): "de TK-API",
        frozenset({BRON_DD}): "Debat Direct",
    }.get(frozenset(bronnen), "de TK-API en Debat Direct")
    if bijgewerkt is not None:
        footer += f", bijgewerkt om {_hhmm(bijgewerkt)}"
    footer += "."
    if any(
        not u.stemmen
        for u in uitslagen
        if u.uitkomst in (UITKOMST_AANGENOMEN, UITKOMST_VERWORPEN)
    ):
        footer += " Waar de stemmen per fractie ontbreken, volgen die later."
    footer += "_"

    per_soort: dict[str, list[Uitslag]] = defaultdict(list)
    for u in sorted(uitslagen, key=_sort_key):
        per_soort[u.zaak_soort].append(u)

    # Packed into messages, an item at a time, each under the limit.
    messages: list[str] = []
    current = head
    for soort in sorted(per_soort, key=lambda s: _ORDER.get(s, 3)):
        kop = f"**{_KOPJES.get(soort, soort)}**"
        pending_kop: str | None = kop
        for u in per_soort[soort]:
            item = render_uitslag(u)
            addition = f"\n\n{pending_kop}\n{item}" if pending_kop else f"\n{item}"
            if len(current) + len(addition) + len(footer) + 2 > MESSAGE_MAX:
                messages.append(current)
                current = f"{titel} (vervolg)"
                addition = f"\n\n{kop}\n{item}"
            current += addition
            pending_kop = None
    messages.append(f"{current}\n\n{footer}")
    return messages


# --- In the channel ---------------------------------------------------------


@dataclass
class StemmingenTickResult:
    sessies: int = 0
    gevraagd: int = 0
    geplaatst: int = 0
    bijgewerkt: int = 0
    fouten: int = 0

    def summary(self) -> str:
        return (
            f"{self.sessies} debatten, {self.gevraagd} keer gevraagd, "
            f"{self.geplaatst} geplaatst, {self.bijgewerkt} bijgewerkt, "
            f"{self.fouten} fouten"
        )


def _hash(messages: list[str]) -> str:
    return hashlib.sha256("\x00".join(messages).encode()).hexdigest()[:16]


class DebatStemmingsuitslag:
    """Keeps the outcome of the votes in the channel of each bill's debate."""

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
        bron = DdBron(client, self.dd_base_url)
        try:
            for sessie_id in sessie_ids:
                result.sessies += 1
                try:
                    await self.update(sessie_id, now, client, bron, result)
                except Exception:
                    # One debate that breaks must not stop the others.
                    await self.session.rollback()
                    result.fouten += 1
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
        bron: DdBron,
        result: StemmingenTickResult,
    ) -> None:
        sessie = await self.session.get(DebatSessie, sessie_id, populate_existing=True)
        if sessie is None or sessie.channel_id is None or sessie.aanvang is None:
            return
        state = dict(sessie.stemmingen or {})
        niet_voor = _moment(state.get("niet_voor"))
        if niet_voor is not None and now < niet_voor:
            return

        since = sessie.aanvang.astimezone(AMSTERDAM).date()
        today = now.astimezone(AMSTERDAM).date()
        try:
            if "dossiers" not in state:
                state["dossiers"] = await fetch_dossiers(
                    sessie.activiteit_id, client, self.tk_base_url
                )
            dossiers = [d for d in state["dossiers"] if isinstance(d, str)]
            if not dossiers:
                # Not a debate on a bill: asked once, and never again.
                state["niet_voor"] = (sessie.aanvang + FOLLOW).isoformat()
                await self._keep(sessie, state)
                return
            result.gevraagd += 1
            tk = await fetch_tk_uitslagen(dossiers, since, client, self.tk_base_url)
            # Debat Direct for today and yesterday only: by then the TK API
            # has the votes per fractie as well.
            days = [d for d in (today - timedelta(days=1), today) if d >= since]
            live = await bron.uitslagen(dossiers, days)
        except StemmingBronError as exc:
            logger.warning("Stemmingen van sessie %s niet te lezen: %s", sessie_id, exc)
            result.fouten += 1
            state["niet_voor"] = (now + AFTER_ERROR).isoformat()
            await self._keep(sessie, state)
            return

        state["niet_voor"] = (now + EVERY).isoformat()
        per_dag: dict[date, list[Uitslag]] = defaultdict(list)
        for u in merge(tk, live):
            if u.dag is not None:
                per_dag[u.dag].append(u)
        berichten = dict(state.get("berichten") or {})
        for day in sorted(per_dag):
            items = per_dag[day]
            blok = dict(berichten.get(day.isoformat()) or {})
            if blok.get("weg"):
                continue
            # The time of the update only in what is posted, not in what is
            # compared: otherwise every round writes the message again.
            inhoud = _hash(render_dag(day, items))
            if blok.get("hash") == inhoud:
                continue
            messages = render_dag(day, items, bijgewerkt=now)
            blok, klaar = await self._write(
                sessie, state, berichten, day.isoformat(), blok, messages, result
            )
            if klaar:
                blok["hash"] = inhoud
            berichten[day.isoformat()] = blok
            state["berichten"] = berichten
        await self._keep(sessie, state)

    async def _write(
        self,
        sessie: DebatSessie,
        state: dict,
        berichten: dict,
        key: str,
        blok: dict,
        messages: list[str],
        result: StemmingenTickResult,
    ) -> tuple[dict, bool]:
        """Write the messages of one day. ``True`` when all of them are there."""
        posts = list(blok.get("posts") or [])
        for i, message in enumerate(messages):
            if i < len(posts):
                if await self.mattermost.update_post(posts[i], message):
                    result.bijgewerkt += 1
                    continue
                try:
                    await self.mattermost.get_post(posts[i])
                except PostNotFoundError:
                    # Someone took it away: not posted again.
                    return {**blok, "posts": posts, "weg": True}, True
                # Mattermost could not be reached: the next round tries again.
                return {**blok, "posts": posts}, False
            post_id = await self.mattermost.send_channel_message(
                sessie.channel_id, message
            )
            if not post_id:
                return {**blok, "posts": posts}, False
            posts.append(post_id)
            result.geplaatst += 1
            # At once: a message that exists has to be known, or a restart
            # posts it a second time.
            berichten[key] = {**blok, "posts": posts}
            await self._keep(sessie, {**state, "berichten": berichten})
            if i == 0:
                await self.mattermost.pin_post(post_id)
        # Fewer messages than before: the ones left over go.
        for post_id in posts[len(messages) :]:
            await self.mattermost.delete_post(post_id)
        return {**blok, "posts": posts[: len(messages)]}, True

    async def _keep(self, sessie: DebatSessie, state: dict) -> None:
        # A deep copy: a JSON column only notices a value that is replaced,
        # and compares with what it holds. A nested dict that was handed in
        # before and changed since would compare equal and not be written.
        sessie.stemmingen = copy.deepcopy(state)
        await self.session.commit()
