"""Endpoints for operators and the scheduler, guarded by a shared secret."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_magic_token
from app.config import settings
from app.db import get_session
from app.models import MagicLinkToken
from app.tasks.poll import run_cycle

router = APIRouter(prefix="/internal", tags=["internal"])


async def verify_token(x_internal_token: str = Header(default="")) -> None:
    # Constant-time compare so the token can't be recovered by timing the endpoint.
    if not secrets.compare_digest(x_internal_token, settings.internal_task_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid internal token")


@router.post("/tasks/poll", dependencies=[Depends(verify_token)])
async def trigger_poll(session: AsyncSession = Depends(get_session)):
    """Run one ingest -> evaluate -> dispatch cycle.

    Called by the GitHub Actions cron. Returns the cycle summary so a failing
    stage is visible in the workflow log rather than silently swallowed.
    """
    return await run_cycle(session)


@router.post("/auth/link", dependencies=[Depends(verify_token)])
async def mint_magic_link(email: str, session: AsyncSession = Depends(get_session)):
    """Mint a sign-in link out-of-band, without sending email.

    Magic-link auth has one hard failure mode: if mail delivery breaks, nobody
    can get in — including whoever needs to fix it. A misconfigured sender, an
    expired API key or a provider that only permits sending to a verified
    address all lock the operator out of their own deployment.

    This is the escape hatch. It is guarded by the same secret as the poller,
    which is server-side only and never reaches a browser, and it issues an
    ordinary single-use token through the normal verification flow rather than
    minting a session directly — so the link still expires, still burns on use,
    and grants nothing that a delivered email wouldn't have.
    """
    address = email.strip().lower()
    if not address or "@" not in address:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A valid email is required")

    raw, hashed = create_magic_token()
    session.add(
        MagicLinkToken(
            email=address,
            token_hash=hashed,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.magic_link_ttl_minutes),
        )
    )
    await session.commit()

    return {
        "email": address,
        "login_url": settings.app_url(f"/auth/verify?token={raw}"),
        "expires_in_minutes": settings.magic_link_ttl_minutes,
    }
