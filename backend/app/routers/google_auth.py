"""Google Sign-In (OAuth 2.0 authorization code flow).

Chosen over magic links as the primary route because it removes the mail
provider from the login path entirely. Transactional email services restrict
free accounts to sending at the account owner's own address until a domain is
verified, which silently limits a multi-user app to exactly one user. Nothing
needs delivering here - the user is already signed in to Google.

Flow:
  /api/auth/google/start     -> redirect to Google's consent screen
  /api/auth/google/callback  -> exchange the code, set the session, bounce to the SPA

The `state` parameter is signed and echoed back in a short-lived cookie, so a
forged callback cannot log anybody in.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SESSION_COOKIE, issue_session
from app.config import settings
from app.db import get_session
from app.models import User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth/google", tags=["auth"])

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"

STATE_COOKIE = "ipo_oauth_state"
STATE_TTL_MINUTES = 10


def _redirect_uri() -> str:
    """Must match a URI registered in the Google Cloud console exactly."""
    return f"{settings.api_base_url.rstrip('/')}/api/auth/google/callback"


def _require_config() -> None:
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google sign-in is not configured on this server.",
        )


@router.get("/start")
async def start(next: str = "/"):
    """Send the browser to Google's consent screen."""
    _require_config()

    nonce = secrets.token_urlsafe(16)
    state = jwt.encode(
        {
            "nonce": nonce,
            "next": next,
            "exp": datetime.now(UTC) + timedelta(minutes=STATE_TTL_MINUTES),
        },
        settings.secret_key,
        algorithm="HS256",
    )

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        # Ask for an account chooser rather than silently reusing one session.
        "prompt": "select_account",
    }
    response = RedirectResponse(f"{AUTH_ENDPOINT}?{urlencode(params)}")
    response.set_cookie(
        STATE_COOKIE,
        nonce,
        httponly=True,
        samesite="lax",  # must survive Google's top-level redirect back to us
        secure=settings.cookie_secure,
        max_age=STATE_TTL_MINUTES * 60,
        path="/",
    )
    return response


def _fail(message: str) -> RedirectResponse:
    """Bounce back to the SPA with a readable reason rather than a bare 400."""
    return RedirectResponse(settings.app_url(f"/login?error={message}"))


@router.get("/callback")
async def callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
    ipo_oauth_state: str | None = Cookie(default=None, alias=STATE_COOKIE),
):
    _require_config()

    error = request.query_params.get("error")
    if error:
        # User pressed Cancel, or the client is misconfigured.
        log.info("google oauth: provider returned error %s", error)
        return _fail("Sign-in was cancelled.")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return _fail("Google did not return an authorization code.")

    try:
        claims = jwt.decode(state, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return _fail("This sign-in attempt expired. Please try again.")

    # Binding state to a cookie is what stops a forged callback: an attacker can
    # replay a state value, but cannot set a cookie on this domain.
    if not ipo_oauth_state or not secrets.compare_digest(ipo_oauth_state, claims.get("nonce", "")):
        return _fail("This sign-in attempt could not be verified. Please try again.")

    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code >= 400:
            log.error("google oauth: token exchange failed: %s", token_resp.text[:400])
            return _fail("Google rejected the sign-in. Please try again.")

        access_token = token_resp.json().get("access_token")
        if not access_token:
            return _fail("Google did not return an access token.")

        # The token came straight from Google over TLS in a server-to-server
        # call, so the profile it authorises is trustworthy without separately
        # verifying an ID token signature.
        user_resp = await client.get(
            USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_resp.status_code >= 400:
            log.error("google oauth: userinfo failed: %s", user_resp.text[:400])
            return _fail("Could not read your Google profile.")

    profile = user_resp.json()
    email = (profile.get("email") or "").strip().lower()
    if not email:
        return _fail("Your Google account has no email address.")
    if profile.get("email_verified") is False:
        # An unverified address could belong to somebody else entirely.
        return _fail("Your Google email address is not verified.")

    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        session.add(user)

    user.google_sub = profile.get("sub") or user.google_sub
    user.display_name = profile.get("name") or user.display_name
    user.avatar_url = profile.get("picture") or user.avatar_url
    await session.commit()
    await session.refresh(user)

    destination = claims.get("next") or "/"
    response = RedirectResponse(settings.app_url(destination))
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user),
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )
    response.delete_cookie(STATE_COOKIE, path="/")
    return response
