"""Per-user resources: watchlist, alert rules, channels, notification inbox."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_session
from app.models import (
    AlertRule,
    Channel,
    Ipo,
    Notification,
    NotificationChannel,
    NotificationStatus,
    User,
    WatchlistItem,
)
from app.schemas import (
    AlertRuleIn,
    AlertRuleOut,
    ChannelIn,
    ChannelOut,
    NotificationOut,
)
from app.services.notifications.base import Message
from app.services.notifications.channels import get_notifier

router = APIRouter(prefix="/api/me", tags=["me"])


# --------------------------------------------------------------------------- #
# Watchlist
# --------------------------------------------------------------------------- #


@router.get("/watchlist", response_model=list[int])
async def get_watchlist(
    session: AsyncSession = Depends(get_session), user: User = Depends(current_user)
):
    rows = await session.execute(
        select(WatchlistItem.ipo_id).where(WatchlistItem.user_id == user.id)
    )
    return list(rows.scalars().all())


@router.put("/watchlist/{ipo_id}")
async def add_to_watchlist(
    ipo_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    if await session.get(Ipo, ipo_id) is None:
        raise HTTPException(404, "IPO not found")

    existing = await session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.ipo_id == ipo_id
        )
    )
    if existing is None:
        session.add(WatchlistItem(user_id=user.id, ipo_id=ipo_id))
        await session.commit()
    return {"watchlisted": True}


@router.delete("/watchlist/{ipo_id}")
async def remove_from_watchlist(
    ipo_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    existing = await session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.ipo_id == ipo_id
        )
    )
    if existing is not None:
        await session.delete(existing)
        await session.commit()
    return {"watchlisted": False}


# --------------------------------------------------------------------------- #
# Notification channels
# --------------------------------------------------------------------------- #


def _serialize_channel(row: NotificationChannel) -> ChannelOut:
    out = ChannelOut.model_validate(row)
    out.is_active = row.is_active
    # A push subscription is a long JSON blob; never echo it back to the client.
    if row.channel is Channel.WEBPUSH:
        out.destination = "(browser subscription)"
    return out


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(
    session: AsyncSession = Depends(get_session), user: User = Depends(current_user)
):
    rows = (
        (
            await session.execute(
                select(NotificationChannel).where(NotificationChannel.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_channel(r) for r in rows]


@router.post("/channels", response_model=ChannelOut)
async def add_channel(
    payload: ChannelIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Register a delivery destination.

    Email and web push are trusted immediately - the address is already proven by
    the magic-link login, and a push subscription can only come from a browser
    that granted permission. Telegram is different: we cannot know your chat id
    until you message the bot, so it stays unverified until you send the code.
    """
    destination = payload.destination.strip()

    if payload.channel is Channel.EMAIL:
        destination = destination or user.email
    elif payload.channel is Channel.WEBPUSH:
        try:
            json.loads(destination)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "destination must be a JSON PushSubscription") from exc
    elif payload.channel is Channel.TELEGRAM:
        # Placeholder row holding the link code until /start arrives.
        destination = destination or f"pending:{secrets.token_hex(4)}"

    existing = await session.scalar(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user.id,
            NotificationChannel.channel == payload.channel,
            NotificationChannel.destination == destination,
        )
    )
    if existing is not None:
        return _serialize_channel(existing)

    verified = (
        datetime.now(UTC)
        if payload.channel in (Channel.EMAIL, Channel.WEBPUSH, Channel.INAPP)
        else None
    )
    row = NotificationChannel(
        user_id=user.id,
        channel=payload.channel,
        destination=destination,
        verified_at=verified,
    )
    session.add(row)
    await session.commit()
    return _serialize_channel(row)


@router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    row = await session.get(NotificationChannel, channel_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Channel not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": True}


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Send a real message through this channel, so you can trust it before relying on it."""
    row = await session.get(NotificationChannel, channel_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Channel not found")

    notifier = get_notifier(row.channel.value)
    if notifier is None or not notifier.configured:
        raise HTTPException(400, f"{row.channel.value} is not configured on the server")
    if not row.is_active:
        raise HTTPException(400, "Channel is not verified yet")

    try:
        await notifier.send(
            row.destination,
            Message(
                title="IPO Tracker test alert",
                body="If you can read this, this channel is working.",
                url=None,
            ),
        )
    except Exception as exc:
        raise HTTPException(502, f"Delivery failed: {exc}") from exc
    return {"sent": True}


# --------------------------------------------------------------------------- #
# Alert rules
# --------------------------------------------------------------------------- #


@router.get("/rules", response_model=list[AlertRuleOut])
async def list_rules(
    session: AsyncSession = Depends(get_session), user: User = Depends(current_user)
):
    rows = (
        (await session.execute(select(AlertRule).where(AlertRule.user_id == user.id)))
        .scalars()
        .all()
    )
    return list(rows)


@router.post("/rules", response_model=AlertRuleOut)
async def create_rule(
    payload: AlertRuleIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    if payload.ipo_id is not None and await session.get(Ipo, payload.ipo_id) is None:
        raise HTTPException(404, "IPO not found")

    hours = sorted({h for h in payload.fire_hours_ist if 0 <= h <= 23})
    if not hours:
        raise HTTPException(400, "fire_hours_ist must contain at least one hour in 0-23")

    rule = AlertRule(
        user_id=user.id,
        ipo_id=payload.ipo_id,
        rule_type=payload.rule_type,
        threshold=payload.threshold,
        channels=[c.value for c in payload.channels],
        fire_hours_ist=hours,
        board_filter=payload.board_filter,
        watchlist_only=payload.watchlist_only,
        active=payload.active,
    )
    session.add(rule)
    await session.commit()
    return rule


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    rule = await session.get(AlertRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(404, "Rule not found")
    await session.delete(rule)
    await session.commit()
    return {"deleted": True}


# --------------------------------------------------------------------------- #
# In-app inbox
# --------------------------------------------------------------------------- #


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    stmt = (
        select(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.channel == Channel.INAPP,
            Notification.status == NotificationStatus.SENT,
        )
        .order_by(Notification.created_at.desc())
        .limit(100)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list((await session.execute(stmt)).scalars().all())


@router.post("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    row = await session.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    row.read_at = datetime.now(UTC)
    await session.commit()
    return {"read": True}
