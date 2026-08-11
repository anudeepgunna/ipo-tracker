"""Delivery pass: send PENDING notifications and record the outcome.

Split from rule evaluation on purpose. Evaluation decides *what* should be sent
and writes it down durably; this pass decides *whether it got there*. A failed
send leaves the row PENDING (until MAX_ATTEMPTS) so the next poll retries it,
rather than the alert vanishing because a third-party API had a bad minute.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, Notification, NotificationChannel, NotificationStatus
from app.services.notifications.base import Message
from app.services.notifications.channels import get_notifier

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BATCH_SIZE = 100


async def _destination_for(
    session: AsyncSession, notification: Notification
) -> str | None:
    """Resolve the address to send to for this notification's channel."""
    if notification.channel is Channel.INAPP:
        return ""
    return await session.scalar(
        select(NotificationChannel.destination).where(
            NotificationChannel.user_id == notification.user_id,
            NotificationChannel.channel == notification.channel,
            NotificationChannel.verified_at.is_not(None),
        )
    )


async def dispatch_pending(session: AsyncSession, *, limit: int = BATCH_SIZE) -> dict:
    """Attempt delivery of pending notifications. Returns a per-outcome summary."""
    summary = {"sent": 0, "failed": 0, "skipped": 0}

    pending = (
        (
            await session.execute(
                select(Notification)
                .where(
                    Notification.status == NotificationStatus.PENDING,
                    Notification.attempts < MAX_ATTEMPTS,
                )
                .order_by(Notification.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    for notification in pending:
        notifier = get_notifier(notification.channel.value)
        if notifier is None or not notifier.configured:
            # Credentials absent: leave PENDING without burning an attempt, so it
            # delivers as soon as the channel is configured.
            summary["skipped"] += 1
            continue

        destination = await _destination_for(session, notification)
        if destination is None:
            notification.status = NotificationStatus.FAILED
            notification.error = "no verified destination for this channel"
            summary["failed"] += 1
            continue

        notification.attempts += 1
        try:
            await notifier.send(
                destination,
                Message(
                    title=notification.title,
                    body=notification.body,
                    url=notification.url,
                ),
            )
        except Exception as exc:  # any channel failure is retryable
            notification.error = str(exc)[:1000]
            if notification.attempts >= MAX_ATTEMPTS:
                notification.status = NotificationStatus.FAILED
            log.warning(
                "dispatch: %s attempt %s failed for notification %s: %s",
                notification.channel.value,
                notification.attempts,
                notification.id,
                exc,
            )
            summary["failed"] += 1
        else:
            notification.status = NotificationStatus.SENT
            notification.sent_at = datetime.now(UTC)
            notification.error = None
            summary["sent"] += 1

    await session.commit()
    if any(summary.values()):
        log.info("dispatch complete: %s", summary)
    return summary
