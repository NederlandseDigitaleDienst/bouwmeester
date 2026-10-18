from functools import lru_cache
from urllib.parse import quote_plus, urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Database — either provide DATABASE_URL directly, or the ZAD platform
    # env vars (DATABASE_SERVER_HOST, etc.) and it will be constructed.
    DATABASE_URL: str = ""
    DATABASE_SERVER_HOST: str = ""
    DATABASE_SERVER_PORT: str = "5432"
    DATABASE_SERVER_USER: str = ""
    DATABASE_PASSWORD: str = ""
    DATABASE_DB: str = ""
    DATABASE_SCHEMA: str = ""

    APP_NAME: str = "Bouwmeester"
    DEBUG: bool = False

    # OIDC — either provide OIDC_ISSUER directly, or the ZAD platform
    # env vars (OIDC_URL + OIDC_REALM) and it will be constructed.
    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_DISCOVERY_URL: str = ""
    OIDC_URL: str = ""
    OIDC_REALM: str = ""

    # Explicit, deliberate opt-in to run with NO authentication. Only for
    # local dev. When OIDC is not configured, the app refuses to start
    # unless this is set, so an accidentally missing OIDC_ISSUER fails
    # closed instead of silently leaving every /api/ route open.
    DEV_NO_AUTH: bool = False

    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "https://component-1.bouwmeester.rijks.app",
        "https://bouwmeester.rijks.app",
    ]

    # Session — SESSION_SECRET_KEY must be set in production (via ZAD).
    # FRONTEND_URL, SESSION_COOKIE_DOMAIN, and SESSION_COOKIE_SECURE are
    # auto-derived from PUBLIC_HOST when not explicitly set.
    SESSION_SECRET_KEY: str = "change-me-in-production"
    PUBLIC_HOST: str = ""  # Injected by ZAD per component
    FRONTEND_URL: str = ""
    BACKEND_URL: str = ""  # Used for OIDC redirect URIs
    SESSION_COOKIE_DOMAIN: str = ""
    SESSION_COOKIE_SECURE: bool = False
    SESSION_TTL_SECONDS: int = 604800  # 7 days

    # WebAuthn (passkey re-authentication)
    WEBAUTHN_RP_ID: str = ""
    WEBAUTHN_RP_NAME: str = "Bouwmeester"
    WEBAUTHN_ORIGIN: str = ""
    WEBAUTHN_SESSION_TTL_SECONDS: int = 86400  # 24 hours (shorter than OIDC's 7 days)

    ANTHROPIC_API_KEY: str = ""
    # Abonnementstoken uit `claude setup-token`, voor de Claude Code CLI.
    # Gaat vóór op ANTHROPIC_API_KEY: dezelfde modellen, maar op een
    # abonnement in plaats van per token. Werkt alleen via de CLI-binary;
    # de Anthropic SDK accepteert dit token niet. Persoonlijk token, dus
    # het hoort in de secretstore en niet in de repo.
    CLAUDE_CODE_OAUTH_TOKEN: str = ""
    TK_API_BASE_URL: str = "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0"
    EK_API_BASE_URL: str = "https://opendata.eerstekamer.nl"
    TK_POLL_INTERVAL_SECONDS: int = 3600
    TK_IMPORT_LIMIT: int = 100

    # The timeline of a debate: how often Debat Direct is asked who speaks.
    # A speaker change shows up there 5.8 to 8.7 seconds after it happened,
    # so asking more often than this gains nothing. A tick without a debate
    # today is one query and no HTTP call.
    DEBAT_TIJDLIJN_INTERVAL_SECONDS: int = 10
    DEBAT_TIJDLIJN_ENABLED: bool = True
    # The text of each turn under its message, from the subtitles of the
    # stream. Off leaves the timeline as it is.
    DEBAT_TRANSCRIPT_ENABLED: bool = True
    # Questions to the bewindspersoon, marked as a thread under the turn
    # they were asked in. The model that is configured for the application
    # reads every finished turn; a debate is public, so any model may.
    # Needs the transcript. Off leaves the transcript as it is.
    DEBAT_VRAGEN_ENABLED: bool = True
    # A turn is finished some 45 seconds before its text is complete, so
    # looking more often than this finds nothing sooner.
    DEBAT_VRAGEN_INTERVAL_SECONDS: int = 15
    # Around a change of speaker the voice decides whose line it is, not
    # the moment of the event, which is seconds off. Needs the speaker model
    # at the path below; the image downloads it at build. Without that file
    # this step is skipped and a line stays where the time put it.
    DEBAT_STEMMEN_ENABLED: bool = True
    DEBAT_STEM_MODEL_PATH: str = "/models/voxceleb_resnet34_LM.onnx"
    # Debates announced for an initiatief: how often is looked whether one
    # is on today. The reminder goes out once, in the morning, so minutes
    # do not matter here.
    DEBAT_AANKONDIGING_INTERVAL_SECONDS: int = 600

    # tkconv (berthub.eu) draait op een privéserver zonder SLA en heeft een
    # eigen poll-ritme, los van de officiële TK-API. Het ritme volgt wanneer
    # kamerstukken verschijnen: een meting over 1010 stukken in acht dagen
    # gaf 08:00-18:00 met een piek om 16:00, en daarbuiten 2 stukken in acht
    # dagen. 's Nachts elke twee minuten pollen zou dus alleen Berts server
    # belasten. Beide feeds ondersteunen If-None-Match, dus een ronde die
    # niets vindt kost 0 bytes body.
    TKCONV_POLL_INTERVAL_KANTOORUREN_SECONDS: int = 120
    TKCONV_POLL_INTERVAL_AVOND_SECONDS: int = 600
    TKCONV_POLL_INTERVAL_NACHT_SECONDS: int = 3600
    # Grenzen in lokale tijd (Europe/Amsterdam). Kantooruren [start, eind),
    # daarna avond tot `avond_eind`, daarna nacht.
    TKCONV_KANTOORUREN_START: int = 8
    TKCONV_KANTOORUREN_EIND: int = 18
    TKCONV_AVOND_EIND: int = 23
    LLM_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_PROVIDER: str = "claude"  # "claude" or "vlam"
    VLAM_API_KEY: str = ""
    VLAM_MODEL_ID: str = ""
    # Het platform (ZAD-dienst `vlam`) injecteert dit adres van de interne
    # VLAM-proxy in elk component dat de dienst afneemt. Het is het
    # basisadres zonder pad, en het gaat vóór op VLAM_BASE_URL: het platform
    # weet waar de proxy staat, een handmatige waarde kan verouderen.
    VLAM_API_URL: str = ""
    # Handmatig ingesteld adres, voor lokaal draaien of een directe
    # VLAM-endpoint buiten het cluster (dan wel via VPN, want vlam-api
    # .rijksweb.nl is niet publiek resolvebaar).
    VLAM_BASE_URL: str = ""
    ENABLED_IMPORT_TYPES: list[str] = ["motie", "kamervraag", "toezegging"]
    OPDRACHT_TASK_INTERVAL_SECONDS: int = 86400

    # Overheidsorganisatie-syncs. Daily = fast-changing (TK-leden, kabinet,
    # ABD); weekly = slow-changing (TOOI, CSV, RIO, organogram).
    OVERHEIDSORG_DAILY_INTERVAL_SECONDS: int = 24 * 3600
    OVERHEIDSORG_WEEKLY_INTERVAL_SECONDS: int = 7 * 24 * 3600

    # FCC (Fortes Change Cloud) integration
    FCC_ODATA_URL: str = ""
    FCC_API_KEY: str = ""
    FCC_POLL_INTERVAL_SECONDS: int = 3600
    FCC_SYNC_ENABLED: bool = False
    FCC_PUSH_ENABLED: bool = False
    FCC_USE_MOCK: bool = False
    FCC_PROJECT_ENTITY: str = "Portfolio_item"

    # Mattermost integration
    MATTERMOST_ENABLED: bool = False
    MATTERMOST_URL: str = "http://mattermost:8065"
    MATTERMOST_BOT_TOKEN: str = ""
    # Default channel for broadcast notifications
    MATTERMOST_NOTIFICATION_CHANNEL_ID: str = ""
    # Token to verify incoming slash commands
    MATTERMOST_WEBHOOK_TOKEN: str = ""
    # Herverwerking van posts die tijdens een LLM-storing niet beoordeeld
    # konden worden. Kort interval: een storing mag niet lang een gat in de
    # leads laten.
    MATTERMOST_RETRY_INTERVAL_SECONDS: int = 900
    MATTERMOST_LINK_CODE_TTL_MINUTES: int = 10
    MATTERMOST_LINK_CODE_LENGTH: int = 8

    # Age encryption for database backups
    AGE_SECRET_KEY: str = ""  # Age secret key for decryption (set on production)

    # Object storage for bijlagen: the S3-compatible bucket that ZAD's
    # `minio-storage` service injects. Unset means files stay in a local
    # directory (see core/blob_store.py).
    OBJECT_STORE_ENDPOINT_URL: str = ""
    OBJECT_STORE_BUCKET_NAME: str = ""
    OBJECT_STORE_USER: str = ""
    OBJECT_STORE_PASSWORD: str = ""
    OBJECT_STORE_REGION: str = ""

    @property
    def object_store_configured(self) -> bool:
        return bool(
            self.OBJECT_STORE_ENDPOINT_URL
            and self.OBJECT_STORE_BUCKET_NAME
            and self.OBJECT_STORE_USER
            and self.OBJECT_STORE_PASSWORD
        )

    @model_validator(mode="after")
    def _derive_database_url(self) -> "Settings":
        """Build DATABASE_URL from ZAD individual env vars if not set."""
        if not self.DATABASE_URL and self.DATABASE_SERVER_HOST:
            password = quote_plus(self.DATABASE_PASSWORD)
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.DATABASE_SERVER_USER}"
                f":{password}"
                f"@{self.DATABASE_SERVER_HOST}"
                f":{self.DATABASE_SERVER_PORT}"
                f"/{self.DATABASE_DB}"
            )
        if not self.DATABASE_URL:
            self.DATABASE_URL = "postgresql+asyncpg://bouwmeester:bouwmeester@localhost:5432/bouwmeester"
        return self

    @model_validator(mode="after")
    def _derive_oidc_issuer(self) -> "Settings":
        """Build OIDC_ISSUER from ZAD env vars if not set."""
        if not self.OIDC_ISSUER and self.OIDC_URL and self.OIDC_REALM:
            self.OIDC_ISSUER = f"{self.OIDC_URL.rstrip('/')}/realms/{self.OIDC_REALM}"
        return self

    _INSECURE_SECRET_DEFAULTS = frozenset(
        {"change-me-in-production", "local-dev-secret-key"}
    )

    @model_validator(mode="after")
    def _validate_session_secret(self) -> "Settings":
        """Reject insecure default SESSION_SECRET_KEY when OIDC is enabled."""
        if (
            self.OIDC_ISSUER
            and self.SESSION_SECRET_KEY in self._INSECURE_SECRET_DEFAULTS
        ):
            raise ValueError(
                "SESSION_SECRET_KEY must be set to a secure random value "
                "when OIDC is configured. Do not use the default."
            )
        return self

    @model_validator(mode="after")
    def _validate_auth_configured(self) -> "Settings":
        """Fail closed when authentication is not configured.

        Without OIDC the AuthRequiredMiddleware is a no-op and every
        /api/ route is unauthenticated. Refuse to start in that state
        unless DEV_NO_AUTH is explicitly set, so a forgotten OIDC_ISSUER
        crashes loudly instead of silently opening everything up.

        DEV_NO_AUTH is honoured only outside production. PUBLIC_HOST is
        injected by ZAD for every deployed component and is never set in
        local dev, so it is the production marker: DEV_NO_AUTH in a
        deployed environment is refused regardless of OIDC. That keeps
        the opt-in genuinely fail-closed instead of just relocating the
        hole to "one stray env var re-opens everything in prod".

        Runs after _derive_oidc_issuer so the ZAD-derived issuer
        (OIDC_URL + OIDC_REALM) counts as configured.
        """
        if self.DEV_NO_AUTH and self.PUBLIC_HOST:
            raise ValueError(
                "DEV_NO_AUTH mag niet aan staan in een gedeployde omgeving "
                "(PUBLIC_HOST is gezet). Zet OIDC_ISSUER (of OIDC_URL + "
                "OIDC_REALM) zodat authenticatie actief is."
            )
        if not self.OIDC_ISSUER and not self.DEV_NO_AUTH:
            raise ValueError(
                "Authenticatie is niet geconfigureerd: OIDC_ISSUER ontbreekt. "
                "Zet OIDC_ISSUER (of OIDC_URL + OIDC_REALM) in productie, "
                "of zet DEV_NO_AUTH=1 om de applicatie bewust zonder "
                "authenticatie te draaien (alleen voor lokale ontwikkeling)."
            )
        return self

    @model_validator(mode="after")
    def _derive_session_settings(self) -> "Settings":
        """Derive session settings from PUBLIC_HOST when not explicitly set.

        The ZAD platform injects PUBLIC_HOST per component, e.g.
        ``https://component-2.bouwmeester.rijks.app``.  From this we can
        derive FRONTEND_URL (component-1 URL), cookie domain, and secure
        flag — so only SESSION_SECRET_KEY needs to be configured manually.
        """
        if self.PUBLIC_HOST:
            parsed = urlparse(self.PUBLIC_HOST)
            hostname = parsed.hostname or ""

            # Derive FRONTEND_URL: component-2 → component-1 (or strip prefix)
            if not self.FRONTEND_URL and hostname.startswith("component-2."):
                base_domain = hostname[len("component-2.") :]
                self.FRONTEND_URL = f"https://{base_domain}"
            elif not self.FRONTEND_URL and hostname.startswith("component-2-"):
                base_domain = hostname[len("component-2-") :]
                self.FRONTEND_URL = f"https://{base_domain}"

            # Derive cookie domain: strip the component-N subdomain to get
            # the shared parent domain (e.g. .bouwmeester.rijks.app).
            #
            # SECURITY NOTE: This allows cookies to be shared across ALL
            # subdomains of bouwmeester.rijks.app. This is required because
            # the frontend (component-1) and backend (component-2) are on
            # different subdomains. Both the session cookie (HttpOnly) and
            # the CSRF cookie (readable by JS) use SameSite=Lax + Secure.
            if not self.SESSION_COOKIE_DOMAIN and "." in hostname:
                # Strip first subdomain (component-N)
                parts = hostname.split(".", 1)
                if len(parts) == 2:
                    self.SESSION_COOKIE_DOMAIN = f".{parts[1]}"

            # HTTPS → secure cookies
            if parsed.scheme == "https":
                self.SESSION_COOKIE_SECURE = True

        if not self.FRONTEND_URL:
            self.FRONTEND_URL = "http://localhost:5173"

        # Ensure FRONTEND_URL is in CORS_ORIGINS so the browser can reach
        # the backend from whichever component hosts the frontend.
        if self.FRONTEND_URL and self.FRONTEND_URL not in self.CORS_ORIGINS:
            self.CORS_ORIGINS = [*self.CORS_ORIGINS, self.FRONTEND_URL]
        # Derive BACKEND_URL from PUBLIC_HOST (which is the backend's URL on ZAD).
        if not self.BACKEND_URL and self.PUBLIC_HOST:
            self.BACKEND_URL = self.PUBLIC_HOST.rstrip("/")
        if not self.BACKEND_URL:
            self.BACKEND_URL = "http://localhost:8000"

        # Derive WebAuthn settings from FRONTEND_URL.
        frontend_parsed = urlparse(self.FRONTEND_URL)
        if not self.WEBAUTHN_RP_ID and frontend_parsed.hostname:
            self.WEBAUTHN_RP_ID = frontend_parsed.hostname
        if not self.WEBAUTHN_ORIGIN:
            self.WEBAUTHN_ORIGIN = (
                f"{frontend_parsed.scheme}://{frontend_parsed.hostname}"
                + (f":{frontend_parsed.port}" if frontend_parsed.port else "")
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def is_dev_mode() -> bool:
    """True when running without an identity provider (local development).

    Settings refuses to start that way unless ``DEV_NO_AUTH`` is set and no
    public host is configured, so this is never true in production.  A
    request without a user gets every right in dev mode and none otherwise.
    """
    return not get_settings().OIDC_ISSUER
