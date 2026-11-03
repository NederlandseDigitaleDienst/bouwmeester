"""Core Mattermost API client for sending DMs, channel posts,
and formatting messages.

Settings are read from:
1. AppConfig table in the database (set via admin panel)
2. Environment variables / config.py settings (fallback)
"""

import ipaddress
import logging
import time
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.config import get_settings
from bouwmeester.models.notification import Notification
from bouwmeester.repositories.mattermost_user import MattermostUserRepository
from bouwmeester.services.mattermost_utils import escape_mattermost_md

logger = logging.getLogger(__name__)


class PostNotFoundError(Exception):
    """De Mattermost-post bestaat niet (meer).

    Bewust apart van een tijdelijke ophaalfout: alleen dit is een reden om
    een post definitief uit de herverwerkings-wachtrij te halen.
    """

    def __init__(self, post_id: str) -> None:
        super().__init__(f"Mattermost-post {post_id} bestaat niet (meer)")
        self.post_id = post_id


# In-memory config cache with TTL — also cleared by admin config update endpoint.
_mm_config_cache: dict[str, str] | None = None
_mm_config_cache_ts: float = 0.0
_MM_CONFIG_CACHE_TTL = 60  # seconds


class MattermostUnavailableError(RuntimeError):
    """Raised wanneer een Mattermost-API-call niet uitvoerbaar is door
    een tijdelijk probleem (netwerk, server-fout, ontbrekende config)
    en de caller dat niet als "expliciet nee" mag interpreteren.
    """


class MattermostPermissionError(RuntimeError):
    """Mattermost refused the call because the bot lacks a permission.

    Separate from `MattermostUnavailableError` because retrying does not
    help: an administrator has to change something first. The caller is
    expected to say so to a human instead of failing quietly.
    """

    def __init__(self, permission: str | None, detail: str = "") -> None:
        super().__init__(detail or f"Mattermost-permissie ontbreekt: {permission}")
        self.permission = permission


class ChannelNameTakenError(RuntimeError):
    """A channel with this url name already exists in the team.

    That includes archived channels: Mattermost keeps the name reserved
    after archiving, so a name can be taken without any visible channel.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"Kanaalnaam {name} bestaat al")
        self.name = name


# Limits Mattermost enforces on a channel; exceeding one is a 400.
CHANNEL_NAME_MAX = 64
CHANNEL_DISPLAY_NAME_MAX = 64
CHANNEL_HEADER_MAX = 1024
CHANNEL_PURPOSE_MAX = 250

PERMISSION_CREATE_PUBLIC_CHANNEL = "create_public_channel"
PERMISSION_CREATE_PRIVATE_CHANNEL = "create_private_channel"

# Error id Mattermost returns for a duplicate channel name within a team.
_CHANNEL_EXISTS_ERROR_ID = "store.sql_channel.save_channel.exists.app_error"
_PERMISSION_ERROR_ID = "api.context.permissions.app_error"


def _error_id(resp: httpx.Response) -> str:
    """The `id` of a Mattermost error body, or empty if there is none."""
    try:
        body = resp.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    return str(body.get("id") or "")


def clear_mattermost_config_cache() -> None:
    """Clear the Mattermost config cache so the next call rebuilds from DB."""
    global _mm_config_cache, _mm_config_cache_ts  # noqa: PLW0603
    _mm_config_cache = None
    _mm_config_cache_ts = 0.0


async def _load_mattermost_config(db: AsyncSession) -> dict[str, str]:
    """Load Mattermost config from the AppConfig table, decrypting secrets."""
    global _mm_config_cache, _mm_config_cache_ts  # noqa: PLW0603
    now = time.monotonic()
    cache_fresh = (now - _mm_config_cache_ts) < _MM_CONFIG_CACHE_TTL
    if _mm_config_cache is not None and cache_fresh:
        return _mm_config_cache

    try:
        from bouwmeester.core.encryption import decrypt_value
        from bouwmeester.models.app_config import AppConfig

        result = await db.execute(
            select(AppConfig.key, AppConfig.value, AppConfig.is_secret).where(
                AppConfig.key.in_(
                    [
                        "MATTERMOST_ENABLED",
                        "MATTERMOST_URL",
                        "MATTERMOST_BOT_TOKEN",
                        "MATTERMOST_WEBHOOK_TOKEN",
                        "MATTERMOST_NOTIFICATION_CHANNEL_ID",
                    ]
                )
            )
        )
        _mm_config_cache = {}
        for key, value, is_secret in result.all():
            if value:
                _mm_config_cache[key] = decrypt_value(value) if is_secret else value
        _mm_config_cache_ts = now
    except Exception:
        logger.debug("Could not load Mattermost config from database, using env vars")
        # Return empty dict but do NOT cache — allow immediate retry next call.
        return {}

    return _mm_config_cache


# Notification type → color for Mattermost attachment sidebar.
_NOTIFICATION_COLORS: dict[str, str] = {
    "task_assigned": "#3B82F6",  # blue
    "task_overdue": "#EF4444",  # red
    "task_completed": "#22C55E",  # green
    "task_reassigned": "#F59E0B",  # amber
    "node_updated": "#6366F1",  # indigo
    "edge_created": "#8B5CF6",  # violet
    "coverage_needed": "#F97316",  # orange
    "stakeholder_added": "#06B6D4",  # cyan
    "stakeholder_role_changed": "#14B8A6",  # teal
    "politieke_input_imported": "#EC4899",  # pink
    "mention": "#3B82F6",  # blue
    "access_request": "#F59E0B",  # amber
    "placement_request": "#6366F1",  # indigo
    "placement_approved": "#22C55E",  # green
    "placement_denied": "#EF4444",  # red
}

# Types that should go to the channel (broadcast) instead of DM.
_CHANNEL_NOTIFICATION_TYPES = frozenset({"politieke_input_imported"})

# Re-export for backwards compatibility within this module.
_escape_md = escape_mattermost_md


def _validate_mattermost_url(url: str) -> None:
    """Validate that MATTERMOST_URL is not pointing to internal/metadata endpoints."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"MATTERMOST_URL must use http or https, got: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("MATTERMOST_URL has no hostname")

    # Allow Docker service names (no dots, not an IP).
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # It's a hostname — block localhost explicitly.
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
            raise ValueError("MATTERMOST_URL must not point to localhost")
        return

    # It's an IP — block private, loopback, link-local, reserved, and multicast.
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    ):
        raise ValueError(f"MATTERMOST_URL must not point to {addr}")


class MattermostService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.repo = MattermostUserRepository(session)
        self._client: httpx.AsyncClient | None = None
        self._config: dict[str, str] | None = None

    async def _get_config(self) -> dict[str, str]:
        """Load Mattermost config from DB (cached), falling back to env vars."""
        if self._config is None:
            self._config = await _load_mattermost_config(self.session)
        return self._config

    def _cfg(self, key: str, fallback: str | bool = "") -> str:
        """Sync config access (use after _get_config has been called)."""
        if self._config:
            val = self._config.get(key)
            if val:
                return val
        return str(getattr(self.settings, key, fallback))

    async def is_enabled(self) -> bool:
        await self._get_config()
        enabled = self._cfg("MATTERMOST_ENABLED", False)
        bot_token = self._cfg("MATTERMOST_BOT_TOKEN")
        return bool(enabled and enabled.lower() not in ("false", "0", "") and bot_token)

    async def _get_client(self) -> httpx.AsyncClient:
        await self._get_config()
        if self._client is None:
            url = self._cfg("MATTERMOST_URL")
            token = self._cfg("MATTERMOST_BOT_TOKEN")
            if not token:
                raise ValueError("MATTERMOST_BOT_TOKEN is not configured")
            _validate_mattermost_url(url)
            self._client = httpx.AsyncClient(
                base_url=url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
        return self._client

    async def get_bot_user_id(self) -> str | None:
        """Get the bot's own Mattermost user ID."""
        client = await self._get_client()
        try:
            resp = await client.get("/api/v4/users/me")
            resp.raise_for_status()
            return resp.json().get("id")
        except httpx.HTTPError:
            logger.exception("Failed to get bot user ID")
            return None

    async def get_bot_identity(self) -> tuple[str | None, str | None]:
        """Get the bot's ``(user_id, username)`` in één call.

        De username hebben we nodig om ``@bouwmeester``-vermeldingen in
        kanaalberichten te herkennen; die is per installatie anders, dus
        hardcoden kan niet.
        """
        client = await self._get_client()
        try:
            resp = await client.get("/api/v4/users/me")
            resp.raise_for_status()
            data = resp.json()
            user_id = data.get("id") or None
            username = data.get("username") or None
            if user_id is None:
                # Zonder user-id werkt de anti-feedback-loop-check niet en
                # zou de bot zijn eigen replies als gebruikersberichten
                # inlezen. Dan liever ook de username laten vallen, zodat
                # hij helemaal niet op mentions reageert.
                logger.error(
                    "Mattermost /users/me gaf geen user-id terug; "
                    "mention-afhandeling blijft uit"
                )
                return None, None
            return user_id, username
        except httpx.HTTPError:
            logger.exception("Failed to get bot identity")
            return None, None

    async def get_bot_dm_url(self) -> str | None:
        """Build a browser URL for DMing the bot: {base}/{team}/messages/@{username}."""
        client = await self._get_client()
        try:
            me_resp = await client.get("/api/v4/users/me")
            me_resp.raise_for_status()
            username = me_resp.json().get("username")
            if not username:
                return None

            # Try bot's own teams first, fall back to any team on the server.
            # Bot accounts are often not explicitly added to a team.
            team_name: str | None = None
            teams_resp = await client.get("/api/v4/users/me/teams")
            teams_resp.raise_for_status()
            teams = teams_resp.json()
            if teams:
                team_name = teams[0].get("name")

            if not team_name:
                all_teams_resp = await client.get(
                    "/api/v4/teams", params={"per_page": 1}
                )
                all_teams_resp.raise_for_status()
                all_teams = all_teams_resp.json()
                if all_teams:
                    team_name = all_teams[0].get("name")

            if not team_name:
                return None

            base_url = self._cfg("MATTERMOST_URL").rstrip("/")
            return f"{base_url}/{team_name}/messages/@{username}"
        except httpx.HTTPError:
            logger.exception("Failed to build bot DM URL")
            return None

    async def send_dm(
        self,
        person_id: UUID,
        text: str,
        props: dict | None = None,
    ) -> bool:
        """Send a direct message to a person via their Mattermost mapping."""
        mapping = await self.repo.get_by_person_id(person_id)
        if not mapping:
            logger.debug("No Mattermost mapping for person %s", person_id)
            return False

        client = await self._get_client()
        bot_user_id = await self.get_bot_user_id()
        if not bot_user_id:
            return False

        try:
            # Create or get DM channel.
            ch_resp = await client.post(
                "/api/v4/channels/direct",
                json=[bot_user_id, mapping.mattermost_user_id],
            )
            ch_resp.raise_for_status()
            channel_id = ch_resp.json()["id"]

            payload: dict = {"channel_id": channel_id, "message": text}
            if props:
                payload["props"] = props

            msg_resp = await client.post("/api/v4/posts", json=payload)
            msg_resp.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.exception("Failed to send DM to person %s", person_id)
            return False

    async def send_channel_message(
        self,
        channel_id: str,
        text: str,
        props: dict | None = None,
        root_id: str | None = None,
    ) -> str | None:
        """Post a message to a Mattermost channel.

        Geeft het post-id terug, of ``None`` als het posten mislukte.

        Met `root_id` wordt het een reply in die thread. Dat is hoe een
        bijlage onder de brief komt te hangen waar hij bij hoort, in plaats
        van als tweede bericht over hetzelfde onderwerp in het kanaal.

        Waarom een id en niet een bool: zonder het id is een bericht later
        nergens meer aan te wijzen. Een emoji-reaction op een alert kwam
        daardoor nooit ergens aan — `_dispatch_reaction_added` zoekt op
        post-id, en dat van een kamerstuk-alert werd weggegooid. De
        "Weggeklikt"-teller stond daardoor sinds de bouw op nul.

        Een `str | None` is hier veilig voor bestaande aanroepers: die
        doen `if await send_channel_message(...)`, en zowel ``None`` als
        een lege string is falsy.
        """
        client = await self._get_client()
        try:
            payload: dict = {"channel_id": channel_id, "message": text}
            if props:
                payload["props"] = props
            if root_id:
                payload["root_id"] = root_id
            resp = await client.post("/api/v4/posts", json=payload)
            resp.raise_for_status()
            # Een post zonder id is theoretisch: Mattermost geeft hem
            # altijd terug. Maar `or None` voorkomt dat een lege string
            # als "gelukt" telt bij de aanroeper die hem opslaat.
            return (resp.json() or {}).get("id") or None
        except (httpx.HTTPError, ValueError):
            # `ValueError` dekt de `JSONDecodeError` van een 200 zonder
            # JSON — een proxy die een foutpagina teruggeeft. Toen dit nog
            # een bool was kon dat niet gebeuren; nu lezen we de body, dus
            # hoort die fout hier thuis en niet bij de aanroeper.
            logger.exception("Failed to send channel message to %s", channel_id)
            return None

    def _deep_link(self, notification: Notification) -> str:
        """Build a deep link back to the Bouwmeester frontend."""
        base = self.settings.FRONTEND_URL.rstrip("/")
        # Validate scheme to prevent open redirect via misconfigured FRONTEND_URL.
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https"):
            logger.warning("FRONTEND_URL has invalid scheme: %s", parsed.scheme)
            return ""
        if notification.related_task_id:
            return f"{base}/taken?task={notification.related_task_id}"
        if notification.related_node_id:
            return f"{base}/nodes/{notification.related_node_id}"
        return base

    def format_notification(self, notification: Notification) -> tuple[str, dict]:
        """Format a notification into a Mattermost message with rich attachment.

        Returns ``(text, props)`` where ``props`` contains the attachment.
        Interactive buttons zijn weggehaald: Mattermost stuurt voor
        message-attachment-button-clicks geen POST naar onze publieke
        endpoint, dus de "Taak afronden"-knop deed nooit iets.
        """
        color = _NOTIFICATION_COLORS.get(notification.type, "#94A3B8")
        deep_link = self._deep_link(notification)

        fields = []
        if notification.related_node_id:
            fields.append(
                {
                    "short": True,
                    "title": "Node",
                    "value": str(notification.related_node_id),
                }
            )
        if notification.related_task_id:
            fields.append(
                {
                    "short": True,
                    "title": "Taak",
                    "value": str(notification.related_task_id),
                }
            )

        from bouwmeester.utils.tiptap import tiptap_to_plain

        plain_message = tiptap_to_plain(notification.message) or ""

        escaped_title = _escape_md(notification.title)
        escaped_message = _escape_md(plain_message)
        attachment: dict = {
            "fallback": escaped_title,
            "color": color,
            "title": escaped_title,
            "title_link": deep_link,
            "text": escaped_message,
            "fields": fields,
            "footer": "Bouwmeester",
        }

        props: dict = {"attachments": [attachment]}
        return ("", props)

    async def send_notification(self, notification: Notification) -> bool:
        """Route a notification to DM or channel based on type."""
        if not await self.is_enabled():
            return False

        text, props = self.format_notification(notification)

        if notification.type in _CHANNEL_NOTIFICATION_TYPES:
            channel_id = self._cfg("MATTERMOST_NOTIFICATION_CHANNEL_ID")
            if not channel_id:
                logger.debug("No notification channel configured, skipping broadcast")
                return False
            # `send_channel_message` geeft sinds kort een post-id terug;
            # deze functie belooft een bool, dus omzetten in plaats van
            # het id laten lekken naar aanroepers die het niet verwachten.
            return bool(await self.send_channel_message(channel_id, text, props))

        return await self.send_dm(notification.person_id, text, props)

    async def get_bot_dm_posts(
        self, since: int, *, max_channels: int = 50
    ) -> list[dict]:
        """Poll for new DMs sent to the bot since a given timestamp (ms).

        Used by the link code poller to detect incoming link codes.
        Caps the number of DM channels checked to avoid API rate-limiting.
        """
        bot_user_id = await self.get_bot_user_id()
        if not bot_user_id:
            return []

        client = await self._get_client()
        try:
            # Get DM channels for the bot.
            resp = await client.get(
                f"/api/v4/users/{bot_user_id}/channels",
                params={"last_delete_at": 0},
            )
            resp.raise_for_status()
            channels = resp.json()

            dm_channels = [ch for ch in channels if ch.get("type") == "D"]
            # Sort by last_post_at descending so we check the most recently
            # active channels first, then cap to avoid API storms.
            dm_channels.sort(key=lambda c: c.get("last_post_at", 0), reverse=True)
            dm_channels = dm_channels[:max_channels]

            posts = []
            for ch in dm_channels:
                try:
                    pr = await client.get(
                        f"/api/v4/channels/{ch['id']}/posts",
                        params={"since": since, "per_page": 20},
                    )
                    pr.raise_for_status()
                    data = pr.json()
                    for post_id in data.get("order", []):
                        post = data["posts"].get(post_id, {})
                        # Only look at messages from others (not the bot).
                        if post.get("user_id") != bot_user_id:
                            posts.append(post)
                except httpx.HTTPError:
                    logger.debug("Failed to get posts for channel %s", ch["id"])
                    continue

            return posts
        except httpx.HTTPError:
            logger.exception("Failed to poll bot DMs")
            return []

    async def reply_to_post(
        self,
        channel_id: str,
        root_id: str,
        message: str,
        *,
        props: dict | None = None,
    ) -> dict | None:
        """Plaats een reply in dezelfde thread.

        Geeft de aangemaakte post-data terug (incl. ``id``) of ``None`` bij
        fout. Backwards compat: callers die alleen op truthy/falsy checken
        blijven werken.
        """
        client = await self._get_client()
        try:
            payload: dict = {
                "channel_id": channel_id,
                "root_id": root_id,
                "message": message,
            }
            if props:
                payload["props"] = props
            resp = await client.post("/api/v4/posts", json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            logger.exception("Failed to reply to post %s", root_id)
            return None

    async def add_reaction(self, post_id: str, emoji_name: str) -> bool:
        """Plak een reactie-emoji op een post.

        Wordt door de ingest-service gebruikt om subtiel te bevestigen dat
        een bericht is verwerkt. We hebben de bot-user-id nodig — de
        Mattermost-API verwacht die in de payload, niet als query-param.
        Returns ``True`` bij succes, ``False`` bij fout (geen retry).
        """
        bot_user_id = await self.get_bot_user_id()
        if not bot_user_id:
            return False
        client = await self._get_client()
        try:
            resp = await client.post(
                "/api/v4/reactions",
                json={
                    "user_id": bot_user_id,
                    "post_id": post_id,
                    "emoji_name": emoji_name,
                },
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.exception(
                "Failed to add reaction %s to post %s", emoji_name, post_id
            )
            return False

    async def get_post_reactions(self, post_id: str) -> list[dict] | None:
        """The reactions that are on a post now, each with who and when.

        ``None`` when they could not be fetched, which is not the same as
        an empty list: no reactions means something to the caller. A post
        that is gone raises ``PostNotFoundError``, as `get_post` does.
        """
        client = await self._get_client()
        try:
            resp = await client.get(f"/api/v4/posts/{post_id}/reactions")
            if resp.status_code == 404:
                raise PostNotFoundError(post_id)
            resp.raise_for_status()
            # Mattermost answers `null` and not `[]` for a post without
            # reactions.
            data = resp.json() or []
        except (httpx.HTTPError, ValueError):
            logger.warning("Kon de reacties op post %s niet ophalen", post_id)
            return None
        if not isinstance(data, list):
            return None
        return [r for r in data if isinstance(r, dict)]

    async def update_post(
        self, post_id: str, message: str, props: dict | None = None
    ) -> bool:
        """Change the text of an existing Mattermost post.

        As a patch, which changes only what is sent. A full update takes
        "pinned" and "has reactions" from the post it is given, so one
        without them unpins the message and hides the reactions under it.
        """
        client = await self._get_client()
        try:
            payload: dict = {"message": message}
            if props:
                payload["props"] = props
            resp = await client.put(f"/api/v4/posts/{post_id}/patch", json=payload)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.exception("Failed to update post %s", post_id)
            return False

    async def delete_post(self, post_id: str) -> bool:
        """Remove a post of the bot itself."""
        client = await self._get_client()
        try:
            resp = await client.delete(f"/api/v4/posts/{post_id}")
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.exception("Failed to delete post %s", post_id)
            return False

    async def get_channel(self, channel_id: str) -> dict | None:
        """Fetch a channel, or ``None`` if that fails for any reason.

        Used to find the team a channel lives in: a channel link stored
        before `team_id` existed does not carry it.
        """
        try:
            client = await self._get_client()
            resp = await client.get(f"/api/v4/channels/{channel_id}")
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("Kon kanaal %s niet ophalen", channel_id, exc_info=True)
            return None
        return data if isinstance(data, dict) else None

    async def channel_is_gone(self, channel_id: str) -> bool:
        """Is this channel archived or deleted? Only a certain yes is True.

        A failed call is False. The caller drops its record of the channel
        on a yes, and a Mattermost hiccup must not make it forget a
        channel that is still there.
        """
        try:
            client = await self._get_client()
            resp = await client.get(f"/api/v4/channels/{channel_id}")
            if resp.status_code == 404:
                return True
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("Kon kanaal %s niet controleren", channel_id, exc_info=True)
            return False
        # An archived channel is still returned, with a `delete_at`.
        return isinstance(data, dict) and bool(data.get("delete_at"))

    async def get_channel_by_name(self, team_id: str, name: str) -> dict | None:
        """Fetch a channel by its url name; ``None`` if it cannot be read.

        This is how a `ChannelNameTakenError` is told apart: the name may
        be taken by a channel this bot created a moment ago. Mattermost
        can save a channel and still answer with an error or not answer in
        time, and then the retry runs into its own first attempt.

        An archived channel is ``None`` here as well: Mattermost only
        returns it when asked for deleted channels.
        """
        try:
            client = await self._get_client()
            resp = await client.get(f"/api/v4/teams/{team_id}/channels/name/{name}")
            if resp.status_code == 404:
                # The ordinary answer for a name held by an archived
                # channel; nothing to log a stack trace about.
                return None
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("Kon kanaal %s niet op naam ophalen", name, exc_info=True)
            return None
        return data if isinstance(data, dict) and data.get("id") else None

    async def create_channel(
        self,
        *,
        team_id: str,
        name: str,
        display_name: str,
        header: str = "",
        purpose: str = "",
        private: bool = False,
    ) -> dict:
        """Create a channel and return it as Mattermost describes it.

        Header and purpose go along in the same call. That is not a
        shortcut: setting them afterwards needs
        `manage_public_channel_properties`, creating them does not, so
        one call needs one permission instead of two.

        Raises instead of returning ``None``, unlike most methods here.
        The three ways this fails ask for three different reactions, and
        a single falsy value would hide which one it was:

        * `MattermostPermissionError`: an administrator has to act;
        * `ChannelNameTakenError`: the name is in use, possibly by a
          channel an earlier attempt of the same caller created (see
          `get_channel_by_name`);
        * `MattermostUnavailableError`: it did not work and the reason is
          in the log. Often temporary, not always: a revoked token or a
          rejected name lands here too, so do not retry in a loop.
        """
        payload = {
            "team_id": team_id,
            "name": name,
            "display_name": display_name,
            "header": header,
            "purpose": purpose,
            "type": "P" if private else "O",
        }
        try:
            # `_get_client` raises ValueError on a missing token or a
            # rejected URL. Inside the try, so the caller sees the three
            # documented exceptions and not a fourth.
            client = await self._get_client()
            resp = await client.post("/api/v4/channels", json=payload)
        except (httpx.HTTPError, ValueError) as exc:
            raise MattermostUnavailableError(
                f"Kon kanaal {name} niet aanmaken: Mattermost onbereikbaar"
            ) from exc

        # On the error id and not on the status alone: a proxy answers 403
        # as well, and that is not something a permission fixes. Mattermost
        # uses this one id both for a missing permission and for a bot that
        # is not a member of the team.
        if resp.status_code == 403 and _error_id(resp) == _PERMISSION_ERROR_ID:
            raise MattermostPermissionError(
                PERMISSION_CREATE_PRIVATE_CHANNEL
                if private
                else PERMISSION_CREATE_PUBLIC_CHANNEL
            )
        if resp.status_code == 400 and _error_id(resp) == _CHANNEL_EXISTS_ERROR_ID:
            raise ChannelNameTakenError(name)
        if resp.status_code >= 400:
            # Body in the log: a 400 here is a limit we exceeded or a name
            # Mattermost rejects, and the error id is the only thing that
            # says which.
            logger.error(
                "Kanaal %s aanmaken gaf status %s: %s",
                name,
                resp.status_code,
                resp.text[:500],
            )
            raise MattermostUnavailableError(
                f"Kon kanaal {name} niet aanmaken: status {resp.status_code}"
            )

        try:
            channel = resp.json()
        except ValueError as exc:
            raise MattermostUnavailableError(
                f"Kanaal {name} aangemaakt, maar het antwoord was onleesbaar"
            ) from exc
        if not isinstance(channel, dict) or not channel.get("id"):
            raise MattermostUnavailableError(
                f"Kanaal {name} aangemaakt, maar het antwoord had geen id"
            )
        return channel

    async def update_channel(
        self,
        channel_id: str,
        *,
        header: str | None = None,
        purpose: str | None = None,
        display_name: str | None = None,
    ) -> bool:
        """Change header, purpose or display name; ``None`` leaves a field.

        Mattermost posts a system message in the channel for a changed
        header or purpose, so only send what really changed.
        """
        patch = {
            key: value
            for key, value in (
                ("header", header),
                ("purpose", purpose),
                ("display_name", display_name),
            )
            if value is not None
        }
        if not patch:
            return True
        try:
            client = await self._get_client()
            resp = await client.put(f"/api/v4/channels/{channel_id}/patch", json=patch)
            resp.raise_for_status()
            return True
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to update channel %s", channel_id)
            return False

    async def add_channel_member(self, channel_id: str, user_id: str) -> bool:
        """Add a user to a channel. Already being a member counts as success."""
        try:
            client = await self._get_client()
            resp = await client.post(
                f"/api/v4/channels/{channel_id}/members", json={"user_id": user_id}
            )
            resp.raise_for_status()
            return True
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to add user %s to channel %s", user_id, channel_id)
            return False

    async def pin_post(self, post_id: str) -> bool:
        """Pin a post in its channel. Needs no more than channel membership."""
        return await self._set_pinned(post_id, pinned=True)

    async def unpin_post(self, post_id: str) -> bool:
        return await self._set_pinned(post_id, pinned=False)

    async def _set_pinned(self, post_id: str, *, pinned: bool) -> bool:
        action = "pin" if pinned else "unpin"
        try:
            client = await self._get_client()
            resp = await client.post(f"/api/v4/posts/{post_id}/{action}")
            resp.raise_for_status()
            return True
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to %s post %s", action, post_id)
            return False

    async def team_permissions(self) -> dict[str, set[str]]:
        """Which permissions the bot holds, per team it is a member of.

        Asks the server instead of assuming. Whether a bot may create a
        channel is not a property of bots: Mattermost checks
        `create_public_channel` on the team, and that permission sits in
        the default role of every team member. A server only refuses if an
        administrator took it out of that role, and that differs per
        server and per team (a team can carry its own permission scheme).

        A permission counts if any of the bot's roles grants it, system
        roles included: that is how Mattermost itself evaluates a team
        permission.

        Raises `MattermostUnavailableError` if the answer cannot be
        established. An empty dict would read as "no permissions anywhere"
        and send an administrator looking for a problem that is not there.
        An empty dict therefore means one thing: the bot is in no team.
        """
        try:
            client = await self._get_client()
            me_resp = await client.get("/api/v4/users/me")
            me_resp.raise_for_status()
            members_resp = await client.get("/api/v4/users/me/teams/members")
            members_resp.raise_for_status()
            system_roles = str(me_resp.json().get("roles") or "").split()
            roles_per_team = {
                member["team_id"]: str(member.get("roles") or "").split()
                for member in members_resp.json()
                # This endpoint also lists teams the bot was removed from,
                # roles and all. Mattermost ignores those when it checks a
                # permission, so counting them promises a right that is
                # gone.
                if member.get("team_id") and not member.get("delete_at")
            }

            names = sorted({*system_roles, *sum(roles_per_team.values(), [])})
            permissions_per_role: dict[str, set[str]] = {}
            if names:
                roles_resp = await client.post("/api/v4/roles/names", json=names)
                roles_resp.raise_for_status()
                permissions_per_role = {
                    role["name"]: set(role.get("permissions") or [])
                    for role in roles_resp.json()
                    # A deleted role grants nothing either.
                    if role.get("name") and not role.get("delete_at")
                }
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            raise MattermostUnavailableError(
                "Kon de rechten van de bot niet opvragen"
            ) from exc

        def granted(role_names: list[str]) -> set[str]:
            result: set[str] = set()
            for role_name in role_names:
                result |= permissions_per_role.get(role_name, set())
            return result

        system_permissions = granted(system_roles)
        return {
            team_id: system_permissions | granted(team_roles)
            for team_id, team_roles in roles_per_team.items()
        }

    async def get_username(self, mattermost_user_id: str) -> str:
        """Fetch the Mattermost username for a user ID."""
        client = await self._get_client()
        try:
            resp = await client.get(f"/api/v4/users/{mattermost_user_id}")
            resp.raise_for_status()
            return resp.json().get("username", mattermost_user_id)
        except httpx.HTTPError:
            return mattermost_user_id

    async def get_file_info(self, file_id: str) -> dict | None:
        """Haal metadata van een Mattermost-bestand op.

        Returns ``None`` bij elke fout zodat de caller (ingest) een rotte
        file kan overslaan zonder de hele post-verwerking te laten klappen.
        """
        client = await self._get_client()
        try:
            resp = await client.get(f"/api/v4/files/{file_id}/info")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            logger.warning("Kon file-info voor %s niet ophalen", file_id)
            return None

    async def download_file(self, file_id: str, *, max_bytes: int) -> bytes | None:
        """Download een Mattermost-bestand, met cap op ``max_bytes``.

        Streamt zodat een veel-te-groot bestand niet eerst volledig in
        geheugen geladen wordt. Bij overschrijden van ``max_bytes``,
        netwerkfout, of niet-200-status returnen we ``None``. De caller
        moet dan deze ene file overslaan.

        Eigen timeout van 30s, ruimer dan de default 10s op het client-
        niveau, omdat file-downloads merkbaar trager zijn dan API-calls.
        """
        client = await self._get_client()
        try:
            async with client.stream(
                "GET",
                f"/api/v4/files/{file_id}",
                timeout=30.0,
            ) as resp:
                if resp.status_code != 200:
                    logger.warning(
                        "Download file %s gaf status %s",
                        file_id,
                        resp.status_code,
                    )
                    return None
                buffer = bytearray()
                async for chunk in resp.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        logger.warning(
                            "File %s overschrijdt max_bytes (%d), abort",
                            file_id,
                            max_bytes,
                        )
                        return None
                return bytes(buffer)
        except httpx.HTTPError:
            logger.warning("Kon file %s niet downloaden", file_id)
            return None

    async def is_bot_member_of_channel(self, channel_id: str) -> bool:
        """Check of de bot momenteel lid is van een kanaal.

        Gebruikt het ``/channels/{id}/members/{bot_user_id}``-endpoint:
        - 200 → lid (``True``)
        - 404 → expliciet geen lid (``False``)
        - andere statussen of netwerkfout → ``MattermostUnavailableError``
          zodat de caller onderscheid kan maken tussen "echt geen lid"
          en "kan het niet bevestigen". Een soft-fail naar ``False``
          zou een tijdelijke MM-storing onterecht laten lijken op een
          weggegooide bot-membership.
        """
        bot_user_id = await self.get_bot_user_id()
        if not bot_user_id:
            raise MattermostUnavailableError(
                "Bot-user-id niet beschikbaar — Mattermost niet bereikbaar"
            )
        client = await self._get_client()
        try:
            resp = await client.get(
                f"/api/v4/channels/{channel_id}/members/{bot_user_id}"
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "Mattermost membership-check faalde voor kanaal %s: %s",
                channel_id,
                exc,
            )
            raise MattermostUnavailableError(
                f"Kon bot-membership voor kanaal {channel_id} niet checken"
            ) from exc
        if resp.status_code == 404:
            return False
        if resp.status_code == 200:
            return True
        logger.warning(
            "Mattermost membership-check gaf onverwachte status %s voor kanaal %s",
            resp.status_code,
            channel_id,
        )
        raise MattermostUnavailableError(
            f"Onverwachte status {resp.status_code} bij membership-check"
        )

    async def team_namen(self) -> dict[str, str]:
        """Team-id naar leesbare naam, voor de teams waar de bot in zit.

        Bij het tonen opgehaald en niet in de database opgeslagen. Een
        opgeslagen naam veroudert zodra iemand het team in Mattermost
        hernoemt, en dan toont Bouwmeester maandenlang iets dat er correct
        uitziet maar het niet is. Er valt op deze manier ook niets te
        backfillen: bestaande koppelingen dragen geen naam en zouden dat
        met een kolom erbij ook niet doen.

        De bot zit in een handvol teams, dus dit is één verzoek per keer
        dat een lijst wordt opgebouwd, niet één per kanaal.

        Faalt zacht: zonder namen is de lijst hetzelfde als voorheen.
        """
        client = await self._get_client()
        try:
            resp = await client.get("/api/v4/users/me/teams")
            resp.raise_for_status()
            teams = resp.json()
        except httpx.HTTPError:
            logger.warning("Kon de teams van de bot niet ophalen", exc_info=True)
            return {}

        namen: dict[str, str] = {}
        for team in teams:
            team_id = team.get("id")
            if not team_id:
                continue
            # `display_name` is wat een mens in Mattermost ziet; `name` is
            # de url-slug. Zonder display_name is de slug beter dan niets.
            namen[team_id] = team.get("display_name") or team.get("name") or ""
        return namen

    async def teams_info(self) -> dict[str, dict[str, str]]:
        """Team id to ``{"slug", "display_name"}``, for the bot's teams.

        The slug is the url name a link needs; the display name is what a
        human reads. One call for both. Fails soft: without it there are
        team ids but no names and no links.
        """
        try:
            client = await self._get_client()
            resp = await client.get("/api/v4/users/me/teams")
            resp.raise_for_status()
            teams = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("Kon de teams van de bot niet ophalen", exc_info=True)
            return {}
        if not isinstance(teams, list):
            return {}
        return {
            team["id"]: {
                "slug": str(team.get("name") or ""),
                "display_name": str(team.get("display_name") or team.get("name") or ""),
            }
            for team in teams
            if isinstance(team, dict) and team.get("id")
        }

    async def is_team_member(self, team_id: str, user_id: str) -> bool:
        """Is this user an active member of this team right now?

        Asked through `POST /teams/{id}/members/ids`, which returns the
        active members among the ids given: a removed member and someone
        who never was one both give an empty list.

        Not through `GET /teams/{id}/members/{user}`, although that looks
        like the obvious question. Newer Mattermost versions hide role data
        of other people's memberships from anyone who cannot manage team
        roles, and blank `delete_at` to -1 while doing so. The field that
        should tell a removed member from an active one then says the same
        for both. Reading it as "non-zero means removed" told an active
        member in production that they were not one; a local Mattermost 9.5
        does not hide anything and showed 0, so it went unnoticed.

        Raises `MattermostUnavailableError` on anything that is not a clear
        answer, so a hiccup reads as neither yes nor no.
        """
        try:
            client = await self._get_client()
            resp = await client.post(
                f"/api/v4/teams/{team_id}/members/ids", json=[user_id]
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise MattermostUnavailableError(
                f"Kon lidmaatschap van team {team_id} niet controleren"
            ) from exc
        if resp.status_code != 200:
            raise MattermostUnavailableError(
                f"Onverwachte status {resp.status_code} bij teamlidmaatschap"
            )
        try:
            members = resp.json()
        except ValueError as exc:
            raise MattermostUnavailableError(
                "Onleesbaar antwoord bij teamlidmaatschap"
            ) from exc
        if not isinstance(members, list):
            raise MattermostUnavailableError("Onverwacht antwoord bij teamlidmaatschap")
        return any(
            isinstance(member, dict) and member.get("user_id") == user_id
            for member in members
        )

    async def base_url(self) -> str:
        """The Mattermost URL as configured, without a trailing slash."""
        await self._get_config()
        return self._cfg("MATTERMOST_URL").rstrip("/")

    async def team_id_per_kanaal(self) -> dict[str, str]:
        """Kanaal-id naar team-id, voor alle kanalen van de bot.

        Bestaande koppelingen zijn zonder `team_id` opgeslagen, dus er is
        niets om een teamnaam mee op te zoeken. In plaats van een
        migratie die dat eenmalig vult (en die voor elke koppeling van
        vóór deze wijziging alsnog gedraaid moet worden), halen we het bij
        het tonen op. Dat herstelt zichzelf en kan niet verouderen.
        """
        bot_user_id = await self.get_bot_user_id()
        if not bot_user_id:
            return {}

        client = await self._get_client()
        try:
            resp = await client.get(
                f"/api/v4/users/{bot_user_id}/channels",
                params={"last_delete_at": 0},
            )
            resp.raise_for_status()
            kanalen = resp.json()
        except httpx.HTTPError:
            logger.warning("Kon de kanalen van de bot niet ophalen", exc_info=True)
            return {}

        return {
            ch["id"]: ch["team_id"]
            for ch in kanalen
            if ch.get("id") and ch.get("team_id")
        }

    async def search_channels(self, query: str) -> list[dict]:
        """Zoek kanalen waar de bot in zit, gefilterd op naam.

        Returns een lijst van dicts met channel_id, channel_name,
        channel_display_name, team_id, team_name, member_count,
        is_bot_member.

        We zoeken alleen binnen de kanalen waarvan de bot lid is — pas
        wanneer de bot toegevoegd wordt aan een kanaal kunnen we daar
        meelezen.
        """
        bot_user_id = await self.get_bot_user_id()
        if not bot_user_id:
            return []

        client = await self._get_client()
        needle = query.strip().lower()
        if not needle:
            return []

        try:
            resp = await client.get(
                f"/api/v4/users/{bot_user_id}/channels",
                params={"last_delete_at": 0},
            )
            resp.raise_for_status()
            channels = resp.json()
        except httpx.HTTPError:
            logger.exception("Failed to list bot channels")
            return []

        # Twee kanalen in verschillende teams kunnen dezelfde naam dragen,
        # en dan toont de picker twee identieke regels met een
        # koppel-knop. Zonder de teamnaam is er geen manier om te kiezen
        # dan gokken.
        namen = await self.team_namen()

        results: list[dict] = []
        for ch in channels:
            ch_type = ch.get("type")
            # Open kanalen ("O") en private kanalen ("P"). DMs ("D") en
            # group-DMs ("G") zijn niet relevant voor lead-koppelingen.
            if ch_type not in ("O", "P"):
                continue
            name = ch.get("name", "")
            display_name = ch.get("display_name", "") or name
            if needle not in name.lower() and needle not in display_name.lower():
                continue
            results.append(
                {
                    "channel_id": ch.get("id", ""),
                    "channel_name": name,
                    "channel_display_name": display_name,
                    "team_id": ch.get("team_id"),
                    "team_name": namen.get(ch.get("team_id") or "") or None,
                    "member_count": ch.get("total_msg_count"),
                    "is_bot_member": True,
                    # Een casus krijgt alleen een privékanaal.
                    "is_private": ch_type == "P",
                }
            )
            if len(results) >= 25:
                break
        return results

    async def get_post(self, post_id: str) -> dict | None:
        """Haal één post op.

        Gebruikt door de herverwerking van posts die eerder door een
        onbereikbare LLM niet beoordeeld konden worden. Daar telt het
        verschil tussen "bestaat niet meer" en "kon 'm even niet ophalen":

        * de post is echt weg (404, of soft-deleted met ``delete_at``) →
          ``PostNotFoundError``, zodat de caller hem uit de wachtrij haalt;
        * tijdelijke fout (time-out, 5xx, 429) → ``None``, zodat de caller
          hem laat staan voor de volgende ronde. Eén Mattermost-hik mag geen
          hele batch echte leads als "verwijderd" afschrijven.
        """
        client = await self._get_client()
        try:
            resp = await client.get(f"/api/v4/posts/{post_id}")
            if resp.status_code == 404:
                raise PostNotFoundError(post_id)
            resp.raise_for_status()
            data = resp.json()
            # Mattermost geeft een soft-deleted post terug met status 200 en
            # een delete_at != 0, niet met een 404.
            if data.get("delete_at"):
                raise PostNotFoundError(post_id)
            return data
        except httpx.HTTPError:
            logger.warning("Kon Mattermost-post %s niet ophalen", post_id)
            return None

    async def get_channel_posts_since(
        self, channel_id: str, since: int, *, per_page: int = 60
    ) -> list[dict]:
        """Haal posts uit een kanaal op vanaf een ms-timestamp.

        Gebruikt voor recovery na websocket-reconnect. Returneert posts
        in chronologische volgorde (oudste eerst) zodat downstream-logica
        ze in volgorde kan verwerken.
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"/api/v4/channels/{channel_id}/posts",
                params={"since": since, "per_page": per_page},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError:
            logger.exception("Failed to fetch posts for channel %s", channel_id)
            return []

        order = data.get("order", [])
        posts_map = data.get("posts", {})
        # `order` komt nieuw->oud terug. Zet om naar oud->nieuw.
        posts = [posts_map.get(pid) for pid in reversed(order) if posts_map.get(pid)]
        return posts

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


async def vul_teamnaam_aan(session: AsyncSession, antwoorden: list) -> list:
    """Vul `team_id` en `team_name` aan op alles wat een kanaal toont.

    Werkt op elk antwoordobject dat `channel_id`, `team_id` en `team_name`
    draagt, zodat de kanaalkaart en het beheeroverzicht dezelfde weg lopen
    in plaats van twee implementaties naast elkaar.

    Twee dingen worden hier opgehaald in plaats van opgeslagen.

    De naam, omdat een opgeslagen naam veroudert zodra iemand het team in
    Mattermost hernoemt; Bouwmeester zou dan maandenlang iets tonen dat er
    correct uitziet en het niet is.

    En het team-id, omdat koppelingen van vóór deze wijziging het niet
    dragen: `team_id` staat daar op NULL, dus er valt niets op te zoeken.
    Een migratie die dat eenmalig vult lost het op voor wat er nu is en
    niet voor wat er tussendoor bijkomt. Bij het tonen ophalen herstelt
    zichzelf.

    Faalt zacht: zonder Mattermost is de lijst precies wat hij hiervoor
    was. Een kanaal zonder teamnaam is beter dan een lijst die omvalt.
    """
    if not antwoorden:
        return antwoorden

    service = MattermostService(session)
    if not await service.is_enabled():
        return antwoorden

    namen = await service.team_namen()
    if not namen:
        return antwoorden

    ontbreekt = any(a.team_id is None for a in antwoorden)
    per_kanaal = await service.team_id_per_kanaal() if ontbreekt else {}

    for a in antwoorden:
        team_id = a.team_id or per_kanaal.get(a.channel_id)
        if team_id:
            a.team_id = team_id
            a.team_name = namen.get(team_id)
    return antwoorden
