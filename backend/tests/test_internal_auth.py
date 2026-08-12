"""The operator escape hatch for magic-link auth.

Passwordless login has a single point of failure: broken mail delivery locks
out the very person who needs to fix it. These tests pin the guard rails on the
bypass, since an unguarded one would be a full authentication bypass.
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth import consume_magic_token, hash_token
from app.config import settings
from app.models import MagicLinkToken, User
from app.routers.internal import mint_magic_link, verify_token


@pytest.mark.parametrize("bad", ["wrong-token", "", "   ", "dev-internal-token "])
async def test_requires_the_internal_token(bad):
    with pytest.raises(HTTPException) as exc:
        await verify_token(x_internal_token=bad)
    assert exc.value.status_code == 403


async def test_accepts_the_correct_token():
    assert await verify_token(x_internal_token=settings.internal_task_token) is None


@pytest.mark.parametrize("bad", ["", "   ", "not-an-email"])
async def test_rejects_invalid_email(session, bad):
    with pytest.raises(HTTPException) as exc:
        await mint_magic_link(email=bad, session=session)
    assert exc.value.status_code == 400


async def test_minted_link_stores_only_a_hash(session):
    """A database leak must not yield usable login links."""
    result = await mint_magic_link(email="Me@Example.COM ", session=session)
    raw = result["login_url"].split("token=")[1]

    stored = (await session.execute(select(MagicLinkToken))).scalars().one()
    assert stored.email == "me@example.com"  # normalised
    assert stored.token_hash == hash_token(raw)
    assert raw not in stored.token_hash


async def test_minted_link_signs_in_and_is_single_use(session):
    result = await mint_magic_link(email="me@example.com", session=session)
    raw = result["login_url"].split("token=")[1]

    user = await consume_magic_token(session, raw)
    assert user.email == "me@example.com"
    assert (await session.execute(select(User))).scalars().one().id == user.id

    # Burned: replaying the same link must fail.
    with pytest.raises(HTTPException) as exc:
        await consume_magic_token(session, raw)
    assert exc.value.status_code == 400


async def test_expired_link_is_refused(session):
    result = await mint_magic_link(email="me@example.com", session=session)
    raw = result["login_url"].split("token=")[1]

    token = (await session.execute(select(MagicLinkToken))).scalars().one()
    token.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await consume_magic_token(session, raw)
    assert exc.value.status_code == 400


async def test_unknown_token_is_refused(session):
    with pytest.raises(HTTPException) as exc:
        await consume_magic_token(session, "never-issued")
    assert exc.value.status_code == 400
