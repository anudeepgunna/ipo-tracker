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
    ],
)
def test_database_url_is_normalised_for_asyncpg(given, expected):
    assert Settings(database_url=given, _env_file=None).database_url == expected


def test_cors_origins_split():
    settings = Settings(
        cors_origins="https://a.example , https://b.example,", _env_file=None
    )
    assert settings.cors_origin_list == ["https://a.example", "https://b.example"]
