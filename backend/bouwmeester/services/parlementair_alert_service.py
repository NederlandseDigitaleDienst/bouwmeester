"""Post een gevonden kamerstuk in de kanalen van het abonnerende initiatief.

Vorm van het bericht: kort, met de bron erbij en een handeling die met één
klik kan. Drie regels samenvatting is de bovengrens — een alert die je moet
lezen zoals je een kamerstuk leest, is geen alert.

Waarom emoji-reactions en geen knoppen: Mattermost stuurt voor
message-attachment-button-clicks geen POST naar onze endpoint, en de
"Taak afronden"-knop die dat wel probeerde deed daarom nooit iets (zie
`MattermostService.format_notification`). Suggested-leads lossen dat al op
met reactions over de bestaande websocket; deze alerts volgen datzelfde
pad.
"""

import logging
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.mattermost_channel_link import (
    SCOPE_INITIATIEF,
    MattermostChannelLink,
)
from bouwmeester.models.parlementair_item import ParlementairItem
from bouwmeester.repositories.parlementair_abonnement import (
    ParlementairAbonnementRepository,
)
from bouwmeester.services.kamerstuk_soort import (
    CAT_NIEUWS,
    CAT_OVERIG,
    CATEGORIE_PRESENTATIE,
)
from bouwmeester.services.mattermost_service import MattermostService
from bouwmeester.services.mattermost_utils import escape_mattermost_md as _escape_md
from bouwmeester.services.mattermost_utils import (
    escape_mattermost_prose as _escape_proza,
)
from bouwmeester.services.zoekterm_passage import knip_rond_termen

logger = logging.getLogger(__name__)

# De kleur van de streep links komt uit de categorie (zie
# `kamerstuk_soort.CATEGORIE_PRESENTATIE`), zodat een kamervraag er anders
# uitziet dan een agenda. Een lage relevantie dempt hem naar grijs: bij een
# breed vangnet (recall boven precisie) wordt niets weggegooid, maar niet
# alles hoeft evenveel aandacht te trekken.
KLEUR_LAAG = "#CBD5E1"

DREMPEL_HOOG = 70
DREMPEL_MIDDEN = 40

_NL_MAANDEN = (
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

# De reactions die de bot zelf plaatst als affordance. De websocket-laag
# leest ze terug; eigen reactions triggeren daar geen actie.
#
# Alleen wat ook iets doet. Hier stond ook "eyes" als knop voor opvolgen,
# maar daar hing nooit een actie aan: een knop die niets doet leert mensen
# dat de knoppen niets doen.
REACTIE_NIET_RELEVANT = "x"


# Teksten die een mislukte LLM-aanroep ooit als samenvatting heeft
# opgeleverd. De bron daarvan is weg (zie `extract_tags`), maar stukken
# die vóór die wijziging zijn geïmporteerd dragen ze nog, en die worden
# opnieuw gepost zodra een nieuwe zoekterm ze aandraagt.
#
# Een vangnet en geen oplossing: het echte werk is dat een foutpad nooit
# tekst produceert die op inhoud lijkt.
_FOUTMELDINGEN = frozenset(
    {
        "tag-extractie mislukt",
        "samenvatting mislukt",
        "extractie mislukt",
    }
)


def reactie_uitleg(*, start_button: bool = False, announce_button: bool = False) -> str:
    """De regel die zegt wat de reacties onder een alert doen.

    Alleen de reacties die er ook staan, in dezelfde volgorde. Zonder deze
    regel stonden er tot vier emoji onder een bericht en moest je drukken
    om te ontdekken wat er gebeurt; bij de koptelefoon is dat een kanaal
    dat er daarna is.

    De emoji staan hier als teken en niet als naam: dit is uitleg bij wat
    je ziet, en de namen horen bij `add_reaction`.
    """
    delen = ["\u274c niet relevant"]
    if start_button:
        delen.append("\U0001f3a7 eigen kanaal voor dit debat")
    if announce_button:
        delen.append("\U0001f4e3 herinner dit kanaal op de dag zelf")
    return f"**Reageer:** {' · '.join(delen)}"


def _kort(tekst: str, grens: int) -> str:
    """Kort een titel in op een woordgrens, met een beletselteken.

    `titel[:70]` hakte midden in een woord: "over cloudbeleid (O.a. Ka"
    stond zo in productie. Een afgekapte titel zonder teken leest
    bovendien als een volledige titel, wat erger is dan zichtbaar
    ingekort.
    """
    tekst = tekst.strip()
    if len(tekst) <= grens:
        return tekst
    afgekapt = tekst[:grens]
    spatie = afgekapt.rfind(" ")
    # Alleen terug naar de spatie als dat niet de halve titel weggooit.
    if spatie > grens * 0.6:
        afgekapt = afgekapt[:spatie]
    return afgekapt.rstrip(" ,.;:-") + "…"


def _terugval(item: ParlementairItem, termen: list[str] | None = None) -> str:
    """Wat er in het bericht komt als de samenvatting ontbreekt.

    Het onderwerp is de eerste keus, maar bij een agenda is dat woord
    voor woord de titel: dan staat er twee keer hetzelfde en zegt het
    bericht niets. Zo stond een agenda van de commissie Digitale Zaken op
    25 september 2026 in het kanaal, terwijl het document wel degelijk
    vertelde dat er een rondetafelgesprek over de oprichting van de
    dienst wordt voorbereid.

    Dan liever de passage uit het document waar de zoekterm valt. Dat is
    geen samenvatting, maar het is wél nieuwe informatie, en het is de
    passage waarom dit stuk überhaupt binnenkwam.
    """
    titel = (item.titel or "").strip().lower()
    onderwerp = (item.onderwerp or "").strip()

    if onderwerp and onderwerp.lower() != titel:
        return onderwerp[:300]

    # Niet het begin van het document, maar de passage waar de zoekterm
    # valt. Het begin van een agenda is de voortouwcommissie en een rij
    # agendapuntnummers; de passage eromheen zegt waarom dit stuk binnenkwam.
    ruw = item.document_tekst or ""
    tekst = ruw
    if termen and ruw:
        geknipt = knip_rond_termen(ruw, termen)
        # `knip_rond_termen` zet de kop van het document vooraan, want een
        # losse passage is zonder die context niet te plaatsen. Voor een
        # prompt is dat goed; hier niet, want de kop van een agenda is de
        # voortouwcommissie en een rij agendapuntnummers. We nemen daarom
        # het eerste stuk ná de kop.
        _, _, na_kop = geknipt.partition("[...]")
        tekst = na_kop or geknipt

    tekst = " ".join(tekst.split())
    if tekst:
        return _kort(tekst, 300)

    # Niets bruikbaars. Het onderwerp herhalen is nog altijd beter dan een
    # leeg bericht; de titel staat er dan twee keer, maar de links en de
    # zoektermen eronder dragen het bericht.
    return onderwerp[:300]


def _bruikbare_samenvatting(ruwe: str | None) -> str:
    """De samenvatting, of leeg als het een foutmelding blijkt.

    Leeg is hier het goede antwoord: `format_alert` valt dan terug op het
    onderwerp van het stuk, en dat is altijd echte tekst uit de bron.
    """
    tekst = (ruwe or "").strip()
    if tekst.lower().rstrip(".") in _FOUTMELDINGEN:
        return ""
    return tekst


def _vinkje_voor(item: ParlementairItem):
    """Welke kanaalinstelling bepaalt of dit stuk gepost mag worden.

    Op de categorie en niet op `item.type`, omdat de categorie al in
    `extra_data` staat op het moment dat een stuk wordt gepost, en omdat
    dat precies het veld is dat de rest van de presentatie stuurt.
    """
    categorie = (item.extra_data or {}).get("categorie")
    if categorie == CAT_NIEUWS:
        return MattermostChannelLink.nieuws_alerts_enabled
    return MattermostChannelLink.parlementaire_alerts_enabled


class ParlementairAlertService:
    """Zet een geïmporteerd kamerstuk om in een bericht per kanaal."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.abonnement_repo = ParlementairAbonnementRepository(session)
        self.mattermost = MattermostService(session)

    async def post_alert(self, item: ParlementairItem) -> int:
        """Post het item in elk kanaal dat via een abonnement meekijkt.

        Geeft terug in hoeveel kanalen is gepost. Nul is een geldige
        uitkomst: een initiatief hoeft geen kanaal te hebben, en dan staat
        de treffer alleen in de webapp.
        """
        if not await self.mattermost.is_enabled():
            return 0

        abonnementen = await self.abonnement_repo.list_abonnementen_voor_item(item.id)
        if not abonnementen:
            return 0

        # Een abonnement kan soorten uitzetten die het niet in Mattermost
        # wil zien — procedurevergaderingen zijn nuttig maar talrijk. Het
        # stuk is dan wél geïmporteerd en in de webapp zichtbaar; alleen
        # het bericht blijft uit. Zo verliest een filter nooit dekking.
        extra = item.extra_data or {}
        categorie = extra.get("categorie") or CAT_OVERIG
        score = _relevantie(extra)
        abonnementen = [
            a
            for a in abonnementen
            if categorie not in (a.uitgezette_categorieen or [])
            # Onder de drempel geen bericht. Het stuk is wél geïmporteerd
            # en staat in de webapp: een drempel hoort ruis te schelen,
            # geen dekking. Een meting over 146 beoordeelde stukken gaf
            # twintig stukken tussen 10 en 19, en geen van alle ging
            # over de NLDD: batterijsystemen, waterstof en
            # eigenwoningforfait, termen die als gewoon woord vielen.
            # Daarboven begint het echte werk pas bij 40. De standaard
            # staat daarom op 20, en is per abonnement bij te stellen
            # omdat een brede term iets anders vraagt dan een smalle.
            # Geen `or 0` eromheen: de kolom is `nullable=False`, dus dat
            # idioom vangt niets en maskeert juist de keuze "Alles tonen".
            # Die zet de drempel op 0, en 0 is falsy: elke fout in de
            # rechterhelft zou dan stil de scherpste stand opleveren voor
            # wie juist alles wil zien.
            and score >= a.minimum_relevantie
        ]
        if not abonnementen:
            logger.info(
                "Kamerstuk %s (%s, score %d) niet gepost: uitgezet of onder "
                "de drempel van alle abonnees",
                item.zaak_nummer,
                categorie,
                score,
            )
            return 0

        # Welk vinkje dit stuk nodig heeft. Nieuws en kamerstukken zijn
        # los aan te zetten: een kanaal dat de Kamer volgt heeft niet
        # vanzelf om de vakpers gevraagd, en andersom.
        vinkje = _vinkje_voor(item)

        # Eén kanaal kan via meerdere termen meekijken; post er één keer.
        kanalen: dict[str, MattermostChannelLink] = {}
        # The channels that hang on an initiatief and not on a lead: only
        # an initiatief has a list of meetings to put one on.
        van_een_initiatief: set[str] = set()
        for abonnement in abonnementen:
            stmt = select(MattermostChannelLink).where(
                MattermostChannelLink.scope_type == abonnement.scope_type,
                MattermostChannelLink.scope_id == abonnement.scope_id,
                MattermostChannelLink.disabled_at.is_(None),
                # Per kanaal aan te zetten, net als auto-notes en
                # lead-suggesties. Een kanaal dat voor leads is gekoppeld
                # hoort niet ongevraagd elk kamerstuk te krijgen.
                vinkje.is_(True),
            )
            for link in (await self.session.execute(stmt)).scalars().all():
                kanalen.setdefault(link.channel_id, link)
                # A channel hangs on exactly one scope, so the scope of the
                # abonnement that found it is the scope of the channel.
                if abonnement.scope_type == SCOPE_INITIATIEF:
                    van_een_initiatief.add(link.channel_id)

        if not kanalen:
            logger.info(
                "Stuk %s heeft abonnees maar geen kanaal met dit soort alerts aan",
                item.zaak_nummer,
            )
            return 0

        termen = [a.term for a in abonnementen]

        # Is dit een bijlage bij een stuk dat we al gepost hebben, dan hoort
        # hij in díe thread en niet als los bericht ernaast. Per kanaal,
        # want hetzelfde stuk kan in meerdere kanalen staan en heeft daar
        # elk een eigen post.
        draden = await self._draden_van_het_hoofdstuk(extra)

        # Per kanaal opmaken, want per kanaal verschilt of er een thread
        # is. Het hoofdstuk kan in het ene kanaal boven de drempel zijn
        # gekomen en in het andere niet, of een kanaal is pas later
        # gekoppeld. Eén keer beknopt beslissen voor alle kanalen gaf daar
        # een bericht zonder kop, zonder termen en zonder voettekst, met
        # niets erboven dat die context droeg.
        vormen: dict[tuple[bool, bool], tuple[str, dict]] = {}

        # Imported here: the debate service builds on helpers of this
        # module, so a module-level import would be circular.
        from bouwmeester.services.debat_kanaal_service import is_startable

        # A convocatie for a meeting that is still to come gets a start
        # button for setting up a channel for that debate.
        start_button = is_startable(extra)

        # Any meeting that is still to come gets a reaction that puts it on
        # the list of the initiatief, so a reminder follows on the day. Not
        # in a channel that hangs on a lead: only an initiatief has a list.
        from bouwmeester.services.debat_aankondiging_service import is_announceable

        announce_button = is_announceable(extra)

        gepost = 0
        for channel_id in kanalen:
            root_id = draden.get(channel_id)
            beknopt = root_id is not None
            announce_here = announce_button and channel_id in van_een_initiatief
            # Also per button: the line that explains the reactions names
            # only the ones that are under this message.
            vorm = (beknopt, announce_here)
            if vorm not in vormen:
                vormen[vorm] = self.format_alert(
                    item,
                    termen,
                    beknopt=beknopt,
                    start_button=start_button,
                    announce_button=announce_here,
                )
            text, props = vormen[vorm]
            post_id = await self.mattermost.send_channel_message(
                channel_id, text, props, root_id=root_id
            )
            if not post_id:
                continue
            gepost += 1
            await self._onthoud_post(
                item.id,
                channel_id,
                post_id,
                start_button=start_button,
                announce_button=announce_here,
            )
        return gepost

    async def _draden_van_het_hoofdstuk(self, extra: dict) -> dict[str, str]:
        """Waar het stuk staat waar deze bijlage bij hoort, per kanaal.

        Leeg als dit geen bijlage is, of als het hoofdstuk nog nergens is
        gepost. Dan wordt het een gewoon bericht, zoals altijd.

        `bijlage_bij_nummer` is een DocumentNummer, en bij tkconv is dat
        precies wat er als `zaak_id` op het item staat. De import zet een
        hoofdstuk bovendien vóór zijn bijlagen, dus binnen één ronde staat
        de thread er al tegen de tijd dat we hier komen.
        """
        hoort_bij = (extra or {}).get("bijlage_bij_nummer")
        if not hoort_bij:
            return {}

        from bouwmeester.models.parlementair_alert_post import ParlementairAlertPost

        stmt = (
            select(ParlementairAlertPost.channel_id, ParlementairAlertPost.post_id)
            .join(
                ParlementairItem,
                ParlementairItem.id == ParlementairAlertPost.parlementair_item_id,
            )
            .where(ParlementairItem.zaak_id == hoort_bij)
            .order_by(ParlementairAlertPost.created_at.desc())
        )
        try:
            rijen = (await self.session.execute(stmt)).all()
        except Exception:
            # Een mislukte lookup mag het bericht niet tegenhouden; dan
            # wordt het een los bericht in plaats van een reply.
            logger.exception("Kon de thread van %s niet opzoeken", hoort_bij)
            return {}

        draden: dict[str, str] = {}
        for channel_id, post_id in rijen:
            draden.setdefault(channel_id, post_id)
        return draden

    async def _onthoud_post(
        self,
        item_id: UUID,
        channel_id: str,
        post_id: str,
        *,
        start_button: bool = False,
        announce_button: bool = False,
    ) -> None:
        """Leg vast waar dit stuk is gepost, en bied de reacties aan.

        Beide zijn nodig om te kunnen wegklikken: het post-id is waar
        `_dispatch_reaction_added` op zoekt, en de reacties zijn de knop
        die de lezer ziet. Zonder allebei blijft de teller op nul staan,
        zoals hij sinds de bouw stond.

        Faalt zacht. Het bericht is al gepost en dat is niet terug te
        draaien; een mislukte administratie mag daar geen exception
        overheen gooien. De prijs is dat wegklikken voor dát bericht niet
        werkt, en dat is minder erg dan een ronde die omvalt.
        """
        from bouwmeester.models.parlementair_alert_post import ParlementairAlertPost

        try:
            self.session.add(
                ParlementairAlertPost(
                    parlementair_item_id=item_id,
                    channel_id=channel_id,
                    post_id=post_id,
                )
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.warning(
                "Post %s van stuk %s niet vastgelegd; wegklikken werkt hier niet",
                post_id,
                item_id,
                exc_info=True,
            )
            return

        # De reacties die de bot zelf plaatst zijn de affordance: zonder
        # zichtbare "x" weet niemand dat wegklikken kan. De websocket
        # negeert reacties van de bot zelf, dus ze triggeren niets.
        reacties = [REACTIE_NIET_RELEVANT]
        if start_button:
            from bouwmeester.services.debat_kanaal_service import REACTIE_UITLUISTEREN

            reacties.append(REACTIE_UITLUISTEREN)
        if announce_button:
            from bouwmeester.services.debat_aankondiging_service import (
                REACTIE_AANKONDIGEN,
            )

            reacties.append(REACTIE_AANKONDIGEN)
        for emoji in reacties:
            if not await self.mattermost.add_reaction(post_id, emoji):
                logger.info("Reactie %s niet geplaatst op post %s", emoji, post_id)

    def format_alert(
        self,
        item: ParlementairItem,
        termen: list[str],
        beknopt: bool = False,
        *,
        start_button: bool = False,
        announce_button: bool = False,
    ) -> tuple[str, dict]:
        """Bouw het bericht: strak, met bron, soort en herkomst.

        Het soort staat vooraan omdat het het eerste is wat iemand wil
        weten. Een agenda van een procedurevergadering die over twee dagen
        is, vraagt iets anders van de lezer dan een besluitenlijst van een
        vergadering die geweest is, en een position paper komt van buiten
        de Kamer en is geen beleid.

        `beknopt` is voor een bijlage die als reply onder zijn hoofdstuk
        komt. Daar staat de context al boven het bericht: dezelfde termen,
        dezelfde datum, dezelfde bron, en een titel die de brief bijna
        letterlijk herhaalt. Wat overblijft is wat de bijlage zelf
        toevoegt: waar hij over gaat en waar hij te vinden is.

        `start_button` en `announce_button` zeggen welke reacties er onder
        dit bericht komen, zodat de uitlegregel alleen die noemt.
        """
        extra = item.extra_data or {}
        score = _relevantie(extra)
        categorie = extra.get("categorie") or CAT_OVERIG
        presentatie = CATEGORIE_PRESENTATIE.get(
            categorie, CATEGORIE_PRESENTATIE[CAT_OVERIG]
        )

        # De categorie geeft de kleur; een lage relevantie dempt hem naar
        # grijs. Zo blijft een zijdelingse treffer zichtbaar zonder de
        # aandacht te trekken die een kerntreffer verdient.
        kleur = presentatie["kleur"] if score >= DREMPEL_MIDDEN else KLEUR_LAAG

        kop = self._kopregel(extra, presentatie)

        # Escapen, ook al komt dit van ons eigen taalmodel: het model vat
        # een kamerstuk van derden samen, dus een stuk dat het overhaalt
        # om `@channel` of een link in de samenvatting te zetten krijgt
        # dat anders ongefilterd in het kanaal.
        samenvatting = _escape_proza(_bruikbare_samenvatting(item.llm_samenvatting))
        if not samenvatting:
            samenvatting = _escape_proza(_terugval(item, termen))

        tekst_delen = [samenvatting]

        actie = (extra.get("actie") or "").strip()
        if actie:
            tekst_delen.append(f":arrow_right: {_escape_proza(actie)}")

        acties = []
        if item.document_url:
            acties.append(f"[Openen op tkconv]({item.document_url})")
        raw_url = extra.get("raw_url")
        if raw_url:
            acties.append(f"[Brondocument]({raw_url})")
        if acties:
            tekst_delen.append(" · ".join(acties))

        fields = [
            {
                "short": False,
                "title": "Gevonden op",
                "value": ", ".join(_escape_proza(t) for t in termen),
            },
            # Zonder titel: het is geen gegeven over het stuk maar een
            # aanwijzing, en als laatste veld staat hij vlak boven de
            # reacties waar hij over gaat.
            {
                "short": False,
                "title": "",
                "value": reactie_uitleg(
                    start_button=start_button, announce_button=announce_button
                ),
            },
        ]

        # Het `title`-veld is platte tekst zolang er een `title_link`
        # staat: de webapp rendert dan `decodeHtmlEntities(title)` binnen
        # een link, zonder markdown en zonder `:emoji:`-codes. Escapen
        # levert daar alleen zichtbare backslashes op
        # (`\(O.a. Kamerstuk 26643-1542\)`) en de emoji-code blijft
        # letterlijk staan; allebei stonden ze zo in productie op
        # 24 september 2026.
        #
        # Zónder `title_link` gaat de titel wél door een markdown-renderer
        # (LinkOnlyRenderer: opmaak wordt gestript, maar links en emoji
        # renderen). `_titel_link` garandeert daarom altijd een link, want
        # deze titel komt uit een kamerstuk van derden en `[tekst](url)`
        # zou dan een klikbare link opleveren die iets anders belooft dan
        # waar hij heen gaat.
        titel_link = item.document_url or ""
        ruwe_titel = f"{presentatie.get('teken', '')} {item.titel}".strip()
        # Zonder link geldt de markdown-tak, en dan escapen we alsnog.
        titel = ruwe_titel if titel_link else _escape_md(ruwe_titel)
        attachment: dict = {
            # Ook platte tekst: dit is wat een notificatie op een telefoon
            # toont. Backslashes horen daar net zomin.
            "fallback": f"{presentatie['label']}: {item.titel}",
            "color": kleur,
            "title": titel,
            "title_link": titel_link,
            "text": "\n\n".join(tekst_delen),
        }

        # Weglaten en niet leeg meesturen. Dat is wat de andere
        # attachment-bouwers in deze codebase doen
        # (`mattermost_ingest_service`, `mattermost_slash_service`), en het
        # scheelt de vraag hoe een renderer een lege string behandelt.
        #
        # In een thread dragen deze drie alleen wat het hoofdstuk erboven
        # al zegt: de kop noemt het soort en bij welk stuk de bijlage
        # hoort, de velden herhalen de gevonden termen, en de voettekst
        # herhaalt soort, commissie, datum en bron. De titel blijft wel
        # staan: die draagt de link naar het document en is waar een
        # ingeklapte reply aan te herkennen is.
        if not beknopt:
            attachment["pretext"] = kop
            attachment["fields"] = fields
            attachment["footer"] = self._voettekst(item, extra)

        return "", {"attachments": [attachment]}

    @staticmethod
    def _kopregel(extra: dict, presentatie: dict) -> str:
        """De regel boven de titel: wat voor stuk, en wat dat betekent.

        Dit is waar het onderscheid zichtbaar wordt. Een vergadering die
        nog komt krijgt er hoeveel dagen bij, want dat is precies het
        verschil tussen "je kunt hier nog iets mee" en "dit is gebeurd".

        Het label is het `Soort` uit de TK-API en niet onze categorie:
        "POSITION PAPER" zegt wat het stuk is, "EXTERN" zegt alleen in
        welk hokje wij het hebben gestopt. De categorie stuurt wel het
        icoon, de kleur en de instructie aan het taalmodel, en springt in
        als de API geen soort kent.
        """
        label = (extra.get("soort") or presentatie["label"]).upper()
        delen = [f"**{label}**"]

        # Een position paper of burgerbrief komt van buiten de Kamer, en
        # dat is precies wat je bij zo'n stuk wilt weten: het is een
        # standpunt van een belanghebbende, geen beleid. Het soort alleen
        # zegt dat niet.
        if presentatie.get("herkomst"):
            delen.append(presentatie["herkomst"])

        termijn = _als_datum(extra.get("termijn"))
        if termijn:
            dagen = (termijn - date.today()).days
            if dagen < 0:
                delen.append(f"termijn verstreken ({_nl_datum(termijn)})")
            elif dagen == 0:
                delen.append("termijn vandaag")
            else:
                delen.append(f"termijn {_nl_datum(termijn)} (over {dagen} dagen)")

        vergadering = _als_datum(extra.get("activiteit_datum"))
        if vergadering:
            dagen = (vergadering - date.today()).days
            if dagen > 1:
                delen.append(f"{_nl_datum(vergadering)} (over {dagen} dagen)")
            elif dagen == 1:
                delen.append(f"{_nl_datum(vergadering)} (morgen)")
            elif dagen == 0:
                delen.append(f"{_nl_datum(vergadering)} (vandaag)")
            else:
                delen.append(_nl_datum(vergadering))

        bijlage_bij = extra.get("bijlage_bij_nummer")
        if bijlage_bij:
            onderwerp = (extra.get("bijlage_bij_onderwerp") or "").strip()
            if onderwerp:
                delen.append(f"bij _{_escape_proza(onderwerp[:60])}_")
            else:
                delen.append(f"bij {bijlage_bij}")

        return " · ".join(delen)

    @staticmethod
    def _voettekst(item: ParlementairItem, extra: dict) -> str:
        soort = extra.get("soort")
        commissie = extra.get("commissie")
        datum = _nl_datum(item.datum) if item.datum else ""
        delen = [x for x in [soort, commissie, datum] if x]
        delen.append("via tkconv (berthub.eu)")
        return " · ".join(delen)

    async def post_inhaalslag(
        self, abonnementen: list, items: list[ParlementairItem]
    ) -> int:
        """Meld in één bericht wat nieuwe zoektermen terugvonden.

        Eén bericht voor álle termen die tegelijk worden aangezet, niet
        één per term. Twee termen vinden vaak dezelfde stukken: in
        productie gaven "van wet naar digitale werking" en "regelrecht"
        samen twee berichten met vier regels over drie unieke stukken,
        met de startnotitie NLDD er twee keer in. Bij vijf termen zouden
        dat vijf berichten zijn.

        De losse alerts ontdubbelen al op documentnummer; dit doet
        hetzelfde.
        """
        if not await self.mattermost.is_enabled() or not items:
            return 0
        if not abonnementen:
            return 0

        # Dezelfde drempel als bij een losse alert. Zonder dit staat de
        # inhaalslag los van elke instelling: in productie leverde dat één
        # bericht met 47 stukken op, waarvan 46 via een term die vooral de
        # metafoor ving. De stukken blijven geïmporteerd en in de webapp
        # zichtbaar; alleen het bericht wordt korter.
        drempel = min((a.minimum_relevantie or 0) for a in abonnementen)
        items = [i for i in items if _relevantie(i.extra_data or {}) >= drempel]
        if not items:
            logger.info(
                "Inhaalslag voor %s: niets boven de drempel van %d",
                ", ".join(repr(a.term) for a in abonnementen),
                drempel,
            )
            return 0

        # Alle termen delen dezelfde scope (de aanroeper groepeert
        # daarop), dus de kanalen zijn voor allemaal gelijk.
        eerste = abonnementen[0]
        stmt = select(MattermostChannelLink).where(
            MattermostChannelLink.scope_type == eerste.scope_type,
            MattermostChannelLink.scope_id == eerste.scope_id,
            MattermostChannelLink.disabled_at.is_(None),
            MattermostChannelLink.parlementaire_alerts_enabled.is_(True),
        )
        kanalen = list((await self.session.execute(stmt)).scalars().all())
        if not kanalen:
            return 0

        text, props = self.format_inhaalslag(abonnementen, items)
        gepost = 0
        for link in kanalen:
            if await self.mattermost.send_channel_message(link.channel_id, text, props):
                gepost += 1
        return gepost

    def format_inhaalslag(
        self, abonnementen: list, items: list[ParlementairItem]
    ) -> tuple[str, dict]:
        """Eén lijst met wat de nieuwe termen in de feed terugvonden."""
        regels = []
        for item in sorted(items, key=lambda i: i.datum or date.min, reverse=True):
            extra = item.extra_data or {}
            categorie = extra.get("categorie") or CAT_OVERIG
            presentatie = CATEGORIE_PRESENTATIE.get(
                categorie, CATEGORIE_PRESENTATIE[CAT_OVERIG]
            )
            datum = _nl_datum(item.datum) if item.datum else ""
            titel = _escape_md(_kort(item.titel, 70))
            link = item.document_url
            regel = f"{presentatie['emoji']} "
            regel += f"[{titel}]({link})" if link else titel
            if datum:
                regel += f" · {datum}"
            regels.append(regel)

        termen = ", ".join(_escape_proza(a.term) for a in abonnementen)
        kop = "Nieuwe zoekterm" if len(abonnementen) == 1 else "Nieuwe zoektermen"
        attachment = {
            "fallback": f"{len(items)} eerdere stukken gevonden voor {termen}",
            "color": "#64748B",
            "pretext": f":mag: **{kop}** · {termen}",
            "title": (
                "1 stuk uit de afgelopen week gevonden"
                if len(items) == 1
                else f"{len(items)} stukken uit de afgelopen week gevonden"
            ),
            "text": "\n".join(regels),
            "footer": (
                "Eenmalige inhaalslag bij het aanzetten. Hierna verschijnen "
                "alleen nieuwe stukken."
            ),
        }
        return "", {"attachments": [attachment]}

    async def markeer_niet_relevant(self, item_id: UUID) -> None:
        """Tel een wegklik bij elke term die dit stuk aandroeg.

        Deactiveert nooit automatisch: bij recall boven precisie is
        wegklikken normaal gedrag, en een term die zichzelf uitzet levert
        stil dekkingsverlies op. Het getal is een signaal voor de
        gebruiker, niet een schakelaar.
        """
        await self.abonnement_repo.markeer_weggeklikt(item_id)


def _relevantie(extra: dict) -> int:
    """Lees de relevantiescore uit extra_data, met een veilige default.

    Zonder score behandelen we het stuk als middenmoot: zichtbaar, niet
    schreeuwend. Een ontbrekende score mag nooit stilte betekenen.
    """
    waarde = extra.get("relevantie_score")
    # `bool` is een `int` in Python, en True zou dan score 1 worden — onder
    # elke drempel, dus stilte. En `int(float("nan"))` gooit een ValueError;
    # een taalmodel dat NaN in zijn JSON zet is niet exotisch.
    if isinstance(waarde, bool) or not isinstance(waarde, int | float):
        return DREMPEL_MIDDEN
    try:
        return max(0, min(100, int(waarde)))
    except (ValueError, OverflowError):
        return DREMPEL_MIDDEN


def _als_datum(waarde) -> date | None:
    """Lees een datum uit `extra_data`, waar hij als ISO-string staat."""
    if waarde is None:
        return None
    if isinstance(waarde, date) and not isinstance(waarde, datetime):
        return waarde
    if isinstance(waarde, datetime):
        return waarde.date()
    try:
        return date.fromisoformat(str(waarde)[:10])
    except ValueError:
        return None


def _nl_datum(waarde) -> str:
    """`24 september` — zonder jaar als het dit jaar is.

    Niet `strftime("%-d %B")`: dat volgt de locale van de container, en die
    staat in productie op C. Dan krijg je Engelse maandnamen in een
    Nederlands bericht.
    """
    d = _als_datum(waarde)
    if d is None:
        return ""
    maand = _NL_MAANDEN[d.month - 1]
    if d.year == date.today().year:
        return f"{d.day} {maand}"
    return f"{d.day} {maand} {d.year}"
