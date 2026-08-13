"""Public reminder sign-up.

Lets a signed-out visitor set a reminder from the IPO card itself, giving their
email at the point they already want something, rather than being stopped by a
login wall before they see any value.

Two things make this safe to expose without authentication:

* The email channel is created **unverified**, and the alert dispatcher only
  delivers to verified destinations. Without that, anyone could enter a stranger's
  address and this endpoint would become a spam cannon aimed at them.
* Confirming the address and signing in are the same click - the confirmation
  mail carries an ordinary single-use magic link.

So a reminder requested for an address nobody controls simply never fires.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_magic_token
from app.config import settings
from app.db import get_session
from app.models import (
    AlertRule,
    Channel,
    Ipo,
    MagicLinkToken,
    NotificationChannel,
    RuleType,
    User,
)
from app.schemas import SubscribeIn
from app.services.notifications.base import Message
from app.services.notifications.channels import EmailNotifier

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Cadences a signed-out visitor may choose. Threshold rules need a number and a
# mental model of subscription multiples, so they stay on the Alerts page.
PUBLIC_RULE_TYPES = {
    RuleType.LAST_DAY,
    RuleType.DAY_BEFORE_CLOSE,
    RuleType.DAILY_UNTIL_CLOSE,
}

# A single visitor has no business creating hundreds of rules.
MAX_RULES_PER_USER = 60


def _fire_hours(rule_type: RuleType) -> list[int]:
    # Two nudges on the final day; a single morning one otherwise.
    return [10, 15] if rule_type is RuleType.LAST_DAY else [10]


async def _ensure_channels(session: AsyncSession, user: User) -> None:
    """In-app is trusted immediately; email must be confirmed before it delivers."""
    existing = {
        c.channel
        for c in (
            await session.execute(
                select(NotificationChannel).where(NotificationChannel.user_id == user.id)
            )
        )
        .scalars()
        .all()
    }

    if Channel.INAPP not in existing:
        session.add(
            NotificationChannel(
                user_id=user.id,
                channel=Channel.INAPP,
                destination="",
                verified_at=datetime.now(UTC),
            )
        )
    if Channel.EMAIL not in existing:
        session.add(
            NotificationChannel(
                user_id=user.id,
                channel=Channel.EMAIL,
                destination=user.email,
                verified_at=None,  # deliberately unverified until confirmed
            )
        )


@router.post("/subscribe")
async def subscribe(payload: SubscribeIn, session: AsyncSession = Depends(get_session)):
    """Create reminders for an email address and send a confirmation link."""
    email = payload.email.lower().strip()

    ipo = await session.get(Ipo, payload.ipo_id)
    if ipo is None:
        return {"ok": False, "error": "That IPO no longer exists."}

    cadences = [c for c in payload.cadences if c in PUBLIC_RULE_TYPES]
    if not cadences:
        return {"ok": False, "error": "Choose at least one reminder option."}

    user = await session.scalar(select(User).where(User.email == email))
    is_new = user is None
    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()

    await _ensure_channels(session, user)

    existing_rules = (
        (await session.execute(select(AlertRule).where(AlertRule.user_id == user.id)))
        .scalars()
        .all()
    )
    if len(existing_rules) >= MAX_RULES_PER_USER:
        return {"ok": False, "error": "You already have the maximum number of reminders."}

    # Re-submitting the same choice should be idempotent, not stack duplicates.
    already = {(r.ipo_id, r.rule_type) for r in existing_rules}
    created = 0
    for rule_type in cadences:
        if (ipo.id, rule_type) in already:
            continue
        session.add(
            AlertRule(
                user_id=user.id,
                ipo_id=ipo.id,
                rule_type=rule_type,
                channels=[Channel.INAPP.value, Channel.EMAIL.value],
                fire_hours_ist=_fire_hours(rule_type),
                active=True,
            )
        )
        created += 1

    raw, hashed = create_magic_token()
    session.add(
        MagicLinkToken(
            email=email,
            token_hash=hashed,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.magic_link_ttl_minutes),
        )
    )
    await session.commit()

    link = settings.app_url(f"/auth/verify?token={raw}")
    notifier = EmailNotifier()

    if not notifier.configured:
        log.warning("subscribe: no email provider - confirm link for %s: %s", email, link)
        return {
            "ok": True,
            "created": created,
            "sent": False,
            "dev_link": link,
            "message": "Reminder saved. Email isn't configured on this server.",
        }

    name = ipo.company_name or ipo.symbol
    try:
        await notifier.send(
            email,
            Message(
                title=f"Confirm your reminders for {name}",
                body=(
                    f"You asked to be reminded about {name}.\n\n"
                    "Click below to confirm this address — until you do, no alerts "
                    "will be sent. The link also signs you in so you can change or "
                    "cancel your reminders at any time."
                ),
                url=link,
            ),
        )
    except Exception as exc:
        from app.routers.auth import _delivery_hint

        log.exception("subscribe: confirmation email failed for %s", email)
        return {
            "ok": True,
            "created": created,
            "sent": False,
            "error": _delivery_hint(str(exc)),
            "message": (
                "Your reminder is saved, but we couldn't email the confirmation, "
                "so email alerts stay off until the address is confirmed."
            ),
        }

    return {
        "ok": True,
        "created": created,
        "sent": True,
        "is_new_user": is_new,
        "message": f"Check {email} to confirm — alerts start once you do.",
    }
