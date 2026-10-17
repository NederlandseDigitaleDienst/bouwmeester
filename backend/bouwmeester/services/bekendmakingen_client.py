"""Leest officiële bekendmakingen via de SRU-API van KOOP.

De Staatscourant, het Staatsblad en het Tractatenblad, uit
repository.overheid.nl en niet van de website: de SRU-API is de officiële
ingang, zonder sleutel en onder CC0. Kamerstukken, Handelingen en
Kamervragen staan in dezelfde collectie maar blijven buiten de vraag; die
komen al via tkconv binnen. Gemeenteblad, Provinciaal blad en
Waterschapsblad ook: ongeveer 2600 lokale stukken per dag, ruis voor wie
een rijksdossier volgt.

Volume, gemeten tussen 9 en 17 oktober 2026: 139 tot 190 stukken per
werkdag, vrijwel allemaal in één ochtendbatch tussen 09:00 en 09:30.

Drie eigenaardigheden van de API die het ontwerp bepalen, alle drie gemeten
op 17 oktober 2026:

Een ongeldige filter wordt niet geweigerd maar weggelaten. Een datetime op
`dt.available` (dat een datum is) levert HTTP 200 op met een diagnostic
erin, en alle 858.619 Staatscourant-records erachter. Een antwoord met een
diagnostic geldt daarom als mislukt, ook als er records in staan.

`sortKeys` wordt stil genegeerd; sorteren gaat via `sortBy` in de CQL.

`cd.datumTijdstipWijzigingWork` verschuift als een oud record wordt
bijgewerkt. Een filter op alleen dat veld brengt dus oude stukken terug als
nieuw: van 237 records met een wijziging na 16 oktober 09:07 hadden er 94
een publicatiedatum van vóór 15 oktober. Daarom staat er altijd een
ondergrens op `dt.available` naast.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from xml.etree.ElementTree import Element, ParseError
from zoneinfo import ZoneInfo

import httpx
from defusedxml.ElementTree import fromstring as xml_fromstring

from bouwmeester.services.nieuws_client import USER_AGENT

logger = logging.getLogger(__name__)

REPOSITORY_HOST = "repository.overheid.nl"
SRU_URL = f"https://{REPOSITORY_HOST}/sru"

TIMEOUT = 30.0

# Een pagina van 200 records is ongeveer 800 kB (gemeten over 1005 records,
# 9 tot 17 oktober 2026); de gebiedsmarkering van een omgevingsvergunning is
# een polygoon en kan een record flink groter maken. Boven de 1000 valt de
# API stil terug op 10 per pagina.
PAGINA_GROOTTE = 200
MAX_ANTWOORD_BYTES = 16 * 1024 * 1024

# Hoe ver een zoekvraag terugkijkt vóór het watermerk. Een record staat pas
# na enige tijd in de index: tussen `datumTijdstipWijzigingWork` en
# `gzd:timestamp` zat over 1005 records een mediaan van 5,4 minuten en een
# maximum van 11,4 minuten. Een uur is ruim daarboven, en kost alleen
# bytes: wat al gezien is wordt niet opnieuw opgehaald (zie de strategie).
TERUGKIJKEN = timedelta(hours=1)

# De repository begrenst het aantal verzoeken, zonder dat te documenteren
# en zonder Retry-After. Gemeten op 17 oktober 2026: zonder pauze gaf nginx
# na 22 verzoeken "429 Too Many Requests"; bij ongeveer acht per seconde
# slaagde daarna een op de drie; bij drie à vier per seconde kwamen 60
# verzoeken op rij door. Twee per seconde blijft daar ruim onder, en kost
# bij een ochtendbatch van 50 kandidaten 25 seconden.
PAUZE_TUSSEN_VERZOEKEN = 0.5

# Een volledige tekst van een wet is ongeveer 100 kB; dit vangt een
# uitzonderlijk lange regeling zonder een geheugenprobleem te worden.
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024

# Zelfde grens als bij tkconv, en niet die van een nieuwsartikel: hierin
# wordt gezocht, en de passage die telt staat vaak achteraan. Gemeten op
# trb-2026-115: 430.497 tekens, de Nederlandse vertaling begint bij teken
# 278.288. Bij een wet of AMvB staat de programmanaam meestal pas in de
# toelichting, na de artikelen. Het model krijgt dit niet in zijn geheel:
# `_relevante_tekst` knipt rond de zoektermen.
MAX_TEKST_TEKENS = 500_000

BLADEN = ("Staatscourant", "Staatsblad", "Tractatenblad")

_AMSTERDAM = ZoneInfo("Europe/Amsterdam")

_NS = {
    "sru": "http://docs.oasis-open.org/ns/search-ws/sruResponse",
    "gzd": "http://standaarden.overheid.nl/sru",
    "dcterms": "http://purl.org/dc/terms/",
    "owg": "http://standaarden.overheid.nl/wetgeving/",
    "cd": "http://standaarden.overheid.nl/cup/data",
}
_DIAG_NS = "{http://docs.oasis-open.org/ns/search-ws/diagnostic}"

_WS = re.compile(r"\s+")


@dataclass
class Bekendmaking:
    """Eén publicatie, met alleen de metadata waar we iets mee doen."""

    identifier: str
    titel: str
    samenvatting: str
    publicatie: str
    rubriek: str
    creator: str
    organisatietype: str
    beschikbaar: date | None
    gewijzigd: datetime
    url: str
    pdf_url: str = ""
    xml_url: str = ""
    onderwerpen: list[str] = field(default_factory=list)
    # De tekst van de publicatie zelf, als die is opgehaald. Leeg betekent
    # niet opgehaald of niet gelukt; dan valt alles terug op titel en
    # samenvatting.
    volledige_tekst: str = ""

    @property
    def doorzoekbare_tekst(self) -> str:
        """Waar een zoekterm in gevonden mag worden.

        Titel, samenvatting en de volledige tekst als we die hebben. Het
        Staatsblad heeft geen samenvatting, en een titel als "Wet van 23
        september 2026, houdende ..." noemt zelden het programma waar het
        om gaat.
        """
        delen = [self.titel, self.samenvatting]
        if self.volledige_tekst:
            delen.append(self.volledige_tekst)
        return "\n".join(d for d in delen if d)


# Rubrieken die over één persoon of één bedrijf gaan, met het aantal over
# 1000 Staatscourant-records (15 september tot 17 oktober 2026). Samen een
# kwart van alles, en geen enkele is beleid.
_PERSOONSGEBONDEN_RUBRIEKEN = frozenset(
    {
        "deurwaardersexploot of betekening belastingdienst",  # 94
        "faillissement, surseance van betaling of schuldsanering",  # 61
        "gerechtelijke oproeping belanghebbenden",  # 60
        "ondercuratelestelling of handlichting",  # 26
        "register streekproducten",  # 14
        "echtscheiding of ontbinding",  # 9
        "koninklijke onderscheiding",  # 6
        "accountantsregister",  # 5
        "handelsregister",  # 5
        "register beroepsbeoefenaren individuele gezondheidszorg",  # 3
        "ongewenstverklaring vreemdeling",  # 2
        "tuchtrechtelijke uitspraak",  # 2
    }
)


def is_persoonsgebonden(b: Bekendmaking) -> bool:
    """Gaat deze publicatie over een privépersoon of een enkel bedrijf?

    Zo ja, dan haalt Bouwmeester hem niet op, slaat hem niet op en post hem
    niet. Deze publicaties staan in de Staatscourant omdat de wet dat
    voorschrijft (een faillissement, een curatele, een betekening door de
    Belastingdienst), en ze dragen namen en adressen van mensen. Dat ze
    openbaar zijn, maakt ze nog niet tot iets wat een beleidstool hoort te
    verzamelen.

    Behalve de rubrieken hierboven, gemeten over dezelfde 1000 records:

    - Alles van de rechterlijke macht (152): oproepingen, curatele en
      echtscheidingen, op naam.
    - "Overige overheidsinformatie" van een openbaar lichaam voor bedrijf
      en beroep (411 van de 448 in die rubriek): vrijwel allemaal een
      "Openbaar exploot" van een gerechtsdeurwaarder of een "gerechtelijke
      aankondiging" van een notaris.
    - Een titel die zo begint, ongeacht de rubriek, omdat dezelfde
      exploten ook onder een andere rubriek of organisatietype voorkomen.
    """
    rubriek = b.rubriek.strip().lower()
    organisatietype = b.organisatietype.strip().lower()
    titel = b.titel.strip().lower()

    if rubriek in _PERSOONSGEBONDEN_RUBRIEKEN:
        return True
    if organisatietype == "rechterlijke macht":
        return True
    if (
        rubriek == "overige overheidsinformatie"
        and organisatietype == "openbaar lichaam voor bedrijf en beroep"
    ):
        return True
    return titel.startswith(("gerechtelijke aankondiging", "openbaar exploot"))


def _tekst(el: Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return _WS.sub(" ", el.text).strip()


def _parse_record(rec: Element) -> Bekendmaking | None:
    """Eén `sru:record`. Zonder identifier, titel of wijzigingsmoment: weg.

    Zonder die drie is er geen dedup-sleutel, geen kop of geen plek ten
    opzichte van het watermerk, en dan liever overslaan dan raden.
    """
    meta = rec.find(".//owg:meta", _NS)
    if meta is None:
        return None

    identifier = _tekst(meta.find(".//dcterms:identifier", _NS))
    titel = _tekst(meta.find(".//dcterms:title", _NS))
    try:
        gewijzigd = datetime.fromisoformat(
            _tekst(meta.find(".//cd:datumTijdstipWijzigingWork", _NS))
        )
    except ValueError:
        return None
    if not identifier or not titel:
        return None
    if gewijzigd.tzinfo is None:
        gewijzigd = gewijzigd.replace(tzinfo=_AMSTERDAM)

    try:
        beschikbaar = date.fromisoformat(_tekst(meta.find(".//dcterms:available", _NS)))
    except ValueError:
        beschikbaar = None

    url = ""
    pdf_url = ""
    xml_url = ""
    verrijkt = rec.find(".//gzd:enrichedData", _NS)
    if verrijkt is not None:
        url = _tekst(verrijkt.find("gzd:preferredUrl", _NS))
        for item in verrijkt.findall("gzd:itemUrl", _NS):
            soort = item.get("manifestation")
            if soort == "pdf":
                pdf_url = _tekst(item)
            elif soort == "xml":
                xml_url = _tekst(item)

    return Bekendmaking(
        identifier=identifier,
        titel=titel,
        samenvatting=_tekst(meta.find(".//dcterms:abstract", _NS)),
        publicatie=_tekst(meta.find(".//owg:publicatienaam", _NS)),
        rubriek=_tekst(meta.find(".//dcterms:type", _NS)),
        creator=_tekst(meta.find(".//dcterms:creator", _NS)),
        organisatietype=_tekst(meta.find(".//owg:organisatietype", _NS)),
        beschikbaar=beschikbaar,
        gewijzigd=gewijzigd,
        url=url or f"https://zoek.officielebekendmakingen.nl/{identifier}.html",
        pdf_url=pdf_url,
        xml_url=xml_url,
        onderwerpen=[
            t for t in (_tekst(s) for s in meta.findall(".//dcterms:subject", _NS)) if t
        ],
    )


def _heeft_diagnostic(root: Element) -> bool:
    """Draagt dit antwoord een SRU-diagnostic?

    Op namespace én op naam, want de API levert ze in twee vormen (gemeten
    17 oktober 2026): een weggelaten filter geeft
    `<sru:diagnostics><diag:diagnostic>` naast gewone records, een
    syntaxfout een kale `<diagnostics><ns3:diagnostic>` zonder records.
    """
    for el in root.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag.startswith(_DIAG_NS) or tag.rsplit("}", 1)[-1] == "diagnostics":
            return True
    return False


def parse_antwoord(inhoud: bytes) -> tuple[list[Bekendmaking], int | None] | None:
    """De records en de volgende startpositie, of None als het mislukt is.

    Mislukt betekent hier: geen XML, of een diagnostic in het antwoord. Dat
    laatste is geen detail: dan heeft de API een deel van de vraag
    weggelaten, en de records die er staan horen niet bij onze vraag.
    """
    try:
        root = xml_fromstring(inhoud)
    except (ParseError, ValueError) as exc:
        logger.warning("SRU-antwoord is geen leesbare XML: %s", exc)
        return None

    if _heeft_diagnostic(root):
        meldingen = [
            " ".join(t for t in (el.text or "" for el in d) if t)
            for d in root.iter(f"{_DIAG_NS}diagnostic")
        ]
        logger.warning("SRU-antwoord met diagnostic, genegeerd: %s", meldingen)
        return None

    bekendmakingen = []
    for rec in root.iterfind(".//sru:record", _NS):
        b = _parse_record(rec)
        if b is not None:
            bekendmakingen.append(b)

    volgende_tekst = _tekst(root.find("sru:nextRecordPosition", _NS))
    volgende = int(volgende_tekst) if volgende_tekst.isdigit() else None
    return bekendmakingen, volgende


def zoekvraag(watermerk: datetime) -> str:
    """De CQL voor alles in de drie bladen sinds het watermerk.

    De tijd gaat in UTC met een `Z` erachter. Gemeten op 17 oktober 2026:
    `>=2026-10-16T09:07:35` (kaal) en `>=2026-10-16T07:07:35Z` geven allebei
    als eerste het record van 09:07:35.36+02:00, dus kaal is Amsterdamse
    tijd en `Z` wordt correct omgerekend. Een offset als `+02:00` is een
    syntaxfout. Met UTC speelt de zomertijd geen rol.

    De ondergrens op `dt.available` is een datum, een dag vóór het
    watermerk: ruim genoeg voor een stuk dat 's nachts verscheen, en krap
    genoeg dat een bijgewerkt record van vorige maand niet terugkomt.
    """
    vanaf = (watermerk - TERUGKIJKEN).astimezone(UTC)
    beschikbaar_vanaf = vanaf.astimezone(_AMSTERDAM).date() - timedelta(days=1)
    bladen = " OR ".join(f"w.publicatienaam=={blad}" for blad in BLADEN)
    return (
        f"cd.datumTijdstipWijzigingWork>={vanaf:%Y-%m-%dT%H:%M:%S}Z"
        f" AND dt.available>={beschikbaar_vanaf.isoformat()}"
        f" AND ({bladen})"
        " sortBy cd.datumTijdstipWijzigingWork/sort.ascending"
    )


def _van_de_repository(url: str) -> bool:
    """Komt deze url van repository.overheid.nl, over https?

    De url staat in het SRU-antwoord en niet in onze code. De worker draait
    binnen het netwerk van de applicatie, dus een url die ergens anders
    heen wijst (ook via een omleiding) wordt niet opgehaald.
    """
    try:
        deel = httpx.URL(url)
    except (httpx.InvalidURL, TypeError):
        return False
    return deel.scheme == "https" and deel.host == REPOSITORY_HOST


def documenttekst(inhoud: bytes) -> str:
    """De leestekst uit de XML van een publicatie, of leeg.

    De kop van het blad zelf ("Staatsblad van het Koninkrijk der
    Nederlanden") en het metadatablok gaan er eerst uit; dat staat in elk
    stuk en zegt niets over dit stuk.

    Het bestand begint soms met een BOM (gemeten bij het Staatsblad, niet
    bij de Staatscourant); de parser krijgt daarom bytes en geen tekst.
    """
    if not inhoud:
        return ""
    try:
        root = xml_fromstring(inhoud)
    except (ParseError, ValueError) as exc:
        logger.warning("Publicatie is geen leesbare XML: %s", exc)
        return ""
    for kind in list(root):
        if kind.tag in ("metadata", "kop"):
            root.remove(kind)
    tekst = _WS.sub(" ", " ".join(root.itertext())).strip()
    return tekst[:MAX_TEKST_TEKENS]


class BekendmakingenClient:
    """Zoekt in de SRU-API en haalt publicaties op.

    `volledig` zegt na `zoek_sinds` of alle records zijn gelezen. De
    strategie heeft dat verschil nodig: alleen na een volledige ronde mag
    het watermerk naar het moment van de vraag; na een afgebroken ronde
    niet verder dan het laatste record dat er wel was.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self.volledig = False
        self._vorige_verzoek: float | None = None

    async def _get(
        self, client: httpx.AsyncClient, url: str, params: dict | None = None
    ) -> httpx.Response:
        """Eén GET, met `PAUZE_TUSSEN_VERZOEKEN` sinds de vorige."""
        if self._vorige_verzoek is not None:
            wacht = PAUZE_TUSSEN_VERZOEKEN - (time.monotonic() - self._vorige_verzoek)
            if wacht > 0:
                await asyncio.sleep(wacht)
        try:
            return await client.get(url, params=params)
        finally:
            self._vorige_verzoek = time.monotonic()

    async def __aenter__(self) -> "BekendmakingenClient":
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _haal_pagina(
        self, vraag: str, start: int
    ) -> tuple[list[Bekendmaking], int | None] | None:
        if self._client is None:
            logger.error("BekendmakingenClient gebruikt buiten zijn context")
            return None
        params = {
            "operation": "searchRetrieve",
            "version": "2.0",
            "x-connection": "officielepublicaties",
            "query": vraag,
            "maximumRecords": str(PAGINA_GROOTTE),
            "startRecord": str(start),
        }
        try:
            resp = await self._get(self._client, SRU_URL, params=params)
        except httpx.HTTPError as exc:
            logger.warning("SRU onbereikbaar: %s", exc)
            return None
        if resp.status_code != 200:
            logger.warning("SRU gaf status %d", resp.status_code)
            return None
        if len(resp.content) > MAX_ANTWOORD_BYTES:
            logger.warning(
                "SRU-antwoord is %d bytes, boven de limiet", len(resp.content)
            )
            return None
        return parse_antwoord(resp.content)

    async def zoek_sinds(
        self, watermerk: datetime, max_paginas: int
    ) -> list[Bekendmaking]:
        """Alles sinds het watermerk, oud naar nieuw, hooguit `max_paginas`.

        Faalt zacht: een fout geeft wat er tot dan toe binnen was, en
        `volledig` blijft False. Records komen gesorteerd binnen, dus een
        afgebroken reeks is altijd het oudste deel; de rest komt de
        volgende ronde.
        """
        self.volledig = False
        vraag = zoekvraag(watermerk)
        gevonden: list[Bekendmaking] = []
        start = 1
        for _ in range(max_paginas):
            pagina = await self._haal_pagina(vraag, start)
            if pagina is None:
                return gevonden
            records, volgende = pagina
            gevonden.extend(records)
            if volgende is None or not records:
                self.volledig = True
                return gevonden
            start = volgende
        logger.info(
            "Bekendmakingen: %d pagina's gelezen, de rest volgt de volgende ronde",
            max_paginas,
        )
        return gevonden

    async def haal_tekst(self, xml_url: str) -> str | None:
        """De tekst van één publicatie; leeg als die er niet is, None als
        het later opnieuw moet.

        Het verschil doet ertoe. Een 404 of een bestand dat geen XML is
        komt niet goed, en dan wordt er gezocht in titel en samenvatting.
        Een 429, een 5xx of een time-out is tijdelijk, en dan zou zoeken
        zonder de tekst een treffer in de body voorgoed missen: de
        strategie stopt dan en probeert het de volgende ronde opnieuw.
        """
        if self._client is None or not _van_de_repository(xml_url):
            return ""
        try:
            resp = await self._get(self._client, xml_url)
        except httpx.HTTPError as exc:
            logger.warning("Publicatie %s onbereikbaar: %s", xml_url, exc)
            return None
        if not _van_de_repository(str(resp.url)):
            logger.warning("Publicatie %s leidt om naar %s", xml_url, resp.url)
            return ""
        if resp.status_code == 429 or resp.status_code >= 500:
            logger.warning("Publicatie %s gaf status %d", xml_url, resp.status_code)
            return None
        if resp.status_code != 200:
            logger.warning("Publicatie %s gaf status %d", xml_url, resp.status_code)
            return ""
        if len(resp.content) > MAX_DOCUMENT_BYTES:
            logger.warning(
                "Publicatie %s is ongebruikelijk groot, overgeslagen", xml_url
            )
            return ""
        return documenttekst(resp.content)
