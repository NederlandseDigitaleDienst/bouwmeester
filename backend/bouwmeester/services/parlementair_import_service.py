"""Orchestration service for parliamentary item import pipeline.

Polls TK/EK APIs for new parliamentary items, extracts tags via LLM,
matches tags to existing corpus nodes, creates CorpusNode + PolitiekeInput
records, creates suggested edges, and sends notifications.
"""

import logging
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.config import get_settings
from bouwmeester.models.corpus_node import CorpusNode
from bouwmeester.models.import_watermerk import ImportWatermerk
from bouwmeester.models.nieuwsbron import Nieuwsbron
from bouwmeester.models.parlementair_item import ParlementairItem, SuggestedEdge
from bouwmeester.models.person import Person
from bouwmeester.models.person_organisatie import PersonOrganisatieEenheid
from bouwmeester.models.politieke_input import PolitiekeInput
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.models.task import Task
from bouwmeester.repositories.parlementair_abonnement import (
    ParlementairAbonnementRepository,
)
from bouwmeester.repositories.parlementair_item import (
    ParlementairItemRepository,
    SuggestedEdgeRepository,
)
from bouwmeester.repositories.signaalcontext import (
    SignaalcontextRepository,
)
from bouwmeester.repositories.tag import TagRepository
from bouwmeester.schema.tag import TagCreate
from bouwmeester.services.import_strategies import nieuws as nieuws_strategie
from bouwmeester.services.import_strategies import tkconv as tkconv_strategie
from bouwmeester.services.import_strategies.base import FetchedItem, ImportStrategy
from bouwmeester.services.import_strategies.nieuws import NieuwsStrategy
from bouwmeester.services.import_strategies.registry import get_strategy
from bouwmeester.services.import_strategies.tkconv import TkconvSearchStrategy
from bouwmeester.services.llm import get_llm_service
from bouwmeester.services.notification_service import NotificationService
from bouwmeester.services.tk_api_client import EersteKamerClient, TweedeKamerClient
from bouwmeester.services.zoekterm_passage import knip_rond_termen

logger = logging.getLogger(__name__)


# How far back a strategy goes on after a restart at most. The search
# feed of tkconv carries about a week.
MAX_ACHTERSTAND = timedelta(days=7)


# How many documents that wait for the model one round tries again, and for
# how long after they came in. A week is what the search feed carries.
WACHTENDEN_PER_RONDE = 5
WACHTENDEN_OPNIEUW_TOT = timedelta(days=7)


def _watermerk_module(strategy: ImportStrategy):  # type: ignore[no-untyped-def]
    """The module that holds the watermark of this strategy, if it has one."""
    if isinstance(strategy, TkconvSearchStrategy):
        return tkconv_strategie
    if isinstance(strategy, NieuwsStrategy):
        return nieuws_strategie
    return None


def _draagt_treffers(strategy: ImportStrategy) -> bool:
    """Komt dit stuk van een zoekterm van een gebruiker?

    Op de eigenschap en niet op het type, omdat tkconv en nieuws hier
    hetzelfde doen en een derde bron dat ook zal doen. Een isinstance per
    strategie zou bij elke nieuwe bron op twee plekken moeten worden
    bijgewerkt, en vergeten betekent dat de treffers stil wegvallen.
    """
    return isinstance(getattr(strategy, "treffers", None), dict)


class ParlementairImportService:
    """Orchestrates the full parliamentary item import pipeline.

    Steps per item:
    1. Idempotency check (skip if zaak_id already imported)
    2. LLM tag extraction from item text (if strategy requires it)
    3. Create any newly suggested tags
    4. Find matching corpus nodes via tag overlap
    5. Create CorpusNode + PolitiekeInput for the item
    6. Tag the new node with matched tags
    7. Create ParlementairItem record
    8. Create SuggestedEdge records
    9. Send notifications to stakeholders of affected nodes
    10. Create review task
    """

    # Also for an instance made without `__init__`, as some tests do.
    _opnieuw: set[str] | frozenset[str] = frozenset()

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.import_repo = ParlementairItemRepository(session)
        self.edge_repo = SuggestedEdgeRepository(session)
        self.tag_repo = TagRepository(session)
        self.abonnement_repo = ParlementairAbonnementRepository(session)
        self.signaalcontext_repo = SignaalcontextRepository(session)
        self.notification_service = NotificationService(session)
        # Items die na een geslaagde commit nog een Mattermost-bericht
        # moeten krijgen. Zie `_process_item` stap 8b.
        self._te_alerteren: list[uuid.UUID] = []
        # abonnement-id -> item-ids die via de eenmalige inhaalslag
        # binnenkwamen. Gevuld ná de idempotency-check, dus alleen voor
        # stukken waarvoor ook echt een treffer is vastgelegd.
        self._inhaalslag: dict[uuid.UUID, list[uuid.UUID]] = {}
        # Wat er deze ronde al een los bericht kreeg. De dedup-poort vlak
        # voor het posten leest dit; zie `_post_inhaalslag`.
        self._gepost_deze_ronde: set[uuid.UUID] = set()
        # The documents this round tries again because the model could not
        # judge them before, and when each first came in: that moment
        # stays with the row, so a document the model keeps failing on
        # stops being tried after `WACHTENDEN_OPNIEUW_TOT`.
        self._opnieuw: set[str] = set()
        self._eerst_gezien: dict[str, datetime] = {}

    async def poll_and_import(
        self,
        item_types: list[str] | None = None,
    ) -> int:
        """Poll TK and EK APIs for new items and import them.

        Args:
            item_types: List of item types to import. If None, uses
                configured ENABLED_IMPORT_TYPES.

        Returns the number of items successfully imported.
        """
        types_to_import = item_types or self.settings.ENABLED_IMPORT_TYPES
        imported_count = 0

        for item_type in types_to_import:
            try:
                strategy = get_strategy(item_type)
            except ValueError:
                logger.warning(f"Unknown import type: {item_type}, skipping")
                continue

            # De tkconv-strategie zoekt naar wat gebruikers volgen, dus de
            # termen komen uit de database in plaats van uit config.
            if isinstance(strategy, TkconvSearchStrategy):
                strategy.abonnementen = await self.abonnement_repo.list_actief()
                if not strategy.abonnementen:
                    logger.info("Geen actieve abonnementen, tkconv overgeslagen")
                    continue

            # Dezelfde zoektermen, andere bronnen: een nieuwsfeed kent geen
            # zoekopdracht, dus de strategie krijgt de feeds erbij en
            # matcht zelf.
            if isinstance(strategy, NieuwsStrategy):
                strategy.abonnementen = await self.abonnement_repo.list_actief()
                if not strategy.abonnementen:
                    logger.info("Geen actieve abonnementen, nieuws overgeslagen")
                    continue
                strategy.bronnen = await self._actieve_nieuwsbronnen()
                if not strategy.bronnen:
                    logger.info("Geen actieve nieuwsbronnen, nieuws overgeslagen")
                    continue

            await self._herstel_watermerk(strategy)
            count = await self._import_type(strategy)
            await self._bewaar_watermerk(strategy)
            imported_count += count

        return imported_count

    async def _herstel_watermerk(self, strategy: ImportStrategy) -> None:
        """Let a strategy that follows a feed go on where it had got to.

        After a restart the strategy has no watermark and would start at
        "now": what appeared between the last round and the restart was
        then never imported. Not further back than `MAX_ACHTERSTAND`: a
        worker that was off for a month must not open with a month of
        alerts. Nothing kept, or no database: the strategy starts at
        "now", as it did.
        """
        module = _watermerk_module(strategy)
        if module is None or module.huidig_watermerk() is not None:
            return
        try:
            bewaard = await self.session.scalar(
                select(ImportWatermerk.tijdstip).where(
                    ImportWatermerk.bron == strategy.item_type
                )
            )
        except Exception:
            await self.session.rollback()
            logger.exception("Watermerk van %s niet te lezen", strategy.item_type)
            return
        if bewaard is None:
            return
        grens = datetime.now(UTC) - MAX_ACHTERSTAND
        module.herstel_watermerk(max(bewaard, grens))
        logger.info(
            "%s gaat verder vanaf %s", strategy.item_type, module.huidig_watermerk()
        )

    async def _bewaar_watermerk(self, strategy: ImportStrategy) -> None:
        """Keep where a strategy has got to, after its items were handled.

        After, not before: a worker that dies halfway a round then starts
        the round again, and what it had imported is recognised by its
        document number. A failure to write costs nothing now; the next
        round writes again.
        """
        module = _watermerk_module(strategy)
        if module is None:
            return
        tijdstip = module.huidig_watermerk()
        if tijdstip is None:
            return
        try:
            stmt = insert(ImportWatermerk).values(
                bron=strategy.item_type, tijdstip=tijdstip
            )
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[ImportWatermerk.bron],
                    set_={"tijdstip": tijdstip, "updated_at": func.now()},
                    # Never back: two workers during a deploy, the older
                    # one writing last.
                    where=ImportWatermerk.tijdstip < tijdstip,
                )
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.exception("Watermerk van %s niet bewaard", strategy.item_type)

    async def _wachtenden(
        self, strategy: ImportStrategy, al_opgehaald: set[str]
    ) -> list[FetchedItem]:
        """The documents of a search term that still wait for the model.

        A document whose judging by the model failed is stored as
        `pending`, without a summary and without an alert, to be done
        later. Nothing did it later: the row made every next round skip
        the document as already imported, so it waited for good and
        nobody was told. A model that is slow or refuses for a minute,
        which happens more often since debates are followed with the same
        model, then cost an alert each time.

        Each round takes a few of them along again. Only what a search
        term brought in, and only for as long as the feed of the source
        carries it: a document the model keeps failing on is not asked
        for every two minutes for ever.
        """
        self._opnieuw = set()
        if not isinstance(strategy, TkconvSearchStrategy):
            return []
        try:
            rijen = (
                (
                    await self.session.execute(
                        select(ParlementairItem)
                        .where(
                            ParlementairItem.type == strategy.item_type,
                            ParlementairItem.status == "pending",
                            ParlementairItem.created_at
                            > datetime.now(UTC) - WACHTENDEN_OPNIEUW_TOT,
                        )
                        .order_by(ParlementairItem.created_at)
                        .limit(WACHTENDEN_PER_RONDE)
                    )
                )
                .scalars()
                .all()
            )
        except Exception:
            await self.session.rollback()
            logger.exception("Wachtende kamerstukken niet op te halen")
            return []

        per_query: dict[str, list] = {}
        for abonnement in strategy.abonnementen:
            per_query.setdefault(abonnement.zoekopdracht(), []).append(abonnement.id)

        items: list[FetchedItem] = []
        for rij in rijen:
            if rij.zaak_id in al_opgehaald:
                # The feed brought it along again: that copy is processed.
                self._opnieuw.add(rij.zaak_id)
                continue
            extra = rij.extra_data or {}
            ids: list = []
            for query in extra.get("matched_terms") or []:
                for abonnement_id in per_query.get(query, []):
                    if abonnement_id not in ids:
                        ids.append(abonnement_id)
            if not ids:
                # The term it came in on is no longer followed.
                continue
            strategy.treffers[rij.zaak_id] = ids
            self._opnieuw.add(rij.zaak_id)
            items.append(
                FetchedItem(
                    zaak_id=rij.zaak_id,
                    zaak_nummer=rij.zaak_nummer,
                    titel=rij.titel,
                    onderwerp=rij.onderwerp,
                    datum=rij.datum,
                    indieners=list(rij.indieners or []),
                    document_tekst=rij.document_tekst,
                    document_url=rij.document_url,
                    bron=rij.bron,
                    deadline=rij.deadline,
                    ministerie=rij.ministerie,
                    extra_data=extra,
                )
            )
        if items:
            logger.info(
                "%d wachtende kamerstukken opnieuw: %s",
                len(items),
                ", ".join(i.zaak_nummer for i in items),
            )
        return items

    async def _actieve_nieuwsbronnen(self) -> list[Nieuwsbron]:
        """De feeds die nu gevolgd worden.

        Uit de database en niet uit config, omdat een bron toevoegen een
        redactionele keuze is en geen deploy hoort te kosten.
        """
        stmt = select(Nieuwsbron).where(Nieuwsbron.actief.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def _import_type(self, strategy: ImportStrategy) -> int:
        """Import all items for a single strategy/type."""
        imported_count = 0

        # Poll Tweede Kamer — or the strategy's own source when it does not
        # use the OData API (tkconv searches full text, which OData cannot).
        if strategy.uses_tk_api:
            tk_client = TweedeKamerClient(
                base_url=self.settings.TK_API_BASE_URL,
                session=self.session,
            )
            bron_naam = "Tweede Kamer"
        else:
            tk_client = strategy.build_client()
            bron_naam = strategy.item_type

        if tk_client is None:
            logger.warning(
                f"{strategy.item_type} has no client to fetch with, skipping"
            )
            tk_items = []
        else:
            try:
                async with tk_client:
                    tk_items = await strategy.fetch_items(
                        client=tk_client,
                        since=None,
                        limit=self.settings.TK_IMPORT_LIMIT,
                    )
                logger.info(
                    f"Fetched {len(tk_items)} {strategy.item_type} items "
                    f"from {bron_naam}"
                )
            except Exception:
                logger.exception(
                    f"Error fetching {strategy.item_type} from {bron_naam}"
                )
                tk_items = []

        # Poll Eerste Kamer (only if strategy supports it)
        ek_items: list[FetchedItem] = []
        if strategy.supports_ek:
            ek_client = EersteKamerClient(
                base_url=self.settings.EK_API_BASE_URL,
                session=self.session,
            )
            try:
                async with ek_client:
                    ek_items = await strategy.fetch_items(
                        client=ek_client,
                        since=None,
                        limit=self.settings.TK_IMPORT_LIMIT,
                    )
                logger.info(
                    f"Fetched {len(ek_items)} {strategy.item_type} "
                    f"items from Eerste Kamer"
                )
            except Exception:
                logger.exception(
                    f"Error fetching {strategy.item_type} from Eerste Kamer"
                )
                ek_items = []

        # What an earlier round could not judge, before what is new: it
        # has waited longest.
        wachtend = await self._wachtenden(strategy, {i.zaak_id for i in tk_items})
        all_items = _hoofdstuk_voor_bijlage(wachtend + tk_items + ek_items)

        self._inhaalslag = {}
        self._gepost_deze_ronde = set()
        for item in all_items:
            self._te_alerteren = []
            try:
                result = await self._process_item(item, strategy)
                await self.session.commit()
                if result:
                    imported_count += 1
            except Exception:
                logger.exception(
                    f"Error processing {strategy.item_type} {item.zaak_id}"
                )
                await self.session.rollback()
                # Niet posten: het item bestaat niet meer.
                continue

            # Pas hier, met het item veilig in de database. Faalt het
            # posten, dan blijft het item staan en wordt het niet opnieuw
            # geïmporteerd — een gemist bericht is beter dan een bericht
            # over een stuk dat is teruggedraaid.
            for item_id in self._te_alerteren:
                # Alleen als er werkelijk een bericht uit is gegaan. Een
                # alert die onder de drempel bleef, geen kanaal vond of
                # faalde, heeft niets getoond — en dan mag de dedup-poort
                # het stuk niet uit de inhaalslag houden.
                #
                # Zonder deze voorwaarde verdween een stuk in stilte: de
                # bestaande term hield hem tegen op `minimum_relevantie`,
                # en de verse term (die hem wél had getoond) sloeg hem
                # over omdat hij "al gepost" heette. `markeer_ingehaald`
                # maakte dat verlies bovendien permanent.
                if await self._alert_kamerstuk(item_id):
                    self._gepost_deze_ronde.add(item_id)

        if self._inhaalslag:
            await self._post_inhaalslag(self._inhaalslag)

        return imported_count

    async def _post_inhaalslag(self, per_abonnement: dict) -> None:
        """Eén samenvattend bericht per nieuwe zoekterm.

        Draait na de hele ronde, dus met alle stukken van die term bij
        elkaar. De losse alerts zijn voor die stukken overgeslagen (zie
        `_process_item`), anders zou het kanaal ze dubbel krijgen.
        """
        from bouwmeester.services.parlementair_alert_service import (
            ParlementairAlertService,
        )

        service = ParlementairAlertService(self.session)

        # Groepeer per scope: alle termen die tegelijk worden aangezet
        # delen één bericht. Per term posten gaf in productie twee
        # berichten over grotendeels dezelfde stukken.
        per_scope: dict[tuple, dict] = {}
        for abonnement_id, item_ids in per_abonnement.items():
            abonnement = await self.abonnement_repo.get(abonnement_id)
            if abonnement is None:
                continue
            sleutel = (abonnement.scope_type, abonnement.scope_id)
            groep = per_scope.setdefault(sleutel, {"abos": [], "items": []})
            groep["abos"].append(abonnement)
            for iid in item_ids:
                if iid not in groep["items"]:
                    groep["items"].append(iid)

        for groep in per_scope.values():
            abonnementen = groep["abos"]
            try:
                # De dedup-poort, vlak voor het posten. Een stuk dat deze
                # ronde al een los bericht kreeg hoort niet nog eens in de
                # inhaalslag te staan: in productie leverde dat twee
                # berichten over hetzelfde kamerstuk op, zeven minuten na
                # elkaar (24 september 2026).
                #
                # Dat gebeurt wanneer een stuk via meerdere termen
                # binnenkomt en er één van vers is: de bestaande termen
                # krijgen hun losse alert, de verse term zijn inhaalslag.
                # Beide keuzes zijn op zichzelf goed; alleen de uitkomst
                # samen is dat niet.
                #
                # Hier en niet in `_process_item`, omdat pas op dit punt
                # vaststaat wat er werkelijk gepost is: een alert die
                # faalde of onder de drempel bleef, zou daar al als
                # "gepost" gelden.
                overgeslagen = [
                    iid for iid in groep["items"] if iid in self._gepost_deze_ronde
                ]
                if overgeslagen:
                    logger.info(
                        "Inhaalslag: %d stuk(ken) overgeslagen, deze ronde al "
                        "los gepost",
                        len(overgeslagen),
                    )

                geladen = [
                    await self.session.get(ParlementairItem, iid)
                    for iid in groep["items"]
                    if iid not in self._gepost_deze_ronde
                ]
                items = [i for i in geladen if i is not None]

                # Beoordeel vóór het posten, anders draagt geen van deze
                # stukken een score en kan `minimum_relevantie` niet wegen.
                # Dit was de reden dat de eerste inhaalslag in productie 47
                # stukken ongefilterd in het kanaal zette: de losse alerts
                # laten scoren en de inhaalslag niet.
                for item in items:
                    await self._beoordeel(item, abonnementen)

                # Eerst vastleggen dát de inhaalslag is gedaan, dan pas
                # posten. Andersom zou een mislukte commit het bericht al
                # de deur uit hebben terwijl `ingehaald_op` NULL blijft, en
                # dan stuurt de volgende ronde hetzelfde bericht opnieuw.
                # Een bericht is niet terug te draaien, een gemiste
                # markering wel te herstellen.
                await self.abonnement_repo.markeer_ingehaald(
                    [a.id for a in abonnementen]
                )
                await self.session.commit()

                if items:
                    gepost = await service.post_inhaalslag(abonnementen, items)
                    logger.info(
                        "Inhaalslag voor %s: %d stukken, %d kanalen",
                        ", ".join(repr(a.term) for a in abonnementen),
                        len(items),
                        gepost,
                    )
            except Exception:
                await self.session.rollback()
                logger.exception(
                    "Inhaalslag mislukt voor %s",
                    ", ".join(str(a.id) for a in abonnementen),
                )

    def _relevante_tekst(
        self, item: FetchedItem, strategy: ImportStrategy
    ) -> str | None:
        """De passages waar de zoektermen vallen, of het begin van het stuk.

        `build_extract_tags_prompt` kapt af op de eerste 10.000 tekens. Bij
        een verslag van een schriftelijk overleg van 43.000 tekens levert
        dat de voorpagina en de inhoudsopgave op, en dan moet het model
        tags kiezen voor een stuk waarvan het het onderwerp nooit heeft
        gezien.

        Komt het stuk niet van een zoekterm (de moties en kamervragen uit
        de OData-API), dan is er niets om omheen te knippen en blijft het
        gedrag zoals het was.
        """
        tekst = item.document_tekst
        if not tekst:
            return tekst

        treffers = getattr(strategy, "treffers", None)
        if not isinstance(treffers, dict):
            return tekst

        ids = treffers.get(item.zaak_id) or []
        abonnementen = getattr(strategy, "abonnementen", []) or []
        termen = [a.term for a in abonnementen if a.id in ids]
        if not termen:
            return tekst

        return knip_rond_termen(tekst, termen)

    async def _beoordeel(
        self, parlementair_item: ParlementairItem, abonnementen: list
    ) -> None:
        """Vat het stuk samen en zet er een relevantiescore op.

        Apart van `_alert_kamerstuk` omdat de inhaalslag dezelfde
        beoordeling nodig heeft en hem niet had: `relevantie_score` werd
        alleen hier gezet, en inhaalslag-stukken lopen langs deze methode
        heen. Gevolg in productie: de eerste inhaalslag zette 47 stukken
        ongefilterd in het kanaal, want `minimum_relevantie` kan niet
        wegen wat nooit gewogen is.

        Faalt zacht. Een mislukte LLM-call mag een stuk niet verzwijgen;
        zonder score valt het stuk terug op de standaarddrempel, en dat is
        de veilige kant (wél tonen).
        """
        termen = [a.term for a in abonnementen]
        if not termen:
            return

        llm_service = await get_llm_service(self.session)
        if llm_service is None:
            return

        try:
            bestaand = parlementair_item.extra_data or {}
            alert = await llm_service.summarize_kamerstuk_alert(
                titel=parlementair_item.titel,
                onderwerp=parlementair_item.onderwerp,
                # Niet de eerste N tekens maar de passages waar de term
                # valt: een begroting noemt het onderwerp halverwege,
                # en het model zag anders alleen de voorpagina.
                document_tekst=knip_rond_termen(
                    parlementair_item.document_tekst or "", termen
                ),
                zoektermen=termen,
                # Het model moet weten wát voor stuk dit is: een agenda
                # die nog moet komen vraagt om een ander bericht dan een
                # besluitenlijst van een vergadering die geweest is.
                categorie=bestaand.get("categorie") or "overig",
                soort=bestaand.get("soort"),
                context_regels=_context_regels(bestaand),
                # Waar dit dossier over gaat, en vooral: wat er níét bij
                # hoort. Een zoekterm kan het verschil tussen een
                # projectnaam en een metafoor niet maken, een oordeel wel.
                signaalcontext=await self._signaalcontext(abonnementen),
            )
            if alert.samenvatting:
                parlementair_item.llm_samenvatting = alert.samenvatting
            else:
                # Geen samenvatting gekregen. Dat wordt gelogd omdat het
                # anders onzichtbaar is: het bericht valt terug op het
                # onderwerp van het stuk en ziet er dan gewoon uit, terwijl
                # het model niets heeft kunnen zeggen. In productie stonden
                # twee mislukte aanroepen op hetzelfde stuk zonder dat er
                # ergens iets over te vinden was.
                logger.warning(
                    "Geen samenvatting voor %s (%d tekens tekst, reden: %s)",
                    parlementair_item.zaak_nummer,
                    len(parlementair_item.document_tekst or ""),
                    alert.reden or "onbekend",
                )
            extra = dict(bestaand)
            extra["relevantie_score"] = alert.relevantie_score
            extra["relevantie_reden"] = alert.reden
            extra["actie"] = alert.actie
            parlementair_item.extra_data = extra
            # Eigen commit: we draaien na de commit van het item, dus
            # zonder dit blijft de samenvatting in de sessie hangen tot
            # de volgende commit en gaat hij bij een fout verloren.
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.exception(
                "Samenvatting mislukt voor %s", parlementair_item.zaak_nummer
            )

    async def _signaalcontext(self, abonnementen: list) -> str | None:
        """De vrije tekst van de scope waar deze abonnementen bij horen.

        Alle abonnementen op één stuk kunnen uit verschillende scopes
        komen (twee initiatieven die dezelfde term volgen). Dan is er geen
        één context; we nemen ze allemaal mee, gescheiden, zodat het model
        ziet dat er twee dossiers meekijken.
        """
        scopes = {(a.scope_type, a.scope_id) for a in abonnementen}
        if not scopes:
            return None
        teksten = []
        for scope_type, scope_id in sorted(scopes, key=lambda s: str(s[1])):
            tekst = await self.signaalcontext_repo.tekst_voor(scope_type, scope_id)
            if tekst:
                teksten.append(tekst)
        return "\n\n".join(teksten) if teksten else None

    async def _alert_kamerstuk(self, parlementair_item_id: uuid.UUID) -> int:
        """Vat het stuk samen vanuit de zoekterm en post het in de kanalen.

        Draait ná de commit van het item, dus met een id in plaats van een
        object: de sessie is op dat moment schoon en het item wordt vers
        geladen.

        Twee stappen in één methode omdat de samenvatting alleen voor het
        bericht wordt gemaakt: de score bepaalt de vorm, niet of er gepost
        wordt. Een mislukte LLM-call mag het stuk niet verzwijgen, dus
        beide stappen falen zacht.

        Geeft terug in hoeveel kanalen werkelijk is gepost. Nul is een
        geldige uitkomst (onder de drempel, geen kanaal, of een fout bij
        het posten), en de aanroeper heeft dat verschil nodig: alleen een
        stuk dat echt is getoond mag uit de inhaalslag worden gehouden.
        """
        from bouwmeester.services.parlementair_alert_service import (
            ParlementairAlertService,
        )

        parlementair_item = await self.session.get(
            ParlementairItem, parlementair_item_id
        )
        if parlementair_item is None:
            logger.warning(
                "Kamerstuk %s verdwenen vóór het alert", parlementair_item_id
            )
            return 0

        abonnementen = await self.abonnement_repo.list_abonnementen_voor_item(
            parlementair_item.id
        )
        await self._beoordeel(parlementair_item, abonnementen)

        try:
            service = ParlementairAlertService(self.session)
            gepost = await service.post_alert(parlementair_item)
            logger.info(
                "Kamerstuk %s in %d kanaal/kanalen gepost",
                parlementair_item.zaak_nummer,
                gepost,
            )
            return gepost
        except Exception:
            logger.exception(
                "Alert posten mislukt voor %s", parlementair_item.zaak_nummer
            )
            return 0

    async def _koppel_aan_bestaand_item(
        self,
        bestaand: ParlementairItem,
        item: FetchedItem,
        strategy: ImportStrategy,
    ) -> None:
        """Leg de treffers vast voor een stuk dat er al was.

        Alleen de koppeling: het stuk is al geïmporteerd, dus er komt geen
        tweede alert en geen tweede samenvatting. `registreer_treffers`
        doet ON CONFLICT DO NOTHING, dus een herhaalde ronde telt niet
        dubbel.

        De inhaalslag krijgt het stuk er wél bij, want voor een verse term
        is dit een van de stukken uit de afgelopen week — ook al kende het
        systeem het al via een ander abonnement.
        """
        if not _draagt_treffers(strategy):
            return

        abonnement_ids = strategy.treffers.get(item.zaak_id, [])
        if not abonnement_ids:
            return

        nieuw = await self.abonnement_repo.registreer_treffers(
            bestaand.id, abonnement_ids
        )
        if nieuw:
            logger.info(
                "Kamerstuk %s aan %d extra zoekterm(en) gekoppeld",
                item.zaak_nummer,
                nieuw,
            )

        for aid in abonnement_ids:
            if aid in strategy.verse_abonnementen:
                self._inhaalslag.setdefault(aid, []).append(bestaand.id)

    async def _process_item(
        self,
        item: FetchedItem,
        strategy: ImportStrategy,
    ) -> bool:
        """Process a single item through the import pipeline.

        Returns True if the item was imported, False if skipped.
        """
        # Step 1: Idempotency check
        existing = await self.import_repo.get_by_zaak_id(item.zaak_id)
        if existing and existing.status == "pending" and item.zaak_id in self._opnieuw:
            # The model could not be reached when this document came in,
            # so it was put aside without a summary, a node or an alert.
            # It is tried again as if it came in now. The row goes first:
            # the steps below make it anew, as imported when the model
            # answers and as waiting once more when it does not.
            self._eerst_gezien[item.zaak_id] = existing.created_at
            await self.session.delete(existing)
            await self.session.flush()
            existing = None
        if existing:
            # Het stuk staat er al, maar de zoekterm die het nú aandroeg
            # misschien nog niet. Twee termen vinden vaak hetzelfde
            # kamerstuk: in productie kwam de startnotitie NLDD binnen via
            # "van wet naar digitale werking" én "regelrecht", en zonder
            # deze stap bleven beide tellers op nul staan terwijl het
            # bericht het stuk wel noemde.
            await self._koppel_aan_bestaand_item(existing, item, strategy)
            logger.debug(
                f"Skipping {strategy.item_type} {item.zaak_nummer}: already imported"
            )
            return False

        # Step 2: LLM tag extraction (if strategy requires it)
        matched_tag_names: list[str] = []
        samenvatting: str | None = None

        if strategy.requires_llm:
            all_tags = await self.tag_repo.get_all()
            tag_names = [t.name for t in all_tags]

            llm_service = await get_llm_service(self.session)
            if not llm_service:
                logger.warning("No LLM provider configured, skipping tag extraction")
                extraction = None
            else:
                try:
                    extraction = await llm_service.extract_tags(
                        titel=item.titel,
                        onderwerp=item.onderwerp,
                        # Niet het hele document: de prompt kapt af op de
                        # eerste 10.000 tekens, en dat is bij een verslag
                        # van 43.000 tekens de voorpagina en de
                        # inhoudsopgave. Dezelfde behandeling als het
                        # alert-pad krijgt, zodat het model naar de
                        # passages kijkt waar de zoektermen vallen.
                        document_tekst=self._relevante_tekst(item, strategy),
                        bestaande_tags=tag_names,
                        context_hint=strategy.context_hint(),
                    )
                except Exception:
                    logger.exception(
                        "LLM extraction failed for %s %s",
                        strategy.item_type,
                        item.zaak_nummer,
                    )
                    extraction = None

            if extraction is None:
                # LLM required but unavailable/failed — queue for later
                await self.import_repo.create(
                    type=strategy.item_type,
                    zaak_id=item.zaak_id,
                    zaak_nummer=item.zaak_nummer,
                    titel=item.titel,
                    onderwerp=item.onderwerp,
                    bron=item.bron,
                    datum=item.datum,
                    status="pending",
                    indieners=item.indieners,
                    document_tekst=item.document_tekst,
                    document_url=item.document_url,
                    deadline=item.deadline,
                    ministerie=item.ministerie,
                    extra_data=item.extra_data,
                    **(
                        {"created_at": self._eerst_gezien[item.zaak_id]}
                        if item.zaak_id in self._eerst_gezien
                        else {}
                    ),
                )
                logger.warning(
                    "%s %s queued as pending: LLM extraction failed",
                    strategy.item_type,
                    item.zaak_nummer,
                )
                return False

            matched_tag_names = extraction.matched_tags
            samenvatting = extraction.samenvatting

        # Step 3: Find matching corpus nodes via tag overlap
        matched_nodes = await self._find_matching_nodes(matched_tag_names)

        if not matched_nodes and not strategy.always_import:
            # No matches and not pre-filtered — mark as out_of_scope
            await self.import_repo.create(
                type=strategy.item_type,
                zaak_id=item.zaak_id,
                zaak_nummer=item.zaak_nummer,
                titel=item.titel,
                onderwerp=item.onderwerp,
                bron=item.bron,
                datum=item.datum,
                status="out_of_scope",
                indieners=item.indieners,
                document_tekst=item.document_tekst,
                document_url=item.document_url,
                llm_samenvatting=samenvatting,
                matched_tags=matched_tag_names,
                deadline=item.deadline,
                ministerie=item.ministerie,
                extra_data=item.extra_data,
            )
            logger.info(
                f"{strategy.item_type} {item.zaak_nummer} out_of_scope: "
                f"no matching corpus nodes"
            )
            return False

        # Step 4: Create any newly suggested tags
        if strategy.requires_llm and extraction:
            for new_tag_name in extraction.suggested_new_tags:
                existing_tag = await self.tag_repo.get_by_name(new_tag_name)
                if not existing_tag:
                    try:
                        await self.tag_repo.create(TagCreate(name=new_tag_name))
                    except SQLAlchemyError:
                        logger.exception(
                            f"Error creating suggested tag '{new_tag_name}'"
                        )

        # Step 5: Create CorpusNode + PolitiekeInput
        title = item.onderwerp
        if len(title) > 500:
            title = title[:497] + "..."
        node = CorpusNode(
            title=title,
            node_type="politieke_input",
            description=samenvatting or f"Zaak: {item.titel}",
            status="actief",
        )
        self.session.add(node)
        await self.session.flush()

        pi = PolitiekeInput(
            id=node.id,
            type=strategy.politieke_input_type,
            referentie=item.zaak_nummer,
            datum=item.datum,
            status=strategy.politieke_input_status(item),
        )
        self.session.add(pi)
        await self.session.flush()

        # Step 6: Link indieners as stakeholders
        await self._link_indieners(node.id, item.indieners, item.bron)

        # Step 7: Tag the new node with matched tags (batch lookup)
        matched_tag_map = await self.tag_repo.get_by_names(matched_tag_names)
        for tag_name, tag in matched_tag_map.items():
            try:
                await self.tag_repo.add_tag_to_node(node.id, tag.id)
            except SQLAlchemyError:
                logger.exception(f"Error tagging node {node.id} with tag '{tag_name}'")

        # Step 8: Create ParlementairItem record
        parlementair_item = await self.import_repo.create(
            type=strategy.item_type,
            zaak_id=item.zaak_id,
            zaak_nummer=item.zaak_nummer,
            titel=item.titel,
            onderwerp=item.onderwerp,
            bron=item.bron,
            datum=item.datum,
            status="imported",
            corpus_node_id=node.id,
            indieners=item.indieners,
            document_tekst=item.document_tekst,
            document_url=item.document_url,
            llm_samenvatting=samenvatting,
            matched_tags=matched_tag_names,
            imported_at=datetime.utcnow(),
            deadline=item.deadline,
            ministerie=item.ministerie,
            extra_data=item.extra_data,
        )

        # Step 8b: Leg vast welke zoektermen dit stuk aandroegen. Eén
        # document matcht in de praktijk op meerdere termen tegelijk, dus
        # dit is een aparte tabel: het item wordt één keer geïmporteerd en
        # één keer gepost, met alle termen eronder.
        if _draagt_treffers(strategy):
            abonnement_ids = strategy.treffers.get(item.zaak_id, [])
            if abonnement_ids:
                await self.abonnement_repo.registreer_treffers(
                    parlementair_item.id, abonnement_ids
                )
                # Posten gebeurt pas ná de commit, in `_import_type`. Een
                # bericht is niet terug te draaien: gaat het eruit vóór de
                # commit en faalt daarna een latere stap, dan rolt het item
                # terug terwijl het bericht blijft staan — en de volgende
                # ronde importeert en post hetzelfde stuk opnieuw, elke
                # twee minuten.
                # Splits per abonnement: wie nog zijn eenmalige inhaalslag
                # doet krijgt dit stuk in het samenvattende bericht, de
                # rest krijgt een losse alert.
                #
                # Dat onderscheid moet hier vallen en niet in
                # `fetch_items`. Daar is de idempotency-check nog niet
                # gedaan, dus een stuk dat al via een andere term
                # binnenkwam zou in de inhaalslag-lijst belanden zonder dat
                # er ooit een treffer-rij voor is aangemaakt — en
                # `ingehaald_op` zou gezet worden voor een term die zijn
                # treffers nooit heeft gekregen.
                inhaal_ids = [
                    aid for aid in abonnement_ids if aid in strategy.verse_abonnementen
                ]
                for aid in inhaal_ids:
                    self._inhaalslag.setdefault(aid, []).append(parlementair_item.id)
                # Eén verse term mag de losse alert van de andere abonnees
                # niet doven: die krijgen hem gewoon.
                if len(inhaal_ids) < len(abonnement_ids):
                    self._te_alerteren.append(parlementair_item.id)

        # Step 9: Create SuggestedEdge records for matching nodes
        affected_nodes: list[CorpusNode] = []
        for match in matched_nodes:
            target_node = match["node"]
            confidence = match["confidence"]
            reason = match["reason"]

            try:
                await self.edge_repo.create(
                    parlementair_item_id=parlementair_item.id,
                    target_node_id=target_node.id,
                    edge_type_id=strategy.default_edge_type(),
                    confidence=confidence,
                    reason=reason,
                    status="pending",
                )
                affected_nodes.append(target_node)
            except SQLAlchemyError:
                logger.exception(
                    f"Error creating suggested edge to node {target_node.id}"
                )

        # Step 10: Send notifications
        if affected_nodes:
            try:
                await self.notification_service.notify_parlementair_item_imported(
                    node,
                    affected_nodes,
                    item_type=strategy.item_type,
                )
            except (SQLAlchemyError, ValueError):
                logger.exception("Error sending import notifications")

        # Step 11: Create review task
        try:
            await self.create_review_task(
                parlementair_item,
                affected_nodes=affected_nodes,
            )
        except SQLAlchemyError:
            logger.exception(
                f"Error creating review task for {strategy.item_type} "
                f"{item.zaak_nummer}"
            )

        logger.info(
            f"{strategy.item_type} {item.zaak_nummer} imported with "
            f"{len(affected_nodes)} suggested edges"
        )
        return True

    async def ensure_corpus_node(
        self,
        item: ParlementairItem,
    ) -> ParlementairItem:
        """Create a CorpusNode + PolitiekeInput for an item that lacks one.

        Used when reopening out-of-scope items that skipped corpus node
        creation during the original import.  If the item already has a
        corpus_node_id this is a no-op.
        """
        if item.corpus_node_id is not None:
            return item

        strategy = get_strategy(item.type)

        title = item.onderwerp
        if len(title) > 500:
            title = title[:497] + "..."
        node = CorpusNode(
            title=title,
            node_type="politieke_input",
            description=item.llm_samenvatting or f"Zaak: {item.titel}",
            status="actief",
        )
        self.session.add(node)
        await self.session.flush()

        pi = PolitiekeInput(
            id=node.id,
            type=strategy.politieke_input_type,
            referentie=item.zaak_nummer,
            datum=item.datum,
            status=strategy.politieke_input_status(
                FetchedItem(
                    zaak_id="",
                    zaak_nummer=item.zaak_nummer,
                    titel=item.titel,
                    onderwerp=item.onderwerp,
                    bron=item.bron,
                )
            ),
        )
        self.session.add(pi)
        await self.session.flush()

        # Link indieners as stakeholders
        await self._link_indieners(node.id, item.indieners or [], item.bron)

        # Tag the node with matched tags
        if item.matched_tags:
            tag_map = await self.tag_repo.get_by_names(item.matched_tags)
            for tag_name, tag in tag_map.items():
                try:
                    await self.tag_repo.add_tag_to_node(node.id, tag.id)
                except SQLAlchemyError:
                    logger.exception(f"Error tagging node {node.id} with '{tag_name}'")

        # Update the item to point to the new node
        item.corpus_node_id = node.id
        await self.session.flush()

        logger.info(
            f"Created corpus node {node.id} for reopened {item.type} {item.zaak_nummer}"
        )
        return item

    async def create_review_task(
        self,
        parlementair_item: ParlementairItem,
        affected_nodes: list[CorpusNode] | None = None,
    ) -> Task | None:
        """Create a review task for a parliamentary item.

        Used both during initial import and when reopening a rejected/
        out-of-scope item.  When *affected_nodes* is ``None`` (reopen
        case), the connected nodes are derived from existing suggested
        edges.
        """
        if parlementair_item.corpus_node_id is None:
            return None

        # Resolve affected nodes from suggested edges when not provided
        if affected_nodes is None:
            affected_nodes = [
                se.target_node
                for se in (parlementair_item.suggested_edges or [])
                if se.target_node is not None
            ]

        review_unit_id = await self._determine_review_unit(affected_nodes)

        # Build title/priority/deadline via the strategy for this item type
        strategy = get_strategy(parlementair_item.type)
        fetched = FetchedItem(
            zaak_id="",
            zaak_nummer=parlementair_item.zaak_nummer,
            titel=parlementair_item.titel,
            onderwerp=parlementair_item.onderwerp,
            bron=parlementair_item.bron,
            deadline=parlementair_item.deadline,
        )
        task_title = strategy.task_title(fetched)
        if len(task_title) > 200:
            task_title = task_title[:197] + "..."

        description_parts = [
            f"Zaak: {parlementair_item.zaak_nummer}",
            f"Bron: {parlementair_item.bron}",
        ]
        if parlementair_item.llm_samenvatting:
            description_parts.append(f"\n{parlementair_item.llm_samenvatting}")
        description_parts.append(
            f"\n{len(affected_nodes)} gerelateerde beleidsdossiers gevonden."
        )

        deadline = strategy.calculate_deadline(fetched)
        if deadline is None:
            deadline = self._business_days_from_now(10)

        task = Task(
            node_id=parlementair_item.corpus_node_id,
            title=task_title,
            description="\n".join(description_parts),
            priority=strategy.task_priority(fetched),
            status="open",
            deadline=deadline,
            organisatie_eenheid_id=review_unit_id,
            assignee_id=None,
            parlementair_item_id=parlementair_item.id,
        )
        self.session.add(task)
        await self.session.flush()
        logger.info(
            f"Created review task for {parlementair_item.type} "
            f"{parlementair_item.zaak_nummer} "
            f"(unit: {review_unit_id or 'none'})"
        )
        return task

    async def _determine_review_unit(
        self,
        affected_nodes: list[CorpusNode],
    ) -> uuid.UUID | None:
        """Determine the best organisatie_eenheid for a review task."""
        if not affected_nodes:
            return None

        node_ids = [n.id for n in affected_nodes]
        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "corpus_node",
            ResourcePermission.resource_id.in_(node_ids),
            ResourcePermission.rol == "eigenaar",
        )
        result = await self.session.execute(stmt)
        stakeholders = result.scalars().all()

        if not stakeholders:
            return None

        person_ids = [sh.person_id for sh in stakeholders]
        person_stmt = select(PersonOrganisatieEenheid.organisatie_eenheid_id).where(
            PersonOrganisatieEenheid.person_id.in_(person_ids),
        )
        person_result = await self.session.execute(person_stmt)
        unit_ids: list[uuid.UUID] = list(person_result.scalars().all())

        if not unit_ids:
            return None

        counter = Counter(unit_ids)
        most_common_id, _ = counter.most_common(1)[0]
        return most_common_id

    @staticmethod
    def _business_days_from_now(days: int) -> date:
        """Calculate a date N business days from today."""
        current = date.today()
        added = 0
        while added < days:
            current += timedelta(days=1)
            if current.weekday() < 5:
                added += 1
        return current

    async def _find_matching_nodes(self, tag_names: list[str]) -> list[dict]:
        """Find corpus nodes that share tags with the item."""
        if not tag_names:
            return []

        tag_objects = await self.tag_repo.get_by_names(tag_names)

        if not tag_objects:
            return []

        all_tag_ids = set()
        for tag in tag_objects.values():
            all_tag_ids.add(tag.id)
            if tag.parent_id:
                all_tag_ids.add(tag.parent_id)

        from bouwmeester.models.tag import NodeTag

        tag_node_stmt = select(NodeTag.tag_id, NodeTag.node_id).where(
            NodeTag.tag_id.in_(all_tag_ids)
        )
        tag_node_result = await self.session.execute(tag_node_stmt)
        tag_to_nodes: dict[uuid.UUID, list[uuid.UUID]] = {}
        all_node_ids: set[uuid.UUID] = set()
        for tag_id, node_id in tag_node_result.all():
            tag_to_nodes.setdefault(tag_id, []).append(node_id)
            all_node_ids.add(node_id)

        nodes_by_id: dict[uuid.UUID, CorpusNode] = {}
        if all_node_ids:
            nodes_stmt = select(CorpusNode).where(
                CorpusNode.id.in_(all_node_ids),
                CorpusNode.node_type != "politieke_input",
            )
            nodes_result = await self.session.execute(nodes_stmt)
            for node in nodes_result.scalars().all():
                nodes_by_id[node.id] = node

        node_scores: dict[str, dict] = {}

        for tag_name, tag in tag_objects.items():
            for node_id in tag_to_nodes.get(tag.id, []):
                nid = str(node_id)
                if nid not in node_scores and node_id in nodes_by_id:
                    node_scores[nid] = {
                        "node": nodes_by_id[node_id],
                        "score": 0.0,
                        "reasons": [],
                        "tag_names": [],
                    }
                if nid in node_scores:
                    node_scores[nid]["score"] += 1.0
                    node_scores[nid]["reasons"].append(f"tag '{tag_name}'")
                    if tag_name not in node_scores[nid]["tag_names"]:
                        node_scores[nid]["tag_names"].append(tag_name)

            if tag.parent_id:
                for node_id in tag_to_nodes.get(tag.parent_id, []):
                    nid = str(node_id)
                    if nid not in node_scores and node_id in nodes_by_id:
                        node_scores[nid] = {
                            "node": nodes_by_id[node_id],
                            "score": 0.0,
                            "reasons": [],
                            "tag_names": [],
                        }
                    if nid in node_scores:
                        node_scores[nid]["score"] += 0.7
                        node_scores[nid]["reasons"].append(
                            f"parent tag van '{tag_name}'"
                        )

        min_confidence = 0.5
        results = []
        max_possible = len(tag_objects)

        for data in node_scores.values():
            confidence = min(data["score"] / max(max_possible, 1), 1.0)
            if confidence < min_confidence:
                continue
            results.append(
                {
                    "node": data["node"],
                    "confidence": confidence,
                    "reason": "Gedeelde tags: " + ", ".join(data["tag_names"]),
                    "tag_names": data["tag_names"],
                }
            )

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:10]

    async def reprocess_imported_items(
        self,
        item_type: str = "toezegging",
    ) -> dict:
        """Re-process imported items that have no suggested edges.

        Runs LLM tag extraction and node matching on items that were
        imported without matching (e.g. toezeggingen before LLM was
        enabled).  Items that still don't match after LLM extraction
        are moved to out_of_scope.
        """
        strategy = get_strategy(item_type)

        # Find imported items of this type with zero suggested edges
        stmt = (
            select(ParlementairItem)
            .where(
                ParlementairItem.type == item_type,
                ParlementairItem.status.in_(["imported", "pending"]),
            )
            .outerjoin(
                SuggestedEdge,
                SuggestedEdge.parlementair_item_id == ParlementairItem.id,
            )
            .group_by(ParlementairItem.id)
            .having(func.count(SuggestedEdge.id) == 0)
        )
        result = await self.session.execute(stmt)
        items = result.scalars().all()

        if not items:
            return {"total": 0, "matched": 0, "out_of_scope": 0, "skipped": 0}

        all_tags = await self.tag_repo.get_all()
        tag_names = [t.name for t in all_tags]

        llm_service = await get_llm_service(self.session)
        if not llm_service:
            logger.warning("No LLM provider configured, cannot reprocess")
            return {
                "total": len(items),
                "matched": 0,
                "out_of_scope": 0,
                "skipped": 0,
                "error": "no_llm",
            }

        matched_count = 0
        out_of_scope_count = 0
        skipped_count = 0

        for item in items:
            try:
                extraction = await llm_service.extract_tags(
                    titel=item.titel,
                    onderwerp=item.onderwerp,
                    document_tekst=item.document_tekst,
                    bestaande_tags=tag_names,
                    context_hint=strategy.context_hint(),
                )
            except Exception:
                logger.exception(
                    "LLM extraction failed for %s %s",
                    item.type,
                    item.zaak_nummer,
                )
                skipped_count += 1
                continue

            matched_tag_names = extraction.matched_tags if extraction else []
            samenvatting = extraction.samenvatting if extraction else None

            # Update item with LLM results
            item.matched_tags = matched_tag_names
            if samenvatting:
                item.llm_samenvatting = samenvatting

            # Find matching nodes
            matched_nodes = await self._find_matching_nodes(matched_tag_names)

            if not matched_nodes:
                # No matches after LLM — move to out_of_scope and
                # remove the orphaned corpus node that was created
                # during the original (matchless) import.
                await self._detach_corpus_node(item)
                item.status = "out_of_scope"
                out_of_scope_count += 1
                await self.session.flush()
                logger.info(
                    "%s %s moved to out_of_scope (no matches after LLM)",
                    item.type,
                    item.zaak_nummer,
                )
                continue

            # Tag the corpus node (only for items that matched)
            if item.corpus_node_id and matched_tag_names:
                tag_map = await self.tag_repo.get_by_names(matched_tag_names)
                for tag_name, tag in tag_map.items():
                    try:
                        await self.tag_repo.add_tag_to_node(item.corpus_node_id, tag.id)
                    except SQLAlchemyError:
                        pass  # duplicate tag, ignore

            # Create suggested edges
            for match in matched_nodes:
                target_node = match["node"]
                try:
                    await self.edge_repo.create(
                        parlementair_item_id=item.id,
                        target_node_id=target_node.id,
                        edge_type_id=strategy.default_edge_type(),
                        confidence=match["confidence"],
                        reason=match["reason"],
                        status="pending",
                    )
                except SQLAlchemyError:
                    logger.exception(
                        "Error creating suggested edge to node %s",
                        target_node.id,
                    )

            matched_count += 1
            await self.session.flush()

            logger.info(
                "%s %s reprocessed: %d suggested edges",
                item.type,
                item.zaak_nummer,
                len(matched_nodes),
            )

        await self.session.flush()
        return {
            "total": len(items),
            "matched": matched_count,
            "out_of_scope": out_of_scope_count,
            "skipped": skipped_count,
        }

    async def _detach_corpus_node(
        self,
        item: ParlementairItem,
    ) -> None:
        """Remove the corpus node created during a matchless import.

        Deletes the CorpusNode (cascading to PolitiekeInput, edges,
        tasks, stakeholders, node_tags) and clears the FK on the item.
        """
        # Delete the corpus node (cascades to politieke_input, tasks, etc.)
        if item.corpus_node_id:
            node = await self.session.get(CorpusNode, item.corpus_node_id)
            if node:
                await self.session.delete(node)
            item.corpus_node_id = None

        await self.session.flush()

    async def _link_indieners(
        self,
        node_id: uuid.UUID,
        indieners: list[str],
        bron: str,
    ) -> None:
        """Find or create Person records for indieners and link as stakeholders."""
        kamer = "Tweede Kamer" if bron == "tweede_kamer" else "Eerste Kamer"
        for naam in indieners:
            naam = naam.strip()
            if not naam or naam == "TK" or naam == "EK":
                continue

            try:
                person = await self._find_or_create_person(naam, kamer)
                rp = ResourcePermission(
                    person_id=person.id,
                    resource_type="corpus_node",
                    resource_id=node_id,
                    rol="indiener",
                )
                self.session.add(rp)
            except SQLAlchemyError:
                logger.exception(f"Error linking indiener '{naam}' to node")

        await self.session.flush()

    async def _find_or_create_person(self, naam: str, kamer: str) -> Person:
        """Find a person by name+functie or create a new external person record.

        First tries exact match on naam+functie. If not found, falls back to
        matching on naam alone to avoid creating duplicates when the same person
        was added manually without a functie.
        """
        functie = f"Kamerlid {kamer}"
        # Exact match on naam + functie
        stmt = select(Person).where(
            Person.naam == naam,
            Person.functie == functie,
        )
        result = await self.session.execute(stmt)
        person = result.scalar_one_or_none()

        if person:
            return person

        # Fallback: match on naam alone (pick oldest active person)
        stmt_naam = (
            select(Person)
            .where(
                Person.naam == naam,
                Person.is_active == True,  # noqa: E712
            )
            .order_by(Person.created_at.asc())
        )
        result_naam = await self.session.execute(stmt_naam)
        matches = list(result_naam.scalars().all())
        if len(matches) > 1:
            logger.warning(
                "Multiple persons found for naam '%s' — using oldest (id=%s)",
                naam,
                matches[0].id,
            )
        person = matches[0] if matches else None

        if person:
            return person

        person = Person(
            naam=naam,
            functie=functie,
            is_active=True,
        )
        self.session.add(person)
        await self.session.flush()
        return person


# Hoeveel omwentelingen de sorteerlus per stuk mag maken.
#
# Twee is ruim zolang de nummers uniek zijn: elk stuk wordt dan hoogstens
# één keer op de stapel gezet door zijn hoofdstuk en één keer door de
# hoofdlus. Zijn er dubbele nummers, dan groeit het aantal omwentelingen
# kwadratisch en raakt het budget op; het vangnet eronder levert de lijst
# dan compleet maar minder net gesorteerd af. Dat is de goede kant om op
# te falen, en het is in de praktijk onbereikbaar: `search_many`
# ontdubbelt op documentnummer en `ParlementairItem.zaak_id` is uniek.
#
# Verlaag dit getal dus niet op de aanname dat één omwenteling per stuk
# genoeg is. De marge staat apart zodat een test hem op nul kan zetten en
# kan aantonen dat het vangnet werkt.
_SORTEER_MARGE = 2


def _hoofdstuk_voor_bijlage(items: list) -> list:
    """Zet elk hoofdstuk vóór de bijlagen die eraan hangen.

    Een beslisnota en de brief waar hij bij hoort komen in dezelfde ronde
    binnen, maar de bron levert ze in willekeurige volgorde. Werd de
    bijlage eerst verwerkt, dan bestond de thread van de brief nog niet en
    kwamen er twee losse berichten in het kanaal die over hetzelfde gaan.

    Sorteren is hier genoeg, en dat is de reden dat er geen wachtrij of
    timer nodig is: beide stukken zitten al in deze lijst. Een bijlage
    waarvan het hoofdstuk niet in dezelfde ronde zit blijft op zijn plek
    staan en wordt los gepost, zoals nu. Wachten zou dat stuk kunnen laten
    verdwijnen als de brief nooit komt, en dat is erger dan twee berichten.

    De volgorde binnen elke groep blijft zoals de bron hem gaf; alleen een
    bijlage verhuist, naar de plek direct achter zijn hoofdstuk.
    """

    def nummer(item) -> str | None:
        return getattr(item, "zaak_id", None)

    aanwezig = {nummer(item) for item in items if nummer(item)}

    bijlagen_van: dict[str, list] = {}
    for item in items:
        extra = getattr(item, "extra_data", None) or {}
        hoort_bij = extra.get("bijlage_bij_nummer")
        # Alleen verhuizen als het hoofdstuk hier ook werkelijk in zit.
        # Anders is dit stuk voor deze ronde gewoon een los bericht. De
        # vergelijking met het eigen nummer vangt een stuk dat naar
        # zichzelf verwijst; dat zou zichzelf anders eindeloos vooruit
        # schuiven.
        if not hoort_bij or hoort_bij not in aanwezig:
            continue
        if hoort_bij == nummer(item):
            continue
        bijlagen_van.setdefault(hoort_bij, []).append(item)

    if not bijlagen_van:
        return items

    # Elk item precies één keer, en dat is hier geen nettigheid maar de
    # hele veiligheid van deze functie. Een stuk dat hier uit de lijst
    # valt wordt niet los gepost maar verdwijnt: `_import_type` loopt
    # alleen over wat hier uitkomt, en `_verschuif_watermerk` draait al in
    # `fetch_items`, dus de volgende ronde ziet het stuk niet meer. Het
    # verlies is dan permanent en stil.
    #
    # Een eerdere versie sloeg een verhuisd item over met `continue`, en
    # sprong daarmee ook over de regel die zijn éígen bijlagen uitgeeft.
    # Bij een keten (A hangt aan B, B hangt aan C) verdween A daardoor
    # helemaal; bij een cykel de hele cykel.
    uitgegeven: set[int] = set()
    gesorteerd: list = []

    # Harde bovengrens naast de `uitgegeven`-check. Die check is wat een
    # cykel breekt, en als hij ooit wegvalt draait de lus hieronder eeuwig
    # door in plaats van te falen. Een vastgelopen importworker is erger
    # dan een verkeerd gesorteerde ronde. Het kost niets zolang alles
    # werkt, want elke omwenteling geeft hoogstens één stuk uit.
    #
    # Over de hele functie en niet per aanroep: anders krijgt elke wortel
    # zijn eigen ruimte terug en begrenst het niets.
    budget = [len(items) * _SORTEER_MARGE]

    def geef_uit(wortel) -> None:
        # Iteratief en niet recursief: de diepte van deze keten komt uit
        # een externe bron, en een stack overflow zou een hele ronde
        # kosten.
        stapel = [wortel]
        while stapel and budget[0] > 0:
            budget[0] -= 1
            item = stapel.pop()
            if id(item) in uitgegeven:
                continue
            uitgegeven.add(id(item))
            gesorteerd.append(item)
            # Omgekeerd op de stapel, zodat ze er in de oorspronkelijke
            # volgorde weer af komen.
            stapel.extend(reversed(bijlagen_van.get(nummer(item), [])))

    # Eerst de stukken die zelf geen bijlage zijn: die trekken hun eigen
    # bijlagen mee, en dat is het hele doel. Zou een bijlage eerder
    # langskomen, dan werd hij meteen uitgegeven en stond hij alsnog vóór
    # zijn hoofdstuk.
    verhuisd = {id(b) for groep in bijlagen_van.values() for b in groep}
    for item in items:
        if id(item) not in verhuisd:
            geef_uit(item)

    # Wat dan nog over is hangt aan niets dat we hebben uitgegeven: een
    # cykel. Wie als eerste langskomt wordt de wortel, de rest hangt
    # eronder, en niemand valt weg.
    for item in items:
        geef_uit(item)

    # Vangnet. Alles hierboven hoort elk stuk al te hebben uitgegeven, dus
    # deze lus doet normaal niets. Hij staat er omdat de prijs van een
    # gemist stuk permanent is: de sortering is een nettigheid, de
    # volledigheid van de lijst niet.
    ontbrekend = [i for i in items if id(i) not in uitgegeven]
    if ontbrekend:
        logger.warning(
            "Sortering liet %d stuk(ken) liggen; alsnog toegevoegd", len(ontbrekend)
        )
        gesorteerd.extend(ontbrekend)
    return gesorteerd


def _context_regels(extra: dict) -> list[str]:
    """Feiten uit de TK-API die het model niet uit de tekst kan halen.

    Een agenda zegt zelden in zijn eigen tekst wanneer de vergadering is,
    en een bijlage noemt niet bij welke brief hij hoort. Die feiten staan
    in de API, dus geven we ze mee in plaats van het model te laten raden.
    """
    regels: list[str] = []
    if extra.get("bijlage_bij_nummer"):
        onderwerp = extra.get("bijlage_bij_onderwerp") or ""
        regels.append(
            f"DIT IS EEN BIJLAGE BIJ: {extra['bijlage_bij_nummer']} {onderwerp}".strip()
        )
    if extra.get("activiteit_datum"):
        soort = extra.get("activiteit_soort") or "vergadering"
        regels.append(f"VERGADERDATUM: {extra['activiteit_datum']} ({soort})")
    if extra.get("termijn"):
        regels.append(f"ANTWOORDTERMIJN: {extra['termijn']}")
    if extra.get("commissie"):
        regels.append(f"COMMISSIE: {extra['commissie']}")
    return regels
