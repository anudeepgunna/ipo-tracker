"""Public reminder sign-up.

The security property under test: an unauthenticated endpoint that accepts an
arbitrary email address must not become a way to send mail to strangers. Alerts
may be *created*, but nothing may be *delivered* until the address is confirmed.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.auth import consume_magic_token
from app.config import IST
from app.models import (
    AlertRule,
    Board,
    Channel,
    Ipo,
    IpoStatus,
    MagicLinkToken,
    Notification,
    NotificationChannel,
    RuleType,
    User,
)
from app.routers.subscribe import subscribe
from app.schemas import SubscribeIn
from app.services.alerts import evaluate_rules

CLOSE_DAY = date(2026, 8, 14)


async def _ipo(session) -> Ipo:
    ipo = Ipo(
        symbol="SHIPROCKET",
        exchange="NSE",
        company_name="Shiprocket Limited",
        board=Board.MAINBOARD,
        status=IpoStatus.OPEN,
        open_date=date(2026, 8, 12),
        close_date=CLOSE_DAY,
        price_band_min=92.0,
        price_band_max=97.0,
        lot_size=154,
    )
    session.add(ipo)
    await session.flush()
    return ipo


async def _subscribe(session, ipo, **kw):
    payload = SubscribeIn(
        email=kw.get("email", "visitor@example.com"),
        ipo_id=kw.get("ipo_id", ipo.id),
        cadences=kw.get("cadences", [RuleType.LAST_DAY]),
    )
    return await subscribe(payload, session=session)


async def test_creates_user_rules_and_channels(session):
    ipo = await _ipo(session)
    result = await _subscribe(
        session, ipo, cadences=[RuleType.LAST_DAY, RuleType.DAILY_UNTIL_CLOSE]
    )

    assert result["ok"] is True
    assert result["created"] == 2

    user = (await session.execute(select(User))).scalars().one()
    assert user.email == "visitor@example.com"

    rules = (await session.execute(select(AlertRule))).scalars().all()
    assert {r.rule_type for r in rules} == {RuleType.LAST_DAY, RuleType.DAILY_UNTIL_CLOSE}
    assert all(r.ipo_id == ipo.id for r in rules)
    # LAST_DAY gets both nudges; the recurring cadence gets one a morning.
    last_day = next(r for r in rules if r.rule_type is RuleType.LAST_DAY)
    assert sorted(last_day.fire_hours_ist) == [10, 15]


async def test_email_channel_starts_unverified(session):
    """The whole anti-abuse property: created, but not yet deliverable."""
    ipo = await _ipo(session)
    await _subscribe(session, ipo)

    channels = (await session.execute(select(NotificationChannel))).scalars().all()
    email = next(c for c in channels if c.channel is Channel.EMAIL)
    inapp = next(c for c in channels if c.channel is Channel.INAPP)

    assert email.verified_at is None
    assert email.is_active is False
    assert inapp.is_active is True  # in-app needs no proof of ownership


async def test_nothing_is_delivered_before_confirmation(session):
    """Subscribing on someone else's behalf must not mail them."""
    ipo = await _ipo(session)
    await _subscribe(session, ipo)

    await evaluate_rules(session, now=datetime(2026, 8, 14, 10, 30, tzinfo=IST))

    queued = (await session.execute(select(Notification))).scalars().all()
    # In-app may queue (it is only visible after signing in), but email must not.
    assert all(n.channel is not Channel.EMAIL for n in queued)


async def test_confirming_the_link_verifies_email_and_enables_delivery(session):
    ipo = await _ipo(session)
    await _subscribe(session, ipo)

    token_row = (await session.execute(select(MagicLinkToken))).scalars().one()
    assert token_row.email == "visitor@example.com"

    # Only the hash of the emailed token is stored, so the raw value can't be
    # recovered here. Mint an equivalent link for the same address to drive the
    # identical confirmation path.
    from app.routers.internal import mint_magic_link

    minted = await mint_magic_link(email="visitor@example.com", session=session)
    raw = minted["login_url"].split("token=")[1]

    await consume_magic_token(session, raw)

    email_channel = (
        await session.execute(
            select(NotificationChannel).where(NotificationChannel.channel == Channel.EMAIL)
        )
    ).scalars().one()
    assert email_channel.verified_at is not None
    assert email_channel.is_active is True

    await evaluate_rules(session, now=datetime(2026, 8, 14, 10, 30, tzinfo=IST))
    queued = (await session.execute(select(Notification))).scalars().all()
    assert any(n.channel is Channel.EMAIL for n in queued)


async def test_resubmitting_the_same_choice_is_idempotent(session):
    ipo = await _ipo(session)
    await _subscribe(session, ipo)
    second = await _subscribe(session, ipo)

    assert second["created"] == 0
    count = await session.scalar(select(func.count()).select_from(AlertRule))
    assert count == 1


async def test_existing_user_is_reused_not_duplicated(session):
    ipo = await _ipo(session)
    session.add(User(email="visitor@example.com"))
    await session.flush()

    await _subscribe(session, ipo)
    assert await session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize(
    "cadences",
    [[], [RuleType.GMP_ABOVE], [RuleType.SUBSCRIPTION_ABOVE], [RuleType.ALLOTMENT_DAY]],
)
async def test_rejects_cadences_not_offered_publicly(session, cadences):
    """Threshold rules need a number, so they aren't exposed to signed-out users."""
    ipo = await _ipo(session)
    result = await _subscribe(session, ipo, cadences=cadences)
    assert result["ok"] is False
    assert await session.scalar(select(func.count()).select_from(AlertRule)) == 0


async def test_unknown_ipo_is_rejected(session):
    ipo = await _ipo(session)
    result = await _subscribe(session, ipo, ipo_id=999999)
    assert result["ok"] is False
    assert await session.scalar(select(func.count()).select_from(AlertRule)) == 0
