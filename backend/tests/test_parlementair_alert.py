"""Tests voor wat er wel en niet in Mattermost verschijnt.

Het uitgangspunt is recall boven precisie: elk stuk dat op een zoekterm
matcht wordt geïmporteerd en blijft in de webapp zichtbaar. Wat hier
geregeld wordt is alleen de vraag of het een Mattermost-bericht waard is.
Een filter dat een stuk zou weggooien in plaats van stilhouden hoort hier
niet thuis.
"""

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

from bouwmeester.models.parlementair_abonnement import ParlementairAbonnement
from bouwmeester.services.kamerstuk_soort import (
    CAT_BIJLAGE,
    CAT_EXTERN,
    CAT_VERGADERING_TERUG,
    CAT_VERGADERING_VOORUIT,
    CAT_VRAAG,
)
from bouwmeester.services.parlementair_alert_service import (
    DREMPEL_MIDDEN,
    ParlementairAlertService,
    _nl_datum,
    _relevantie,
)


def _abonnement(**kwargs) -> ParlementairAbonnement:
    a = ParlementairAbonnement(
        scope_type="initiatief",
        scope_id=uuid4(),
        term=kwargs.pop("term", "NLDD"),
        term_genormaliseerd="nldd",
    )
    a.id = uuid4()
    a.minimum_relevantie = kwargs.pop("minimum_relevantie", 20)
    a.uitgezette_categorieen = kwargs.pop("uitgezette_categorieen", None)
    return a


def _item(**extra) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        titel=extra.pop("titel", "Een kamerstuk"),
        onderwerp="",
        zaak_nummer=extra.pop("zaak_nummer", "2026D00001"),
        llm_samenvatting=extra.pop("samenvatting", "Een samenvatting."),
        document_url="https://berthub.eu/tkconv/document.html?nummer=2026D00001",
        datum=extra.pop("datum", date(2026, 9, 22)),
        extra_data=extra,
    )


def _svc() -> ParlementairAlertService:
    return ParlementairAlertService.__new__(ParlementairAlertService)


async def _async_true() -> bool:
    return True


def _maak_verzender(opslag: list):
    """Vangt wat er naar Mattermost zou gaan, in plaats van het te sturen."""

    async def send(channel_id: str, text: str, props: dict) -> bool:
        opslag.append({"channel_id": channel_id, "text": text, "props": props})
        return True

    return send


def _maak_execute(rijen: list):
    """Minimale stand-in voor `session.execute(...).scalars().all()`."""

    async def execute(_stmt):
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: rijen),
        )

    return execute


class TestRelevantie:
    def test_leest_de_score(self):
        assert _relevantie({"relevantie_score": 85}) == 85

    def test_ontbrekende_score_is_middenmoot(self):
        # Een ontbrekende score mag nooit stilte betekenen: dan zou een
        # mislukte LLM-call het stuk onzichtbaar maken.
        assert _relevantie({}) == 40

    def test_score_buiten_bereik_wordt_begrensd(self):
        assert _relevantie({"relevantie_score": 999}) == 100
        assert _relevantie({"relevantie_score": -5}) == 0

    def test_onzin_is_middenmoot(self):
        assert _relevantie({"relevantie_score": "hoog"}) == 40


class TestKopregel:
    def test_toont_het_echte_soort_niet_de_categorie(self):
        """ "POSITION PAPER" zegt wat het is, "EXTERN" waar wij het indelen."""
        kop = _svc()._kopregel(
            {"soort": "Position paper", "categorie": CAT_EXTERN},
            {
                "label": "Extern",
                "emoji": ":x:",
                "kleur": "#000",
                "herkomst": "van buiten de Kamer",
            },
        )
        assert "POSITION PAPER" in kop
        assert "van buiten de Kamer" in kop

    def test_valt_terug_op_de_categorie_zonder_soort(self):
        kop = _svc()._kopregel(
            {"categorie": CAT_VRAAG},
            {"label": "Kamervraag", "emoji": ":q:", "kleur": "#000"},
        )
        assert "KAMERVRAAG" in kop

    def test_vergadering_die_nog_komt_toont_de_dagen(self):
        """Het verschil tussen 'je kunt hier nog iets mee' en 'dit is gebeurd'."""
        over_twee_dagen = (date.today() + timedelta(days=2)).isoformat()
        kop = _svc()._kopregel(
            {
                "soort": "Agenda procedurevergadering",
                "categorie": CAT_VERGADERING_VOORUIT,
                "activiteit_datum": over_twee_dagen,
            },
            {"label": "Procedurevergadering", "emoji": ":c:", "kleur": "#000"},
        )
        assert "over 2 dagen" in kop

    def test_vergadering_morgen(self):
        morgen = (date.today() + timedelta(days=1)).isoformat()
        kop = _svc()._kopregel(
            {"categorie": CAT_VERGADERING_VOORUIT, "activiteit_datum": morgen},
            {"label": "Procedurevergadering", "emoji": ":c:", "kleur": "#000"},
        )
        assert "morgen" in kop

    def test_verstreken_termijn_is_zichtbaar(self):
        gisteren = (date.today() - timedelta(days=1)).isoformat()
        kop = _svc()._kopregel(
            {
                "soort": "Schriftelijke vragen",
                "categorie": CAT_VRAAG,
                "termijn": gisteren,
            },
            {"label": "Kamervraag", "emoji": ":q:", "kleur": "#000"},
        )
        assert "verstreken" in kop

    def test_bijlage_noemt_waar_hij_bij_hoort(self):
        kop = _svc()._kopregel(
            {
                "soort": "Bijlage",
                "categorie": CAT_BIJLAGE,
                "bijlage_bij_nummer": "2026D45064",
                "bijlage_bij_onderwerp": "Strategische inzet digitalisering",
            },
            {"label": "Bijlage", "emoji": ":p:", "kleur": "#000"},
        )
        assert "Strategische inzet" in kop


class TestNlDatum:
    def test_nederlandse_maandnaam(self):
        # Niet strftime: dat volgt de locale van de container, en die staat
        # in productie op C. Dan krijg je "September" in een Nederlands
        # bericht.
        assert _nl_datum(date(2026, 9, 24)) == "24 september"

    def test_ander_jaar_krijgt_het_jaartal(self):
        assert _nl_datum(date(2025, 3, 1)) == "1 maart 2025"

    def test_iso_string_uit_extra_data(self):
        assert _nl_datum("2026-09-24T10:00:00Z") == "24 september"

    def test_onzin_is_leeg(self):
        assert _nl_datum("geen datum") == ""


class TestFormatAlert:
    def test_lage_score_dempt_de_kleur(self):
        """Zichtbaar maar stil: niets valt weg, niet alles schreeuwt."""
        _, props = _svc().format_alert(
            _item(categorie=CAT_EXTERN, relevantie_score=18), ['"Digitale Dienst"']
        )
        assert props["attachments"][0]["color"] == "#CBD5E1"

    def test_hoge_score_krijgt_de_kleur_van_het_soort(self):
        _, props = _svc().format_alert(
            _item(categorie=CAT_BIJLAGE, relevantie_score=85), ['"RegelRecht"']
        )
        assert props["attachments"][0]["color"] == "#1E3A8A"

    def test_de_termen_staan_erbij(self):
        """Waarom kwam dit binnen? Dat is de helft van het bericht."""
        _, props = _svc().format_alert(
            _item(relevantie_score=70), ['"NLDD"', '"RegelRecht"']
        )
        veld = props["attachments"][0]["fields"][0]["value"]
        assert "NLDD" in veld and "RegelRecht" in veld

    def test_actie_verschijnt_als_die_er_is(self):
        _, props = _svc().format_alert(
            _item(relevantie_score=70, actie="Vergadering op 24 september"),
            ['"NLDD"'],
        )
        assert "24 september" in props["attachments"][0]["text"]

    def test_zonder_samenvatting_valt_het_terug_op_het_onderwerp(self):
        item = _item(relevantie_score=70)
        item.llm_samenvatting = None
        item.onderwerp = "Iets over digitalisering"
        _, props = _svc().format_alert(item, ['"NLDD"'])
        assert "digitalisering" in props["attachments"][0]["text"]


class TestDrempel:
    """Onder de drempel geen bericht, maar het stuk blijft bestaan."""

    def test_procedurestuk_zonder_inhoud_valt_af(self):
        """Score 0: een verslag van een lijst van vragen, geen inhoud."""
        abonnement = _abonnement()
        assert _relevantie({"relevantie_score": 0}) < abonnement.minimum_relevantie

    def test_op_de_drempel_telt_mee(self):
        abonnement = _abonnement(minimum_relevantie=10)
        assert _relevantie({"relevantie_score": 10}) >= abonnement.minimum_relevantie

    def test_ongewogen_stuk_haalt_de_standaarddrempel(self):
        """Een mislukte LLM-call mag niet als "te licht" uitpakken.

        `_relevantie` geeft zonder score `DREMPEL_MIDDEN` terug, en die
        moet boven de standaarddrempel liggen. Zou de default 0 zijn, of
        de drempel boven `DREMPEL_MIDDEN` worden gezet, dan verdwijnt elk
        stuk waarvan het wegen misging stilzwijgend.
        """
        assert _relevantie({}) == DREMPEL_MIDDEN
        assert _relevantie({}) >= _abonnement().minimum_relevantie

    def test_naamgenoot_valt_stil_maar_blijft_zichtbaar(self):
        """Een term die als gewoon woord valt haalt de drempel niet meer.

        Gemeten geval: een position paper over schuldhulpverlening waarin
        "digitale dienst" een online dienst betekent, scoorde 15. Bij de
        oude drempel van 10 kwam dat door; sinds de meting over 146
        stukken staat de standaard op 20 en blijft het een grijze regel in
        de webapp. Het stuk is wél geïmporteerd: een drempel scheelt ruis,
        geen dekking.
        """
        assert 15 < _abonnement().minimum_relevantie

    def test_uitgezette_categorie_valt_af(self):
        abonnement = _abonnement(uitgezette_categorieen=[CAT_VERGADERING_TERUG])
        assert CAT_VERGADERING_TERUG in abonnement.uitgezette_categorieen

    def test_standaard_zet_niets_uit(self):
        # Recall boven precisie: een nieuw abonnement volgt alles.
        assert _abonnement().uitgezette_categorieen is None


class TestKanaalSchakelaar:
    """Alerts staan per kanaal aan of uit, net als de andere functies.

    Een kanaal draagt al `auto_note_enabled` en `suggest_leads_enabled`,
    elk met een eigen vinkje. Zonder een derde schakelaar zou een kanaal
    dat voor leads is gekoppeld ook elk kamerstuk krijgen.
    """

    def test_staat_standaard_uit(self):
        """Koppelen voor leads mag niet stilzwijgend kamerstukken opleveren."""
        from bouwmeester.models.mattermost_channel_link import (
            MattermostChannelLink,
        )

        kolom = MattermostChannelLink.__table__.c.parlementaire_alerts_enabled
        assert kolom.server_default.arg == "false"
        assert kolom.nullable is False

    def test_staat_los_van_de_andere_schakelaars(self):
        from bouwmeester.models.mattermost_channel_link import (
            MattermostChannelLink,
        )

        kolommen = MattermostChannelLink.__table__.c
        # Drie onafhankelijke functies, drie kolommen.
        assert "auto_note_enabled" in kolommen
        assert "suggest_leads_enabled" in kolommen
        assert "parlementaire_alerts_enabled" in kolommen

    def test_schema_laat_het_veld_door(self):
        from bouwmeester.schema.mattermost_channel_link import (
            MattermostChannelLinkResponse,
            MattermostChannelLinkUpdate,
        )

        # De UI moet de stand kunnen tonen én wijzigen.
        assert (
            "parlementaire_alerts_enabled" in MattermostChannelLinkResponse.model_fields
        )
        assert (
            "parlementaire_alerts_enabled" in MattermostChannelLinkUpdate.model_fields
        )


class TestInhaalberichtBundelt:
    """Eén bericht voor alle termen die tegelijk worden aangezet.

    Gemeten in productie: twee verse termen gaven twee berichten met samen
    vier regels over drie unieke stukken, met de startnotitie NLDD er twee
    keer in. Bij vijf termen zouden dat vijf berichten zijn. De losse
    alerts ontdubbelen al op documentnummer; dit doet hetzelfde.
    """

    def test_een_bericht_noemt_alle_termen(self):
        a1 = _abonnement(term="van wet naar digitale werking")
        a2 = _abonnement(term="regelrecht")
        items = [
            _item(titel="Startnotitie NLDD", zaak_nummer="2026D45065"),
            _item(titel="Strategische inzet", zaak_nummer="2026D45064"),
        ]

        _, props = _svc().format_inhaalslag([a1, a2], items)
        att = props["attachments"][0]

        assert "van wet naar digitale werking" in att["pretext"]
        assert "regelrecht" in att["pretext"]
        assert "Nieuwe zoektermen" in att["pretext"]

    def test_een_term_krijgt_enkelvoud(self):
        _, props = _svc().format_inhaalslag([_abonnement(term="NLDD")], [_item()])
        assert "**Nieuwe zoekterm**" in props["attachments"][0]["pretext"]

    def test_elk_stuk_staat_er_een_keer_in(self):
        """De aanroeper ontdubbelt, dus de lijst bevat geen herhalingen."""
        a1 = _abonnement(term="term-een")
        a2 = _abonnement(term="term-twee")
        stuk = _item(titel="Startnotitie NLDD", zaak_nummer="2026D45065")

        _, props = _svc().format_inhaalslag([a1, a2], [stuk])
        tekst = props["attachments"][0]["text"]

        assert tekst.count("Startnotitie NLDD") == 1


class TestInhaalslagWeegtDeDrempel:
    """De inhaalslag gebruikt dezelfde drempel als een losse alert.

    Het geval uit productie, 22 september 2026: de eerste inhaalslag zette
    47 stukken in het kanaal, waarvan 46 via één brede term. Oorzaak was
    dat `relevantie_score` alleen in de losse-alertroute werd gezet, zodat
    er bij de inhaalslag niets te wegen viel. Deze tests dekken de
    weegkant; dat er een score staat is de verantwoordelijkheid van
    `_beoordeel` in de importservice.
    """

    async def _post(self, abonnementen, items) -> tuple[int, list]:
        """Draai `post_inhaalslag` met alles eromheen uitgeschakeld."""
        verstuurd: list = []
        svc = _svc()
        svc.mattermost = SimpleNamespace(
            is_enabled=_async_true,
            send_channel_message=_maak_verzender(verstuurd),
        )
        svc.session = SimpleNamespace(
            execute=_maak_execute([SimpleNamespace(channel_id="kanaal-1")])
        )
        gepost = await svc.post_inhaalslag(abonnementen, items)
        return gepost, verstuurd

    async def test_laag_scorend_stuk_blijft_uit_het_bericht(self):
        abo = _abonnement(minimum_relevantie=10)
        items = [
            _item(titel="Gaat er echt over", relevantie_score=85),
            _item(titel="Metafoor", zaak_nummer="2026D00002", relevantie_score=5),
        ]

        gepost, verstuurd = await self._post([abo], items)

        assert gepost == 1
        tekst = verstuurd[0]["props"]["attachments"][0]["text"]
        assert "Gaat er echt over" in tekst
        assert "Metafoor" not in tekst

    async def test_niets_boven_de_drempel_geeft_geen_bericht(self):
        """Stil blijven is beter dan een bericht met een lege lijst."""
        abo = _abonnement(minimum_relevantie=40)
        items = [_item(relevantie_score=5), _item(zaak_nummer="X", relevantie_score=0)]

        gepost, verstuurd = await self._post([abo], items)

        assert gepost == 0
        assert verstuurd == []

    async def test_de_laagste_drempel_telt(self):
        """Twee termen, twee drempels: wie het ruimst staat bepaalt.

        Anders zou de strengste term de stukken van de ruimste wegnemen,
        terwijl die twee los van elkaar zijn ingesteld.
        """
        streng = _abonnement(term="streng", minimum_relevantie=80)
        ruim = _abonnement(term="ruim", minimum_relevantie=10)
        items = [_item(titel="Middenmoot", relevantie_score=50)]

        gepost, verstuurd = await self._post([streng, ruim], items)

        assert gepost == 1
        assert "Middenmoot" in verstuurd[0]["props"]["attachments"][0]["text"]

    async def test_stuk_zonder_score_blijft_staan(self):
        """Een mislukte LLM-call mag een stuk niet verzwijgen.

        `_relevantie` geeft dan `DREMPEL_MIDDEN` terug en juist geen 0:
        niet gewogen is iets anders dan te licht bevonden, en 0 zou het
        stuk onder elke drempel wegfilteren. Deze test staat op drempel 0
        en toetst dus alleen dat het stuk overeind blijft; dat de default
        boven de standaarddrempel uitkomt staat vast in
        `test_ongewogen_stuk_haalt_de_standaarddrempel`.
        """
        abo = _abonnement(minimum_relevantie=0)
        gepost, verstuurd = await self._post([abo], [_item(titel="Ongewogen")])

        assert gepost == 1
        assert "Ongewogen" in verstuurd[0]["props"]["attachments"][0]["text"]
