"""Persistente Mattermost-websocket voor het meelezen in gekoppelde kanalen.

Auth/heartbeat/reconnect, plus recovery via REST na disconnect. Voor de
verwerking van individuele posts delegeren we naar
``MattermostIngestService``.

Protocol-referentie: het Mattermost websocket-protocol uit
`claude-threads/src/platform/mattermost/client.ts`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from urllib.parse import urlparse

import httpx
import websockets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.database import async_session
from bouwmeester.models.mattermost_channel_link import MattermostChannelLink
from bouwmeester.services.mattermost_ingest_service import MattermostIngestService
from bouwmeester.services.mattermost_service import (
    MattermostService,
    _load_mattermost_config,
    _validate_mattermost_url,
)
from bouwmeester.services.worker_health import tick as health_tick

logger = logging.getLogger(__name__)


_HEARTBEAT_INTERVAL = 30.0  # sec
_RECONNECT_BACKOFF_BASE = 2.0
_RECONNECT_BACKOFF_MAX = 60.0
_BACKOFF_RESET_AFTER_HEALTHY_SEC = 120.0
# Cold-start-window voor DM-recovery bij eerste connect — dekt de paar
# seconden tussen worker-restart en WS-connect. Bij elke volgende reconnect
# kijken we vanaf het vorige recovery-tijdstip terug.
_DM_COLD_START_WINDOW_MS = 120_000
# Cap op de in-memory cache van recent-verwerkte DM-post-ids; voorkomt
# dubbele processing bij race tussen WS-event en recovery-loop.
_RECENT_DM_CACHE_CAP = 500


def _ws_url_from_http(http_url: str) -> str:
    """Vervang het scheme zodat http(s) → ws(s) en plak `/api/v4/websocket`.

    Behoudt het pad uit ``http_url`` — Mattermost achter een reverse-proxy
    op een sub-pad (bv. ``https://host/chat``) heeft de websocket-endpoint
    op ``wss://host/chat/api/v4/websocket``. Zonder het pad krijg je een
    HTTP 404 terug van de proxy.
    """
    parsed = urlparse(http_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base_path = parsed.path.rstrip("/")
    return f"{scheme}://{parsed.netloc}{base_path}/api/v4/websocket"


async def disable_channel_link(
    session: AsyncSession, channel_id: str, *, event: str = "manual"
) -> bool:
    """Zet ``disabled_at`` op een ``MattermostChannelLink``.

    Module-level zodat tests dit pad kunnen oefenen zonder de hele
    websocket-loop te mocken. Returns ``True`` als de link bestond en is
    bijgewerkt, ``False`` als hij niet bestond of al disabled was.
    """
    from datetime import UTC, datetime

    from bouwmeester.repositories.mattermost_channel_link import (
        MattermostChannelLinkRepository,
    )

    repo = MattermostChannelLinkRepository(session)
    link = await repo.get_by_channel_id(channel_id)
    if link is None or link.disabled_at is not None:
        return False
    link.disabled_at = datetime.now(UTC)
    await session.flush()
    logger.info(
        "Channel-link %s uitgeschakeld via event=%s op kanaal %s",
        link.id,
        event,
        channel_id,
    )
    return True


class MattermostWebsocketService:
    """Eén persistente websocket-verbinding voor het meelezen.

    Loop-pattern: ``run()`` blijft draaien tot de event-loop hem stopt.
    Bij disconnects past hij exponential backoff toe binnen dezelfde call.
    """

    def __init__(self) -> None:
        self._seq = 0
        self._stop = False
        self._bot_user_id: str | None = None
        self._bot_username: str | None = None
        self._mm_base_url: str | None = None
        self._last_dm_recovery_ms: int | None = None
        self._recent_dm_post_ids: OrderedDict[str, None] = OrderedDict()

    async def run(self) -> None:
        """Hoofdloop: connect, auth, lees events, reconnect bij disconnect."""
        backoff = _RECONNECT_BACKOFF_BASE
        while not self._stop:
            connected_at: float | None = None
            try:
                async with async_session() as bootstrap:
                    config = await _load_mattermost_config(bootstrap)
                enabled = (config.get("MATTERMOST_ENABLED") or "").lower()
                if enabled in ("", "false", "0"):
                    await health_tick(
                        "mattermost_websocket",
                        status="disabled",
                        detail="MATTERMOST_ENABLED is false",
                    )
                    await asyncio.sleep(_RECONNECT_BACKOFF_MAX)
                    continue

                http_url = config.get("MATTERMOST_URL", "")
                token = config.get("MATTERMOST_BOT_TOKEN", "")
                if not http_url or not token:
                    logger.debug("Mattermost niet geconfigureerd, skip websocket-loop")
                    await health_tick(
                        "mattermost_websocket",
                        status="disabled",
                        detail="MATTERMOST_URL or token missing",
                    )
                    await asyncio.sleep(_RECONNECT_BACKOFF_MAX)
                    continue

                # Block SSRF naar interne hosts (link-local, loopback, etc.)
                # net als de HTTP-client doet voor de REST API.
                _validate_mattermost_url(http_url)
                self._mm_base_url = http_url.rstrip("/")
                ws_url = _ws_url_from_http(http_url)
                logger.info("Mattermost websocket: connect %s", ws_url)
                # Ping elke 20s — zonder pings sluit een reverse-proxy
                # (zoals die voor digilab.overheid.nl) een idle websocket
                # binnen ~1min met "ConnectionClosedError: no close frame".
                # ping_timeout iets lager dan ons idle-timeout zodat een
                # gemiste pong eerder een reconnect triggert dan de
                # heartbeat-loop dat zou doen.
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2 * 1024 * 1024,
                ) as ws:
                    connected_at = time.monotonic()
                    await self._authenticate(ws, token)
                    await self._resolve_bot_user_id()
                    await health_tick(
                        "mattermost_websocket",
                        status="connected",
                        detail=f"connected to {ws_url}",
                    )
                    await self._recover_missed_posts()
                    await self._read_loop(ws)
                    backoff = _RECONNECT_BACKOFF_BASE
            except asyncio.CancelledError:
                logger.info("Mattermost websocket: loop cancelled")
                raise
            except Exception as exc:
                logger.exception(
                    "Mattermost websocket: error, reconnect in %.1fs", backoff
                )
                await health_tick(
                    "mattermost_websocket",
                    status="reconnecting",
                    detail=f"{type(exc).__name__}: {exc!s}"[:500],
                )

            if self._stop:
                break

            # Reset backoff als we lang stabiel verbonden waren.
            if (
                connected_at is not None
                and time.monotonic() - connected_at > _BACKOFF_RESET_AFTER_HEALTHY_SEC
            ):
                backoff = _RECONNECT_BACKOFF_BASE

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)

    async def stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def _authenticate(self, ws, token: str) -> None:
        await ws.send(
            json.dumps(
                {
                    "seq": self._next_seq(),
                    "action": "authentication_challenge",
                    "data": {"token": token},
                }
            )
        )
        # Wacht op de eerste paar messages tot we hello/auth-ok zien.
        for _ in range(5):
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event = msg.get("event")
            if event == "hello":
                logger.info("Mattermost websocket: authenticated")
                return
            if msg.get("status") == "OK":
                continue
            if msg.get("status") == "FAIL" or msg.get("error"):
                raise RuntimeError(f"Mattermost websocket auth failed: {msg}")
        raise RuntimeError("Mattermost websocket: no hello received")

    async def _resolve_bot_user_id(self) -> None:
        async with async_session() as session:
            service = MattermostService(session)
            try:
                self._bot_user_id, self._bot_username = await service.get_bot_identity()
            finally:
                await service.close()

    async def _read_loop(self, ws) -> None:
        last_heartbeat = 0.0
        while not self._stop:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=_HEARTBEAT_INTERVAL)
            except TimeoutError:
                # Geen events binnen het heartbeat-venster — gewoon
                # admin-UI heartbeat ticken. De `websockets`-library doet
                # zelf ping/pong elke 20s (zie ``ping_interval`` in run());
                # die control-frames passeren ``recv()`` niet, dus stilte
                # hier zegt niets over de connectie-gezondheid. Een dode
                # connectie wordt door de library zelf opgemerkt en als
                # ``ConnectionClosed`` op ``recv()`` opgegooid.
                if time.monotonic() - last_heartbeat > 60.0:
                    last_heartbeat = time.monotonic()
                    await health_tick(
                        "mattermost_websocket",
                        status="connected",
                        detail="idle (no events)",
                    )
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event_name = msg.get("event") or msg.get("seq_reply") or "(unknown)"
            await self._dispatch(msg)
            if time.monotonic() - last_heartbeat > 60.0:
                last_heartbeat = time.monotonic()
                await health_tick(
                    "mattermost_websocket",
                    status="connected",
                    detail=f"last event: {event_name}",
                )

    async def _dispatch(self, msg: dict) -> None:
        event = msg.get("event")
        if event == "posted":
            await self._dispatch_posted(msg)
            return
        if event in ("user_removed", "channel_deleted"):
            await self._dispatch_channel_lost(event, msg)
            return
        if event == "reaction_added":
            await self._dispatch_reaction_added(msg)
            return
        if event == "reaction_removed":
            await self._dispatch_reaction_removed(msg)
            return
        if event == "post_edited":
            await self._dispatch_post_edited(msg)
            return
        # ``post_deleted`` wordt in een latere PR ingehaakt.

    async def _dispatch_post_edited(self, msg: dict) -> None:
        data = msg.get("data") or {}
        post_raw = data.get("post")
        if not post_raw:
            return
        try:
            post = json.loads(post_raw) if isinstance(post_raw, str) else post_raw
        except json.JSONDecodeError:
            logger.warning("Kan post_edited-event niet parsen")
            return
        if not post.get("id"):
            return
        async with async_session() as session:
            try:
                ingest = MattermostIngestService(
                    session,
                    bot_user_id=self._bot_user_id,
                    bot_username=self._bot_username,
                    mm_base_url=self._mm_base_url,
                )
                await ingest.ingest_edit(post)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Fout bij verwerken bewerkte post %s", post.get("id"))

    async def _dispatch_posted(self, msg: dict) -> None:
        data = msg.get("data") or {}
        post_raw = data.get("post")
        if not post_raw:
            return
        # ``channel_type`` zit op ``data``, niet op de geparste ``post`` —
        # ``"D"`` markeert een 1-op-1 DM (link-code-pad), ``"G"`` group-DM.
        channel_type = data.get("channel_type") if isinstance(data, dict) else None
        try:
            post = json.loads(post_raw) if isinstance(post_raw, str) else post_raw
        except json.JSONDecodeError:
            logger.warning("Kan posted-event niet parsen")
            return

        post_id = post.get("id")
        channel_id = post.get("channel_id")
        if not post_id or not channel_id:
            return

        # DM-events kunnen ook via _recover_missed_posts binnenkomen vlak
        # na een reconnect — skip als we 'm net hebben verwerkt.
        if channel_type == "D" and self._dm_already_processed(post_id):
            return

        # Hard signaal in productie-logs dat een bericht überhaupt is
        # aangekomen via de websocket — voorkomt giswerk wanneer een note
        # uitblijft. Korte regel zodat 'm niet snel uit het log-venster
        # rolt door noise.
        logger.info(
            "Mattermost posted event: channel=%s post=%s type=%s len=%d",
            channel_id,
            post_id,
            channel_type or "?",
            len(post.get("message") or ""),
        )

        # DM-events doen al hun werk in een eigen session via
        # ``handle_dm_post`` — open hier geen outer session voor niets.
        if channel_type == "D":
            from bouwmeester.services.mattermost_ingest_service import (
                handle_dm_post,
            )

            # ``handle_dm_post`` swallowt eigen exceptions en returnt
            # False bij fouten. Alleen geslaagde DMs in de dedup-cache
            # zetten — anders mist de recovery-loop ze later.
            ok = await handle_dm_post(post, bot_user_id=self._bot_user_id)
            if ok:
                self._mark_dm_processed(post_id)
            return

        async with async_session() as session:
            try:
                await self._record_post(session, post, channel_type=channel_type)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Fout bij verwerken Mattermost-post %s", post_id)

    async def _dispatch_channel_lost(self, event: str, msg: dict) -> None:
        """Markeer kanaal-koppelingen als ``disabled_at`` wanneer de bot
        verdwijnt (uit kanaal getrapt of kanaal verwijderd).

        Mattermost stuurt ``user_removed`` als event met ``user_id`` (de
        verwijderde user) en ``channel_id`` in ``broadcast`` of ``data``.
        We schakelen de koppeling alleen uit als het de bot zelf is.
        """
        channel_id = self._channel_lost_channel_id(event, msg)
        if not channel_id:
            return

        async with async_session() as session:
            try:
                await disable_channel_link(session, channel_id, event=event)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception(
                    "Kon channel-link voor %s niet uitschakelen", channel_id
                )

    def _channel_lost_channel_id(self, event: str, msg: dict) -> str | None:
        """Pure helper — pikt de juiste channel_id op, mits het de bot
        zelf is die uit het kanaal is. Geen DB-toegang, makkelijk te
        testen met dummy event-payloads."""
        data = msg.get("data") or {}
        broadcast = msg.get("broadcast") or {}
        if event == "user_removed":
            removed_user_id = data.get("user_id") or broadcast.get("user_id")
            if not removed_user_id or removed_user_id != self._bot_user_id:
                return None
            return data.get("channel_id") or broadcast.get("channel_id")
        if event == "channel_deleted":
            return (
                data.get("channel_id")
                or broadcast.get("channel_id")
                or (data.get("channel") or {}).get("id")
            )
        return None

    # Mapping van emoji-naam naar suggested-lead-action. Zelfde keys als
    # in ``MattermostSlashService.handle_action``.
    _SUGGESTION_REACTION_ACTIONS = {
        "white_check_mark": "create_lead_from_suggestion",
        "x": "reject_suggestion",
        "link": "link_lead_to_suggestion",
    }

    async def _verwerk_kamerstuk_reactie(self, post_id: str, emoji_name: str) -> bool:
        """Tel een wegklik als deze reactie op een kamerstuk-alert staat.

        Geeft terug of de reactie hier is afgehandeld, zodat de aanroeper
        weet dat hij niet ook nog het suggested-lead-pad moet proberen.

        Alleen "x" telt. De koptelefoon en de megafoon zijn hiervoor al
        afgehandeld; elke andere emoji is gewoon een reactie.
        """
        from bouwmeester.services.parlementair_alert_service import (
            REACTIE_NIET_RELEVANT,
        )

        if emoji_name != REACTIE_NIET_RELEVANT:
            return False

        from bouwmeester.models.parlementair_alert_post import ParlementairAlertPost
        from bouwmeester.services.parlementair_alert_service import (
            ParlementairAlertService,
        )

        async with async_session() as session:
            # De lookup staat apart van het tellen, en dat is het verschil
            # tussen "dit is geen kamerstuk" en "dit ging mis". Zaten ze in
            # één try, dan zou een databasefout tijdens het zoeken ook
            # `True` opleveren — en dan slikt deze functie een reactie op
            # een suggested-lead op die daarna nergens meer terechtkomt.
            try:
                stmt = select(ParlementairAlertPost.parlementair_item_id).where(
                    ParlementairAlertPost.post_id == post_id
                )
                row = (await session.execute(stmt)).first()
            except Exception:
                logger.exception(
                    "Kon niet opzoeken of post %s bij een kamerstuk hoort", post_id
                )
                # Niet afgehandeld: we weten het simpelweg niet, dus het
                # andere pad mag het alsnog proberen.
                return False

            if row is None:
                return False

            item_id = row[0]
            try:
                await ParlementairAlertService(session).markeer_niet_relevant(item_id)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception(
                    "Wegklik op kamerstuk %s kon niet worden geteld", item_id
                )
                # Hier wél afgehandeld: de post hóórt bij een kamerstuk,
                # dus het suggested-lead-pad zou hem toch niet vinden.
                return True

            logger.info(
                "Kamerstuk %s weggeklikt via reactie op post %s",
                item_id,
                post_id,
            )
            return True

    async def _handle_debat_start(
        self, post_id: str, emoji_name: str, user_id: str
    ) -> bool:
        """Set up a debate channel if this is the start button on an alert.

        Returns whether the reaction was handled here. Any human may add
        the reaction, also under an alert that was posted without the
        button; whether there is a meeting to start is decided when it is
        pressed.

        Runs inline, so the read loop waits for it. That is a handful of
        HTTP calls with their own timeouts, and it keeps two presses on
        the same button in order.
        """
        from bouwmeester.services.debat_kanaal_service import (
            REACTIE_UITLUISTEREN,
            DebatKanaalService,
        )

        if emoji_name != REACTIE_UITLUISTEREN:
            return False

        from bouwmeester.models.parlementair_alert_post import ParlementairAlertPost
        from bouwmeester.models.parlementair_item import ParlementairItem

        async with async_session() as session:
            # The lookup apart from the work, as in
            # `_verwerk_kamerstuk_reactie`: "not an alert" and "this went
            # wrong" must not look the same to the caller.
            try:
                stmt = (
                    select(ParlementairItem, ParlementairAlertPost.channel_id)
                    .join(
                        ParlementairAlertPost,
                        ParlementairAlertPost.parlementair_item_id
                        == ParlementairItem.id,
                    )
                    .where(ParlementairAlertPost.post_id == post_id)
                )
                row = (await session.execute(stmt)).first()
            except Exception:
                logger.exception(
                    "Kon niet opzoeken of post %s bij een kamerstuk hoort", post_id
                )
                return False

            if row is None:
                return False
            item, channel_id = row

            service = DebatKanaalService(session)
            try:
                result = await service.start(
                    item=item,
                    source_channel_id=channel_id,
                    source_post_id=post_id,
                    mattermost_user_id=user_id,
                )
                logger.info(
                    "Startknop op post %s door %s: %s",
                    post_id,
                    user_id,
                    result.outcome.value,
                )
            except Exception:
                await session.rollback()
                logger.exception("Debatkanaal starten vanaf post %s mislukt", post_id)
            finally:
                await service.close()
            return True

    async def _handle_debat_aankondiging(
        self, post_id: str, emoji_name: str, user_id: str
    ) -> bool:
        """Put the meeting of an alert on the list of its initiatief.

        Returns whether the reaction was handled here. Like the start
        button: any human may add the reaction, also under an alert that
        was posted without it, and whether there is a meeting to list is
        decided when it is pressed. The answer is a reply in the thread.
        """
        from bouwmeester.services.debat_aankondiging_service import (
            REACTIE_AANKONDIGEN,
            DebatAankondigingService,
        )

        if emoji_name != REACTIE_AANKONDIGEN:
            return False

        from bouwmeester.models.parlementair_alert_post import ParlementairAlertPost
        from bouwmeester.models.parlementair_item import ParlementairItem

        async with async_session() as session:
            # The lookup apart from the work, as in `_handle_debat_start`.
            try:
                stmt = (
                    select(
                        ParlementairItem.extra_data, ParlementairAlertPost.channel_id
                    )
                    .join(
                        ParlementairAlertPost,
                        ParlementairAlertPost.parlementair_item_id
                        == ParlementairItem.id,
                    )
                    .where(ParlementairAlertPost.post_id == post_id)
                )
                row = (await session.execute(stmt)).first()
            except Exception:
                logger.exception(
                    "Kon niet opzoeken of post %s bij een kamerstuk hoort", post_id
                )
                return False

            if row is None:
                return False
            extra, channel_id = row

            service = DebatAankondigingService(session)
            try:
                outcome = await service.announce_from_alert(
                    extra=extra,
                    channel_id=channel_id,
                    post_id=post_id,
                    mattermost_user_id=user_id,
                )
                logger.info(
                    "Aankondigknop op post %s door %s: %s", post_id, user_id, outcome
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Vergadering op de lijst zetten vanaf post %s mislukt", post_id
                )
            finally:
                await service.close()
            return True

    async def _handle_vraag_reactie(self, post_id: str, emoji_name: str) -> bool:
        """Note a reaction on the reply of a marked question in a debate.

        Returns whether the post is such a reply, so the caller knows not
        to look for another meaning of the same emoji.

        All this does is mark the markering: one statement on an index.
        Which status follows, and writing it to the channel, is for the
        round of the questions (`DebatVraagStatusService`). That keeps the
        read loop from waiting for Mattermost, makes a burst of clicks one
        write, and survives a restart between the click and the write.

        Who reacted is not looked at: anyone in the channel may say what
        became of a question. Never raises: a database that is away is a
        reaction that is not handled here, not a websocket that reconnects.
        """
        from bouwmeester.services.debat_vraag_status_service import (
            is_status_reactie,
            markeer_reactie,
        )

        # Before the database: most reactions in most channels are a
        # thumbs-up on something else.
        if not is_status_reactie(emoji_name):
            return False
        try:
            async with async_session() as session:
                try:
                    handled = await markeer_reactie(session, post_id)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
        except Exception:
            logger.exception(
                "Kon niet opzoeken of post %s het antwoord op een vraag is", post_id
            )
            return False
        return handled

    async def _dispatch_reaction_removed(self, msg: dict) -> None:
        """A reaction that is taken away can only matter to a question.

        The other reactions the bot listens to are buttons: pressing one
        does something, and letting go does not undo it. On the reply of a
        question a reaction is a state, and taking it away changes it.
        """
        reaction = self._parse_reaction(msg)
        if reaction is None:
            return
        user_id = reaction.get("user_id")
        post_id = reaction.get("post_id")
        emoji_name = reaction.get("emoji_name")
        if not user_id or not post_id or not emoji_name:
            return
        # The same guard as for a reaction that is added, for the same
        # reason: see there.
        if self._bot_user_id is None or user_id == self._bot_user_id:
            return
        await self._handle_vraag_reactie(post_id, emoji_name)

    async def _dispatch_reaction_added(self, msg: dict) -> None:
        """Verwerk een ``reaction_added`` event als trigger voor een
        suggested-lead approval.

        Mattermost stuurt voor message-attachment-button-clicks geen POST
        naar onze publieke endpoint; we gebruiken daarom emoji-reactions
        op de bot-suggestion-post als trigger. Alleen reacties op een
        post die als ``SuggestedLead.mm_thread_post_id`` bekend is en met
        een herkende emoji-naam triggeren een actie.
        """
        reaction = self._parse_reaction(msg)
        if reaction is None:
            return
        user_id = reaction.get("user_id")
        post_id = reaction.get("post_id")
        emoji_name = reaction.get("emoji_name")
        if not user_id or not post_id or not emoji_name:
            return
        # Skip eigen reactions (we plaatsen zelf white_check_mark/x/link
        # als affordance, die mogen geen actie triggeren).
        #
        # Weten we niet wie de bot is, dan verwerken we niets. Dat is geen
        # overdreven voorzichtigheid: `get_bot_identity()` geeft
        # `(None, None)` terug als Mattermost even onbereikbaar is, en
        # `_resolve_bot_user_id` kent dat toe zonder retry. Eén mislukte
        # REST-call bij het opzetten van de verbinding zou dan, zolang die
        # verbinding staat, elke alert zichzelf laten wegklikken: de bot
        # zet zijn eigen "x" en `None == None` laat die door. De rij in
        # `parlementair_alert_post` staat er op dat moment al, want die
        # wordt gecommit vóór `add_reaction`. Hetzelfde patroon als in
        # `mattermost_ingest_service`, dat overal `if bot_user_id and ...`
        # schrijft.
        #
        # `is None` en niet `not self._bot_user_id`, omdat het verschil
        # hier nergens uit deze functie blijkt: `get_bot_identity()`
        # normaliseert een lege id naar `None` (`data.get("id") or None`),
        # dus een lege string komt hier niet aan. `get_bot_user_id()` op de
        # regel ernaast doet dat níet en geeft bij dezelfde respons wél
        # `""`. Verdwijnt die normalisatie, dan valt de bot samen met een
        # onbekende gebruiker en klikt elk alert zichzelf weg.
        if self._bot_user_id is None or user_id == self._bot_user_id:
            return

        # Eerst kijken of dit een kamerstuk-alert is. "x" zit in beide
        # tabellen — daar betekent het "geen lead", hier "niet relevant" —
        # en zonder deze volgorde zou een wegklik op een alert in het
        # suggested-lead-pad belanden, daar niets vinden en stil verdwijnen.
        if await self._handle_debat_start(post_id, emoji_name, user_id):
            return

        if await self._handle_debat_aankondiging(post_id, emoji_name, user_id):
            return

        # Before the two below: "x" and "white_check_mark" mean something
        # there as well, and a reply of a question is never one of their
        # posts.
        if await self._handle_vraag_reactie(post_id, emoji_name):
            return

        if await self._verwerk_kamerstuk_reactie(post_id, emoji_name):
            return

        action_name = self._SUGGESTION_REACTION_ACTIONS.get(emoji_name)
        if action_name is None:
            return

        async with async_session() as session:
            try:
                from bouwmeester.models.suggested_lead import (
                    STATUS_PENDING,
                    SuggestedLead,
                )
                from bouwmeester.services.mattermost_slash_service import (
                    MattermostSlashService,
                )

                # Filter ook op status: een afgehandelde SuggestedLead
                # heeft niets meer te doen, en handle_action zou alleen
                # een ephemeral-melding teruggeven die we niet tonen.
                stmt = select(SuggestedLead.id).where(
                    SuggestedLead.mm_thread_post_id == post_id,
                    SuggestedLead.status == STATUS_PENDING,
                )
                row = (await session.execute(stmt)).first()
                if row is None:
                    return
                suggested_lead_id = row[0]

                logger.info(
                    "Mattermost reaction trigger: emoji=%s post=%s user=%s "
                    "suggested_lead=%s action=%s",
                    emoji_name,
                    post_id,
                    user_id,
                    suggested_lead_id,
                    action_name,
                )

                service = MattermostSlashService(session)
                await service.handle_action(
                    mattermost_user_id=user_id,
                    action=action_name,
                    context={"suggested_lead_id": str(suggested_lead_id)},
                )
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Fout bij verwerken reaction op post %s", post_id)

    @staticmethod
    def _parse_reaction(msg: dict) -> dict | None:
        """Haal de reaction-payload uit een ``reaction_added`` event.

        Mattermost wrapt de reaction als JSON-string in ``data.reaction``;
        oudere/varianten leveren soms een dict aan. Beide ondersteunen.
        """
        data = msg.get("data") or {}
        raw = data.get("reaction")
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return None

    async def _record_post(
        self,
        session: AsyncSession,
        post: dict,
        *,
        channel_type: str | None = None,
    ) -> None:
        """Verwerk één Mattermost-post via :class:`MattermostIngestService`."""
        ingest = MattermostIngestService(
            session,
            bot_user_id=self._bot_user_id,
            bot_username=self._bot_username,
            mm_base_url=self._mm_base_url,
        )
        await ingest.ingest_post(post, channel_type=channel_type)

    def _dm_already_processed(self, post_id: str) -> bool:
        return post_id in self._recent_dm_post_ids

    def _mark_dm_processed(self, post_id: str) -> None:
        self._recent_dm_post_ids[post_id] = None
        while len(self._recent_dm_post_ids) > _RECENT_DM_CACHE_CAP:
            self._recent_dm_post_ids.popitem(last=False)

    async def _recover_missed_posts(self) -> None:
        """Haal posts op die binnenkwamen terwijl we offline waren.

        Twee paden:
        1. Per gekoppeld kanaal vanaf ``last_seen_post_at`` (meelees-flow).
        2. Bot-DMs voor link-codes vanaf ``_last_dm_recovery_ms`` (bij
           cold start: laatste 2 minuten).

        Dubbele posts (zowel via WS-event als recovery) worden afgevangen
        door de unique constraint op ``mattermost_post_link.post_id`` voor
        kanaal-posts en door de in-memory dedup-cache voor DM-posts.
        """
        async with async_session() as session:
            stmt = select(MattermostChannelLink).where(
                MattermostChannelLink.disabled_at.is_(None)
            )
            result = await session.execute(stmt)
            links = list(result.scalars().all())

            service = MattermostService(session)
            try:
                if not await service.is_enabled():
                    return

                for link in links:
                    since = link.last_seen_post_at or 0
                    if since == 0:
                        # Niet recoveren bij verse koppeling — anders
                        # importeren we een hele kanaal-historie.
                        continue
                    try:
                        posts = await service.get_channel_posts_since(
                            link.channel_id, since
                        )
                    except httpx.HTTPError:
                        logger.exception(
                            "Recovery faalde voor kanaal %s", link.channel_id
                        )
                        continue
                    for post in posts:
                        try:
                            await self._record_post(session, post)
                        except Exception:
                            logger.exception(
                                "Recovery: fout bij post %s", post.get("id")
                            )

                await self._recover_dm_posts(session, service)

                await session.commit()
            finally:
                await service.close()

    async def _recover_dm_posts(
        self, session: AsyncSession, service: MattermostService
    ) -> None:
        """Eenmalige REST-poll van bot-DMs sinds laatste recovery-tijdstip.

        Vangnet voor link-codes die binnenkwamen tijdens een korte
        WS-disconnect. Bij cold start: 2 minuten terug.
        """
        now_ms = int(time.time() * 1000)
        since_ms = self._last_dm_recovery_ms
        if since_ms is None:
            since_ms = now_ms - _DM_COLD_START_WINDOW_MS

        try:
            posts = await service.get_bot_dm_posts(since=since_ms)
        except httpx.HTTPError:
            logger.exception("DM-recovery faalde")
            return

        recovered = 0
        failures = 0
        for post in posts:
            post_id = post.get("id")
            if not post_id or self._dm_already_processed(post_id):
                continue
            try:
                await self._record_post(session, post, channel_type="D")
            except Exception:
                logger.exception("DM-recovery: fout bij post %s", post_id)
                failures += 1
                continue
            self._mark_dm_processed(post_id)
            recovered += 1

        # Schuif de cursor alleen door bij volledig succes — anders willen
        # we mislukte posts bij de volgende reconnect opnieuw zien.
        if failures == 0:
            self._last_dm_recovery_ms = now_ms
        if recovered:
            logger.info("DM-recovery: %d posts opnieuw verwerkt", recovered)
        if failures:
            logger.warning(
                "DM-recovery: %d posts mislukt, cursor blijft staan", failures
            )
