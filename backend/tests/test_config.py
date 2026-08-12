"""Deployment-shaped config concerns."""

import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Render/Heroku/Railway hand out this form; asyncpg needs the explicit driver.
        (
            "postgres://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        (
            "postgresql://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        # Already explicit: leave alone.
        (
            "postgresql+asyncpg://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        # Local dev.
        ("sqlite+aiosqlite:///./ipo_dev.db", "sqlite+aiosqlite:///./ipo_dev.db"),
        # Neon's real shape. `sslmode` is a libpq parameter that asyncpg rejects
        # with "unexpected keyword argument", so it must become `ssl`, not be
        # dropped - these hosts refuse plaintext connections.
        (
            "postgresql://u:p@ep-x.aws.neon.tech/neondb?sslmode=require",
            "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/neondb?ssl=require",
        ),
        # Supabase-style, with a libpq-only extra that would also raise.
        (
            "postgres://u:p@db.supabase.co:5432/postgres?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@db.supabase.co:5432/postgres?ssl=require",
        ),
        # verify-full needs a CA bundle we don't ship; downgrade to require
        # rather than fail to connect.
        (
            "postgresql://u:p@host/db?sslmode=verify-full",
            "postgresql+asyncpg://u:p@host/db?ssl=require",
        ),
        # Non-SSL params must survive untouched.
        (
            "postgresql://u:p@host/db?sslmode=require&application_name=ipo",
            "postgresql+asyncpg://u:p@host/db?application_name=ipo&ssl=require",
        ),
        ("postgresql://u:p@host/db?sslmode=disable", "postgresql+asyncpg://u:p@host/db?ssl=disable"),
    ],
)
def test_database_url_is_normalised_for_asyncpg(given, expected):
    assert Settings(database_url=given, _env_file=None).database_url == expected


def test_sqlite_query_params_are_left_alone():
    """The libpq translation must only apply to asyncpg URLs."""
    url = "sqlite+aiosqlite:///./x.db?mode=ro"
    assert Settings(database_url=url, _env_file=None).database_url == url


def test_split_host_deploy_requires_samesite_none():
    """Two Render services = cross-site; Lax would drop the cookie silently."""
    settings = Settings(
        app_base_url="https://ipo-tracker-web.onrender.com",
        api_base_url="https://ipo-tracker-api.onrender.com",
        _env_file=None,
    )
    assert settings.cookie_samesite == "none"
    # SameSite=None is rejected by browsers unless Secure is also set.
    assert settings.cookie_secure is True


def test_same_host_keeps_lax():
    settings = Settings(
        app_base_url="https://ipo.example.com",
        api_base_url="https://ipo.example.com",
        _env_file=None,
    )
    assert settings.cookie_samesite == "lax"


def test_local_dev_stays_lax_and_insecure():
    """Vite proxies /api, so localhost is same-origin and http."""
    settings = Settings(
        app_base_url="http://localhost:5173",
        api_base_url="http://localhost:5173",
        _env_file=None,
    )
    assert settings.cookie_samesite == "lax"
    assert settings.cookie_secure is False


def test_samesite_can_be_forced():
    settings = Settings(
        app_base_url="https://a.example",
        api_base_url="https://b.example",
        session_cookie_samesite="lax",
        _env_file=None,
    )
    assert settings.cookie_samesite == "lax"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/ipo/SHIPROCKET", "https://app.example/#/ipo/SHIPROCKET"),
        ("ipo/SHIPROCKET", "https://app.example/#/ipo/SHIPROCKET"),  # leading slash added
        ("/auth/verify?token=abc", "https://app.example/#/auth/verify?token=abc"),
    ],
)
def test_app_url_is_hash_routed(path, expected):
    """Outbound links must survive a static host with no rewrite rule.

    A plain /auth/verify path 404s there, which would break sign-in entirely.
    """
    settings = Settings(app_base_url="https://app.example", _env_file=None)
    assert settings.app_url(path) == expected


def test_app_url_tolerates_trailing_slash():
    settings = Settings(app_base_url="https://app.example/", _env_file=None)
    assert settings.app_url("/inbox") == "https://app.example/#/inbox"


def test_cors_origins_split():
    settings = Settings(
        cors_origins="https://a.example , https://b.example,", _env_file=None
    )
    assert settings.cors_origin_list == ["https://a.example", "https://b.example"]
