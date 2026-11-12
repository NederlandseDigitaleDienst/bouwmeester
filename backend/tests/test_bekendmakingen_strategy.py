"""Tests voor het matchen van zoektermen tegen officiële bekendmakingen.

Het watermerk is hier de plek waar het mis kan gaan zonder dat iemand het
merkt. Drie gevallen die elk een stuk zouden laten verdwijnen:

- Een ronde die op de limiet stopt, mag het watermerk niet voorbij de
  stukken zetten die hij liet liggen.
- Een vraag die mislukt (een diagnostic, een time-out), mag het watermerk
  niet verzetten.
- Een record verschijnt pas minuten na zijn wijzigingsmoment in de index;
  daarom kijkt de vraag terug, en daarom moet wat al bekeken is niet nog
  eens worden opgehaald.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from bouwmeester.services.bekendmakingen_client import (
    Bekendmaking,
    BekendmakingenClient,
)
from bouwmeester.services.import_strategies import bekendmakingen as mod
from bouwmeester.services.import_strategies.bekendmakingen import (
    BekendmakingenStrategy,
)
from bouwmeester.services.kamerstuk_soort import CAT_BEKENDMAKING, CAT_REGELGEVING

# Ten opzichte van nu en niet een vaste datum: de strategie kijkt niet
# verder terug dan `MAX_ACHTERSTAND`, en een vaste datum valt daar over een
# week buiten.
T0 = (datetime.now(UTC) - timedelta(days=1)).replace(second=0, microsecond=0)


def _abo(term: str, actief: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        term=term,
        term_genormaliseerd=term.lower(),
        actief=actief,
        zoekopdracht=lambda: f'"{term}"',
    )


def _b(nummer: int, titel: str = "Regeling", minuten: int = 0, **kw) -> Bekendmaking:
    standaard = {
        "identifier": f"stcrt-2026-{nummer}",
        "titel": titel,
        "samenvatting": "",
        "publicatie": "Staatscourant",
        "rubriek": "algemeen verbindend voorschrift (ministeriële regeling)",
        "creator": "Ministerie van Binnenlandse Zaken en Koninkrijksrelaties",
        "organisatietype": "ministerie",
        "beschikbaar": T0.date(),
        "gewijzigd": T0 + timedelta(minutes=minuten),
        "url": f"https://zoek.officielebekendmakingen.nl/stcrt-2026-{nummer}.html",
        "pdf_url": f"https://repository.overheid.nl/stcrt-2026-{nummer}.pdf",
        "xml_url": f"https://repository.overheid.nl/stcrt-2026-{nummer}.xml",
    }
    standaard.update(kw)
    return Bekendmaking(**standaard)


class _VasteClient(BekendmakingenClient):
    """Levert een vaste lijst in plaats van de echte API."""

    def __init__(
        self,
        records,
        *,
        volledig: bool = True,
        tekst: str = "",
        tijdelijk_mis: set[str] | None = None,
    ):
        super().__init__()
        self._records = records
        self._volledig = volledig
        self._tekst = tekst
        # xml-urls die een 429 of 5xx geven.
        self._tijdelijk_mis = tijdelijk_mis or set()
        self.vragen: list[datetime] = []
        self.opgehaald: list[str] = []

    async def zoek_sinds(self, watermerk, max_paginas):
        self.vragen.append(watermerk)
        self.volledig = self._volledig
        return list(self._records)

    async def haal_tekst(self, xml_url: str) -> str | None:
        self.opgehaald.append(xml_url)
        if xml_url in self._tijdelijk_mis:
            return None
        return self._tekst


@pytest.fixture(autouse=True)
def _schoon_watermerk():
    mod.reset_watermerk()
    yield
    mod.reset_watermerk()


def _strategie(*abonnementen) -> BekendmakingenStrategy:
    s = BekendmakingenStrategy()
    s.abonnementen = list(abonnementen)
    return s


class TestEersteRonde:
    async def test_importeert_niets_en_vraagt_niets(self):
        """Anders opent de feature met weken aan bekendmakingen."""
        client = _VasteClient([_b(1, "NLDD")])
        items = await _strategie(_abo("NLDD")).fetch_items(client, None, 50)

        assert items == []
        assert client.vragen == []
        assert client.opgehaald == []

    async def test_zet_wel_het_watermerk(self):
        voor = datetime.now(UTC)
        await _strategie(_abo("NLDD")).fetch_items(_VasteClient([]), None, 50)
        assert mod.huidig_watermerk() >= voor

    async def test_zonder_abonnementen_niets(self):
        assert await _strategie().fetch_items(_VasteClient([]), None, 50) == []
        assert mod.huidig_watermerk() is None


class TestMatchen:
    @pytest.fixture(autouse=True)
    def _al_een_ronde_gedraaid(self):
        mod.herstel_watermerk(T0 - timedelta(minutes=5))

    async def test_term_in_de_titel(self):
        items = await _strategie(_abo("Digitale Dienst")).fetch_items(
            _VasteClient([_b(1, "Instellingsbesluit Nederlandse Digitale Dienst")]),
            None,
            50,
        )
        assert [i.zaak_id for i in items] == ["stcrt-2026-1"]

    async def test_term_alleen_in_de_volledige_tekst(self):
        """Een titel als "Wet van ..., houdende ..." noemt het programma niet."""
        client = _VasteClient(
            [_b(1, "Wet van 23 september 2026, houdende wijziging")],
            tekst="Artikel 1. De Nederlandse Digitale Dienst wordt opgericht.",
        )
        items = await _strategie(_abo("Nederlandse Digitale Dienst")).fetch_items(
            client, None, 50
        )
        assert len(items) == 1
        assert client.opgehaald == ["https://repository.overheid.nl/stcrt-2026-1.xml"]
        assert "wordt opgericht" in items[0].document_tekst

    async def test_zonder_treffer_geen_item(self):
        items = await _strategie(_abo("RegelRecht")).fetch_items(
            _VasteClient([_b(1, "Omgevingsvergunning")]), None, 50
        )
        assert items == []

    async def test_gepauzeerde_term_telt_niet(self):
        items = await _strategie(_abo("NLDD", actief=False)).fetch_items(
            _VasteClient([_b(1, "NLDD")]), None, 50
        )
        assert items == []

    async def test_treffers_worden_vastgelegd(self):
        abo = _abo("NLDD")
        s = _strategie(abo)
        await s.fetch_items(_VasteClient([_b(1, "NLDD")]), None, 50)
        assert s.treffers == {"stcrt-2026-1": [abo.id]}

    async def _raakt(self, term: str, tekst: str) -> bool:
        client = _VasteClient([_b(1, "Wet van 14 oktober 2026")], tekst=tekst)
        return bool(await _strategie(_abo(term)).fetch_items(client, None, 50))

    @pytest.mark.parametrize(
        ("term", "tekst"),
        [
            # Gemeten op 17 oktober 2026 in echte bekendmakingen; geen van
            # deze stukken gaat over de term.
            ("GDI", "de Beginselenwet justitiële jeugdinrichtingen"),
            ("GDI", "de aspirant-crowdfundingdienstverlener"),
            ("GDI", "het belastingdienstbestand"),
            ("GDI", "beschermde zoogdieren"),
            ("AI", "per e-mail aan de secretaris"),
            ("AI", "Schiphol Airport"),
            ("Woo", "woonachtig te Utrecht"),
            ("Woo", "de verantwoordelijke minister"),
            ("API", "op papier ingediend"),
        ],
    )
    async def test_een_korte_term_in_een_ander_woord_telt_niet(self, term, tekst):
        assert not await self._raakt(term, tekst)

    @pytest.mark.parametrize(
        "tekst",
        [
            "De GDI wordt uitgebreid.",
            "de GDI-voorzieningen",
            "Generieke Digitale Infrastructuur (GDI).",
            "gdi",
        ],
    )
    async def test_een_korte_term_als_heel_woord_telt(self, tekst):
        assert await self._raakt("GDI", tekst)

    @pytest.mark.parametrize(
        ("term", "tekst"),
        [
            # Ook gemeten: samenstellingen en meervouden die met alleen
            # hele woorden gemist werden.
            ("algoritme", "het gebruik van algoritmes door de overheid"),
            ("cloud", "het cloudbeleid van het Rijk"),
            ("cloud", "de soevereine overheidscloud"),
            ("informatiebeveiliging", "het informatiebeveiligingsbeleid"),
            ("digitale overheid", "qua digitale overheidsinformatie"),
        ],
    )
    async def test_een_langere_term_telt_ook_in_een_samenstelling(self, term, tekst):
        assert await self._raakt(term, tekst)

    async def test_persoonsgebonden_wordt_niet_opgehaald_of_gematcht(self):
        """Een faillissement met de term erin komt nergens terecht."""
        faillissement = _b(
            1,
            "Faillissement NLDD Consultancy B.V.",
            rubriek="faillissement, surseance van betaling of schuldsanering",
            organisatietype="rechterlijke macht",
        )
        client = _VasteClient([faillissement], tekst="NLDD")
        s = _strategie(_abo("NLDD"))
        items = await s.fetch_items(client, None, 50)

        assert items == []
        assert client.opgehaald == []
        assert s.treffers == {}


class TestVorm:
    @pytest.fixture(autouse=True)
    def _al_een_ronde_gedraaid(self):
        mod.herstel_watermerk(T0 - timedelta(minutes=5))

    async def _een(self, b: Bekendmaking):
        items = await _strategie(_abo("NLDD")).fetch_items(_VasteClient([b]), None, 50)
        return items[0]

    async def test_regeling_van_een_ministerie(self):
        item = await self._een(
            _b(1, "Regeling NLDD", samenvatting="Over de NLDD.", minuten=1)
        )
        assert item.zaak_id == item.zaak_nummer == "stcrt-2026-1"
        assert item.onderwerp == "Over de NLDD."
        assert item.datum == T0.date()
        assert item.document_url.endswith("stcrt-2026-1.html")
        assert item.bron == "Staatscourant"
        assert item.ministerie == (
            "Ministerie van Binnenlandse Zaken en Koninkrijksrelaties"
        )
        extra = item.extra_data
        assert extra["categorie"] == CAT_REGELGEVING
        # De categorie uit de echte rubriek, de kop met een leesbare.
        assert extra["soort"] == "Ministeriële regeling"
        assert extra["publicatie"] == "Staatscourant"
        assert extra["herkomst_label"] == (
            "Staatscourant, Ministerie van Binnenlandse Zaken en Koninkrijksrelaties"
        )
        assert extra["raw_url"].endswith("stcrt-2026-1.pdf")

    async def test_de_zoektermen_waarop_het_binnenkwam(self):
        """Om een stuk dat op het model wacht later opnieuw te koppelen."""
        strategie = _strategie(_abo("NLDD"), _abo("nldd"), _abo("algoritme"))
        (item,) = await strategie.fetch_items(
            _VasteClient([_b(1, "Regeling NLDD", minuten=1)]), None, 50
        )
        # Twee initiatieven met dezelfde term: die term één keer.
        assert item.extra_data["matched_terms"] == ['"NLDD"', '"nldd"']

    async def test_besluit_van_een_dienst(self):
        item = await self._een(
            _b(
                2,
                "Autorisatiebesluit NLDD",
                rubriek="autorisatiebesluit basisregistratie personen",
                creator="Rijksdienst voor Identiteitsgegevens",
                organisatietype="dienst en agentschap",
            )
        )
        # Geen samenvatting: dan is de titel het onderwerp.
        assert item.onderwerp == "Autorisatiebesluit NLDD"
        assert item.ministerie is None
        assert item.extra_data["categorie"] == CAT_BEKENDMAKING
        assert item.extra_data["herkomst_label"] == (
            "Staatscourant, Rijksdienst voor Identiteitsgegevens"
        )

    async def test_geen_herkomst_sleutel(self):
        """`herkomst` draagt bij tkconv de bron en stuurt dus niets aan."""
        item = await self._een(_b(1, "NLDD"))
        assert "herkomst" not in item.extra_data

    def test_taak_en_melding_in_het_nederlands(self):
        s = BekendmakingenStrategy()
        item = SimpleNamespace(titel="Regeling NLDD", onderwerp="x")
        assert s.task_title(item) == "Beoordeel bekendmaking: Regeling NLDD"
        assert s.notification_title("Regeling NLDD").startswith("Nieuwe bekendmaking")
        assert s.context_hint() == "bekendmaking"


class TestWatermerk:
    @pytest.fixture(autouse=True)
    def _al_een_ronde_gedraaid(self):
        mod.herstel_watermerk(T0)

    async def test_volledige_ronde_zet_het_op_het_moment_van_de_vraag(self):
        voor = datetime.now(UTC)
        await _strategie(_abo("NLDD")).fetch_items(
            _VasteClient([_b(1, "x", minuten=3)]), None, 50
        )
        assert mod.huidig_watermerk() >= voor

    async def test_lege_volledige_ronde_schuift_ook_op(self):
        """Anders kijkt elke ronde in het weekend naar de batch van vrijdag."""
        voor = datetime.now(UTC)
        await _strategie(_abo("NLDD")).fetch_items(_VasteClient([]), None, 50)
        assert mod.huidig_watermerk() >= voor

    async def test_mislukte_vraag_laat_het_staan(self):
        """Een diagnostic of time-out: `[]` en niet volledig."""
        await _strategie(_abo("NLDD")).fetch_items(
            _VasteClient([], volledig=False), None, 50
        )
        assert mod.huidig_watermerk() == T0

    async def test_paginagrens_niet_verder_dan_het_laatste_record(self):
        records = [_b(1, "x", minuten=1), _b(2, "y", minuten=2)]
        await _strategie(_abo("NLDD")).fetch_items(
            _VasteClient(records, volledig=False), None, 50
        )
        assert mod.huidig_watermerk() == T0 + timedelta(minutes=2)

    async def test_record_uit_de_toekomst_zet_het_niet_voorbij_nu(self):
        """Het wijzigingsmoment komt uit het record; een datum in de
        toekomst zou alles tot dan overslaan."""
        toekomst = _b(1, "x", gewijzigd=datetime.now(UTC) + timedelta(days=30))
        await _strategie(_abo("NLDD")).fetch_items(
            _VasteClient([toekomst], volledig=False), None, 50
        )
        assert T0 < mod.huidig_watermerk() <= datetime.now(UTC)

    def test_herstel_niet_voorbij_nu(self):
        """Wat bewaard was, kan net zo goed uit zo'n record komen."""
        mod.reset_watermerk()
        mod.herstel_watermerk(datetime.now(UTC) + timedelta(days=30))
        assert mod.huidig_watermerk() <= datetime.now(UTC)

    async def test_limiet_laat_de_rest_voor_de_volgende_ronde(self):
        """Het watermerk mag niet voorbij wat de limiet liet liggen."""
        abo = _abo("NLDD")
        records = [_b(n, f"NLDD {n}", minuten=n) for n in range(1, 6)]

        eerste = await _strategie(abo).fetch_items(_VasteClient(records), None, 2)
        assert [i.zaak_id for i in eerste] == ["stcrt-2026-1", "stcrt-2026-2"]
        assert mod.huidig_watermerk() == T0 + timedelta(minutes=2)

        # De volgende vraag kijkt terug en krijgt alles weer; wat al bekeken
        # is wordt overgeslagen, de rest komt alsnog.
        client = _VasteClient(records)
        tweede = await _strategie(abo).fetch_items(client, None, 50)
        assert [i.zaak_id for i in tweede] == [
            "stcrt-2026-3",
            "stcrt-2026-4",
            "stcrt-2026-5",
        ]
        assert len(client.opgehaald) == 3

    async def test_limiet_bij_gelijke_tijdstippen(self):
        """Twee records met hetzelfde wijzigingsmoment, de limiet ertussen."""
        abo = _abo("NLDD")
        records = [_b(1, "NLDD een", minuten=1), _b(2, "NLDD twee", minuten=1)]

        eerste = await _strategie(abo).fetch_items(_VasteClient(records), None, 1)
        tweede = await _strategie(abo).fetch_items(_VasteClient(records), None, 50)

        assert [i.zaak_id for i in eerste + tweede] == ["stcrt-2026-1", "stcrt-2026-2"]

    async def test_al_bekeken_wordt_niet_opnieuw_opgehaald(self):
        """De vraag kijkt een uur terug; dat mag geen downloads kosten."""
        # Rond nu: wat ver achter het watermerk ligt, wordt uit de lijst
        # opgeruimd omdat de vraag het niet meer teruggeeft.
        mod.reset_watermerk()
        nu = datetime.now(UTC)
        mod.herstel_watermerk(nu - timedelta(minutes=5))
        records = [_b(1, "Omgevingsvergunning", gewijzigd=nu - timedelta(minutes=1))]
        await _strategie(_abo("NLDD")).fetch_items(_VasteClient(records), None, 50)

        client = _VasteClient(records)
        await _strategie(_abo("NLDD")).fetch_items(client, None, 50)
        assert client.opgehaald == []

    async def test_laat_geindexeerd_record_komt_alsnog(self):
        """Een record dat ouder is dan het watermerk maar pas nu in de index
        staat, valt binnen het terugkijken en telt mee."""
        laat = _b(9, "NLDD laat", minuten=-10)
        items = await _strategie(_abo("NLDD")).fetch_items(
            _VasteClient([laat]), None, 50
        )
        assert [i.zaak_id for i in items] == ["stcrt-2026-9"]

    async def test_herstart_gaat_verder_waar_het_was(self):
        mod.reset_watermerk()
        mod.herstel_watermerk(T0)
        client = _VasteClient([])
        await _strategie(_abo("NLDD")).fetch_items(client, None, 50)
        assert client.vragen == [T0]

    async def test_niet_verder_terug_dan_een_week(self):
        """Zoektermen die weken op pauze stonden: geen berichten van toen."""
        mod.reset_watermerk()
        mod.herstel_watermerk(T0 - timedelta(days=30))
        client = _VasteClient([])
        voor = datetime.now(UTC)
        await _strategie(_abo("NLDD")).fetch_items(client, None, 50)
        assert client.vragen[0] >= voor - mod.MAX_ACHTERSTAND


class TestTijdelijkMis:
    """De repository gaf bij een meting na 22 snelle verzoeken een 429.

    Zonder tekst matchen zou een treffer in de body voorgoed missen, want
    het stuk geldt daarna als bekeken. Dus: stoppen, en de volgende ronde
    verder vanaf dat stuk.
    """

    @pytest.fixture(autouse=True)
    def _al_een_ronde_gedraaid(self):
        mod.herstel_watermerk(T0)

    async def test_stopt_bij_het_stuk_en_houdt_het_watermerk_ervoor(self):
        abo = _abo("NLDD")
        records = [_b(n, f"NLDD {n}", minuten=n) for n in range(1, 4)]
        client = _VasteClient(
            records, tijdelijk_mis={"https://repository.overheid.nl/stcrt-2026-2.xml"}
        )

        items = await _strategie(abo).fetch_items(client, None, 50)

        assert [i.zaak_id for i in items] == ["stcrt-2026-1"]
        assert mod.huidig_watermerk() == T0 + timedelta(minutes=1)
        # Het stuk erna is niet aangeraakt.
        assert "https://repository.overheid.nl/stcrt-2026-3.xml" not in client.opgehaald

    async def test_de_volgende_ronde_gaat_verder(self):
        abo = _abo("NLDD")
        records = [_b(n, f"NLDD {n}", minuten=n) for n in range(1, 4)]
        await _strategie(abo).fetch_items(
            _VasteClient(
                records,
                tijdelijk_mis={"https://repository.overheid.nl/stcrt-2026-2.xml"},
            ),
            None,
            50,
        )

        tweede = await _strategie(abo).fetch_items(_VasteClient(records), None, 50)

        assert [i.zaak_id for i in tweede] == ["stcrt-2026-2", "stcrt-2026-3"]

    async def test_een_hardnekkig_stuk_houdt_de_bron_niet_tegen(self):
        """Na `MAX_POGINGEN` rondes geldt het als zonder tekst."""
        abo = _abo("NLDD")
        records = [_b(1, "NLDD hardnekkig", minuten=1), _b(2, "NLDD", minuten=2)]
        mis = {"https://repository.overheid.nl/stcrt-2026-1.xml"}

        rondes = []
        for _ in range(mod.MAX_POGINGEN):
            rondes.append(
                await _strategie(abo).fetch_items(
                    _VasteClient(records, tijdelijk_mis=mis), None, 50
                )
            )

        assert rondes[:-1] == [[]] * (mod.MAX_POGINGEN - 1)
        # Gematcht op de titel, zonder de body.
        assert [i.zaak_id for i in rondes[-1]] == ["stcrt-2026-1", "stcrt-2026-2"]
        assert mod._POGINGEN == {}

    async def test_persoonsgebonden_stuk_haalt_niets_op_dus_stopt_niet(self):
        records = [
            _b(1, "Faillissement", rubriek="handelsregister", minuten=1),
            _b(2, "NLDD", minuten=2),
        ]
        client = _VasteClient(
            records, tijdelijk_mis={"https://repository.overheid.nl/stcrt-2026-1.xml"}
        )
        items = await _strategie(_abo("NLDD")).fetch_items(client, None, 50)
        assert [i.zaak_id for i in items] == ["stcrt-2026-2"]
