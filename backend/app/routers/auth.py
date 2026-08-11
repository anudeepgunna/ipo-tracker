"""Magic-link login."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    SESSION_COOKIE,
    consume_magic_token,
    create_magic_token,
    current_user,
    issue_session,
)
from app.config import settings
from app.db import get_session
from app.models import MagicLinkToken, User
from app.schemas import MagicLinkRequest, UserOut
from app.services.notifications.base import Message
from app.services.notifications.channels import EmailNotifier

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/request-link")
async def request_link(
    payload: MagicLinkRequest, session: AsyncSession = Depends(get_session)
):
    """Email a single-use sign-in link.

    Always reports success: telling an anonymous caller whether an address is
    registered would leak the user list.
    """
    raw, hashed = create_magic_token()
    session.add(
        MagicLinkToken(
            email=payload.email.lower(),
            token_hash=hashed,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.magic_link_ttl_minutes),
        )
    )
    await session.commit()

    link = f"{settings.app_base_url}/auth/verify?token={raw}"
    notifier = EmailNotifier()

    if not notifier.configured:
        # Without an email provider there is no way in, so in development we log
        # the link rather than leaving you locked out.
        log.warning("auth: RESEND_API_KEY unset - magic link for %s: %s", payload.email, link)
        return {"sent": False, "dev_link": link}

    try:
        await notifier.send(
            payload.email,
            Message(
                title="Your IPO Tracker sign-in link",
                body=(
                    f"Click below to sign in. This link is single-use and expires in "
                    f"{settings.magic_link_ttl_minutes} minutes.\n\nIf you didn't request "
                    f"it, you can ignore this email."
                ),
                url=link,
            ),
        )
    except Exception:
        log.exception("auth: failed to send magic link")
        return {"sent": False, "error": "Could not send the email. Try again shortly."}

    return {"sent": True}


@router.post("/verify", response_model=UserOut)
async def verify(
    token: str, response: Response, session: AsyncSession = Depends(get_session)
):
    user = await consume_magic_token(session, token)
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user),
        httponly=True,
        samesite="lax",
        secure=settings.app_base_url.startswith("https"),
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )
    return user


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
