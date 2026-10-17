"""Tests voor het lezen van officiële bekendmakingen uit de SRU-API.

De records hieronder zijn ingekort uit echte antwoorden van 17 oktober
2026. Twee dingen die fout kunnen gaan zonder dat iemand het merkt:

Een ongeldige filter wordt door de API niet geweigerd maar weggelaten,
met HTTP 200 en een diagnostic. Wie daar overheen leest, krijgt alle
858.619 Staatscourant-records als "nieuw".

Wat over één persoon gaat (een faillissement, een curatele, een exploot)
mag nooit verder komen dan de metadata.
"""

import time
from datetime import UTC, datetime

import httpx
import pytest

from bouwmeester.services import bekendmakingen_client as mod
from bouwmeester.services.bekendmakingen_client import (
    MAX_TEKST_TEKENS,
    Bekendmaking,
    BekendmakingenClient,
    documenttekst,
    is_persoonsgebonden,
    parse_antwoord,
    zoekvraag,
)
from bouwmeester.services.kamerstuk_soort import (
    CAT_BEKENDMAKING,
    CAT_REGELGEVING,
    categorie_van_bekendmaking,
)

_KOP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<sru:searchRetrieveResponse"
    ' xmlns:overheidwetgeving="http://standaarden.overheid.nl/wetgeving/"'
    ' xmlns:dcterms="http://purl.org/dc/terms/"'
    ' xmlns:cd="http://standaarden.overheid.nl/cup/data"'
    ' xmlns:sru="http://docs.oasis-open.org/ns/search-ws/sruResponse"'
    ' xmlns:gzd="http://standaarden.overheid.nl/sru"'
    ' xmlns:diag="http://docs.oasis-open.org/ns/search-ws/diagnostic"'
    ' xmlns:c="http://standaarden.overheid.nl/collectie/">'
    "<sru:version>2.0</sru:version>"
)

_REPO = "https://repository.overheid.nl/frbr/officielepublicaties"
_ZOEK = "https://zoek.officielebekendmakingen.nl"

STCRT = (
    "<sru:record><sru:recordSchema>http://standaarden.overheid.nl/sru/</sru:recordSchema>"
    "<sru:recordPacking>xml</sru:recordPacking><sru:recordData><gzd:gzd>"
    "<gzd:originalData><overheidwetgeving:meta><overheidwetgeving:owmskern>"
    "<dcterms:identifier>stcrt-2026-35556</dcterms:identifier>"
    "<dcterms:title>Kennisgeving melding voor het lozen te Moezelweg 241 Europoort"
    " Rotterdam</dcterms:title>"
    "<dcterms:language>nl</dcterms:language>"
    '<dcterms:type scheme="OVERHEIDop.Rubriek">omgevingsmelding</dcterms:type>'
    '<dcterms:creator scheme="OVERHEIDop.DienstAgentschapInstellingOfProject">'
    "Rijkswaterstaat</dcterms:creator>"
    "<dcterms:modified>2026-10-07</dcterms:modified></overheidwetgeving:owmskern>"
    "<overheidwetgeving:owmsmantel><dcterms:available>2026-10-07</dcterms:available>"
    "<dcterms:date>2026-10-07</dcterms:date>"
    '<dcterms:subject scheme="OVERHEID.TaxonomieBeleidsagendaDecentraal">'
    "Ruimte en infrastructuur | Organisatie en beleid</dcterms:subject>"
    "<dcterms:abstract>Omgevingsmelding Air Products Nederland B.V.</dcterms:abstract>"
    '<dcterms:publisher scheme="OVERHEID.Ministerie">Ministerie van Binnenlandse'
    " Zaken en Koninkrijksrelaties</dcterms:publisher></overheidwetgeving:owmsmantel>"
    "<overheidwetgeving:tpmeta><c:product-area>officielepublicaties</c:product-area>"
    '<overheidwetgeving:organisatietype scheme="OVERHEID.Organisatietype">'
    "dienst en agentschap</overheidwetgeving:organisatietype>"
    "<overheidwetgeving:publicatienummer>35556</overheidwetgeving:publicatienummer>"
    "<overheidwetgeving:publicatienaam>Staatscourant</overheidwetgeving:publicatienaam>"
    "<overheidwetgeving:gebiedsmarkering>POLYGON((4.0 51.9, 4.1 51.9, 4.1 52.0,"
    " 4.0 51.9))</overheidwetgeving:gebiedsmarkering>"
    "<cd:datumTijdstipWijzigingWork>2026-10-07T09:16:21.0923262+02:00"
    "</cd:datumTijdstipWijzigingWork></overheidwetgeving:tpmeta>"
    "</overheidwetgeving:meta></gzd:originalData><gzd:enrichedData>"
    f"<gzd:preferredUrl>{_ZOEK}/stcrt-2026-35556.html</gzd:preferredUrl>"
    f'<gzd:itemUrl manifestation="pdf">{_REPO}/stcrt/2026/stcrt-2026-35556/1/pdf/'
    "stcrt-2026-35556.pdf</gzd:itemUrl>"
    f'<gzd:itemUrl manifestation="xml">{_REPO}/stcrt/2026/stcrt-2026-35556/1/xml/'
    "stcrt-2026-35556.xml</gzd:itemUrl>"
    "</gzd:enrichedData></gzd:gzd></sru:recordData>"
    "<sru:recordPosition>1</sru:recordPosition></sru:record>"
)

STB = (
    "<sru:record><sru:recordSchema>http://standaarden.overheid.nl/sru/</sru:recordSchema>"
    "<sru:recordPacking>xml</sru:recordPacking><sru:recordData><gzd:gzd>"
    "<gzd:originalData><overheidwetgeving:meta><overheidwetgeving:owmskern>"
    "<dcterms:identifier>stb-2026-296</dcterms:identifier>"
    "<dcterms:title>Wet van 23 september 2026, houdende Jaarverslag en slotwet van"
    " het Ministerie van Sociale Zaken en Werkgelegenheid (XV) 2025</dcterms:title>"
    "<dcterms:language>nl</dcterms:language>"
    '<dcterms:type scheme="OVERHEIDop.Staatsblad">Wet</dcterms:type>'
    '<dcterms:creator scheme="OVERHEID.Ministerie">Ministerie van Sociale Zaken en'
    " Werkgelegenheid</dcterms:creator>"
    "<dcterms:modified>2026-10-01</dcterms:modified></overheidwetgeving:owmskern>"
    "<overheidwetgeving:owmsmantel><dcterms:available>2026-10-01</dcterms:available>"
    '<dcterms:subject scheme="OVERHEID.TaxonomieBeleidsagenda">Bestuur |'
    " Rijksoverheid</dcterms:subject>"
    '<dcterms:subject scheme="OVERHEID.TaxonomieBeleidsagenda">Financiën |'
    " Begroting</dcterms:subject>"
    '<dcterms:publisher scheme="OVERHEID.Ministerie">Ministerie van Justitie en'
    " Veiligheid</dcterms:publisher></overheidwetgeving:owmsmantel>"
    "<overheidwetgeving:tpmeta>"
    '<overheidwetgeving:organisatietype scheme="OVERHEID.Organisatietype">'
    "ministerie</overheidwetgeving:organisatietype>"
    "<overheidwetgeving:publicatienaam>Staatsblad</overheidwetgeving:publicatienaam>"
    "<cd:datumTijdstipWijzigingWork>2026-10-01T09:19:54.2335702+02:00"
    "</cd:datumTijdstipWijzigingWork></overheidwetgeving:tpmeta>"
    "</overheidwetgeving:meta></gzd:originalData><gzd:enrichedData>"
    f"<gzd:preferredUrl>{_ZOEK}/stb-2026-296.html</gzd:preferredUrl>"
    f'<gzd:itemUrl manifestation="pdf">{_REPO}/stb/2026/stb-2026-296/1/pdf/'
    "stb-2026-296.pdf</gzd:itemUrl>"
    f'<gzd:itemUrl manifestation="xml">{_REPO}/stb/2026/stb-2026-296/1/xml/'
    "stb-2026-296.xml</gzd:itemUrl>"
    "</gzd:enrichedData></gzd:gzd></sru:recordData>"
    "<sru:recordPosition>2</sru:recordPosition></sru:record>"
)


def _antwoord(*records: str, volgende: int | None = None, extra: str = "") -> bytes:
    aantal = f"<sru:numberOfRecords>{len(records)}</sru:numberOfRecords>"
    lijst = f"<sru:records>{''.join(records)}</sru:records>" if records else ""
    verder = (
        f"<sru:nextRecordPosition>{volgende}</sru:nextRecordPosition>"
        if volgende
        else ""
    )
    return (
        f"{_KOP}{aantal}{lijst}{verder}{extra}</sru:searchRetrieveResponse>"
    ).encode()


# Een weggelaten filter: HTTP 200, records erbij, en de diagnostic achteraan.
DIAGNOSTIC_NAAST_RECORDS = _antwoord(
    STCRT,
    extra=(
        "<sru:diagnostics><diag:diagnostic>"
        "<diag:uri>info:srw/diagnostic/1/10</diag:uri>"
        "<diag:details>[:2026-10-16T09:00:00] is not a valid range constraint "
        "against type date</diag:details>"
        "<diag:message>SEARCH-IGNOREDQTEXT</diag:message>"
        "</diag:diagnostic></sru:diagnostics>"
    ),
)

# Een syntaxfout: een kale `diagnostics` in de standaardnamespace.
DIAGNOSTIC_ZONDER_PREFIX = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<searchRetrieveResponse xmlns="http://docs.oasis-open.org/ns/search-ws/sruResponse"'
    b' xmlns:ns3="http://docs.oasis-open.org/ns/search-ws/diagnostic">'
    b"<version>2.0</version><diagnostics><ns3:diagnostic>"
    b"<ns3:uri>info:srw/diagnostic/1/10</ns3:uri>"
    b"<ns3:message>line 1:51 mismatched input '02:00'</ns3:message>"
    b"</ns3:diagnostic></diagnostics></searchRetrieveResponse>"
)


def _bekendmaking(**kw) -> Bekendmaking:
    standaard = {
        "identifier": "stcrt-2026-1",
        "titel": "Regeling van de minister",
        "samenvatting": "",
        "publicatie": "Staatscourant",
        "rubriek": "algemeen verbindend voorschrift (ministeriële regeling)",
        "creator": "Ministerie van Binnenlandse Zaken en Koninkrijksrelaties",
        "organisatietype": "ministerie",
        "beschikbaar": None,
        "gewijzigd": datetime(2026, 10, 16, 7, 10, tzinfo=UTC),
        "url": "https://zoek.officielebekendmakingen.nl/stcrt-2026-1.html",
    }
    standaard.update(kw)
    return Bekendmaking(**standaard)


class TestParseAntwoord:
    def test_leest_een_staatscourant_record(self):
        records, volgende = parse_antwoord(_antwoord(STCRT))
        assert volgende is None
        b = records[0]
        assert b.identifier == "stcrt-2026-35556"
        assert b.publicatie == "Staatscourant"
        assert b.rubriek == "omgevingsmelding"
        assert b.creator == "Rijkswaterstaat"
        assert b.organisatietype == "dienst en agentschap"
        assert b.samenvatting == "Omgevingsmelding Air Products Nederland B.V."
        assert b.beschikbaar.isoformat() == "2026-10-07"
        assert b.url == "https://zoek.officielebekendmakingen.nl/stcrt-2026-35556.html"
        assert b.pdf_url.endswith("/pdf/stcrt-2026-35556.pdf")
        assert b.xml_url.endswith("/xml/stcrt-2026-35556.xml")
        assert b.onderwerpen == ["Ruimte en infrastructuur | Organisatie en beleid"]

    def test_wijzigingsmoment_met_zeven_decimalen_en_tijdzone(self):
        """De API levert 7 cijfers achter de komma; Python er 6."""
        b = parse_antwoord(_antwoord(STCRT))[0][0]
        assert b.gewijzigd.tzinfo is not None
        assert b.gewijzigd.astimezone(UTC) == datetime(
            2026, 10, 7, 7, 16, 21, 92326, tzinfo=UTC
        )

    def test_leest_een_staatsblad_record(self):
        """Geen samenvatting, wel meerdere onderwerpen."""
        b = parse_antwoord(_antwoord(STB))[0][0]
        assert b.publicatie == "Staatsblad"
        assert b.rubriek == "Wet"
        assert b.creator == "Ministerie van Sociale Zaken en Werkgelegenheid"
        assert b.samenvatting == ""
        assert len(b.onderwerpen) == 2

    def test_de_uitgever_is_niet_de_beslisser(self):
        """`dcterms:publisher` is voor het Staatsblad altijd JenV."""
        b = parse_antwoord(_antwoord(STB))[0][0]
        assert "Justitie" not in b.creator

    def test_volgende_positie(self):
        _, volgende = parse_antwoord(_antwoord(STCRT, volgende=201))
        assert volgende == 201

    def test_diagnostic_naast_records_is_mislukt(self):
        """De filter is weggelaten; de records horen niet bij onze vraag."""
        assert parse_antwoord(DIAGNOSTIC_NAAST_RECORDS) is None

    def test_diagnostic_zonder_prefix_is_mislukt(self):
        assert parse_antwoord(DIAGNOSTIC_ZONDER_PREFIX) is None

    def test_onzin_is_mislukt(self):
        assert parse_antwoord(b"dit is geen xml") is None

    def test_leeg_antwoord_is_gelukt(self):
        assert parse_antwoord(_antwoord()) == ([], None)

    def test_record_zonder_wijzigingsmoment_valt_af(self):
        zonder = STCRT.replace(
            "<cd:datumTijdstipWijzigingWork>2026-10-07T09:16:21.0923262+02:00"
            "</cd:datumTijdstipWijzigingWork>",
            "",
        )
        assert parse_antwoord(_antwoord(zonder)) == ([], None)


class TestZoekvraag:
    def test_tijd_in_utc_met_terugkijken(self):
        vraag = zoekvraag(datetime(2026, 10, 16, 8, 0, tzinfo=UTC))
        assert "cd.datumTijdstipWijzigingWork>=2026-10-16T07:00:00Z" in vraag

    def test_ondergrens_op_de_publicatiedatum(self):
        """Een bijgewerkt record van vorige maand komt niet terug als nieuw."""
        vraag = zoekvraag(datetime(2026, 10, 16, 8, 0, tzinfo=UTC))
        assert "dt.available>=2026-10-15" in vraag
        # Een datum en geen datetime: dat laatste laat de API de filter
        # weggooien.
        assert "dt.available>=2026-10-15T" not in vraag

    def test_alleen_de_drie_bladen(self):
        vraag = zoekvraag(datetime(2026, 10, 16, 8, 0, tzinfo=UTC))
        for blad in ("Staatscourant", "Staatsblad", "Tractatenblad"):
            assert f"w.publicatienaam=={blad}" in vraag
        assert "Gemeenteblad" not in vraag

    def test_gesorteerd_via_cql(self):
        """`sortKeys` wordt stil genegeerd."""
        vraag = zoekvraag(datetime(2026, 10, 16, 8, 0, tzinfo=UTC))
        assert vraag.endswith("sortBy cd.datumTijdstipWijzigingWork/sort.ascending")


class TestPersoonsgebonden:
    def test_regeling_van_een_ministerie_blijft(self):
        assert not is_persoonsgebonden(_bekendmaking())

    def test_elke_persoonsgebonden_rubriek(self):
        for rubriek in (
            "deurwaardersexploot of betekening Belastingdienst",
            "faillissement, surseance van betaling of schuldsanering",
            "gerechtelijke oproeping belanghebbenden",
            "ondercuratelestelling of handlichting",
            "echtscheiding of ontbinding",
            "ongewenstverklaring vreemdeling",
            "tuchtrechtelijke uitspraak",
            "koninklijke onderscheiding",
            "register streekproducten",
            "accountantsregister",
            "handelsregister",
            "register beroepsbeoefenaren individuele gezondheidszorg",
        ):
            assert is_persoonsgebonden(
                _bekendmaking(rubriek=rubriek, organisatietype="zbo")
            ), rubriek

    def test_hoofdletters_en_witruimte_maken_niet_uit(self):
        assert is_persoonsgebonden(_bekendmaking(rubriek="  Handelsregister "))

    def test_rechterlijke_macht(self):
        assert is_persoonsgebonden(
            _bekendmaking(
                rubriek="ander besluit van algemene strekking",
                organisatietype="rechterlijke macht",
            )
        )

    def test_overige_informatie_van_beroepsorganisatie(self):
        """411 van de 448 in deze rubriek: exploten van deurwaarders."""
        assert is_persoonsgebonden(
            _bekendmaking(
                rubriek="overige overheidsinformatie",
                organisatietype="openbaar lichaam voor bedrijf en beroep",
            )
        )

    def test_overige_informatie_van_een_ministerie_blijft(self):
        assert not is_persoonsgebonden(
            _bekendmaking(
                rubriek="overige overheidsinformatie", organisatietype="ministerie"
            )
        )

    def test_titel_openbaar_exploot(self):
        assert is_persoonsgebonden(
            _bekendmaking(rubriek="", titel="Openbaar exploot X tegen Y")
        )

    def test_titel_gerechtelijke_aankondiging(self):
        assert is_persoonsgebonden(
            _bekendmaking(
                rubriek="", titel="Gerechtelijke aankondiging | overige aankondiging"
            )
        )


class TestCategorie:
    def test_staatsblad_en_tractatenblad_zijn_regelgeving(self):
        assert categorie_van_bekendmaking("Staatsblad", "Wet") == CAT_REGELGEVING
        assert (
            categorie_van_bekendmaking("Staatsblad", "Klein Koninklijk Besluit")
            == CAT_REGELGEVING
        )
        assert categorie_van_bekendmaking("Tractatenblad", "Verdrag") == (
            CAT_REGELGEVING
        )

    def test_regelgevende_rubrieken_van_de_staatscourant(self):
        for rubriek in (
            "algemeen verbindend voorschrift (ministeriële regeling)",
            "beleidsregel",
            "ander besluit van algemene strekking",
            "delegatie- of mandaatbesluit",
            "interne regeling",
            "algemeenverbindendverklaring van cao-bepalingen",
            "advies Raad van State",
        ):
            assert (
                categorie_van_bekendmaking("Staatscourant", rubriek) == CAT_REGELGEVING
            ), rubriek

    def test_de_rest_is_een_bekendmaking(self):
        for rubriek in ("omgevingsvergunning", "benoeming of ontslag", "", None):
            assert (
                categorie_van_bekendmaking("Staatscourant", rubriek) == CAT_BEKENDMAKING
            ), rubriek

    def test_blad_zonder_hoofdletter(self):
        assert categorie_van_bekendmaking(" staatsblad ", None) == CAT_REGELGEVING


class TestDocumenttekst:
    STB_XML = (
        # Het Staatsblad begint met een BOM.
        "\ufeff"
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<officiele-publicatie xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:noNamespaceSchemaLocation="http://technische-documentatie.oep.overheid.nl'
        '/x.xsd">'
        '<metadata><meta name="OVERHEIDop.externMetadataRecord" content="x" />'
        "</metadata>"
        "<kop><titel>Staatsblad</titel><subtitel>van het Koninkrijk der Nederlanden"
        "</subtitel></kop>"
        "<staatsblad><intitule>Wet van 23 september 2026</intitule>"
        "<wet-besluit><wettekst><?xpp qa?><artikel><kop><label>Artikel</label>"
        "<nr>1</nr></kop><al>De Nederlandse Digitale Dienst wordt opgericht.</al>"
        "</artikel></wettekst></wet-besluit></staatsblad></officiele-publicatie>"
    ).encode()

    def test_leest_de_tekst_met_bom(self):
        tekst = documenttekst(self.STB_XML)
        assert "Nederlandse Digitale Dienst wordt opgericht" in tekst
        assert "Wet van 23 september 2026" in tekst

    def test_de_kop_van_het_blad_gaat_eruit(self):
        """Die staat in elk stuk en zegt niets over dit stuk."""
        tekst = documenttekst(self.STB_XML)
        assert "Koninkrijk der Nederlanden" not in tekst
        # De kop van een artikel blijft wel staan.
        assert "Artikel 1" in tekst

    def test_lengtegrens(self):
        lang = (
            "<officiele-publicatie><al>" + "woord " * 100_000 + "</al>"
            "</officiele-publicatie>"
        ).encode()
        assert len(documenttekst(lang)) == MAX_TEKST_TEKENS

    def test_een_term_ver_achterin_blijft_vindbaar(self):
        """Zoals de Nederlandse vertaling in trb-2026-115, vanaf teken 278.288."""
        verdrag = (
            "<officiele-publicatie><al>" + "treaty text " * 25_000 + "</al>"
            "<al>Het Koninkrijk der Nederlanden en de Digitale Dienst</al>"
            "</officiele-publicatie>"
        ).encode()
        assert "Digitale Dienst" in documenttekst(verdrag)

    def test_onzin_is_leeg(self):
        assert documenttekst(b"<niet af") == ""
        assert documenttekst(b"") == ""

    def test_entiteiten_worden_niet_uitgevouwen(self):
        """Externe XML, dus defusedxml: een entity-bom geeft niets."""
        bom = (
            b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">'
            b'<!ENTITY b "&a;&a;&a;">]><x>&b;</x>'
        )
        assert documenttekst(bom) == ""


def _client_met(handler) -> BekendmakingenClient:
    client = BekendmakingenClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.fixture(autouse=True)
def _geen_pauze(monkeypatch):
    """De pauze tussen verzoeken is voor de echte repository."""
    monkeypatch.setattr(mod, "PAUZE_TUSSEN_VERZOEKEN", 0.0)


class TestZoekSinds:
    WATERMERK = datetime(2026, 10, 16, 7, 0, tzinfo=UTC)

    async def test_bladert_tot_het_einde(self):
        starts = []

        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params["startRecord"])
            starts.append(start)
            if start == 1:
                return httpx.Response(200, content=_antwoord(STB, volgende=201))
            return httpx.Response(200, content=_antwoord(STCRT))

        client = _client_met(handler)
        gevonden = await client.zoek_sinds(self.WATERMERK, max_paginas=5)

        assert [b.identifier for b in gevonden] == ["stb-2026-296", "stcrt-2026-35556"]
        assert starts == [1, 201]
        assert client.volledig is True

    async def test_stuurt_de_vraag_en_de_paginagrootte_mee(self):
        gezien = {}

        def handler(request: httpx.Request) -> httpx.Response:
            gezien.update(request.url.params)
            return httpx.Response(200, content=_antwoord())

        await _client_met(handler).zoek_sinds(self.WATERMERK, max_paginas=1)

        assert gezien["x-connection"] == "officielepublicaties"
        assert gezien["maximumRecords"] == str(mod.PAGINA_GROOTTE)
        assert int(gezien["maximumRecords"]) <= 1000
        assert gezien["query"] == zoekvraag(self.WATERMERK)

    async def test_een_lege_pagina_is_het_einde(self):
        """Ook als de API er toch een volgende positie bij zet."""
        starts = []

        def handler(request: httpx.Request) -> httpx.Response:
            starts.append(int(request.url.params["startRecord"]))
            return httpx.Response(200, content=_antwoord(volgende=201))

        client = _client_met(handler)
        assert await client.zoek_sinds(self.WATERMERK, max_paginas=5) == []
        assert starts == [1]
        assert client.volledig is True

    async def test_paginagrens_is_niet_volledig(self):
        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params["startRecord"])
            return httpx.Response(200, content=_antwoord(STB, volgende=start + 200))

        client = _client_met(handler)
        gevonden = await client.zoek_sinds(self.WATERMERK, max_paginas=2)

        assert len(gevonden) == 2
        assert client.volledig is False

    async def test_diagnostic_levert_niets_en_is_niet_volledig(self):
        client = _client_met(
            lambda r: httpx.Response(200, content=DIAGNOSTIC_NAAST_RECORDS)
        )
        assert await client.zoek_sinds(self.WATERMERK, max_paginas=5) == []
        assert client.volledig is False

    async def test_fout_halverwege_houdt_wat_er_al_was(self):
        """Gesorteerd oud naar nieuw, dus dat deel is bruikbaar."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params["startRecord"] == "1":
                return httpx.Response(200, content=_antwoord(STB, volgende=201))
            return httpx.Response(503)

        client = _client_met(handler)
        gevonden = await client.zoek_sinds(self.WATERMERK, max_paginas=5)

        assert [b.identifier for b in gevonden] == ["stb-2026-296"]
        assert client.volledig is False

    async def test_onbereikbaar_is_leeg(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("weg")

        client = _client_met(handler)
        assert await client.zoek_sinds(self.WATERMERK, max_paginas=5) == []
        assert client.volledig is False

    async def test_te_groot_antwoord_is_leeg(self, monkeypatch):
        monkeypatch.setattr(mod, "MAX_ANTWOORD_BYTES", 100)
        client = _client_met(lambda r: httpx.Response(200, content=_antwoord(STCRT)))
        assert await client.zoek_sinds(self.WATERMERK, max_paginas=5) == []
        assert client.volledig is False


class TestHaalTekst:
    async def test_haalt_en_strip_de_xml(self):
        client = _client_met(
            lambda r: httpx.Response(200, content=TestDocumenttekst.STB_XML)
        )
        tekst = await client.haal_tekst("https://repository.overheid.nl/x.xml")
        assert "Nederlandse Digitale Dienst" in tekst

    async def test_404_is_leeg(self):
        """Komt niet goed: dan wordt er gezocht in titel en samenvatting."""
        client = _client_met(lambda r: httpx.Response(404))
        assert await client.haal_tekst("https://repository.overheid.nl/x.xml") == ""

    async def test_geen_xml_is_leeg(self):
        client = _client_met(lambda r: httpx.Response(200, content=b"<html"))
        assert await client.haal_tekst("https://repository.overheid.nl/x.xml") == ""

    async def test_tijdelijke_fout_is_none(self):
        """Gemeten: nginx geeft 429 zonder Retry-After. Later opnieuw."""
        for status in (429, 500, 503):
            client = _client_met(lambda r, s=status: httpx.Response(s))
            assert (
                await client.haal_tekst("https://repository.overheid.nl/x.xml") is None
            ), status

    async def test_onbereikbaar_is_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("traag")

        client = _client_met(handler)
        assert await client.haal_tekst("https://repository.overheid.nl/x.xml") is None

    async def test_zonder_url_geen_verzoek(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("geen verzoek verwacht")

        assert await _client_met(handler).haal_tekst("") == ""

    async def test_alleen_van_de_repository(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("geen verzoek verwacht")

        client = _client_met(handler)
        assert await client.haal_tekst("http://169.254.169.254/latest/x.xml") == ""
        assert await client.haal_tekst("http://repository.overheid.nl/x.xml") == ""
        assert (
            await client.haal_tekst("https://repository.overheid.nl.evil.example/x")
            == ""
        )

    async def test_een_omleiding_naar_elders_telt_niet(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "repository.overheid.nl":
                return httpx.Response(
                    302, headers={"Location": "http://intern.local/x.xml"}
                )
            return httpx.Response(200, content=b"<al>geheim</al>")

        client = BekendmakingenClient()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        )
        assert await client.haal_tekst("https://repository.overheid.nl/x.xml") == ""


class TestPauze:
    async def test_wacht_tussen_verzoeken(self, monkeypatch):
        """Zonder pauze gaf de repository na 22 verzoeken een 429."""
        monkeypatch.setattr(mod, "PAUZE_TUSSEN_VERZOEKEN", 0.1)
        momenten: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            momenten.append(time.monotonic())
            return httpx.Response(404)

        client = _client_met(handler)
        for _ in range(3):
            await client.haal_tekst("https://repository.overheid.nl/x.xml")

        tussen = [b - a for a, b in zip(momenten, momenten[1:], strict=False)]
        assert all(t >= 0.09 for t in tussen), tussen

    async def test_eerste_verzoek_wacht_niet(self, monkeypatch):
        monkeypatch.setattr(mod, "PAUZE_TUSSEN_VERZOEKEN", 5.0)
        client = _client_met(lambda r: httpx.Response(404))
        begin = time.monotonic()
        await client.haal_tekst("https://repository.overheid.nl/x.xml")
        assert time.monotonic() - begin < 1.0
