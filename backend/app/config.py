"""Application settings, loaded from the environment."""

from functools import lru_cache
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Every date the NSE publishes is in IST, and every alert time the user picks is
# in IST. We store UTC and convert at the edges; this is the only timezone the
# domain logic should ever reference.
IST = ZoneInfo("Asia/Kolkata")

# libpq connection parameters that managed Postgres providers append to their
# connection strings and that asyncpg rejects outright.
_LIBPQ_ONLY_PARAMS = frozenset(
    {"channel_binding", "sslcert", "sslkey", "sslrootcert", "gssencmode", "target_session_attrs"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Core ---
    database_url: str = "postgresql+asyncpg://ipo:ipo@localhost:5432/ipo"
    app_base_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173"

    # --- Auth ---
    # Magic-link tokens and session JWTs are both signed with this. Override in prod.
    secret_key: str = "dev-secret-change-me"
    magic_link_ttl_minutes: int = 15
    session_ttl_days: int = 30
    # "auto" derives SameSite from whether the SPA and API share a site; set
    # "lax"/"none"/"strict" to force it.
    session_cookie_samesite: str = "auto"

    # --- Google Sign-In (optional; magic link remains as a fallback) ---
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- Internal task endpoint ---
    # The GitHub Actions cron presents this in X-Internal-Token to trigger a poll.
    internal_task_token: str = "dev-internal-token"

    # --- GMP provider (optional; app degrades gracefully without it) ---
    gmp_provider: str = "none"  # "none" | "ipoguru"
    ipoguru_api_key: str = ""

    # --- Notification channels (all optional) ---
    resend_api_key: str = ""
    email_from: str = "IPO Tracker <onboarding@resend.dev>"
    telegram_bot_token: str = ""
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Coerce a managed-provider URL into the async driver form.

        Render (and Heroku, Railway, Fly) expose `postgres://...`, which
        SQLAlchemy will not route to asyncpg. Rewriting here means the platform's
        generated connection string can be used verbatim.
        Managed providers also append libpq connection parameters that asyncpg
        does not accept - `sslmode` above all, which Neon and Supabase always
        include. Left in place it raises `unexpected keyword argument 'sslmode'`
        on the first connect, so it is translated to asyncpg's `ssl` equivalent
        rather than dropped: these hosts require TLS.
        """
        if value.startswith("postgres://"):
            value = "postgresql+asyncpg://" + value[len("postgres://") :]
        elif value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value[len("postgresql://") :]

        if "+asyncpg" not in value or "?" not in value:
            return value

        base, _, query = value.partition("?")
        kept: list[str] = []
        ssl_mode: str | None = None

        for param in query.split("&"):
            if not param:
                continue
            key, _, val = param.partition("=")
            key_lower = key.lower()
            if key_lower == "sslmode":
                ssl_mode = val.lower()
            elif key_lower in _LIBPQ_ONLY_PARAMS:
                continue  # meaningless to asyncpg; would raise on connect
            else:
                kept.append(param)

        if ssl_mode and ssl_mode != "disable":
            # asyncpg understands require/prefer/disable; verify-* modes need a
            # certificate bundle we don't ship, so treat them as plain require.
            kept.append("ssl=require" if ssl_mode != "prefer" else "ssl=prefer")
        elif ssl_mode == "disable":
            kept.append("ssl=disable")

        return f"{base}?{'&'.join(kept)}" if kept else base

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def app_url(self, path: str) -> str:
        """Build a link into the SPA.

        The dashboard is hash-routed, so every in-app path lives after a `#`.
        That keeps deep links - magic-link sign-in above all - working on any
        static host without a server-side rewrite rule, which several hosts
        (Render included) only expose through their dashboard rather than an
        API. Every outbound link is built here so the two can't drift apart.
        """
        return f"{self.app_base_url.rstrip('/')}/#{path if path.startswith('/') else '/' + path}"

    @property
    def cookie_samesite(self) -> str:
        """SameSite policy for the session cookie.

        When the SPA and the API are served from different hosts - the normal
        outcome of deploying them as two Render services - the browser treats
        every API call as cross-site and silently discards a `Lax` cookie. The
        failure is quiet and confusing: login succeeds, then every authenticated
        request 401s. `None` is required there, and it is only honoured over
        HTTPS, which `cookie_secure` enforces.
        """
        if self.session_cookie_samesite != "auto":
            return self.session_cookie_samesite.lower()

        app_host = urlparse(self.app_base_url).netloc.lower()
        api_host = urlparse(self.api_base_url).netloc.lower()
        # Same host (or a dev proxy making them same-origin) keeps the stricter
        # default, which protects against CSRF.
        return "lax" if not app_host or not api_host or app_host == api_host else "none"

    @property
    def cookie_secure(self) -> bool:
        # SameSite=None without Secure is rejected outright by every browser.
        return self.cookie_samesite == "none" or self.app_base_url.startswith("https")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
