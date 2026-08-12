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
    except Exception as exc:
        log.exception("auth: failed to send magic link")
        return {"sent": False, "error": _delivery_hint(str(exc))}

    return {"sent": True}


def _delivery_hint(error: str) -> str:
    """Turn a provider rejection into something the operator can act on.

    A generic "try again shortly" is actively misleading for a misconfiguration:
    retrying will fail forever. The provider's own text is not echoed back,
    because it names the account owner's address and this endpoint is
    unauthenticated.
    """
    lowered = error.lower()

    if "403" in lowered and ("verify a domain" in lowered or "testing emails" in lowered):
        return (
            "The mail provider only allows sending to the account owner's address "
            "until a sending domain is verified. Verify a domain at resend.com/domains "
            "and set EMAIL_FROM to an address on it — or sign in with the address that "
            "owns the Resend account."
        )
    if "401" in lowered or "invalid api key" in lowered:
        return "The mail provider rejected the API key. Check RESEND_API_KEY on the server."
    if "422" in lowered or "domain is not verified" in lowered:
        return "The sender address in EMAIL_FROM is not on a verified domain."

    return "The mail provider could not deliver this message. Check the server logs."


@router.post("/verify", response_model=UserOut)
async def verify(
    token: str, response: Response, session: AsyncSession = Depends(get_session)
):
    user = await consume_magic_token(session, token)
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user),
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
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
