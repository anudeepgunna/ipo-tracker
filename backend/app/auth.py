"""Magic-link authentication.

Passwordless by design: there is no password to store, leak, or reset, and the
email delivery it depends on is already a hard requirement for alerts. Tokens are
stored only as SHA-256 hashes, so a database leak does not yield usable login
links, and each is single-use with a short TTL.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import MagicLinkToken, User

SESSION_COOKIE = "ipo_session"
_ALGORITHM = "HS256"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_magic_token() -> tuple[str, str]:
    """Return (plaintext, hash). Only the hash is persisted."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def issue_session(user: User) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user.id),
            "email": user.email,
            "iat": now,
            "exp": now + timedelta(days=settings.session_ttl_days),
        },
        settings.secret_key,
        algorithm=_ALGORITHM,
    )


async def consume_magic_token(session: AsyncSession, raw_token: str) -> User:
    """Validate a magic link and return the user, creating them on first login."""
    record = await session.scalar(
        select(MagicLinkToken).where(MagicLinkToken.token_hash == hash_token(raw_token))
    )
    now = datetime.now(UTC)

    def _expiry_aware(value: datetime) -> datetime:
        # SQLite drops tzinfo on round-trip; treat naive values as UTC.
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    if record is None or record.used_at is not None or _expiry_aware(record.expires_at) < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This login link is invalid or has expired. Request a new one.",
        )

    record.used_at = now

    user = await session.scalar(select(User).where(User.email == record.email))
    if user is None:
        user = User(email=record.email)
        session.add(user)
        await session.flush()

    # Clicking a link sent to this address proves control of it, so any pending
    # email destination for the same address becomes verified. Without this a
    # public reminder sign-up would confirm nothing and never deliver.
    from app.models import Channel, NotificationChannel

    pending = (
        (
            await session.execute(
                select(NotificationChannel).where(
                    NotificationChannel.user_id == user.id,
                    NotificationChannel.channel == Channel.EMAIL,
                    NotificationChannel.verified_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for channel in pending:
        if channel.destination.lower() == record.email.lower():
            channel.verified_at = now

    await session.commit()
    return user


async def current_user(
    ipo_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Dependency resolving the signed-in user, or 401."""
    if not ipo_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        payload = jwt.decode(ipo_session, settings.secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc

    user = await session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    return user


async def optional_user(
    ipo_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Like `current_user` but returns None instead of raising.

    Lets the IPO list render for signed-out visitors while still personalising
    (watchlist flags) when a session is present.
    """
    if not ipo_session:
        return None
    try:
        return await current_user(ipo_session, session)
    except HTTPException:
        return None
