"""Verwerking van Mattermost-posts in gekoppelde kanalen.

Per binnenkomend ``posted``-event:
- skip bot-eigen berichten en niet-gekoppelde kanalen
- match auteur via bestaande ``mattermost_user``-link
- voor lead-scope met ``auto_note_enabled``: maak ``LeadActivity`` (note),
  haal doc-links op naar ``LeadAttachment(soort=link)`` en download
  native Mattermost file-uploads naar ``LeadAttachment(soort=file)``
- voor initiatief-scope met ``suggest_leads_enabled``: nog niet — komt in
  PR3 (hier alleen ``mattermost_post_link``-record)
- altijd: schrijf ``mattermost_post_link`` zodat de post niet opnieuw
  wordt verwerkt

Een expliciete ``@bouwmeester``-vermelding is een menselijk signaal en krijgt
aparte behandeling: de ruis-classificatie wordt overgeslagen (iemand zegt al
dat dit relevant is) en de bot bevestigt kort in de thread wat hij ermee
heeft gedaan. In een ongekoppeld kanaal legt hij uit dat hij niet meeleest —
anders is "niets zien gebeuren" niet te onderscheiden van "de bot is stuk".
"""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.database import async_session
from bouwmeester.core.storage import (
    ALLOWED_CONTENT_TYPES,
    MAX_UPLOAD_SIZE,
    store_upload,
    verify_content_type,
)
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.lead_activity import LeadActivity
from bouwmeester.models.lead_attachment import LeadAttachment
from bouwmeester.models.mattermost_channel_link import (
    SCOPE_INITIATIEF,
    SCOPE_LEAD,
)
from bouwmeester.models.mattermost_post_link import MattermostPostLink
from bouwmeester.models.suggested_lead import (
    STATUS_PENDING,
    SuggestedLead,
)
from bouwmeester.repositories.mattermost_channel_link import (
    MattermostChannelLinkRepository,
)
from bouwmeester.repositories.mattermost_user import MattermostUserRepository
from bouwmeester.services.mattermost_doc_link_extractor import (
    derive_attachment_label,
    extract_doc_links,
)
from bouwmeester.services.mattermost_mention_renderer import (
    render_mattermost_message_to_markdown,
)
from bouwmeester.services.mention_helper import sync_and_notify_mentions

logger = logging.getLogger(__name__)

# Hoe lang we in een ongekoppeld kanaal zwijgen na een uitleg-reply. Zonder
# deze rem zou elke "@bouwmeester?" in een druk kanaal een nieuwe bot-post
# opleveren. Eén uitleg per kanaal per uur is genoeg om het misverstand weg
# te nemen zonder het kanaal vol te zetten.
_UNLINKED_HINT_COOLDOWN_SECONDS = 3600
# Kortere cooldown na een mislukte poging: snel genoeg om een tijdelijke
# storing te overleven, lang genoeg om niet te hameren op een kanaal waar
# de bot structureel niet mag posten.
_UNLINKED_HINT_RETRY_SECONDS = 300
_UNLINKED_HINT_CACHE_CAP = 256

# channel_id -> monotonic timestamp van de laatste uitleg-reply. In-process:
# de worker is een singleton (zie WorkerLock), en na een herstart één extra
# uitleg posten is onschuldig. Een DB-tabel hiervoor zou zwaarder zijn dan
# het probleem.
_unlinked_hint_sent_at: OrderedDict[str, float] = OrderedDict()


def _claim_unlinked_hint(channel_id: str) -> bool:
    """True als we nú een uitleg mogen posten in dit kanaal (en claimt 'm)."""
    now = time.monotonic()
    last = _unlinked_hint_sent_at.get(channel_id)
    if last is not None and (now - last) < _UNLINKED_HINT_COOLDOWN_SECONDS:
        return False
    _unlinked_hint_sent_at[channel_id] = now
    _unlinked_hint_sent_at.move_to_end(channel_id)
    while len(_unlinked_hint_sent_at) > _UNLINKED_HINT_CACHE_CAP:
        _unlinked_hint_sent_at.popitem(last=False)
    return True


def _backoff_unlinked_hint(channel_id: str) -> None:
    """Zet de claim terug op een korte cooldown na een mislukte poging.

    Niet volledig vrijgeven: in een kanaal waar de bot permanent niet mag
    posten (403) zou elke mention anders een nieuwe API-call en een volledige
    stacktrace in de logs opleveren.
    """
    _unlinked_hint_sent_at[channel_id] = (
        time.monotonic()
        - _UNLINKED_HINT_COOLDOWN_SECONDS
        + _UNLINKED_HINT_RETRY_SECONDS
    )


# (post_id, edit_at) van bewerkingen die al verwerkt zijn. Mattermost stuurt
# ``post_edited`` ook bij pinnen en losmaken; ``edit_at`` blijft dan gelijk,
# en zonder deze rem kost elke pin een LLM-call.
_EDIT_CACHE_CAP = 512
_seen_edits: OrderedDict[tuple[str, int], None] = OrderedDict()


def _claim_edit(post_id: str, edit_at: int) -> bool:
    """True als deze bewerking nog niet verwerkt is (en claimt 'm)."""
    key = (post_id, edit_at)
    if key in _seen_edits:
        return False
    _seen_edits[key] = None
    while len(_seen_edits) > _EDIT_CACHE_CAP:
        _seen_edits.popitem(last=False)
    return True


def message_mentions_bot(message: str, bot_username: str | None) -> bool:
    """True als ``message`` de bot expliciet aanspreekt met ``@username``.

    Bewust alleen een echte mention van de bot-username: ``@channel``,
    ``@here`` en het los voorkomende woord "bouwmeester" tellen niet. Anders
    zou elk bericht dat over het product gaat de bot laten reageren.
    """
    if not bot_username or not message:
        return False
    # Rechts mag geen langere username volgen. `\b` alleen is niet genoeg,
    # want `.`, `-` en `_` zijn geldige username-tekens maar tellen voor
    # `\b` als grens — dan zou `@bouwmeester-test` ook matchen.
    #
    # `.` en `-` sluiten we alleen uit als er een woordteken achteraan komt,
    # anders zou een mention aan het eind van een zin ("leg dit vast
    # @bouwmeester.") niet matchen. Dat is juist het natuurlijkste geval, en
    # een Mattermost-username mag sowieso niet op een punt eindigen.
    pattern = rf"(?<![\w@])@{re.escape(bot_username)}(?![\w]|[.\-]\w)"
    return re.search(pattern, message, re.IGNORECASE) is not None


# Selectie van bestaande leads die meegaan in de LLM-prompt voor
# duplicate-detection. We nemen een unie van twee groepen, dedupliceren op
# id en cappen op MAX_LEADS_FOR_LLM:
#   1. de N nieuwste leads (vangt kwesties op die nog actief gespeeld worden)
#   2. de M leads waarvan titel/organisatie het meest lijkt op het
#      bericht via pg_trgm word_similarity (vangt oude leads waarvan de
#      naam expliciet genoemd wordt)
RECENT_LEADS_FOR_LLM = 25
SIMILAR_LEADS_FOR_LLM = 50
SIMILAR_LEAD_THRESHOLD = 0.3
MAX_LEADS_FOR_LLM = 60

# Bij een mention in een thread gaat de thread mee naar de LLM. Een thread
# met meer posts dan dit is een discussie, geen intake; de laatste posts
# tellen dan. De limiet per post houdt één geplakte mailwisseling binnen het
# prompt-budget (MAX_TEXT_IN_PROMPT) zonder de rest te verdringen.
THREAD_POSTS_FOR_LLM = 30
THREAD_POST_CHARS_FOR_LLM = 4000


# Fallback labels voor de 7 default-stages. De echte naam komt sinds
# per-initiatief lead_columns uit `lead_column.name`; deze map dient
# alleen als reservering wanneer de stage-slug niet (meer) als kolom
# bestaat (orphan-data, oude rij).
_DEFAULT_STAGE_LABELS = {
    "inbox": "Inbox",
    "verkennen": "Verkennen",
    "eerste_gesprek": "Eerste gesprek",
    "interne_check": "Interne check",
    "follow_up": "Follow-up",
    "in_the_pocket": "In the pocket",
    "koelkast": "Koelkast",
}


async def handle_dm_post(post: dict, *, bot_user_id: str | None = None) -> bool:
    """Verwerk een DM naar de bot: zoek link-code, koppel account.

    Draait in een eigen ``async_session`` zodat fouten in
    ``MattermostLinkPoller`` (bijvoorbeeld een ``IntegrityError`` op een
    race-conditie bij ``create_mapping``) niet doorslaan naar de session
    waar de caller in zit. Bij een crash is alleen deze ene DM verloren.

    Skip bot-eigen DMs als ``bot_user_id`` bekend is — anti
    feedback-loop voor bevestigingsreplies van de bot zelf. Bot-skips
    tellen als ``True`` (niets te doen, geslaagd).

    Returns ``True`` als de post zonder fouten is doorgelopen, ``False``
    als er een exception was. De caller gebruikt dit om te beslissen
    of de post in een dedup-cache mag — een mislukte DM moet bij
    recovery opnieuw kunnen worden geprobeerd.
    """
    if bot_user_id and post.get("user_id") == bot_user_id:
        return True

    from bouwmeester.services.mattermost_link_poller import MattermostLinkPoller
    from bouwmeester.services.mattermost_service import MattermostService

    async with async_session() as dm_session:
        mm_service = MattermostService(dm_session)
        try:
            poller = MattermostLinkPoller(dm_session, mm_service=mm_service)
            try:
                await poller.process_posts([post])
                await dm_session.commit()
                return True
            except Exception:
                await dm_session.rollback()
                logger.exception("DM-handling faalde voor post %s", post.get("id"))
                return False
        finally:
            await mm_service.close()


class MattermostIngestService:
    """Stateless verwerking — instantieer per session, gooi daarna weg."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        bot_user_id: str | None = None,
        bot_username: str | None = None,
        mm_base_url: str | None = None,
    ):
        self.session = session
        self.bot_user_id = bot_user_id
        self.bot_username = bot_username
        self.mm_base_url = mm_base_url.rstrip("/") if mm_base_url else None
        # Waarom de LLM de laatste post afwees; de mention-bevestiging noemt
        # het, zodat "geen lead" geen zwarte doos is.
        self._no_lead_reasoning: str | None = None

    async def ingest_post(
        self,
        post: dict,
        *,
        channel_type: str | None = None,
        reply_to_mentions: bool = True,
        reprocess: bool = False,
    ) -> None:
        """Verwerk één Mattermost-post.

        De caller is verantwoordelijk voor commit/rollback van de session.

        ``channel_type`` komt uit de ``data.channel_type`` van het Mattermost
        ``posted``-event: ``"D"`` = 1-op-1 DM (link-code-pad),
        ``"G"`` = group-DM (genegeerd, consistent met legacy poller-gedrag),
        andere waardes (``"O"`` open, ``"P"`` private) of ``None`` vallen
        door naar de channel-link-flow.
        """
        post_id = post.get("id")
        channel_id = post.get("channel_id")
        if not post_id or not channel_id:
            return

        mm_user_id = post.get("user_id") or None
        root_id = post.get("root_id") or None

        # Skip bot's eigen posts (anti feedback-loop).
        if self.bot_user_id and mm_user_id == self.bot_user_id:
            return

        if channel_type == "D":
            await handle_dm_post(post, bot_user_id=self.bot_user_id)
            return
        if channel_type == "G":
            return

        message = post.get("message") or ""
        # Zonder bekende bot-user-id kunnen we eigen posts niet herkennen
        # (zie de skip hierboven). Dan geen replies plaatsen: de bot zou
        # zijn eigen bevestigingen als gebruikersberichten inlezen.
        mentions_bot = bool(self.bot_user_id) and message_mentions_bot(
            message, self.bot_username
        )

        link_repo = MattermostChannelLinkRepository(self.session)
        channel_link = await link_repo.get_by_channel_id(channel_id)
        if channel_link is None or channel_link.disabled_at is not None:
            if reprocess:
                # Het kanaal is ontkoppeld sinds de post geparkeerd werd.
                # Markeren en uit de wachtrij halen, anders blijft hij elke
                # ronde terugkomen voor een classificatie die niet meer kan.
                await self._mark_reprocess_outcome(post_id, "channel_unlinked")
                return
            # Normaal zwijgen we in een ongekoppeld kanaal. Maar wie de bot
            # direct aanspreekt en niets terugkrijgt, concludeert dat hij
            # stuk is — dat is precies hoe een werkende bot voor dood werd
            # versleten. Eén korte uitleg neemt dat misverstand weg.
            if mentions_bot:
                await self._handle_unlinked_mention(
                    post_id=post_id,
                    channel_id=channel_id,
                    root_id=root_id,
                    mm_user_id=mm_user_id,
                )
            return

        # Idempotency-check vóór insert vermijdt een IntegrityError-rollback
        # die in een ge-savepointe testtransactie de hele session sloopt.
        existing_stmt = select(MattermostPostLink).where(
            MattermostPostLink.post_id == post_id
        )
        existing = (await self.session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None and not reprocess:
            return

        # Auteur-match via mattermost_user (alleen via expliciete koppeling).
        person_id: UUID | None = None
        if mm_user_id:
            mm_repo = MattermostUserRepository(self.session)
            mapping = await mm_repo.get_by_mattermost_user_id(mm_user_id)
            if mapping is not None:
                person_id = mapping.person_id

        if existing is not None:
            # Herverwerking: de bestaande rij blijft staan en houdt daarmee
            # de claim op deze post vast. Hem eerst verwijderen zou het gat
            # openen dat de insert-first-claim hieronder juist dichtzet, en
            # bij een vroege return verderop zou de post helemaal uit de
            # administratie verdwijnen.
            record = existing
            record.scope_type = channel_link.scope_type
            record.scope_id = channel_link.scope_id
            record.person_id = person_id
        else:
            # Claim de post NU, vóór de LLM-call en eventuele bot-reply naar
            # Mattermost. Twee overlappende workers (bv. tijdens een
            # deploy-overlap) kunnen de pre-check-SELECT hierboven allebei
            # passeren vóórdat een van beiden commit; zonder deze insert-
            # first-claim zouden beiden de LLM aanroepen en allebei een
            # zichtbare suggestie-post naar Mattermost sturen, en pas de
            # állerlaatste insert zou de unique constraint raken — te laat om
            # de dubbele Mattermost-post nog te voorkomen.
            record = MattermostPostLink(
                post_id=post_id,
                channel_id=channel_id,
                root_id=root_id,
                scope_type=channel_link.scope_type,
                scope_id=channel_link.scope_id,
                mm_user_id=mm_user_id,
                person_id=person_id,
            )
            self.session.add(record)
            try:
                async with self.session.begin_nested():
                    await self.session.flush()
            except (IntegrityError, PendingRollbackError):
                # Race-condition op unique post_id — andere worker was sneller.
                # Bij een conflict tegen een nog-niet-gecommitte rij van de
                # andere worker (i.p.v. een al-gecommitte rij) blokkeert onze
                # INSERT eerst op de rij-lock en faalt pas zodra de andere
                # transactie commit; dat laat de *outer* transactie hier
                # poisoned achter (niet alleen het savepoint), dus zonder
                # expliciete rollback zou de volgende `session.commit()` bij
                # de caller alsnog een PendingRollbackError geven.
                await self.session.rollback()
                return

        lead_activity_id: UUID | None = None
        suggested_lead_id: UUID | None = None
        skipped_reason: str | None = None

        if (
            channel_link.scope_type == SCOPE_LEAD
            and channel_link.auto_note_enabled
            and message.strip()
        ):
            # Een mention is een expliciet menselijk signaal: dan hoeft de
            # ruis-classificatie niet meer te raden of dit relevant is.
            if not mentions_bot and await self._is_noise(message):
                skipped_reason = "noise"
            else:
                lead_activity_id = await self._create_auto_note(
                    lead_id=channel_link.scope_id,
                    post=post,
                    message=message,
                    author_person_id=person_id,
                    mm_user_id=mm_user_id,
                    post_id=post_id,
                    channel_id=channel_id,
                )
        elif (
            channel_link.scope_type == SCOPE_INITIATIEF
            and channel_link.suggest_leads_enabled
            and message.strip()
        ):
            # Wie de bot in een thread aanspreekt ("zie je deze niet?") wijst
            # naar de thread, niet naar zijn eigen vraag. Alleen dat ene
            # bericht beoordelen levert gegarandeerd "geen lead" op.
            text_for_llm = message
            if mentions_bot and root_id:
                text_for_llm = await self._thread_transcript(root_id, post) or message
            suggested_lead_id, suggest_reason = await self._create_suggested_lead(
                channel_link_initiatief_id=channel_link.scope_id,
                channel_display_name=channel_link.channel_display_name,
                channel_id=channel_id,
                post=post,
                message=text_for_llm,
                explicit_request=mentions_bot,
            )
            if suggested_lead_id is None:
                skipped_reason = suggest_reason
        elif channel_link.scope_type == SCOPE_LEAD and not message.strip():
            # Joins, leaves, system-events — nuttig om vast te leggen
            # zodat we de post niet opnieuw zien, maar geen note van maken.
            skipped_reason = "no_link"

        record.lead_activity_id = lead_activity_id
        record.suggested_lead_id = suggested_lead_id
        record.skipped_reason = skipped_reason
        await self.session.flush()

        # Wie de bot expliciet aanspreekt hoort te zien dát er iets gebeurd
        # is. Bij een lead-suggestie post ``_create_suggested_lead`` al een
        # eigen reply met knoppen — die niet dubbelen.
        if mentions_bot and suggested_lead_id is None and reply_to_mentions:
            await self._reply_mention_ack(
                channel_id=channel_id,
                root_post_id=root_id or post_id,
                channel_link=channel_link,
                lead_activity_id=lead_activity_id,
                skipped_reason=skipped_reason,
            )

        # Eén regel per verwerkte post in production logs zodat we
        # kunnen zien waarom een note wel/niet ontstaat zonder DB-query.
        outcome = (
            f"note={lead_activity_id}"
            if lead_activity_id
            else f"suggested={suggested_lead_id}"
            if suggested_lead_id
            else f"skipped={skipped_reason or 'none'}"
        )
        logger.info(
            "Ingest %s scope=%s/%s %s",
            post_id,
            channel_link.scope_type,
            channel_link.scope_id,
            outcome,
        )

        # Bump last_seen_post_at zodat recovery na reconnect klopt.
        create_at = post.get("create_at")
        if isinstance(create_at, int):
            await link_repo.update_last_seen(channel_link, create_at)

    async def ingest_edit(self, post: dict) -> None:
        """Verwerk een bewerkte post (``post_edited``).

        Mensen posten vaak eerst kort en plakken de inhoud er daarna in. Zonder
        dit zag de bot alleen die eerste versie. Per uitkomst van de eerste
        ronde:

        * afgewezen (``no_lead`` of ``noise``): opnieuw beoordelen met de
          nieuwe tekst, zonder nieuwe mention-bevestiging;
        * open lead-suggestie: de intake-tekst bijwerken, zodat goedkeuren de
          laatste versie gebruikt;
        * notitie bij een lead: de notitie bijwerken.

        Een post die we nooit gezien hebben blijft liggen: een bewerking is
        geen reden om oude berichten alsnog op te pikken. De caller doet
        commit/rollback.
        """
        post_id = post.get("id")
        edit_at = post.get("edit_at")
        message = (post.get("message") or "").strip()
        if not post_id or not isinstance(edit_at, int) or edit_at <= 0:
            return  # Pin, losmaken of andere metadata, geen tekstwijziging.
        if self.bot_user_id and post.get("user_id") == self.bot_user_id:
            return
        if not message or not _claim_edit(post_id, edit_at):
            return

        record = (
            await self.session.execute(
                select(MattermostPostLink).where(MattermostPostLink.post_id == post_id)
            )
        ).scalar_one_or_none()
        if record is None:
            return

        if record.skipped_reason in ("no_lead", "noise"):
            logger.info("Bewerkte post %s opnieuw beoordelen", post_id)
            await self.ingest_post(post, reply_to_mentions=False, reprocess=True)
            return

        if record.suggested_lead_id is not None:
            suggested = await self.session.get(SuggestedLead, record.suggested_lead_id)
            if suggested is not None and suggested.status == STATUS_PENDING:
                suggested.raw_text = post.get("message") or ""
                await self.session.flush()
            return

        if record.lead_activity_id is not None:
            activity = await self.session.get(LeadActivity, record.lead_activity_id)
            if activity is None:
                return
            raw = post.get("message") or ""
            summary = await self._maybe_summarize(raw)
            prefix = ""
            if record.person_id is None and record.mm_user_id:
                prefix = f"_(via mm:@{record.mm_user_id})_  \n"
            plain_content = prefix + (summary or raw)
            rendered, _ = await render_mattermost_message_to_markdown(
                self.session, plain_content
            )
            activity.content = rendered or plain_content
            metadata = dict(activity.metadata_ or {})
            metadata["mm_edit_at"] = edit_at
            if summary:
                metadata["mm_original"] = raw
            else:
                metadata.pop("mm_original", None)
            activity.metadata_ = metadata
            await self.session.flush()

    async def _handle_unlinked_mention(
        self,
        *,
        post_id: str,
        channel_id: str,
        root_id: str | None,
        mm_user_id: str | None,
    ) -> None:
        """Reageer één keer per kanaal-tijdvenster op een mention zonder
        koppeling, en log 'm zodat je in de logs ziet dat mensen de bot in
        ongekoppelde kanalen aanspreken."""
        logger.info(
            "Mention in ongekoppeld kanaal: channel=%s post=%s user=%s",
            channel_id,
            post_id,
            mm_user_id,
        )
        if not _claim_unlinked_hint(channel_id):
            return
        sent = await self._reply_not_linked(
            channel_id=channel_id, root_post_id=root_id or post_id
        )
        if not sent:
            # Niets geplaatst (Mattermost uit of API-fout). De volledige
            # claim vasthouden zou een uur zwijgen zonder dat er ooit een
            # uitleg verscheen; 'm helemaal vrijgeven zou in een kanaal waar
            # de bot structureel niet mág posten elke mention opnieuw laten
            # proberen. Dus een korte cooldown: een tijdelijke storing is zo
            # weer over, een permanente 403 floodt de logs niet vol.
            _backoff_unlinked_hint(channel_id)

    async def _mark_reprocess_outcome(self, post_id: str, reason: str) -> None:
        """Zet ``skipped_reason`` op een post die niet herverwerkt kon worden.

        De wachtrij selecteert op ``llm_unavailable``; een andere waarde
        haalt de post er dus uit. Zonder dit zou een post waarvan het kanaal
        is ontkoppeld elke ronde terugkomen.
        """
        row = (
            await self.session.execute(
                select(MattermostPostLink).where(MattermostPostLink.post_id == post_id)
            )
        ).scalar_one_or_none()
        if row is not None:
            row.skipped_reason = reason
            await self.session.flush()

    async def reprocess_one(self, post: dict) -> bool:
        """Herverwerk één eerder geparkeerde post. True als er een lead uitkwam.

        Geen mention-bevestiging: bij een lange storing zou elke ronde
        opnieuw ":eyes: Gezien" in de thread posten. De gebruiker heeft die
        bevestiging al gehad toen het bericht binnenkwam; wat hij nog mist is
        de suggestie, en die komt via ``_post_suggestion_reply`` wel door.
        """
        await self.ingest_post(post, reply_to_mentions=False, reprocess=True)
        row = (
            await self.session.execute(
                select(MattermostPostLink).where(
                    MattermostPostLink.post_id == post["id"]
                )
            )
        ).scalar_one_or_none()
        return row is not None and row.suggested_lead_id is not None

    async def _reply_not_linked(self, *, channel_id: str, root_post_id: str) -> bool:
        """Leg in een ongekoppeld kanaal uit dat we niet meelezen.

        Returns ``True`` als de uitleg daadwerkelijk geplaatst is. Fouten
        zijn niet fataal — een gemiste uitleg mag nooit de ingest van andere
        posts breken.
        """
        from bouwmeester.services.mattermost_service import MattermostService

        service = MattermostService(self.session)
        try:
            if not await service.is_enabled():
                return False
            data = await service.reply_to_post(
                channel_id,
                root_post_id,
                ":wave: Ik lees in dit kanaal niet mee, dus ik pik hier niets "
                "op.\n\nKoppel het kanaal met `/bouwmeester koppel initiatief "
                "<naam>` of `/bouwmeester koppel lead <titel>`, dan neem ik "
                "berichten voortaan mee. Met `/bouwmeester kanaal` zie je de "
                "huidige koppeling.",
            )
            # reply_to_post swallowt HTTP-fouten en geeft dan None terug.
            return data is not None
        except Exception:
            logger.exception(
                "Kon uitleg-reply in ongekoppeld kanaal %s niet plaatsen",
                channel_id,
            )
            return False
        finally:
            await service.close()

    async def _reply_mention_ack(
        self,
        *,
        channel_id: str,
        root_post_id: str,
        channel_link,
        lead_activity_id: UUID | None,
        skipped_reason: str | None,
    ) -> None:
        """Bevestig kort wat er met een mention is gebeurd.

        Zonder dit is "niets zien gebeuren" niet te onderscheiden van "de
        bot is stuk", en dat is precies de verwarring die we willen weghalen.
        """
        from bouwmeester.services.mattermost_service import MattermostService

        if lead_activity_id is not None:
            text = ":memo: Genoteerd bij deze lead in Bouwmeester."
        elif (
            channel_link.scope_type == SCOPE_LEAD and not channel_link.auto_note_enabled
        ):
            text = (
                ":information_source: Ik lees dit kanaal wel mee, maar "
                "automatische notities staan uit. Zet ze aan in Bouwmeester "
                "onder Beheer > Mattermost."
            )
        elif (
            channel_link.scope_type == SCOPE_INITIATIEF
            and not channel_link.suggest_leads_enabled
        ):
            text = (
                ":information_source: Ik lees dit kanaal wel mee, maar "
                "lead-suggesties staan uit. Zet ze aan in Bouwmeester onder "
                "Beheer > Mattermost."
            )
        elif skipped_reason == "llm_unavailable":
            text = (
                ":warning: Ik kon dit even niet beoordelen — de taalmodel-"
                "dienst is nu niet bereikbaar. Ik probeer het vanzelf "
                "opnieuw zodra hij er weer is."
            )
        elif skipped_reason == "llm_not_configured":
            text = (
                ":warning: Ik kon dit niet beoordelen — er is geen "
                "taalmodel-dienst ingesteld. Dit vraagt om een beheerder, "
                "opnieuw sturen helpt niet."
            )
        elif skipped_reason == "no_lead":
            why = f" ({self._no_lead_reasoning})" if self._no_lead_reasoning else ""
            text = (
                f":mag: Gezien, maar ik zie hier geen nieuwe lead in{why}. "
                "Maak hem handmatig aan in Bouwmeester als dat wel zo is."
            )
        elif skipped_reason == "stale_initiatief":
            text = (
                ":warning: Dit kanaal is gekoppeld aan een initiatief dat "
                "niet meer bestaat. Koppel het opnieuw met "
                "`/bouwmeester koppel initiatief <naam>`."
            )
        else:
            text = ":eyes: Gezien. Ik heb hier verder niets mee gedaan."

        service = MattermostService(self.session)
        try:
            if not await service.is_enabled():
                return
            await service.reply_to_post(channel_id, root_post_id, text)
        except Exception:
            logger.exception(
                "Kon mention-bevestiging in kanaal %s niet plaatsen", channel_id
            )
        finally:
            await service.close()

    async def _is_noise(self, message: str) -> bool:
        """Vraag VLAM of dit een triviaal/ack-bericht is.

        Korte heuristiek vooraf: berichten van < 4 chars of alleen emoji's
        zijn sowieso ruis — daar verspillen we geen LLM-call aan.
        """
        stripped = message.strip()
        if len(stripped) < 4:
            return True
        from bouwmeester.services.llm import DataSensitivity
        from bouwmeester.services.llm.factory import get_llm_service_for

        llm = await get_llm_service_for(DataSensitivity.CONFIDENTIAL, self.session)
        if llm is None:
            return False
        return await llm.is_mattermost_noise(stripped)

    async def _maybe_summarize(self, message: str) -> str | None:
        """Vat lange berichten samen via VLAM. Returns None als niet
        gesummariseerd is."""
        if len(message) <= 600:
            return None
        from bouwmeester.services.llm import DataSensitivity
        from bouwmeester.services.llm.factory import get_llm_service_for

        llm = await get_llm_service_for(DataSensitivity.CONFIDENTIAL, self.session)
        if llm is None:
            return None
        summary = await llm.summarize_mattermost_message(message)
        return summary or None

    async def _create_auto_note(
        self,
        *,
        lead_id: UUID,
        post: dict,
        message: str,
        author_person_id: UUID | None,
        mm_user_id: str | None,
        post_id: str,
        channel_id: str,
    ) -> UUID:
        """Schrijf een LeadActivity en eventuele doc-link-attachments."""
        permalink = self._build_permalink(channel_id, post_id)
        summary = await self._maybe_summarize(message)
        body = summary or message
        prefix = ""
        if author_person_id is None and mm_user_id:
            prefix = f"_(via mm:@{mm_user_id})_  \n"
        plain_content = prefix + body

        # Probeer @username-vermeldingen om te zetten naar markdown-mentions
        # zodat het frontend ze als klikbare badge rendert. Als geen enkele
        # username aan een Person gekoppeld is, vallen we terug op platte
        # tekst (bestaand gedrag).
        rendered_markdown, mentioned_ids = await render_mattermost_message_to_markdown(
            self.session, plain_content
        )
        content = rendered_markdown or plain_content

        metadata = {
            "source": "mattermost",
            "mm_post_id": post_id,
            "mm_channel_id": channel_id,
            "mm_user_id": mm_user_id,
            "mm_root_id": post.get("root_id") or None,
            "mm_create_at": post.get("create_at"),
            "mm_permalink": permalink,
        }
        if summary:
            metadata["mm_original"] = message

        activity = LeadActivity(
            lead_id=lead_id,
            author_id=author_person_id,
            content=content,
            activity_type="note",
            metadata_=metadata,
        )
        self.session.add(activity)
        await self.session.flush()
        await self.session.refresh(activity)

        # Sync mentions + notify gementionde personen. Geen-op als content
        # geen TipTap-JSON is (sync_mentions parsed dan een lege lijst).
        if mentioned_ids:
            lead = await self.session.get(Lead, lead_id)
            lead_title = lead.title if lead is not None else "Mattermost-bericht"
            await sync_and_notify_mentions(
                self.session,
                "lead_activity",
                activity.id,
                content,
                lead_title,
                sender_id=author_person_id,
                source_lead_id=lead_id,
                exclude_person_id=author_person_id,
            )

        for link in extract_doc_links(message):
            url = link["url"]
            label = derive_attachment_label(url)
            attachment = LeadAttachment(
                lead_id=lead_id,
                soort="link",
                url=url,
                bestandsnaam=label,
                source="mattermost",
                source_ref=post_id,
            )
            # Naïef dedupe binnen één lead: niet twee keer dezelfde URL.
            existing = await self.session.execute(
                select(LeadAttachment.id).where(
                    LeadAttachment.lead_id == lead_id,
                    LeadAttachment.url == url,
                )
            )
            if existing.scalar_one_or_none() is None:
                self.session.add(attachment)

        await self._ingest_post_files(lead_id=lead_id, post=post, post_id=post_id)
        await self.session.flush()
        return activity.id

    async def _ingest_post_files(
        self,
        *,
        lead_id: UUID,
        post: dict,
        post_id: str,
    ) -> None:
        """Download native Mattermost file-uploads naar ``LeadAttachment``.

        Mattermost stuurt ``file_ids`` mee in ``posted``-events; de rijkere
        ``metadata.files`` is niet altijd aanwezig maar bevat naam + mime
        + size zodat we per-file één API-call kunnen besparen. Per file:

        - haal info op (uit ``metadata.files`` of via ``get_file_info``)
        - check tegen ``ALLOWED_CONTENT_TYPES``
        - download met ``MAX_UPLOAD_SIZE`` cap
        - magic-byte verificatie
        - schrijf naar disk via bestaand storage-pad
        - dedupe op ``(lead_id, source='mattermost', source_ref)`` waarbij
          ``source_ref = "{post_id}:{file_id}"``

        Per-file ``try/except`` zodat één rotte file de andere files en
        de note zelf niet sloopt.
        """
        file_ids = post.get("file_ids") or []
        if not file_ids:
            return

        # metadata.files (indien aanwezig) heeft naam/mime/size — dat
        # bespaart een get_file_info-call per bestand.
        meta_by_id: dict[str, dict] = {}
        for f in (post.get("metadata") or {}).get("files") or []:
            fid = f.get("id")
            if fid:
                meta_by_id[fid] = f

        from bouwmeester.services.mattermost_service import MattermostService

        service = MattermostService(self.session)
        try:
            for file_id in file_ids:
                try:
                    await self._ingest_one_file(
                        service=service,
                        lead_id=lead_id,
                        post_id=post_id,
                        file_id=file_id,
                        meta=meta_by_id.get(file_id),
                    )
                except ValueError:
                    # Mattermost niet (volledig) geconfigureerd, bv. geen
                    # bot-token. Niet zinvol om de loop af te maken; alle
                    # volgende files zouden dezelfde error geven.
                    logger.warning(
                        "Mattermost niet geconfigureerd, sla %d file(s) over",
                        len(file_ids),
                    )
                    return
                except Exception:
                    logger.exception(
                        "Kon Mattermost-file %s voor lead %s niet ingesten",
                        file_id,
                        lead_id,
                    )
        finally:
            await service.close()

    async def _ingest_one_file(
        self,
        *,
        service,
        lead_id: UUID,
        post_id: str,
        file_id: str,
        meta: dict | None,
    ) -> None:
        """Verwerk één file_id. Helper van ``_ingest_post_files`` zodat de
        try/except-loop daar leesbaar blijft."""
        source_ref = f"{post_id}:{file_id}"

        # Dedupe vooraf — voorkomt overbodige download bij replay.
        existing = await self.session.execute(
            select(LeadAttachment.id).where(
                LeadAttachment.lead_id == lead_id,
                LeadAttachment.source == "mattermost",
                LeadAttachment.source_ref == source_ref,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return

        info = meta or await service.get_file_info(file_id)
        if not info:
            logger.warning("Geen file-info voor %s, skip", file_id)
            return

        claimed_ct = (info.get("mime_type") or "application/octet-stream").lower()
        if claimed_ct not in ALLOWED_CONTENT_TYPES:
            logger.info(
                "Mattermost-file %s heeft niet-toegestaan type %s, skip",
                file_id,
                claimed_ct,
            )
            return

        content = await service.download_file(file_id, max_bytes=MAX_UPLOAD_SIZE)
        if content is None:
            return

        if not verify_content_type(content, claimed_ct):
            logger.info(
                "Mattermost-file %s magic bytes komen niet overeen met %s, skip",
                file_id,
                claimed_ct,
            )
            return

        original_name = info.get("name") or f"bijlage-{file_id}"
        filename, relative_path = await store_upload(
            content,
            original_name,
            prefix="leads",
            item_id=lead_id,
            content_type=claimed_ct,
        )
        # store_upload geeft het pad zonder prefix; lead_attachment.pad houdt
        # "leads/" erin.
        relative_path = f"leads/{relative_path}"

        attachment = LeadAttachment(
            lead_id=lead_id,
            soort="file",
            bestandsnaam=filename,
            content_type=claimed_ct,
            bestandsgrootte=len(content),
            pad=relative_path,
            source="mattermost",
            source_ref=source_ref,
        )
        self.session.add(attachment)
        await self.session.flush()

    async def _create_suggested_lead(
        self,
        *,
        channel_link_initiatief_id: UUID,
        channel_display_name: str,
        channel_id: str,
        post: dict,
        message: str,
        explicit_request: bool = False,
    ) -> tuple[UUID | None, str | None]:
        """Vraag VLAM of dit een lead is en maak — bij ja — een SuggestedLead
        plus een bot-reply met approval-knoppen in de thread.

        Returns ``(uuid_of_None, reason)`` met ``reason`` ∈
        ``"llm_unavailable" | "no_lead" | "stale_initiatief" | None``.
        ``reason`` wordt door de caller in ``MattermostPostLink.skipped_reason``
        bewaard, zodat we onderscheid kunnen maken tussen "VLAM was tijdelijk
        offline" (reprocessable) en "echt geen lead" (definitief)."""
        from bouwmeester.services.llm import DataSensitivity
        from bouwmeester.services.llm.factory import get_llm_service_for

        llm = await get_llm_service_for(DataSensitivity.CONFIDENTIAL, self.session)
        if llm is None:
            # Niet hetzelfde als een storing: er is geen provider opgebouwd,
            # dus er gaat geen enkele netwerkcall uit. Dat onderscheid staat
            # ook in de reply en in skipped_reason, anders is "onbereikbaar"
            # en "niet geconfigureerd" van buitenaf niet uit elkaar te halen.
            logger.warning(
                "Geen CONFIDENTIAL-LLM opgebouwd — sla suggested-lead over. "
                "Zie de LLM-providers-regel bij worker-start voor de reden."
            )
            return None, "llm_not_configured"

        initiatief = await self.session.get(Initiatief, channel_link_initiatief_id)
        if initiatief is None:
            logger.warning(
                "Initiatief %s voor kanaal-koppeling bestaat niet (meer)",
                channel_link_initiatief_id,
            )
            return None, "stale_initiatief"

        rows = await self._collect_lead_candidates_for_llm(
            channel_link_initiatief_id, message
        )
        recent = [
            {
                "id": str(row.id),
                "title": row.title,
                "organization": row.organization,
                "stage": row.stage,
            }
            for row in rows
        ]

        result = await llm.classify_mattermost_lead_candidate(
            message=message,
            initiatief_naam=initiatief.naam,
            channel_display_name=channel_display_name,
            recent_leads=recent,
            explicit_request=explicit_request,
        )
        if result.failed:
            # Onbereikbare of stukke LLM is geen oordeel. Als "no_lead"
            # afdoen zou de post definitief afgeschreven zijn en de
            # gebruiker te horen krijgen dat er niets in zit, terwijl er
            # niemand gekeken heeft.
            return None, "llm_unavailable"
        if not result.is_lead:
            reasoning = (result.reasoning or "").strip().rstrip(".")
            self._no_lead_reasoning = reasoning or None
            return None, "no_lead"

        match_lead_uuid: UUID | None = None
        matched_lead: dict | None = None
        if result.match_existing_lead_id:
            try:
                candidate = UUID(result.match_existing_lead_id)
            except ValueError:
                candidate = None
            if candidate is not None:
                for row in rows:
                    if str(row.id) == str(candidate):
                        match_lead_uuid = candidate
                        stage_label = await self._resolve_stage_label(
                            channel_link_initiatief_id, row.stage
                        )
                        matched_lead = {
                            "title": row.title,
                            "stage": row.stage,
                            "stage_label": stage_label,
                        }
                        break

        suggested = SuggestedLead(
            source_type="mattermost",
            source_post_id=post["id"],
            source_channel_id=channel_id,
            source_root_id=post.get("root_id") or None,
            initiatief_id=channel_link_initiatief_id,
            proposed_title=(result.proposed_title or "Nieuwe lead vanuit Mattermost")[
                :500
            ],
            proposed_description=result.proposed_description or None,
            raw_text=message,
            confidence=result.confidence,
            reasoning=result.reasoning or None,
            match_existing_lead_id=match_lead_uuid,
            status=STATUS_PENDING,
        )
        self.session.add(suggested)
        await self.session.flush()
        await self.session.refresh(suggested)

        # Post de bot-reply met knoppen — fout daar is niet fataal voor het
        # SuggestedLead-record. Als er geen MattermostService is (test) doen
        # we niets.
        try:
            await self._post_suggestion_reply(
                channel_id=channel_id,
                root_post_id=post.get("root_id") or post["id"],
                suggested=suggested,
                initiatief=initiatief,
                matched_lead=matched_lead,
            )
        except Exception:
            logger.exception(
                "Kon bot-reply voor suggested lead %s niet plaatsen", suggested.id
            )

        return suggested.id, None

    async def _thread_transcript(self, root_id: str, post: dict) -> str | None:
        """De thread tot en met ``post`` als leesbare tekst voor de LLM.

        Bot-posts vallen weg (eigen bevestigingen zijn geen inhoud), net als
        posts ná ``post``. Per post de Mattermost-username, zodat de LLM kan
        zien wie extern is en wie collega. ``None`` als de thread niet op te
        halen is; de caller valt dan terug op het losse bericht.
        """
        from bouwmeester.services.mattermost_service import MattermostService

        service = MattermostService(self.session)
        try:
            posts = await service.get_post_thread(root_id)
            if not posts:
                return None
            cutoff = post.get("create_at") or 0
            posts = [
                p
                for p in posts
                if (p.get("message") or "").strip()
                and not (self.bot_user_id and p.get("user_id") == self.bot_user_id)
                and not (cutoff and (p.get("create_at") or 0) > cutoff)
            ]
            # De root draagt meestal het contact; bij een lange thread die
            # houden en de rest van achteren aanvullen.
            if len(posts) > THREAD_POSTS_FOR_LLM:
                posts = [posts[0], *posts[-(THREAD_POSTS_FOR_LLM - 1) :]]
            names: dict[str, str] = {}
            lines: list[str] = []
            for p in posts:
                user_id = p.get("user_id") or ""
                if user_id and user_id not in names:
                    names[user_id] = await service.get_username(user_id)
                author = names.get(user_id) or "onbekend"
                text = p["message"].strip()[:THREAD_POST_CHARS_FOR_LLM]
                lines.append(f"[{author}]: {text}")
            return "\n\n".join(lines) or None
        except Exception:
            logger.exception("Kon thread %s niet ophalen voor classificatie", root_id)
            return None
        finally:
            await service.close()

    async def _collect_lead_candidates_for_llm(
        self, initiatief_id: UUID, message: str
    ) -> list:
        """Selecteer bestaande leads die mogelijk relevant zijn voor de
        LLM-duplicate-check.

        Twee groepen, gededupliceerd op id en gecapped:

        1. ``RECENT_LEADS_FOR_LLM`` nieuwste leads voor dit initiatief
           (recency, vangt actieve kwesties zonder expliciete naam in
           het bericht).
        2. ``SIMILAR_LEADS_FOR_LLM`` leads die het meest lijken op het
           bericht via ``pg_trgm.word_similarity`` op titel of
           organisatie (vangt oude leads waarvan de naam expliciet
           genoemd wordt; bv. "HHNK" matcht een lead "HHNK
           (Hoogheemraadschap...)" ook al staat die niet in de top-25).

        Recente leads krijgen voorrang in de dedup zodat hun ``stage``
        consistent is. ``SIMILAR_LEAD_THRESHOLD`` is een ruime default;
        ``word_similarity`` retourneert 0..1 en 0.3 vangt afkortingen +
        kleine spelvariaties zonder te veel ruis.
        """
        recent_stmt = (
            select(Lead.id, Lead.title, Lead.organization, Lead.stage)
            .where(Lead.initiatief_id == initiatief_id)
            .order_by(Lead.created_at.desc())
            .limit(RECENT_LEADS_FOR_LLM)
        )
        recent_rows = (await self.session.execute(recent_stmt)).all()

        # Pre-filter ruwweg op een ondergrens om geen full-table-scan op te
        # eten in initiatieven met veel leads. word_similarity is symmetrisch:
        # we zoeken leads waar TITEL of ORG voorkomt als "woord" in MESSAGE.
        title_sim = func.word_similarity(Lead.title, message)
        org_sim = func.word_similarity(Lead.organization, message)
        max_sim = func.greatest(title_sim, func.coalesce(org_sim, 0.0))
        similar_stmt = (
            select(Lead.id, Lead.title, Lead.organization, Lead.stage)
            .where(
                Lead.initiatief_id == initiatief_id,
                or_(
                    title_sim > SIMILAR_LEAD_THRESHOLD,
                    org_sim > SIMILAR_LEAD_THRESHOLD,
                ),
            )
            .order_by(max_sim.desc())
            .limit(SIMILAR_LEADS_FOR_LLM)
        )
        similar_rows = (await self.session.execute(similar_stmt)).all()

        merged: dict = {}
        for row in recent_rows:
            merged[row.id] = row
        for row in similar_rows:
            merged.setdefault(row.id, row)
        return list(merged.values())[:MAX_LEADS_FOR_LLM]

    async def _resolve_stage_label(
        self, initiatief_id: UUID | None, stage: str | None
    ) -> str:
        """Vertaal een stage-slug naar de zichtbare kolomnaam.

        Sinds per-initiatief lead_columns kunnen eigenaren stages
        hernoemen; we lezen de naam direct uit ``lead_column``. Voor
        orphan-leads (geen initiatief) of slugs die niet langer als
        kolom bestaan vallen we terug op de 7-default-labels — anders
        krijgt de bot-reply de raw slug te zien.
        """
        if not stage:
            return ""
        if initiatief_id is not None:
            from sqlalchemy import select

            from bouwmeester.models.lead_column import LeadColumn

            stmt = select(LeadColumn.name).where(
                LeadColumn.initiatief_id == initiatief_id,
                LeadColumn.slug == stage,
            )
            name = (await self.session.execute(stmt)).scalar_one_or_none()
            if name:
                return name
        return _DEFAULT_STAGE_LABELS.get(stage, stage)

    async def _post_suggestion_reply(
        self,
        *,
        channel_id: str,
        root_post_id: str,
        suggested: SuggestedLead,
        initiatief: Initiatief,
        matched_lead: dict | None,
    ) -> None:
        """Plaats een bot-reply met emoji-reactions als trigger.

        We gebruiken bewust geen interactive message-attachment-buttons:
        Mattermost stuurt voor button-clicks geen authenticatie-token mee
        in de webhook, en de digilab-installatie levert sowieso geen POSTs
        naar onze publieke endpoint. Reactions komen via dezelfde
        websocket binnen die we al gebruiken voor het meelezen, en zijn
        daarmee robuust tegen die platformbeperkingen.

        Bij ``matched_lead`` (titel + stage van een door de LLM herkende
        bestaande lead) gebruiken we andere copy en zetten we :link: als
        eerste/aanbevolen actie boven :white_check_mark:.
        """
        from bouwmeester.services.mattermost_service import MattermostService

        service = MattermostService(self.session)
        try:
            if not await service.is_enabled():
                return

            pct = int((suggested.confidence or 0) * 100)

            if matched_lead is not None:
                stage_label = matched_lead.get("stage_label") or ""
                text = (
                    f":link: Dit lijkt te gaan over een bestaande lead voor "
                    f"**{initiatief.naam}**: **{matched_lead['title']}**"
                    f"{f' ({stage_label})' if stage_label else ''}.\n"
                    f"_Vertrouwen:_ {pct}%\n\n"
                    "_Reageer met:_\n"
                    ":link: om dit bericht aan die lead te koppelen "
                    "_(aanbevolen)_\n"
                    ":white_check_mark: om tóch een nieuwe lead aan te maken\n"
                    ":x: om de suggestie te negeren"
                )
                attachment = {
                    "color": "#3B82F6",
                    "title": matched_lead["title"],
                    "text": (
                        f"Bestaande lead in stage _{stage_label}_. "
                        if stage_label
                        else ""
                    )
                    + "Bij koppelen wordt dit Mattermost-bericht als notitie "
                    "aan de lead toegevoegd.",
                    "footer": "Bouwmeester · bestaande lead herkend",
                }
            else:
                text = (
                    f":dart: Nieuwe lead voor **{initiatief.naam}**?\n"
                    f"_Voorstel:_ {suggested.proposed_title}\n"
                    f"_Vertrouwen:_ {pct}%\n\n"
                    "_Reageer met:_\n"
                    ":white_check_mark: om de lead aan te maken\n"
                    ":x: om de suggestie te negeren"
                )
                attachment = {
                    "color": "#3B82F6",
                    "title": suggested.proposed_title,
                    "text": suggested.proposed_description or "",
                    "footer": "Bouwmeester · suggestie vanuit Mattermost",
                }

            data = await service.reply_to_post(
                channel_id,
                root_post_id,
                text,
                props={"attachments": [attachment]},
            )
            mm_thread_post_id = (data or {}).get("id")
            if not mm_thread_post_id:
                return
            suggested.mm_thread_post_id = mm_thread_post_id
            await self.session.flush()

            # Plaats bot-reactions als clickable affordance. Bij een match
            # komt :link: eerst (aanbevolen actie), anders alleen :check: + :x:.
            # Failures zijn niet fataal; de gebruiker kan zelf reacties plaatsen.
            if matched_lead is not None:
                await service.add_reaction(mm_thread_post_id, "link")
                await service.add_reaction(mm_thread_post_id, "white_check_mark")
            else:
                await service.add_reaction(mm_thread_post_id, "white_check_mark")
            await service.add_reaction(mm_thread_post_id, "x")
        finally:
            await service.close()

    def _build_permalink(self, channel_id: str, post_id: str) -> str | None:
        """Best-effort permalink: ``{mm_base}/_redirect/pl/{post_id}``.

        Mattermost ondersteunt een teamonafhankelijke redirect-URL voor
        post-permalinks. Dat scheelt ons het opzoeken van de team-naam.
        Zonder bekende base-URL geven we ``None`` terug.
        """
        if not self.mm_base_url:
            return None
        return f"{self.mm_base_url}/_redirect/pl/{post_id}"


#: Posts per ronde. Ruim boven het realistische berichttempo op
#: initiatief-kanalen, dus de wachtrij loopt leeg na een storing.
RETRY_BATCH_SIZE = 50

#: Redenen die een herkansing verdienen zodra de LLM er weer is. Een
#: onbereikbare dienst en een niet-geconfigureerde dienst zijn allebei
#: oplosbaar zonder dat het bericht verandert; ``no_lead`` niet, want daar
#: heeft de LLM wél een oordeel over gegeven.
_RETRYABLE_REASONS = ("llm_unavailable", "llm_not_configured")


async def retry_llm_unavailable(
    *, max_posts: int = RETRY_BATCH_SIZE
) -> tuple[int, int]:
    """Bied posts opnieuw aan die de LLM eerder niet kon beoordelen.

    Bij een VLAM-storing kwam ``classify_mattermost_lead_candidate`` niet
    door, en werd de post weggeschreven met
    ``skipped_reason="llm_unavailable"``. Zonder herverwerking is zo'n
    bericht definitief verloren: ``ingest_post`` slaat elke post over die al
    een ``mattermost_post_link`` heeft.

    **Elke post krijgt een eigen sessie en commit.** Dat is geen detail:
    ``ingest_post`` doet bij een insert-race een volledige
    ``session.rollback()``, en met één gedeelde transactie zou die ene
    botsing ook alle geslaagde herverwerkingen van deze ronde terugdraaien —
    inclusief ``SuggestedLead``-rijen waarvan de bot-reply al in Mattermost
    staat. Die replies zijn niet terug te draaien, dus je houdt goedkeur-
    knoppen over zonder rij erachter.

    Returns ``(aantal_opnieuw_verwerkt, aantal_leads)``.
    """
    from bouwmeester.services.llm import DataSensitivity
    from bouwmeester.services.llm.factory import get_llm_service_for
    from bouwmeester.services.mattermost_service import (
        MattermostService,
        PostNotFoundError,
    )

    async with async_session() as session:
        # Geen provider opgebouwd: niets te proberen, de wachtrij blijft
        # staan tot een beheerder de configuratie rechtzet. Let op: dit zegt
        # alleen iets over de configuratie, niet over bereikbaarheid. Ligt
        # VLAM eruit terwijl hij wél geconfigureerd is, dan komen de posts
        # gewoon opnieuw als ``llm_unavailable`` terug en wachten ze op de
        # volgende ronde.
        if await get_llm_service_for(DataSensitivity.CONFIDENTIAL, session) is None:
            return 0, 0

        stmt = (
            select(MattermostPostLink.post_id, MattermostPostLink.scope_id)
            .where(MattermostPostLink.skipped_reason.in_(_RETRYABLE_REASONS))
            .order_by(MattermostPostLink.created_at)
            .limit(max_posts)
        )
        pending = [(row[0], row[1]) for row in (await session.execute(stmt)).all()]

    if not pending:
        return 0, 0

    processed = 0
    leads = 0
    for post_id, scope_id in pending:
        async with async_session() as session:
            service = MattermostService(session)
            try:
                if not await service.is_enabled():
                    return processed, leads
                try:
                    post = await service.get_post(post_id)
                except PostNotFoundError:
                    # Alleen een 404 is definitief. Een time-out of 5xx laat
                    # de post in de wachtrij staan voor de volgende ronde —
                    # anders schrijft één Mattermost-hik een hele batch
                    # echte leads af als "verwijderd".
                    ingest = MattermostIngestService(session)
                    await ingest._mark_reprocess_outcome(post_id, "post_gone")
                    await session.commit()
                    continue
                if post is None:
                    continue  # Tijdelijke fout: volgende ronde opnieuw.

                ingest = MattermostIngestService(session)
                # Scope-wissel sinds het parkeren (ontkoppeld en opnieuw
                # gekoppeld aan iets anders): niet alsnog door de
                # notitie-flow duwen, dat maakt weken oude berichten aan op
                # een scope waar ze nooit voor bedoeld waren.
                link_repo = MattermostChannelLinkRepository(session)
                current = await link_repo.get_by_channel_id(
                    post.get("channel_id") or ""
                )
                if current is not None and current.scope_id != scope_id:
                    await ingest._mark_reprocess_outcome(post_id, "scope_changed")
                    await session.commit()
                    continue

                got_lead = await ingest.reprocess_one(post)
                await session.commit()
                processed += 1
                if got_lead:
                    leads += 1
            except Exception:
                await session.rollback()
                logger.exception("Herverwerking van post %s faalde", post_id)
            finally:
                await service.close()

    if processed:
        logger.info(
            "Herverwerkt na LLM-storing: %d posts, %d nieuwe lead-suggesties",
            processed,
            leads,
        )
    return processed, leads
