"""Abstract base class for LLM providers with capability-based data classification."""

import json
import logging
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DataSensitivity(StrEnum):
    """Data sensitivity levels for LLM provider routing."""

    PUBLIC = "public"  # Parliamentary data, public tag names
    INTERNAL = "internal"  # Corpus node titles/descriptions (policy content)
    CONFIDENTIAL = "confidential"  # Person names, org structure, tasks


class ProviderCapabilities(BaseModel):
    """Declares what data sensitivity levels a provider may process."""

    allowed_data: set[DataSensitivity]

    def supports(self, level: DataSensitivity) -> bool:
        return level in self.allowed_data


class TagExtractionResult(BaseModel):
    matched_tags: list[str]
    suggested_new_tags: list[str]
    samenvatting: str


class KamerstukAlertResult(BaseModel):
    """Samenvatting van een kamerstuk vanuit de zoekterm die het aandroeg."""

    samenvatting: str
    # 0-100: hoe centraal de zoekterm in het stuk staat. Stuurt de vorm van
    # het bericht, nooit of het gepost wordt — het vangnet staat bewust
    # breed en niets valt stil weg.
    relevantie_score: int
    reden: str
    # Een concrete vervolgactie als het stuk er een draagt: een
    # antwoordtermijn, een vergadering waar nog input op kan. Leeg als er
    # niets te doen is; het model mag niets verzinnen.
    actie: str = ""


class TagSuggestionResult(BaseModel):
    matched_tags: list[str]
    suggested_new_tags: list[str]


class EdgeRelevanceResult(BaseModel):
    score: float  # 0.0 - 1.0
    suggested_edge_type: str
    reason: str


class OpdrachtContactMatch(BaseModel):
    target_id: str
    link_type: str  # "person" | "organisatie_eenheid"
    confidence: float
    reason: str
    suggested_rol: str
    source_field: str | None = None


class OpdrachtContactMatchResult(BaseModel):
    matches: list[OpdrachtContactMatch]


class GapAnalysisResult(BaseModel):
    narrative: str
    recommendations: list[str]


class LeadCandidateClassification(BaseModel):
    is_lead: bool
    confidence: float
    proposed_title: str
    proposed_description: str
    match_existing_lead_id: str | None
    reasoning: str
    failed: bool = False
    """True als de LLM-call zelf mislukte (netwerk, parse-fout).

    Zonder dit is een onbereikbare LLM niet te onderscheiden van een echt
    oordeel "dit is geen lead": beide geven ``is_lead=False``. Dat verschil
    is wél belangrijk — een mislukte call betekent dat het bericht opnieuw
    beoordeeld moet worden, en de gebruiker hoort niet te horen dat er geen
    lead in zit terwijl er niemand gekeken heeft."""


class DebatVraag(BaseModel):
    """Eén vraag aan de bewindspersoon, zoals het model hem uit een beurt haalt."""

    citaat: str
    gericht_aan: str
    samenvatting: str
    # Het nummer van een vraag die al openstaat, als dit dezelfde vraag is.
    hoort_bij: int | None = None
    # Het nummer van het geagendeerde stuk waar de vraag over gaat.
    stuk: int | None = None


class DebatToezegging(BaseModel):
    """One toezegging of the bewindspersoon, as the model takes it from a turn."""

    citaat: str
    samenvatting: str
    # When, in the words of the speaker ("voor het kerstreces"), if said.
    termijn: str | None = None
    # The number of the open question this is the answer to.
    bij_vraag: int | None = None
    # The number of an earlier toezegging that is said again here.
    hoort_bij: int | None = None


DEBAT_VRAGEN_ONBEREIKBAAR = "onbereikbaar"
DEBAT_VRAGEN_ONBRUIKBAAR = "onbruikbaar"


class DebatVragenResult(BaseModel):
    vragen: list[DebatVraag] = []
    fout: str | None = None
    """Waarom er geen oordeel is, of ``None`` als het model heeft geoordeeld.

    Een lege lijst zonder fout betekent: gelezen, geen vraag. Dat is iets
    anders dan niet gelezen, en de aanroeper moet die twee uit elkaar kunnen
    houden.

    * ``onbereikbaar``: de call zelf mislukte (netwerk, time-out, login).
      Er is niets beoordeeld; later opnieuw proberen heeft zin.
    * ``onbruikbaar``: het model antwoordde twee keer met iets dat niet te
      lezen was. Nog een keer proberen levert waarschijnlijk hetzelfde op.
    """


class DebatToezeggingenResult(BaseModel):
    """What the model made of a turn of the bewindspersoon.

    `fout` means what it means in `DebatVragenResult`: an empty list
    without it is "read, nothing promised", and that is not "not read".
    """

    toezeggingen: list[DebatToezegging] = []
    fout: str | None = None


class DebatAgendapunt(BaseModel):
    """One agendapunt of a procedurevergadering and what the committee
    decided on it, as the model reads it from the chairman's words."""

    # The number the chairman calls it by ("27"), if said.
    nummer: str | None = None
    onderwerp: str
    besluiten: list[str] = []


class DebatBesluitenResult(BaseModel):
    """What the model made of a procedurevergadering so far.

    `fout` means what it means in `DebatVragenResult`: an empty list
    without it is "read, nothing decided yet", and that is not "not read".
    """

    agendapunten: list[DebatAgendapunt] = []
    # Only when the meeting is over: a few sentences on what matters most.
    samenvatting: str = ""
    fout: str | None = None


class LegeLLMResponsError(ValueError):
    """Het model gaf niets terug.

    Een eigen fout, omdat `json.loads("")` anders `Expecting value: line 1
    column 1 (char 0)` oplevert. Die melding leest als kapotte JSON en
    wijst naar de parser, terwijl het probleem bij de provider ligt. In
    productie kostte dat verschil een middag zoeken (25 september 2026):
    de traceback wees vier frames diep naar `json/decoder.py`, en wat er
    werkelijk stond was dat VLAM een lege string had teruggegeven.

    Erft van ValueError, zodat bestaande `except Exception`-paden hem
    blijven vangen en een lege respons nog steeds zacht faalt.
    """


class BaseLLMService(ABC):
    """Abstract base for all LLM providers."""

    capabilities: ProviderCapabilities

    def _parse_json(self, content: str) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks.

        Een lege respons krijgt een eigen fout. `json.loads("")` geeft
        anders `Expecting value: line 1 column 1 (char 0)`, en dat leest
        als kapotte JSON terwijl er niets terugkwam. In productie kostte
        dat verschil een middag zoeken (25 september 2026): de provider
        gaf een lege string terug en de traceback wees naar de parser.
        """
        import re

        if not content or not content.strip():
            raise LegeLLMResponsError(
                "het model gaf een lege respons terug (geen tekst om te lezen)"
            )

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        content = content.strip()
        # Fix trailing commas (common LLM issue)
        content = re.sub(r",\s*([}\]])", r"\1", content)
        return json.loads(content)

    @abstractmethod
    async def _complete(self, prompt: str, max_tokens: int = 1024) -> str:
        """Send a prompt to the LLM and return the text response."""
        ...

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
    ) -> Any:
        """Multi-turn chat with function-calling tools.

        Returns the raw ChatCompletion from the OpenAI-compatible API.
        Subclasses that support tool calling should override this.
        """
        raise NotImplementedError("This provider does not support tool calling")

    async def extract_tags(
        self,
        titel: str,
        onderwerp: str,
        document_tekst: str | None,
        bestaande_tags: list[str],
        context_hint: str = "motie",
    ) -> TagExtractionResult:
        """Extract relevant tags from a parliamentary item text.

        Only public text and tag names are sent. No corpus node content
        or personal data is included.
        """
        from bouwmeester.services.llm.prompts import build_extract_tags_prompt

        prompt = build_extract_tags_prompt(
            titel=titel,
            onderwerp=onderwerp,
            document_tekst=document_tekst,
            bestaande_tags=bestaande_tags,
            context_hint=context_hint,
        )
        try:
            # 2048 en niet de standaard 1024: het antwoord draagt een lijst
            # tags plus een samenvatting van twee zinnen, en een afgekapt
            # antwoord is geen geldige JSON. Andere aanroepen in dit
            # bestand zetten hun budget ook expliciet; deze twee vielen
            # stil terug op de standaard.
            text = await self._complete(prompt, max_tokens=2048)
            result = self._parse_json(text)
            return TagExtractionResult(
                matched_tags=result.get("matched_tags", []),
                suggested_new_tags=result.get("suggested_new_tags", []),
                samenvatting=result.get("samenvatting", ""),
            )
        except Exception:
            logger.exception("Fout bij LLM tag-extractie")
            # Leeg en niet "Tag-extractie mislukt". Deze waarde landt in
            # `ParlementairItem.llm_samenvatting`, en dat veld wordt
            # gepost als de tekst van een Mattermost-alert. Een interne
            # foutmelding stond daardoor in productie als samenvatting in
            # het kanaal (24 september 2026), waar hij eruitzag als iets
            # dat iemand had geschreven.
            #
            # Leeg is bovendien wat de rest van de keten al verwacht:
            # `format_alert` valt terug op het onderwerp zodra de
            # samenvatting leeg is, en dat gedrag werkte hier niet omdat
            # het veld gevuld was met een zin.
            return TagExtractionResult(
                matched_tags=[],
                suggested_new_tags=[],
                samenvatting="",
            )

    async def summarize_kamerstuk_alert(
        self,
        titel: str,
        onderwerp: str,
        document_tekst: str | None,
        zoektermen: list[str],
        categorie: str = "overig",
        soort: str | None = None,
        context_regels: list[str] | None = None,
        signaalcontext: str | None = None,
    ) -> "KamerstukAlertResult":
        """Vat een kamerstuk samen vanuit de zoekterm die het aandroeg.

        `categorie` en `soort` komen uit de TK-API en vertellen het model
        wát voor stuk dit is: een agenda van een vergadering die nog moet
        komen vraagt om een ander bericht dan een besluitenlijst van een
        vergadering die geweest is.

        `signaalcontext` is de vrije tekst van het dossier zelf: waar het
        over gaat en vooral wat er níét bij hoort. Een zoekterm kan het
        verschil tussen een projectnaam en een staande metafoor niet
        maken; dit is waar dat oordeel vandaan komt.

        Alleen publieke tekst en de zoektermen gaan de LLM in; het stuk
        staat op tweedekamer.nl.
        """
        from bouwmeester.services.llm.prompts import build_kamerstuk_alert_prompt

        prompt = build_kamerstuk_alert_prompt(
            titel=titel,
            onderwerp=onderwerp,
            document_tekst=document_tekst,
            zoektermen=zoektermen,
            categorie=categorie,
            soort=soort,
            context_regels=context_regels,
            signaalcontext=signaalcontext,
        )
        # Twee pogingen. Een alert is eenmalig: mislukt de samenvatting,
        # dan valt het bericht terug op de titel en komt het stuk nooit
        # meer langs — de volgende ronde ziet het als bekend. Dat is een
        # andere afweging dan bij een achtergrondtaak die vanzelf opnieuw
        # draait.
        #
        # Waarom dit nodig bleek: op 24 en 25 september 2026 kwam een
        # kamerstuk en een agenda zonder samenvatting in het kanaal,
        # terwijl dezelfde prompt handmatig in één keer een bruikbaar
        # antwoord gaf. De oorzaak was niet te achterhalen omdat de logs
        # te kort bewaard blijven; een tweede poging kost weinig en dekt
        # de vluchtige gevallen (time-out, een hapering in de CLI).
        laatste: Exception | None = None
        for poging in (1, 2):
            try:
                # Idem: samenvatting, reden en actie in één JSON.
                text = await self._complete(prompt, max_tokens=2048)
                result = self._parse_json(text)
                score = result.get("relevantie_score", 50)
                if not isinstance(score, int | float):
                    score = 50
                return KamerstukAlertResult(
                    samenvatting=str(result.get("samenvatting", "")).strip(),
                    relevantie_score=max(0, min(100, int(score))),
                    reden=str(result.get("reden", "")).strip(),
                    actie=str(result.get("actie", "") or "").strip(),
                )
            except Exception as exc:
                laatste = exc
                if poging == 1:
                    logger.warning(
                        "Samenvatting mislukt (poging 1, %s: %s), nog een keer",
                        type(exc).__name__,
                        str(exc)[:200],
                    )

        # Geen samenvatting is geen reden om het stuk te verzwijgen: het
        # bericht valt terug op de titel. De reden gaat mee naar de
        # aanroeper, die hem logt met het documentnummer erbij.
        logger.exception(
            "Samenvatting definitief mislukt na twee pogingen",
            exc_info=laatste,
        )
        return KamerstukAlertResult(
            samenvatting="",
            relevantie_score=50,
            reden=(
                f"samenvatting mislukt: {type(laatste).__name__}"
                if laatste
                else "samenvatting mislukt"
            ),
        )

    async def suggest_tags(
        self,
        title: str,
        description: str | None,
        node_type: str,
        bestaande_tags: list[str],
    ) -> TagSuggestionResult:
        """Suggest tags for a corpus node based on its content."""
        from bouwmeester.services.llm.prompts import build_suggest_tags_prompt

        prompt = build_suggest_tags_prompt(
            title=title,
            description=description,
            node_type=node_type,
            bestaande_tags=bestaande_tags,
        )
        try:
            text = await self._complete(prompt)
            result = self._parse_json(text)
            return TagSuggestionResult(
                matched_tags=result.get("matched_tags", []),
                suggested_new_tags=result.get("suggested_new_tags", []),
            )
        except Exception:
            logger.exception("Fout bij LLM tag-suggestie")
            return TagSuggestionResult(matched_tags=[], suggested_new_tags=[])

    async def score_edge_relevance(
        self,
        source_title: str,
        source_description: str | None,
        target_title: str,
        target_description: str | None,
    ) -> EdgeRelevanceResult:
        """Score the relevance of a potential edge between two nodes."""
        from bouwmeester.services.llm.prompts import build_edge_relevance_prompt

        prompt = build_edge_relevance_prompt(
            source_title=source_title,
            source_description=source_description,
            target_title=target_title,
            target_description=target_description,
        )
        try:
            text = await self._complete(prompt)
            result = self._parse_json(text)
            return EdgeRelevanceResult(
                score=float(result.get("score", 0.0)),
                suggested_edge_type=result.get(
                    "suggested_edge_type", "gerelateerd_aan"
                ),
                reason=result.get("reason", ""),
            )
        except Exception:
            logger.exception("Fout bij LLM edge-relevantie scoring")
            return EdgeRelevanceResult(
                score=0.0,
                suggested_edge_type="gerelateerd_aan",
                reason="Scoring mislukt",
            )

    async def match_opdracht_contacts(
        self,
        opdracht_titel: str,
        opdracht_beschrijving: str | None,
        fcc_contact_fields: dict[str, str],
        fcc_afdeling: str | None,
        kandidaat_personen: list[dict],
        kandidaat_eenheden: list[dict],
    ) -> OpdrachtContactMatchResult:
        """Match persons and org units to an opdracht using LLM analysis."""
        from bouwmeester.services.llm.prompts import (
            build_match_opdracht_contacts_prompt,
        )

        prompt = build_match_opdracht_contacts_prompt(
            opdracht_titel=opdracht_titel,
            opdracht_beschrijving=opdracht_beschrijving,
            fcc_contact_fields=fcc_contact_fields,
            fcc_afdeling=fcc_afdeling,
            kandidaat_personen=kandidaat_personen,
            kandidaat_eenheden=kandidaat_eenheden,
        )
        try:
            text = await self._complete(prompt, max_tokens=2048)
            result = self._parse_json(text)
            matches = [
                OpdrachtContactMatch(**m)
                for m in result.get("matches", [])
                if m.get("confidence", 0) >= 0.5
            ]
            return OpdrachtContactMatchResult(matches=matches)
        except Exception:
            logger.exception("Fout bij LLM opdracht contact matching")
            return OpdrachtContactMatchResult(matches=[])

    async def generate_gap_analysis(
        self,
        dossier_title: str,
        dossier_description: str | None,
        gaps: list[dict],
    ) -> GapAnalysisResult:
        """Generate a narrative summary and recommendations for policy gaps."""
        from bouwmeester.services.llm.prompts import build_gap_analysis_prompt

        prompt = build_gap_analysis_prompt(
            dossier_title=dossier_title,
            dossier_description=dossier_description,
            gaps=gaps,
        )
        try:
            text = await self._complete(prompt, max_tokens=1024)
            result = self._parse_json(text)
            return GapAnalysisResult(
                narrative=result.get("narrative", ""),
                recommendations=result.get("recommendations", []),
            )
        except Exception:
            logger.exception("Fout bij LLM gap-analyse")
            return GapAnalysisResult(narrative="", recommendations=[])

    async def markeer_debat_vragen(
        self,
        *,
        onderwerp: str,
        soort_vergadering: str | None,
        bewindspersonen: list[str],
        stukken: list[str],
        openstaand: list[tuple[int, str, str]],
        spreker: str,
        interruptie: bool,
        tekst: str,
        onderbroken: str | None = None,
        initiatiefnemers: bool = False,
        initiatiefnemer_namen: list[str] | None = None,
        spreker_is_initiatiefnemer: bool = False,
    ) -> DebatVragenResult:
        """Haal uit één spreekbeurt de vragen aan de bewindspersoon.

        `openstaand` is de lijst vragen van deze spreker die al gemarkeerd
        zijn en nog openstaan, als (nummer, vragensteller, samenvatting). Het model
        zegt per vraag of hij nieuw is of bij een van die nummers hoort.
        `onderbroken` is bij een interruptie wie er het woord had.
        `initiatiefnemers` zegt dat er naast de bewindspersoon Kamerleden
        zitten die zelf vragen beantwoorden, zoals bij een initiatiefnota.
        `initiatiefnemer_namen` zijn hun namen als die bekend zijn, en
        `spreker_is_initiatiefnemer` zegt dat deze beurt van een van hen is.

        PUBLIC: een debat is openbaar en wordt uitgezonden.
        """
        from bouwmeester.services.llm.prompts import build_debat_vragen_prompt

        prompt = build_debat_vragen_prompt(
            onderwerp=onderwerp,
            soort_vergadering=soort_vergadering,
            bewindspersonen=bewindspersonen,
            stukken=stukken,
            openstaand=openstaand,
            spreker=spreker,
            interruptie=interruptie,
            tekst=tekst,
            onderbroken=onderbroken,
            initiatiefnemers=initiatiefnemers,
            initiatiefnemer_namen=initiatiefnemer_namen,
            spreker_is_initiatiefnemer=spreker_is_initiatiefnemer,
        )
        # Twee pogingen voor een onleesbaar antwoord, geen voor een
        # onbereikbaar model. Een beurt komt maar één keer langs, dus een
        # antwoord dat net geen JSON was verdient een tweede kans; een model
        # dat niet antwoordt wordt door de aanroeper later opnieuw gevraagd.
        for poging in (1, 2):
            try:
                text = await self._complete(prompt, max_tokens=2048)
            except Exception:
                logger.exception("LLM onbereikbaar bij het markeren van debatvragen")
                return DebatVragenResult(fout=DEBAT_VRAGEN_ONBEREIKBAAR)
            try:
                return DebatVragenResult(vragen=_lees_debat_vragen(self, text))
            except Exception as exc:
                logger.warning(
                    "Onbruikbaar LLM-antwoord bij debatvragen (poging %d, %s: %s)",
                    poging,
                    type(exc).__name__,
                    str(exc)[:200],
                )
        return DebatVragenResult(fout=DEBAT_VRAGEN_ONBRUIKBAAR)

    async def markeer_debat_toezeggingen(
        self,
        *,
        onderwerp: str,
        soort_vergadering: str | None,
        bewindspersonen: list[str],
        spreker: str,
        tekst: str,
        vragen: list[tuple[int, str, str]],
        eerdere: list[tuple[int, str]],
        voorafgaand: str | None = None,
        voorafgaand_tekst: str = "",
        passages: list[str] | None = None,
    ) -> DebatToezeggingenResult:
        """Take the toezeggingen from one turn of the bewindspersoon.

        `vragen` are the open questions put to this bewindspersoon, as
        (number, who asked, summary); the model may say of a toezegging
        which one it answers. `eerdere` are the toezeggingen this
        bewindspersoon made before in the debate, as (number, summary), so
        that one said again is not marked twice. `voorafgaand` is the
        member whose interruption came right before this turn, with what
        they said: "dat zeg ik toe" cannot be summarised without it.
        `passages` are sentences of the turn to look at in any case.

        The same two tries as for the questions, and for the same reason.

        PUBLIC: a debate is public and broadcast.
        """
        from bouwmeester.services.llm.prompts import (
            build_debat_toezeggingen_prompt,
        )

        prompt = build_debat_toezeggingen_prompt(
            onderwerp=onderwerp,
            soort_vergadering=soort_vergadering,
            bewindspersonen=bewindspersonen,
            spreker=spreker,
            tekst=tekst,
            vragen=vragen,
            eerdere=eerdere,
            voorafgaand=voorafgaand,
            voorafgaand_tekst=voorafgaand_tekst,
            passages=passages,
        )
        # Room for a window in which nearly every sentence promises
        # something: a reply that is cut off is not JSON, and the second
        # try would be cut off at the same place.
        for poging in (1, 2):
            try:
                text = await self._complete(prompt, max_tokens=4096)
            except Exception:
                logger.exception("LLM onbereikbaar bij het markeren van toezeggingen")
                return DebatToezeggingenResult(fout=DEBAT_VRAGEN_ONBEREIKBAAR)
            try:
                return DebatToezeggingenResult(
                    toezeggingen=_lees_debat_toezeggingen(self, text)
                )
            except Exception as exc:
                logger.warning(
                    "Onbruikbaar LLM-antwoord bij toezeggingen (poging %d, %s: %s)",
                    poging,
                    type(exc).__name__,
                    str(exc)[:200],
                )
        return DebatToezeggingenResult(fout=DEBAT_VRAGEN_ONBRUIKBAAR)

    async def markeer_debat_slotlijst(
        self,
        *,
        onderwerp: str,
        soort_vergadering: str | None,
        tekst: str,
        eerdere: list[tuple[int, str, str]],
    ) -> DebatToezeggingenResult:
        """Take the items from the list of toezeggingen the chairman reads
        out at the end of a debate.

        `tekst` is what the chairman said from the opening of the list on.
        `eerdere` are the toezeggingen that were marked during the debate,
        as (number, who promised, summary). An item comes back as a
        `DebatToezegging` whose `hoort_bij` is the number of the one it
        is, or ``None`` for one that was not marked; `bij_vraag` is never
        set.

        The same two tries as for the questions, and for the same reason.

        PUBLIC: a debate is public and broadcast.
        """
        from bouwmeester.services.llm.prompts import build_debat_slotlijst_prompt

        prompt = build_debat_slotlijst_prompt(
            onderwerp=onderwerp,
            soort_vergadering=soort_vergadering,
            tekst=tekst,
            eerdere=eerdere,
        )
        for poging in (1, 2):
            try:
                text = await self._complete(prompt, max_tokens=4096)
            except Exception:
                logger.exception("LLM onbereikbaar bij het lezen van de slotlijst")
                return DebatToezeggingenResult(fout=DEBAT_VRAGEN_ONBEREIKBAAR)
            try:
                gelezen = _lees_debat_toezeggingen(self, text)
            except Exception as exc:
                logger.warning(
                    "Onbruikbaar LLM-antwoord bij de slotlijst (poging %d, %s: %s)",
                    poging,
                    type(exc).__name__,
                    str(exc)[:200],
                )
                continue
            # A list answers no question: a number the model put there
            # anyway is not passed on.
            return DebatToezeggingenResult(
                toezeggingen=[
                    item.model_copy(update={"bij_vraag": None}) for item in gelezen
                ]
            )
        return DebatToezeggingenResult(fout=DEBAT_VRAGEN_ONBRUIKBAAR)

    async def vat_procedurevergadering_samen(
        self,
        *,
        onderwerp: str,
        agenda: list[str],
        tekst: str,
        eerder: list[DebatAgendapunt],
        af: bool,
    ) -> DebatBesluitenResult:
        """Put what was said in a procedurevergadering in order: per
        agendapunt what the committee decided.

        `agenda` are the agendapunten as the TK API lists them, `eerder`
        what an earlier reading of the same meeting found, `af` whether
        the meeting is over (then a samenvatting is asked for too).

        Two tries, like the other readings of a debate.

        PUBLIC: a procedurevergadering is public and broadcast.
        """
        from bouwmeester.services.llm.prompts import (
            build_procedurevergadering_prompt,
        )

        prompt = build_procedurevergadering_prompt(
            onderwerp=onderwerp,
            agenda=agenda,
            tekst=tekst,
            eerder=[(p.nummer, p.onderwerp, p.besluiten) for p in eerder],
            af=af,
        )
        for poging in (1, 2):
            try:
                text = await self._complete(prompt, max_tokens=4096)
            except Exception:
                logger.exception("LLM onbereikbaar bij de procedurevergadering")
                return DebatBesluitenResult(fout=DEBAT_VRAGEN_ONBEREIKBAAR)
            try:
                return _lees_besluiten(self, text, af=af)
            except Exception as exc:
                logger.warning(
                    "Onbruikbaar LLM-antwoord bij de procedurevergadering "
                    "(poging %d, %s: %s)",
                    poging,
                    type(exc).__name__,
                    str(exc)[:200],
                )
        return DebatBesluitenResult(fout=DEBAT_VRAGEN_ONBRUIKBAAR)

    async def is_mattermost_noise(self, message: str) -> bool:
        """True als het bericht ruis is (ack/emoji/no-content)."""
        from bouwmeester.services.llm.prompts import build_is_noise_prompt

        prompt = build_is_noise_prompt(message)
        try:
            text = await self._complete(prompt, max_tokens=64)
            result = self._parse_json(text)
            return bool(result.get("is_noise", False))
        except Exception:
            logger.exception("Fout bij LLM noise-classificatie")
            return False  # Bij twijfel: behouden.

    async def summarize_mattermost_message(
        self, message: str, *, max_words: int = 80
    ) -> str:
        """Vat een lang MM-bericht samen. Returns lege string bij fout."""
        from bouwmeester.services.llm.prompts import (
            build_summarize_mattermost_thread_prompt,
        )

        prompt = build_summarize_mattermost_thread_prompt(
            message=message, max_words=max_words
        )
        try:
            text = await self._complete(prompt, max_tokens=300)
            result = self._parse_json(text)
            return str(result.get("samenvatting") or "")
        except Exception:
            logger.exception("Fout bij LLM samenvatting")
            return ""

    async def classify_mattermost_lead_candidate(
        self,
        *,
        message: str,
        initiatief_naam: str,
        channel_display_name: str,
        recent_leads: list[dict],
        explicit_request: bool = False,
    ) -> LeadCandidateClassification:
        """Classificeer een Mattermost-bericht als (mogelijke) lead.

        Wordt aangeroepen voor berichten in een aan een initiatief gekoppeld
        kanaal. CONFIDENTIAL: alleen door VLAM uitvoerbaar.
        """
        from bouwmeester.services.llm.prompts import (
            build_classify_mattermost_lead_prompt,
        )

        prompt = build_classify_mattermost_lead_prompt(
            message=message,
            initiatief_naam=initiatief_naam,
            channel_display_name=channel_display_name,
            recent_leads=recent_leads,
            explicit_request=explicit_request,
        )
        try:
            text = await self._complete(prompt, max_tokens=512)
        except Exception:
            # Netwerk, time-out, rate-limit: de LLM heeft niets gezegd, dus
            # er is niets beoordeeld. Wél opnieuw proberen.
            logger.exception("LLM onbereikbaar bij lead-classificatie")
            return LeadCandidateClassification(
                is_lead=False,
                confidence=0.0,
                proposed_title="",
                proposed_description="",
                match_existing_lead_id=None,
                reasoning="LLM-call mislukt",
                failed=True,
            )

        try:
            result = self._parse_json(text)
            match_id = result.get("match_existing_lead_id")
            if isinstance(match_id, str):
                match_id = match_id.strip() or None
            else:
                match_id = None
            try:
                raw_confidence = float(result.get("confidence") or 0.0)
            except (TypeError, ValueError):
                raw_confidence = 0.0
            confidence = max(0.0, min(1.0, raw_confidence))
            return LeadCandidateClassification(
                is_lead=bool(result.get("is_lead", False)),
                confidence=confidence,
                proposed_title=str(result.get("proposed_title") or "")[:500],
                proposed_description=str(result.get("proposed_description") or ""),
                match_existing_lead_id=match_id,
                reasoning=str(result.get("reasoning") or ""),
            )
        except Exception:
            # De LLM antwoordde wél, maar onbruikbaar (geen JSON, of
            # afgekapt op de token-limiet). Opnieuw proberen levert
            # waarschijnlijk hetzelfde op, dus niet als ``failed`` markeren:
            # die post zou anders elke ronde terugkomen en telkens een
            # LLM-call kosten zonder ooit uit de wachtrij te verdwijnen.
            logger.exception("Onbruikbaar LLM-antwoord bij lead-classificatie")
            return LeadCandidateClassification(
                is_lead=False,
                confidence=0.0,
                proposed_title="",
                proposed_description="",
                match_existing_lead_id=None,
                reasoning="LLM-antwoord niet te lezen",
            )


def _heel_getal(value: object) -> int | None:
    """Een nummer uit het antwoord, of ``None`` voor alles wat er geen is."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _lees_debat_vragen(service: BaseLLMService, text: str) -> list[DebatVraag]:
    """Lees het antwoord op de debatvragen-prompt.

    Gooit een fout als het antwoord als geheel niet te lezen is. Eén vraag
    die niet deugt (geen citaat) valt weg zonder de rest mee te nemen.
    """
    result = service._parse_json(text)
    if not isinstance(result, dict) or not isinstance(result.get("vragen"), list):
        raise ValueError("antwoord draagt geen lijst `vragen`")
    vragen: list[DebatVraag] = []
    for item in result["vragen"]:
        if not isinstance(item, dict):
            continue
        citaat = item.get("citaat")
        if not isinstance(citaat, str) or not citaat.strip():
            continue
        vragen.append(
            DebatVraag(
                citaat=citaat.strip(),
                gericht_aan=str(item.get("gericht_aan") or "").strip(),
                samenvatting=str(item.get("samenvatting") or "").strip(),
                hoort_bij=_heel_getal(item.get("hoort_bij")),
                stuk=_heel_getal(item.get("stuk")),
            )
        )
    return vragen


def _lees_debat_toezeggingen(
    service: BaseLLMService, text: str
) -> list[DebatToezegging]:
    """Read the answer to the toezeggingen prompt.

    Raises when the answer as a whole cannot be read. One item that is no
    good (no quote) is left out without taking the rest along.
    """
    result = service._parse_json(text)
    if not isinstance(result, dict) or not isinstance(result.get("toezeggingen"), list):
        raise ValueError("antwoord draagt geen lijst `toezeggingen`")
    toezeggingen: list[DebatToezegging] = []
    for item in result["toezeggingen"]:
        if not isinstance(item, dict):
            continue
        citaat = item.get("citaat")
        if not isinstance(citaat, str) or not citaat.strip():
            continue
        termijn = item.get("termijn")
        toezeggingen.append(
            DebatToezegging(
                citaat=citaat.strip(),
                samenvatting=str(item.get("samenvatting") or "").strip(),
                termijn=termijn.strip()
                if isinstance(termijn, str) and termijn.strip()
                else None,
                bij_vraag=_heel_getal(item.get("bij_vraag")),
                hoort_bij=_heel_getal(item.get("hoort_bij")),
            )
        )
    return toezeggingen


def _lees_besluiten(
    service: BaseLLMService, text: str, *, af: bool
) -> DebatBesluitenResult:
    """Read the answer to the procedurevergadering prompt.

    Raises when the answer as a whole cannot be read. An agendapunt
    without a subject is left out without taking the rest along, and so
    is a decision that is not a line of text.
    """
    result = service._parse_json(text)
    if not isinstance(result, dict) or not isinstance(result.get("agendapunten"), list):
        raise ValueError("antwoord draagt geen lijst `agendapunten`")
    punten: list[DebatAgendapunt] = []
    for item in result["agendapunten"]:
        if not isinstance(item, dict):
            continue
        onderwerp = item.get("onderwerp")
        if not isinstance(onderwerp, str) or not onderwerp.strip():
            continue
        nummer = item.get("nummer")
        if isinstance(nummer, int) and not isinstance(nummer, bool):
            nummer = str(nummer)
        besluiten = item.get("besluiten")
        punten.append(
            DebatAgendapunt(
                nummer=nummer.strip()
                if isinstance(nummer, str) and nummer.strip()
                else None,
                onderwerp=onderwerp.strip(),
                besluiten=[
                    b.strip()
                    for b in (besluiten if isinstance(besluiten, list) else [])
                    if isinstance(b, str) and b.strip()
                ],
            )
        )
    samenvatting = result.get("samenvatting")
    return DebatBesluitenResult(
        agendapunten=punten,
        # Asked for only at the end; a model that gives one halfway is
        # not shown, it would read as final.
        samenvatting=samenvatting.strip()
        if af and isinstance(samenvatting, str)
        else "",
    )
