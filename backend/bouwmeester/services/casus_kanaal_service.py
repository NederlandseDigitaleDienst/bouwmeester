"""Voortgang van een casus in het Mattermost-kanaal dat eraan hangt.

Een kanaal aan een casus (scope casus, zie models/mattermost_channel_link.py)
krijgt een kort bericht als de casus naar een andere fase gaat, en als er
een issue bijkomt of af is (een onderzoeksvraag of een gewoon issue). Alleen een
privékanaal, en alleen als de voortgang er aan staat. Bij een kanaal dat
van de lead is meegekomen staat die uit tot het team hem aanzet.

Een bericht draagt korte inhoud (de toelichting van de vraag, de
omschrijving van de fase), want daar dient het kanaal voor. Wie in het
kanaal zit, hoeft niet in het casusteam te zitten: de link wijst naar
Bouwmeester, en daar geldt de toegangsregel van de casus.

Elk bericht komt ook bij de casus te staan (models/casus_kanaalbericht.py),
met of zonder kanaal en ook als Mattermost uit staat. Zo is in Bouwmeester
te zien wat er in het kanaal staat, of zou staan.

Verzenden gebeurt pas na de commit, in de achtergrond en met een eigen
sessie, zoals bij notificaties (notification_service.py). Een bericht over
iets dat niet doorgaat gaat zo nooit weg, en niemand wacht op Mattermost.
Daarna krijgt het bewaarde bericht zijn status.
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.config import get_settings
from bouwmeester.models.casus_kanaalbericht import (
    STATUS_GEEN_KANAAL,
    STATUS_MISLUKT,
    STATUS_UIT,
    STATUS_VERSTUURD,
    STATUS_WACHT,
    CasusKanaalbericht,
)
from bouwmeester.models.mattermost_channel_link import (
    SCOPE_CASUS,
    MattermostChannelLink,
)
from bouwmeester.schema.casus_fases import geldende_casus_fases
from bouwmeester.services.mattermost_utils import escape_mattermost_prose

logger = logging.getLogger(__name__)

# Zelfde reden als in notification_service: zonder sterke verwijzing kan de
# GC een taak opruimen voor hij gedraaid heeft, en dan valt het bericht stil.
_BACKGROUND_TASKS: set[asyncio.Task] = set()

# Waar de berichten van een request wachten tot de commit (session.info),
# en of de sessie al luistert naar zijn commit.
_WACHTRIJ = "casuskanaal_berichten"
_LUISTERT = "casuskanaal_luistert"

# Achter een `@` of `~` in tekst van gebruikers; zie `_esc`.
ZERO_WIDTH_SPACE = "\u200b"

# Korte inhoud: genoeg om te weten waar het over gaat, niet het hele stuk.
MAX_INHOUD = 300


@dataclass(frozen=True)
class Bericht:
    bericht_id: UUID
    channel_ids: tuple[str, ...]
    tekst: str


def wachtende_berichten(session: AsyncSession) -> list[Bericht]:
    """De berichten die na de commit naar Mattermost gaan."""
    return list(session.info.get(_WACHTRIJ, []))


async def kanalen_van_casus(
    session: AsyncSession, casus_id: UUID
) -> list[tuple[str, str]]:
    """De kanalen van deze casus waar de voortgang aan staat: (id, naam)."""
    stmt = (
        select(
            MattermostChannelLink.channel_id,
            MattermostChannelLink.channel_display_name,
        )
        .where(
            MattermostChannelLink.scope_type == SCOPE_CASUS,
            MattermostChannelLink.scope_id == casus_id,
            MattermostChannelLink.casus_updates_enabled.is_(True),
            MattermostChannelLink.disabled_at.is_(None),
        )
        .order_by(MattermostChannelLink.channel_display_name)
    )
    return [(r.channel_id, r.channel_display_name) for r in await session.execute(stmt)]


async def meld(session: AsyncSession, casus_id: UUID, tekst: str) -> None:
    """Bewaar een bericht bij de casus en zet het klaar voor zijn kanalen.

    Zonder kanaal met voortgang aan blijft het bij bewaren: dan staat het
    alleen in Bouwmeester, en er komt geen achtergrondtaak.
    """
    kanalen = await kanalen_van_casus(session, casus_id)
    bericht = CasusKanaalbericht(
        id=uuid.uuid4(),
        casus_id=casus_id,
        tekst=tekst,
        kanalen=[{"id": kanaal_id, "naam": naam} for kanaal_id, naam in kanalen],
        status=STATUS_WACHT if kanalen else STATUS_GEEN_KANAAL,
    )
    session.add(bericht)
    if not kanalen:
        return
    wachtrij = session.info.get(_WACHTRIJ)
    if wachtrij is None:
        wachtrij = session.info[_WACHTRIJ] = []
        _na_commit_versturen(session)
    wachtrij.append(
        Bericht(bericht.id, tuple(kanaal_id for kanaal_id, _ in kanalen), tekst)
    )


async def berichten_van_casus(
    session: AsyncSession, casus_id: UUID, limit: int = 50
) -> list[CasusKanaalbericht]:
    """De bewaarde berichten van een casus, nieuwste eerst."""
    stmt = (
        select(CasusKanaalbericht)
        .where(CasusKanaalbericht.casus_id == casus_id)
        .order_by(CasusKanaalbericht.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def _na_commit_versturen(session: AsyncSession) -> None:
    """Hang aan de sessie: na de echte commit gaan de berichten weg.

    `after_commit` vuurt ook als een savepoint wordt vrijgegeven
    (`begin_nested()`), en dan is er nog niets gecommit: het bericht zou
    vertrekken voor de rij bestaat en de status zou op "wacht" blijven.
    Daarom luisteren we niet eenmalig (`once`), maar laten we een savepoint
    voorbijgaan en wachten we op de commit van de buitenste transactie.
    Eén keer per sessie aanhaken is genoeg; de wachtrij wordt leeggehaald.
    """
    if session.info.get(_LUISTERT):
        return
    session.info[_LUISTERT] = True
    sync_session = session.sync_session

    @event.listens_for(sync_session, "after_commit")
    def _after_commit(sess):
        if sess.in_nested_transaction():
            return
        berichten = sess.info.pop(_WACHTRIJ, None)
        if not berichten:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(_verstuur(berichten))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

    # Wat terugrolt, is niet gebeurd: dan gaat er ook niets naar het kanaal.
    @event.listens_for(sync_session, "after_rollback")
    def _after_rollback(sess):
        if sess.in_nested_transaction():
            return
        sess.info.pop(_WACHTRIJ, None)


async def _verstuur(berichten: list[Bericht]) -> None:
    try:
        from bouwmeester.core.database import async_session
        from bouwmeester.services.mattermost_service import MattermostService

        async with async_session() as session:
            mm = MattermostService(session)
            try:
                statussen = await plaats(mm, berichten)
            finally:
                await mm.close()
            await zet_status(session, statussen)
            await session.commit()
    except Exception:
        logger.exception("Casusberichten naar Mattermost mislukt")


async def plaats(mm: Any, berichten: list[Bericht]) -> dict[UUID, str]:
    """Zet de berichten in hun kanalen; per bericht hoe dat afliep.

    Vlak voor het versturen nog een keer: is het kanaal privé? Een
    beheerder kan een kanaal in Mattermost openbaar maken nadat het aan de
    casus is gekoppeld. Dan gaat er niets heen.
    """
    if not await mm.is_enabled():
        return {bericht.bericht_id: STATUS_UIT for bericht in berichten}
    kanalen: dict[str, Any] = {}
    statussen: dict[UUID, str] = {}
    for bericht in berichten:
        gelukt = True
        for channel_id in bericht.channel_ids:
            if channel_id not in kanalen:
                kanalen[channel_id] = await mm.get_channel(channel_id)
            kanaal = kanalen[channel_id]
            if not is_privekanaal(kanaal):
                gelukt = False
                # Met wat Mattermost zei: een nieuwere versie kan een ander
                # antwoord geven dan de 9.5 van lokaal, en dan is dit de plek
                # waar dat te zien moet zijn.
                logger.warning(
                    "Casusbericht niet geplaatst: kanaal %s is niet te lezen of "
                    "niet (meer) privé; Mattermost zegt %s",
                    channel_id,
                    kanaal_kort(kanaal),
                )
            elif not await mm.send_channel_message(channel_id, bericht.tekst):
                gelukt = False
                logger.warning("Casusbericht niet geplaatst in kanaal %s", channel_id)
        statussen[bericht.bericht_id] = STATUS_VERSTUURD if gelukt else STATUS_MISLUKT
    return statussen


async def zet_status(session: AsyncSession, statussen: dict[UUID, str]) -> None:
    """Hoe het versturen afliep, bij de bewaarde berichten."""
    for bericht_id, status in statussen.items():
        await session.execute(
            update(CasusKanaalbericht)
            .where(CasusKanaalbericht.id == bericht_id)
            .values(status=status)
        )


def is_privekanaal(kanaal: Any) -> bool:
    """Een bestaand, niet gearchiveerd privékanaal, zoals Mattermost het geeft."""
    return (
        isinstance(kanaal, dict)
        and kanaal.get("type") == "P"
        and not kanaal.get("delete_at")
    )


def kanaal_kort(kanaal: Any) -> dict[str, Any] | None:
    """Wat van het antwoord van Mattermost in het log mag: geen naam of kop."""
    if not isinstance(kanaal, dict):
        return None
    return {k: kanaal.get(k) for k in ("id", "type", "delete_at", "team_id")}


# Een bericht dat niet (zeker) is aangekomen mag opnieuw.
OPNIEUW_STATUSSEN = (STATUS_WACHT, STATUS_MISLUKT, STATUS_UIT)

# Na zo lang is "wacht" niet meer onderweg maar blijven hangen: de taak
# liep stuk of het proces is herstart tussen de commit en het versturen.
BLIJFT_HANGEN_NA = timedelta(minutes=10)


async def opnieuw(session: AsyncSession, mm: Any, bericht: CasusKanaalbericht) -> str:
    """Bied een bewaard bericht nog een keer aan zijn kanalen aan.

    Naar de kanalen van toen, met dezelfde controles als de eerste keer.
    Geeft de nieuwe status terug en zet die bij het bericht.
    """
    te_versturen = Bericht(
        bericht.id, tuple(k["id"] for k in bericht.kanalen), bericht.tekst
    )
    statussen = await plaats(mm, [te_versturen])
    await zet_status(session, statussen)
    return statussen[bericht.id]


async def blijven_hangen(
    session: AsyncSession, ouder_dan: timedelta = BLIJFT_HANGEN_NA
) -> list[CasusKanaalbericht]:
    """Berichten die op "wacht" staan terwijl dat allang niet meer kan."""
    grens = datetime.now(UTC) - ouder_dan
    stmt = (
        select(CasusKanaalbericht)
        .where(
            CasusKanaalbericht.status == STATUS_WACHT,
            CasusKanaalbericht.created_at < grens,
        )
        .order_by(CasusKanaalbericht.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def verstuur_blijven_hangen(session: AsyncSession, mm: Any) -> int:
    """Voor de worker: wat bleef hangen alsnog versturen. Geeft het aantal."""
    hangend = await blijven_hangen(session)
    for bericht in hangend:
        await opnieuw(session, mm, bericht)
    return len(hangend)


# ---------------------------------------------------------------------------
# Opmaak
# ---------------------------------------------------------------------------


def casus_url(casus: Any) -> str | None:
    """De casus in Bouwmeester, op de tab Casussen van zijn initiatief."""
    base = get_settings().FRONTEND_URL.rstrip("/")
    # Zelfde controle als bij notificaties: geen link met een raar schema.
    if urlparse(base).scheme not in ("http", "https"):
        return None
    if casus.initiatief_id is None:
        return None
    return f"{base}/initiatieven/{casus.initiatief_id}/casussen?casus={casus.id}"


def _platte_tekst(tekst: str) -> str:
    """Tiptap-JSON als lopende tekst, met een spatie tussen de blokken.

    Niet `tiptap_to_plain`: die plakt alinea's aan elkaar ("Eerstetweede").
    Gewone tekst komt ongewijzigd terug. JSON die op tiptap lijkt maar het
    niet is, geeft geen fout: anders lukt het afronden van een issue niet
    meer omdat het bericht erover niet te maken is.
    """
    try:
        doc = json.loads(tekst)
    except (ValueError, TypeError, RecursionError):
        return tekst
    if not (isinstance(doc, dict) and doc.get("type") == "doc"):
        return tekst
    delen: list[str] = []

    def lees(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if "text" in node:
            delen.append(str(node["text"]))
        elif node.get("type") in ("mention", "hashtagMention"):
            attrs = node.get("attrs")
            if isinstance(attrs, dict):
                delen.append(str(attrs.get("label", "")))
        elif node.get("type") == "hardBreak":
            delen.append(" ")
        kinderen = node.get("content")
        if not isinstance(kinderen, list):
            return
        for kind in kinderen:
            lees(kind)
        if kinderen:
            delen.append(" ")

    try:
        lees(doc)
    except RecursionError:
        return ""
    return "".join(delen)


def _kort(tekst: str | None) -> str | None:
    """Platte tekst op één regel, afgekapt op een woordgrens."""
    plat = _platte_tekst(tekst) if tekst else None
    if not plat:
        return None
    plat = re.sub(r"\s+", " ", plat).strip()
    if len(plat) <= MAX_INHOUD:
        return plat or None
    knip = plat[:MAX_INHOUD].rsplit(" ", 1)[0]
    return f"{knip}…"


def _esc(tekst: str) -> str:
    """Tekst van gebruikers in een bericht: op één regel en geëscapet.

    Eerst de backslash zelf. Anders wordt `\\@channel` na het escapen
    `\\\\@channel`: een gewone backslash met een werkende @channel erachter,
    en zo ook een werkende link. Regeleinden gaan eruit, anders schrijft een
    titel eigen regels in het bericht, zoals een nep-voetregel of een citaat.

    Een vermelding (`@`) en een kanaalverwijzing (`~`) krijgen geen
    backslash maar een zero-width space erachter. Mattermost leest
    vermeldingen op de server uit de ruwe tekst en knipt die op alles wat
    geen letter, cijfer, `@` of leesteken van een naam is; een backslash is
    zo'n knippunt, dus van `\\@channel` blijft `@channel` over en de melding
    gaat af. In de client blijft de backslash bovendien zichtbaar. Gemeten
    tegen Mattermost 9.5.14 op 20 november 2026: met backslash een melding
    voor elk lid, met zero-width space niet.
    """
    een_regel = re.sub(r"\s+", " ", tekst).strip()
    # `<` ook: anders wordt `<node:…>` in de weergave bij de casus een
    # autolink, en daarmee een nep-vermelding.
    uit = escape_mattermost_prose(een_regel.replace("\\", "\\\\")).replace("<", "\\<")
    for teken in ("@", "~"):
        uit = uit.replace("\\" + teken, teken + ZERO_WIDTH_SPACE)
    return uit


def _bericht(kop: str, inhoud: str | None, casus: Any, actor: str | None) -> str:
    """Kop, citaat en voetregel, met een lege regel ertussen.

    Zonder die lege regel hoort de voetregel in markdown nog bij het citaat
    (lazy continuation), en dan staat "Door ..." in het grijze blok.
    """
    regels = [kop]
    kort = _kort(inhoud)
    if kort:
        regels.append(f"> {_esc(kort)}")
    voet = []
    if actor:
        voet.append(f"Door {_esc(actor)}")
    url = casus_url(casus)
    if url:
        voet.append(f"[Open in Bouwmeester]({url})")
    if voet:
        regels.append(" · ".join(voet))
    return "\n\n".join(regels)


def _vet(tekst: str) -> str:
    return f"**{_esc(tekst)}**"


def _soort(issue: Any) -> str:
    return "Onderzoeksvraag" if issue.is_onderzoeksvraag else "Issue"


def bericht_fase(casus: Any, oud: str | None, nieuw: str, actor: str | None) -> str:
    fases = {
        f.id: f
        for f in geldende_casus_fases(
            casus.initiatief.casus_fases if casus.initiatief else None
        )
    }
    nieuwe = fases.get(nieuw)
    naam_nieuw = nieuwe.naam if nieuwe else nieuw
    kop = f":arrow_right: Casus {_vet(casus.title)} is naar fase {_vet(naam_nieuw)}"
    if oud:
        naam_oud = fases[oud].naam if oud in fases else oud
        kop += f" gegaan (was {_esc(naam_oud)})."
    else:
        kop += " gegaan."
    return _bericht(kop, nieuwe.omschrijving if nieuwe else None, casus, actor)


def bericht_issue_nieuw(casus: Any, issue: Any, actor: str | None) -> str:
    kop = (
        f":new: Nieuw in casus {_vet(casus.title)}: "
        f"{_soort(issue).lower()} {_vet(issue.title)}"
    )
    return _bericht(kop, issue.toelichting, casus, actor)


def bericht_issue_afgerond(
    casus: Any, issue: Any, taken_af: int, taken: int, actor: str | None
) -> str:
    kop = (
        f":white_check_mark: {_soort(issue)} {_vet(issue.title)} is afgerond "
        f"in casus {_vet(casus.title)}."
    )
    if taken:
        kop += f" {taken_af} van {taken} taken af."
    return _bericht(kop, issue.toelichting, casus, actor)
