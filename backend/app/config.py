"""Application settings, loaded from the environment."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Every date the NSE publishes is in IST, and every alert time the user picks is
# in IST. We store UTC and convert at the edges; this is the only timezone the
# domain logic should ever reference.
IST = ZoneInfo("Asia/Kolkata")


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
        """
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
