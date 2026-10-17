"""Volgt zoektermen in officiële bekendmakingen.

Dezelfde zoektermen als de kamerstukken en de vakpers, een derde soort bron:
de Staatscourant, het Staatsblad en het Tractatenblad. Hier staat wat is
vastgesteld, niet wat wordt voorgesteld: een ministeriële regeling, een
AMvB, een besluit van algemene strekking.

Zoeken gebeurt aan onze kant, net als bij het nieuws. De SRU-API kan wel
op tekst zoeken, maar één vraag per zoekterm per ronde is verkeer dat niets
oplevert: alles wat sinds het watermerk verscheen is op een werkdag een
pagina van 150 records, en daar matchen we alle abonnementen tegen.

Wat over één persoon of bedrijf gaat (faillissementen, curatele, exploten
van deurwaarders) wordt overgeslagen vóór de tekst wordt opgehaald, en komt
dus nergens terecht. Zie `is_persoonsgebonden`.
"""

import logging
import re
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

from bouwmeester.models.parlementair_abonnement import ParlementairAbonnement
from bouwmeester.services.bekendmakingen_client import (
    TERUGKIJKEN,
    Bekendmaking,
    BekendmakingenClient,
    is_persoonsgebonden,
)
from bouwmeester.services.import_strategies.base import FetchedItem, ImportStrategy
from bouwmeester.services.kamerstuk_soort import categorie_van_bekendmaking

logger = logging.getLogger(__name__)

ITEM_TYPE = "bekendmaking"

# Ruim boven een werkdag (140 tot 190 records in de drie bladen) en boven
# wat zich na een herstart van een week ophoopt, zonder dat een ronde
# eindeloos doorleest als er iets mis is met de vraag.
MAX_PAGINAS = 5

# Niet verder terug dan dit, ook niet binnen één proces. Het watermerk blijft
# staan zolang er geen actieve zoektermen zijn of de API plat ligt; zonder
# deze grens opent de eerste ronde daarna met berichten over stukken van
# weken terug. Dezelfde grens als `MAX_ACHTERSTAND` na een herstart, hier
# apart omdat de import-service deze module importeert.
MAX_ACHTERSTAND = timedelta(days=7)

# Het watermerk, op moduleniveau om dezelfde reden als bij tkconv en het
# nieuws: de import-service bouwt elke ronde een verse strategie.
_WATERMERK: datetime | None = None

# Wat al bekeken is, met zijn wijzigingsmoment. De vraag kijkt
# `TERUGKIJKEN` terug omdat een record pas na enkele minuten in de index
# staat; zonder deze lijst zou elk record in dat venster vier rondes lang
# opnieuw worden opgehaald en gematcht. Een record dat wél matchte zou de
# import-service op `zaak_id` tegenhouden, maar een record dat niet matchte
# kost dan elke ronde een download.
_GEZIEN: dict[str, datetime] = {}

# Hoe vaak de tekst van een stuk tijdelijk niet op te halen was; zie
# `BekendmakingenStrategy._haal_tekst`.
_POGINGEN: dict[str, int] = {}
MAX_POGINGEN = 3


@lru_cache(maxsize=512)
def _als_woord(term: str) -> re.Pattern[str]:
    """De term als heel woord: "GDI" wel in "de GDI-voorzieningen", niet in
    "jeugdinrichting"."""
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def reset_watermerk() -> None:
    """Voor tests: zet het procesgeheugen terug."""
    global _WATERMERK  # noqa: PLW0603
    _WATERMERK = None
    _GEZIEN.clear()
    _POGINGEN.clear()


def huidig_watermerk() -> datetime | None:
    """Where this process has got to, for whoever keeps it across restarts."""
    return _WATERMERK


def herstel_watermerk(tijdstip: datetime | None) -> None:
    """Go on from where the process before this one had got to.

    Only when this process has no watermark of its own yet: one that is
    there is at least as new as what was kept.
    """
    global _WATERMERK  # noqa: PLW0603
    if _WATERMERK is None and tijdstip is not None:
        _WATERMERK = tijdstip


class BekendmakingenStrategy(ImportStrategy):
    """Zoekt de abonnementen van alle initiatieven in de bekendmakingen."""

    def __init__(self) -> None:
        self.abonnementen: list[ParlementairAbonnement] = []
        # identifier -> abonnement-ids, zoals bij tkconv en het nieuws.
        self.treffers: dict[str, list] = {}
        self.verse_abonnementen: set = set()

    @property
    def item_type(self) -> str:
        return ITEM_TYPE

    @property
    def politieke_input_type(self) -> str:
        return "bekendmaking"

    @property
    def requires_llm(self) -> bool:
        return True

    @property
    def supports_ek(self) -> bool:
        return False

    @property
    def uses_tk_api(self) -> bool:
        return False

    @property
    def always_import(self) -> bool:
        # De zoekterm is de scope-check, net als bij de kamerstukken.
        return True

    @property
    def creates_corpus_node(self) -> bool:
        return True

    def build_client(self) -> BekendmakingenClient:
        return BekendmakingenClient()

    async def fetch_items(
        self,
        client: object,
        since: date | None,
        limit: int,
    ) -> list[FetchedItem]:
        global _WATERMERK  # noqa: PLW0603

        if not isinstance(client, BekendmakingenClient):
            logger.error("BekendmakingenStrategy kreeg een %s", type(client).__name__)
            return []
        if not self.abonnementen:
            return []

        nu = datetime.now(UTC)
        if _WATERMERK is None:
            # Zoals bij tkconv en het nieuws: de eerste ronde zet alleen
            # het watermerk. Hier zelfs zonder vraag, want wat die zou
            # opleveren wordt toch niet gepost.
            _WATERMERK = nu
            logger.info("Bekendmakingen: eerste ronde, watermerk gezet op %s", nu)
            return []

        grens = max(_WATERMERK, nu - MAX_ACHTERSTAND)
        bekendmakingen = await client.zoek_sinds(grens, MAX_PAGINAS)

        # Wat ouder is dan het venster van de vraag komt niet meer terug.
        for identifier, wanneer in list(_GEZIEN.items()):
            if wanneer < grens - 2 * TERUGKIJKEN:
                del _GEZIEN[identifier]

        resultaten: list[FetchedItem] = []
        # Het laatste record dat helemaal is afgehandeld. Records komen
        # oud naar nieuw binnen, dus tot hier is alles gezien.
        laatst_bekeken: datetime | None = None
        afgebroken = False
        for b in bekendmakingen:
            if b.identifier in _GEZIEN:
                laatst_bekeken = b.gewijzigd
                continue

            if len(resultaten) >= limit:
                # Wat hier begint is niet bekeken. Het watermerk mag er
                # niet overheen, anders verdwijnt de rest voorgoed.
                afgebroken = True
                break

            if not is_persoonsgebonden(b):
                if b.xml_url and not await self._haal_tekst(client, b):
                    # Tijdelijk mis: de rest wacht op de volgende ronde,
                    # zodat een treffer in de body niet voorgoed wegvalt.
                    afgebroken = True
                    break
                ids = self._passende_abonnementen(b)
                if ids:
                    self.treffers[b.identifier] = ids
                    resultaten.append(self._naar_item(b))

            _GEZIEN[b.identifier] = b.gewijzigd
            _POGINGEN.pop(b.identifier, None)
            laatst_bekeken = b.gewijzigd

        if client.volledig and not afgebroken:
            # Alles tot het moment van de vraag is gezien. Wat daarvoor nog
            # niet in de index stond, valt binnen `TERUGKIJKEN` en komt de
            # volgende ronde alsnog mee.
            _WATERMERK = nu
        elif laatst_bekeken is not None and laatst_bekeken > grens:
            # Afgebroken (limiet, paginagrens of een fout halverwege): niet
            # verder dan wat er werkelijk bekeken is. Zonder enig record
            # (de vraag mislukte) blijft het watermerk staan.
            _WATERMERK = laatst_bekeken

        logger.info(
            "Bekendmakingen: %d gelezen, %d treffers, watermerk %s",
            len(bekendmakingen),
            len(resultaten),
            _WATERMERK,
        )
        return resultaten

    @staticmethod
    async def _haal_tekst(client: BekendmakingenClient, b: Bekendmaking) -> bool:
        """Haal de tekst op vóór het matchen; False als het later moet.

        Vóór het matchen, want het Staatsblad heeft geen samenvatting, en
        een titel als "Wet van 23 september 2026, houdende ..." noemt zelden
        het programma waar het om gaat.

        Na `MAX_POGINGEN` tijdelijke fouten op hetzelfde stuk geldt het als
        zonder tekst. Anders houdt één stuk dat blijvend een 503 geeft de
        hele bron tegen.
        """
        tekst = await client.haal_tekst(b.xml_url)
        if tekst is None:
            _POGINGEN[b.identifier] = _POGINGEN.get(b.identifier, 0) + 1
            if _POGINGEN[b.identifier] < MAX_POGINGEN:
                return False
            logger.warning(
                "Bekendmaking %s: tekst na %d pogingen niet op te halen, "
                "gezocht in titel en samenvatting",
                b.identifier,
                MAX_POGINGEN,
            )
            tekst = ""
        b.volledige_tekst = tekst
        return True

    def _passende_abonnementen(self, b: Bekendmaking) -> list:
        """Welke zoektermen komen als heel woord voor in deze publicatie?

        Op woordgrenzen, niet als losse tekenreeks zoals bij het nieuws. Een
        wettekst is lang, en een korte afkorting zit dan vrijwel altijd in
        een ander woord. Gemeten op 17 oktober 2026: "GDI" raakte zes van
        acht stukken, via "jeugdinrichting", "crowdfundingdienst",
        "jeugdigen" en "belastingdienstbestand", en geen enkele keer de GDI.
        """
        tekst = b.doorzoekbare_tekst
        return [
            a.id
            for a in self.abonnementen
            if a.actief
            and a.term_genormaliseerd
            and _als_woord(a.term_genormaliseerd).search(tekst)
        ]

    def _naar_item(self, b: Bekendmaking) -> FetchedItem:
        herkomst = ", ".join(x for x in (b.publicatie, b.creator) if x)
        return FetchedItem(
            zaak_id=b.identifier,
            zaak_nummer=b.identifier,
            titel=b.titel,
            onderwerp=b.samenvatting or b.titel,
            datum=b.beschikbaar,
            # Precies de tekst waarin ook gezocht is.
            document_tekst=b.doorzoekbare_tekst,
            document_url=b.url,
            bron=b.publicatie,
            # Niet `dcterms:publisher`: dat is voor de Staatscourant altijd
            # BZK en voor het Staatsblad altijd JenV, de uitgevers van het
            # blad, en niet wie het besluit nam.
            ministerie=b.creator if b.organisatietype.lower() == "ministerie" else None,
            extra_data={
                "categorie": categorie_van_bekendmaking(b.publicatie, b.rubriek),
                "soort": b.rubriek or None,
                "publicatie": b.publicatie,
                # Niet `herkomst`: die sleutel draagt bij tkconv de bron
                # ("tkconv") en mag de kopregel daar niet veranderen.
                "herkomst_label": herkomst,
                "raw_url": b.pdf_url or None,
                "onderwerpen": b.onderwerpen,
            },
        )

    def task_title(self, item: FetchedItem) -> str:
        onderwerp = (item.titel or item.onderwerp or "onbekend")[:80]
        return f"Beoordeel bekendmaking: {onderwerp}"

    def task_priority(self, item: FetchedItem) -> str:
        # Een signaal, geen deadline, zoals bij tkconv.
        return "normaal"

    def notification_title(self, node_title: str) -> str:
        return f"Nieuwe bekendmaking: {node_title}"

    def context_hint(self) -> str:
        return "bekendmaking"
