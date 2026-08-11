"""Telegram account linking.

Telegram is the one channel where the server cannot learn the destination on its
own - a chat id only exists once the user messages the bot. The flow is:

  1. user asks for a link code here;
  2. user sends "/start <code>" to the bot;
  3. Telegram posts an update to /api/telegram/webhook, which binds the chat id.

Polling `getUpdates` is offered as a fallback for local development, where no
public HTTPS URL exists for a webhook.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import settings
from app.db import get_session
from app.models import Channel, NotificationChannel, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/telegram", tags=["telegram"])

_START = re.compile(r"^/start\s+([A-Za-z0-9_-]{6,})$")
PENDING_PREFIX = "pending:"


@router.post("/link-code")
async def create_link_code(
    session: AsyncSession = Depends(get_session), user: User = Depends(current_user)
):
    """Issue a code and return the deep link that starts the bot conversation."""
    if not settings.telegram_bot_token:
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN is not configured on the server")

    code = secrets.token_urlsafe(9)
    session.add(
        NotificationChannel(
            user_id=user.id,
            channel=Channel.TELEGRAM,
            destination=f"{PENDING_PREFIX}{code}",
            verified_at=None,
        )
    )
    await session.commit()

    bot_username = await _bot_username()
    deep_link = f"https://t.me/{bot_username}?start={code}" if bot_username else None
    return {"code": code, "deep_link": deep_link, "command": f"/start {code}"}


async def _bot_username() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
            )
        return resp.json().get("result", {}).get("username")
    except Exception:
        log.warning("telegram: getMe failed", exc_info=True)
        return None


async def _bind(session: AsyncSession, code: str, chat_id: str) -> bool:
    row = await session.scalar(
        select(NotificationChannel).where(
            NotificationChannel.channel == Channel.TELEGRAM,
            NotificationChannel.destination == f"{PENDING_PREFIX}{code}",
        )
    )
    if row is None:
        return False

    row.destination = str(chat_id)
    row.verified_at = datetime.now(UTC)
    await session.commit()
    return True


@router.post("/webhook")
async def webhook(request: Request, session: AsyncSession = Depends(get_session)):
    """Receive bot updates and bind a chat id to the pending code."""
    update = await request.json()
    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")

    match = _START.match(text)
    if not match or chat_id is None:
        return {"ok": True}

    linked = await _bind(session, match.group(1), str(chat_id))
    # Always 200 - a non-2xx makes Telegram retry the same update indefinitely.
    if linked:
        await _reply(chat_id, "Linked. You'll get IPO alerts here.")
    else:
        await _reply(chat_id, "That code isn't valid or has already been used.")
    return {"ok": True}


async def _reply(chat_id: int | str, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
    except Exception:
        log.warning("telegram: reply failed", exc_info=True)


@router.post("/poll-updates")
async def poll_updates(
    session: AsyncSession = Depends(get_session), user: User = Depends(current_user)
):
    """Local-dev alternative to the webhook: pull recent /start messages."""
    if not settings.telegram_bot_token:
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN is not configured")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
        )
    linked = 0
    for update in resp.json().get("result", []):
        message = update.get("message") or {}
        match = _START.match((message.get("text") or "").strip())
        chat_id = (message.get("chat") or {}).get("id")
        if match and chat_id and await _bind(session, match.group(1), str(chat_id)):
            linked += 1
    return {"linked": linked}
