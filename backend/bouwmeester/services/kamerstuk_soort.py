"""Wat voor kamerstuk is dit, en wat betekent dat voor de lezer?

tkconv levert een documentnummer, een titel en de tekst — maar niet het
soort. Zonder dat zegt elk alert "Kamerstuk", terwijl het verschil juist het
eerste is wat iemand wil weten: een kamervraag heeft een antwoordtermijn,
een agenda van een procedurevergadering ligt in de toekomst (je kunt er nog
input op leveren), en een position paper komt van buiten de Kamer.

Het soort komt uit de officiële TK-API, één call per nieuw stuk. Dat is de
enige plek waar het staat, en het is goedkoop omdat het alleen bij import
gebeurt en niet bij elke poll-ronde.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx

logger = logging.getLogger(__name__)

TK_BASE_URL = "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0"

# Categorieën waarin de soorten uiteenvallen. Niet het `Soort`-veld zelf:
# de TK-API kent tientallen soorten, en wat een lezer ermee moet is met een
# handvol groepen gedekt. De categorie stuurt het icoon, de kopregel en de
# instructie die de LLM krijgt.
CAT_VRAAG = "vraag"
CAT_VERGADERING_VOORUIT = "vergadering_vooruit"
CAT_VERGADERING_TERUG = "vergadering_terug"
# Het woordelijke verslag van een debat, apart van `vergadering_terug`.
# Dat laatste is een besluitenlijst: wat is er besloten. Hier staat wat er
# gezégd is, door wie, en dat vraagt een andere samenvatting.
CAT_DEBAT = "debat"
CAT_BIJLAGE = "bijlage"
CAT_BRIEF = "brief"
CAT_EXTERN = "extern"
CAT_WETGEVING = "wetgeving"
# Geen kamerstuk maar een artikel uit de vakpers. Staat hier omdat de
# categorie het icoon, de kopregel en de LLM-instructie stuurt, en een
# nieuwsbericht alle drie anders nodig heeft dan een kamerstuk.
CAT_NIEUWS = "nieuws"
CAT_OVERIG = "overig"

# Gemeten op 22 september 2026 tegen de echte API; de sleutels zijn het
# letterlijke `Soort`-veld uit `Document`.
_SOORT_CATEGORIE: dict[str, str] = {
    "Schriftelijke vragen": CAT_VRAAG,
    "Antwoord schriftelijke vragen": CAT_VRAAG,
    "Antwoord schriftelijke vragen (nader)": CAT_VRAAG,
    "Vragen gesteld door de leden der Kamer": CAT_VRAAG,
    "Lijst van vragen": CAT_VRAAG,
    "Lijst van vragen en antwoorden": CAT_VRAAG,
    "Inbreng verslag schriftelijk overleg": CAT_VRAAG,
    "Verslag van een schriftelijk overleg": CAT_VRAAG,
    # Geen administratief lijstje maar het bericht dat een antwoordtermijn
    # verschuift: "Uitstel beantwoording vragen van de leden X en Y over
    # ...". Dat hoort bij de vraag waar het over gaat, en de vraag-categorie
    # draagt de termijn al in de kopregel.
    "Mededeling (uitstel antwoord)": CAT_VRAAG,
    # Opgeheven soort: in 2010 gesplitst in "Antwoord schriftelijke vragen"
    # en de mededeling hierboven. Staat hier voor het archief, want een
    # zoekterm kan ook een oud stuk raken.
    "Aanhangsel van de Handelingen": CAT_VRAAG,
    # Vooraf: er komt een vergadering aan waar deze term in staat, en daar
    # is nog iets mee te doen. Een convocatie is de uitnodiging met de
    # agenda erbij, en met bijna 30.000 stukken de grootste soort die we
    # hier nog niet benoemden.
    "Convocatie commissieactiviteit": CAT_VERGADERING_VOORUIT,
    "Convocatie inbreng": CAT_VERGADERING_VOORUIT,
    "Agenda plenaire vergadering": CAT_VERGADERING_VOORUIT,
    "Agenda procedurevergadering": CAT_VERGADERING_VOORUIT,
    "Herziene agenda procedurevergadering": CAT_VERGADERING_VOORUIT,
    "Tweede herziene agenda procedurevergadering": CAT_VERGADERING_VOORUIT,
    "Besluitenlijst procedurevergadering": CAT_VERGADERING_TERUG,
    # Woordelijke verslagen. Het stenogram is het ongecorrigeerde verslag
    # van een plenair debat en staat er binnen een dag of twee; een
    # conceptverslag van een commissiedebat na een tot drie weken. Het
    # definitieve "Verslag van een commissiedebat" duurde bij een meting op
    # 1 oktober 2026 bijna drie maanden (debat 1 juli, verslag 21
    # september), dus zonder deze soorten hoor je weken niets over een
    # debat waarin je term viel.
    #
    # "Verslag van een algemeen overleg" is de oude naam voor een
    # commissiedebat en komt in het archief vaker voor dan de nieuwe.
    "Stenogram": CAT_DEBAT,
    "Verslag van een commissiedebat": CAT_DEBAT,
    "Verslag van een algemeen overleg": CAT_DEBAT,
    "Verslag van een wetgevingsoverleg": CAT_DEBAT,
    "Verslag van een notaoverleg": CAT_DEBAT,
    "Verslag van een hoorzitting / rondetafelgesprek": CAT_DEBAT,
    "Verslag van een bijeenkomst": CAT_DEBAT,
    "Mondelinge vragen": CAT_DEBAT,
    "Bijlage": CAT_BIJLAGE,
    "Brief regering": CAT_BRIEF,
    "Brief commissie": CAT_BRIEF,
    "Brief commissie aan bewindspersoon": CAT_BRIEF,
    "Brief lid / fractie": CAT_BRIEF,
    "Brief Kamer": CAT_BRIEF,
    "Brief Presidium": CAT_BRIEF,
    "Geleidende brief": CAT_BRIEF,
    "Position paper": CAT_EXTERN,
    "Burgerbrief": CAT_EXTERN,
    # Ook van buiten de Kamer en het kabinet: adviezen en rapporten van
    # onafhankelijke instanties. Geen beleid, wel vaak het stuk waar een
    # discussie op teruggaat.
    "Advies Afdeling advisering Raad van State": CAT_EXTERN,
    "Advies Afdeling advisering Raad van State en Nader rapport": CAT_EXTERN,
    "Brief Algemene Rekenkamer": CAT_EXTERN,
    "Rapport Algemene Rekenkamer": CAT_EXTERN,
    "Memorie van toelichting": CAT_WETGEVING,
    "Voorstel van wet": CAT_WETGEVING,
    "Nota naar aanleiding van het (nader) verslag": CAT_WETGEVING,
    "Nota n.a.v. het (nader/tweede nader/enz.) verslag": CAT_WETGEVING,
    "Nota van wijziging": CAT_WETGEVING,
    "Amendement": CAT_WETGEVING,
    "Amendement (gewijzigd/nader/vervangend)": CAT_WETGEVING,
    "Motie": CAT_WETGEVING,
    # Een gewijzigde motie vervangt de oorspronkelijke en is dus de versie
    # waar over gestemd wordt.
    "Motie (gewijzigd/nader)": CAT_WETGEVING,
    "Memorie van toelichting (initiatiefvoorstel)": CAT_WETGEVING,
    "Voorstel van wet (initiatiefvoorstel)": CAT_WETGEVING,
    "Verslag (initiatief)wetsvoorstel (nader)": CAT_WETGEVING,
    "Nader rapport": CAT_WETGEVING,
    "Koninklijke boodschap": CAT_WETGEVING,
}

# Hoe elke categorie in Mattermost verschijnt. Het icoon is een emoji omdat
# een attachment geen eigen iconenset heeft; de kleur is de streep links.
#
# Twee vormen van hetzelfde icoon, omdat Mattermost ze niet overal gelijk
# behandelt: `emoji` (de `:code:`-vorm) rendert in `text` en `pretext`,
# `teken` (het Unicode-teken zelf) is nodig in het `title`-veld van een
# attachment. Daar bleef `:question:` letterlijk staan, zichtbaar in
# productie op 24 september 2026.
CATEGORIE_PRESENTATIE: dict[str, dict[str, str]] = {
    CAT_VRAAG: {
        "emoji": ":question:",
        "teken": "\u2753",
        "label": "Kamervraag",
        "kleur": "#B45309",
    },
    CAT_VERGADERING_VOORUIT: {
        "emoji": ":calendar:",
        "teken": "\U0001f4c5",
        "label": "Procedurevergadering",
        "kleur": "#7C3AED",
    },
    CAT_VERGADERING_TERUG: {
        "emoji": ":memo:",
        "teken": "\U0001f4dd",
        "label": "Verslag vergadering",
        "kleur": "#64748B",
    },
    CAT_BIJLAGE: {
        "emoji": ":paperclip:",
        "teken": "\U0001f4ce",
        "label": "Bijlage",
        "kleur": "#1E3A8A",
    },
    CAT_BRIEF: {
        "emoji": ":envelope:",
        "teken": "\u2709\ufe0f",
        "label": "Kamerbrief",
        "kleur": "#1E3A8A",
    },
    # `herkomst` verschijnt achter het soort in de kopregel, waar het iets
    # toevoegt dat het soort niet zegt. Bij een position paper is dat het
    # belangrijkste feit: het komt van buiten de Kamer en is een standpunt
    # van een belanghebbende, geen beleid.
    CAT_EXTERN: {
        "emoji": ":speech_balloon:",
        "teken": "\U0001f4ac",
        "label": "Extern",
        "kleur": "#0F766E",
        "herkomst": "van buiten de Kamer",
    },
    CAT_WETGEVING: {
        "emoji": ":scroll:",
        "teken": "\U0001f4dc",
        "label": "Wetgeving",
        "kleur": "#991B1B",
    },
    CAT_NIEUWS: {
        "emoji": ":newspaper:",
        "teken": "\U0001f4f0",
        "label": "Nieuws",
        "kleur": "#7C3AED",
        # De publicatie staat in de kopregel omdat het bij journalistiek
        # het eerste is wat je wil weten: wie schrijft dit.
        "herkomst": "vakpers",
    },
    CAT_DEBAT: {
        # Een microfoon en niet een tekstballon: die laatste heeft `extern`
        # al, en in de inhaalslag-lijst is de emoji het enige dat een lezer
        # ziet. Daar zouden een debatverslag en een position paper dan niet
        # uit elkaar te houden zijn.
        "emoji": ":microphone:",
        "teken": "\U0001f3a4",
        "label": "Debatverslag",
        "kleur": "#0E7490",
    },
    CAT_OVERIG: {
        "emoji": ":page_facing_up:",
        "teken": "\U0001f4c4",
        "label": "Kamerstuk",
        "kleur": "#64748B",
    },
}


@dataclass
class KamerstukContext:
    """Wat de TK-API over dit document weet, voor zover het iets toevoegt."""

    soort: str | None = None
    categorie: str = CAT_OVERIG
    # Bij een bijlage: het stuk waar hij bij hoort.
    bijlage_bij_nummer: str | None = None
    bijlage_bij_onderwerp: str | None = None
    # Bij een kamervraag: wanneer het antwoord er moet zijn.
    termijn: date | None = None
    afgedaan: bool | None = None
    # Bij een vergaderstuk: welke vergadering, en wanneer.
    activiteit_soort: str | None = None
    activiteit_datum: date | None = None
    # De vergadering waar dit stuk bij hoort. Draagt geen betekenis voor
    # het bericht, wel voor wat erna kan komen: met dit id is de
    # vergadering op de dag zelf terug te vinden, inclusief de actuele
    # status en begintijd.
    activiteit_id: str | None = None
    activiteit_status: str | None = None
    commissie: str | None = None
    zaak_nummer: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def presentatie(self) -> dict[str, str]:
        return CATEGORIE_PRESENTATIE.get(
            self.categorie, CATEGORIE_PRESENTATIE[CAT_OVERIG]
        )

    def dagen_tot_vergadering(self, vandaag: date | None = None) -> int | None:
        """Hoeveel dagen tot de vergadering; negatief als hij geweest is."""
        if self.activiteit_datum is None:
            return None
        return (self.activiteit_datum - (vandaag or date.today())).days

    def as_extra_data(self) -> dict:
        """Platte vorm voor `ParlementairItem.extra_data`."""
        return {
            "soort": self.soort,
            "categorie": self.categorie,
            "bijlage_bij_nummer": self.bijlage_bij_nummer,
            "bijlage_bij_onderwerp": self.bijlage_bij_onderwerp,
            "termijn": self.termijn.isoformat() if self.termijn else None,
            "afgedaan": self.afgedaan,
            "activiteit_soort": self.activiteit_soort,
            "activiteit_datum": (
                self.activiteit_datum.isoformat() if self.activiteit_datum else None
            ),
            "activiteit_id": self.activiteit_id,
            "activiteit_status": self.activiteit_status,
            "zaak_nummer": self.zaak_nummer,
        }


def categorie_van(soort: str | None) -> str:
    """Welke categorie hoort bij dit `Soort`?

    Onbekende soorten vallen terug op `overig`. Dat is bewust geen fout:
    de TK-API kent tientallen soorten en er komen er bij, en een stuk
    verzwijgen omdat we het label niet kennen is het tegenovergestelde van
    een breed vangnet.
    """
    if not soort:
        return CAT_OVERIG
    if soort in _SOORT_CATEGORIE:
        return _SOORT_CATEGORIE[soort]

    # Een paar soorten zijn per commissie of per gelegenheid net anders
    # geformuleerd ("Herziene agenda …", "… (nader)"), dus val terug op de
    # kern van de naam in plaats van op een exacte match.
    klein = soort.lower()
    if "agenda" in klein and "procedurevergadering" in klein:
        return CAT_VERGADERING_VOORUIT
    if "besluitenlijst" in klein:
        return CAT_VERGADERING_TERUG
    # "Verslag van een ..." is een woordelijk verslag en geen besluitenlijst.
    # Elke benoemde variant staat hierboven al in de tabel; wat hier langs
    # komt is restmateriaal (werkbezoek, rapporteur, politieke dialoog) of
    # een soort die de TK heeft hernoemd. Dan is `debat` de goede terugval,
    # want anders zegt dit vangnet precies het omgekeerde van de tabel.
    if "verslag van een" in klein:
        return CAT_DEBAT
    if "vragen" in klein:
        return CAT_VRAAG
    if klein.startswith("brief"):
        return CAT_BRIEF
    return CAT_OVERIG


def _parse_datum(waarde: object) -> date | None:
    """Lees een datum uit de API-respons.

    `except ValueError` alleen is te smal: JSON mag een getal of een object
    leveren waar wij een string verwachten, en `.replace` gooit dan een
    AttributeError die `haal_context` niet vangt. Dan valt de hele ronde om
    op één afwijkend veld, terwijl dit zacht hoort te falen.
    """
    if not waarde:
        return None
    try:
        return datetime.fromisoformat(str(waarde).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


async def haal_context(
    nummer: str, client: httpx.AsyncClient, base_url: str = TK_BASE_URL
) -> KamerstukContext:
    """Zoek het soort en de context van één document op bij de TK-API.

    Faalt zacht: zonder context wordt het alert een gewoon kamerstuk, en
    dat is beter dan geen alert. De officiële API is rijksinfrastructuur,
    dus hier geen speciale terughoudendheid zoals bij tkconv — maar het
    blijft één call per nieuw stuk, niet per ronde.
    """
    params = {
        "$filter": f"DocumentNummer eq '{nummer}'",
        "$select": "DocumentNummer,Soort,Onderwerp,Datum,Kamer",
        "$expand": (
            "Zaak($select=Nummer,Soort,Onderwerp,Termijn,Afgedaan),"
            "BronDocument($select=DocumentNummer,Soort,Onderwerp),"
            # `Id` en `Status` lijken overbodig voor het bericht, en dat
            # zijn ze ook: ze dragen de koppeling naar de vergadering zelf.
            # Een convocatie kondigt een debat aan dat weken later pas
            # plaatsvindt (mediaan 20,5 dagen, gemeten over 80 convocaties),
            # en de activiteit is dan de enige sleutel die blijft werken.
            # Debat Direct kent het debat op dat moment nog niet: dat geeft
            # nul resultaten voor elke toekomstige datum.
            #
            # `Status` staat erbij omdat een aangekondigd debat niet altijd
            # doorgaat: van 250 gemeten activiteiten werden er 14
            # geannuleerd en 11 verplaatst.
            "Activiteit($select=Id,Nummer,Soort,Onderwerp,Datum,Status)"
        ),
    }
    try:
        response = await client.get(f"{base_url}/Document", params=params)
        response.raise_for_status()
        waarden = response.json().get("value", [])
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Kon soort van %s niet ophalen: %s", nummer, e)
        return KamerstukContext()

    if not waarden:
        logger.info("Document %s staat niet in de TK-API", nummer)
        return KamerstukContext()

    doc = waarden[0]
    soort = doc.get("Soort")
    ctx = KamerstukContext(soort=soort, categorie=categorie_van(soort))

    zaken = doc.get("Zaak") or []
    if zaken:
        zaak = zaken[0]
        ctx.zaak_nummer = zaak.get("Nummer")
        ctx.termijn = _parse_datum(zaak.get("Termijn"))
        ctx.afgedaan = zaak.get("Afgedaan")

    bron = doc.get("BronDocument") or []
    if bron:
        ctx.bijlage_bij_nummer = bron[0].get("DocumentNummer")
        ctx.bijlage_bij_onderwerp = bron[0].get("Onderwerp")

    activiteiten = doc.get("Activiteit") or []
    if activiteiten:
        act = activiteiten[0]
        ctx.activiteit_soort = act.get("Soort")
        ctx.activiteit_datum = _parse_datum(act.get("Datum"))
        ctx.activiteit_id = act.get("Id") or None
        ctx.activiteit_status = act.get("Status") or None
        # Een agenda die in het verleden ligt is geen vooruitblik meer.
        #
        # Een convocatie inbreng niet: dat is de aankondiging van een
        # inbrengdatum, geen vergadering. Verstreken of niet, er is geen
        # besluitenlijst, en `vergadering_terug` zou het model opdragen te
        # zeggen "welk besluit is genomen" over een stuk dat er geen bevat.
        # Dan liever de vooruitblik laten staan: die klopt tenminste over
        # wat voor stuk het is.
        if (
            ctx.categorie == CAT_VERGADERING_VOORUIT
            and ctx.soort != "Convocatie inbreng"
            and ctx.activiteit_datum
            and ctx.activiteit_datum < date.today()
        ):
            ctx.categorie = CAT_VERGADERING_TERUG

    return ctx
