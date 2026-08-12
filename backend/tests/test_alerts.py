"""Alert rule evaluation.

The dedupe tests here are the most important in the suite. The poller runs every
15 minutes, so an off-by-one in the dedupe key means ~28 duplicate alerts per day
per rule - the failure mode most likely to make the whole feature unusable.
"""

from datetime import date, datetime, timedelta

import pytest

from app.config import IST
from app.models import (
    AlertRule,
    Board,
    Channel,
    Ipo,
    IpoStatus,
    Notification,
    NotificationChannel,
    RuleType,
    SubCategory,
    SubscriptionSnapshot,
    User,
    WatchlistItem,
)
from app.services.alerts import evaluate_rules

CLOSE_DAY = date(2026, 8, 14)


async def _setup(session, **rule_kwargs):
    """A user with a verified email channel and one IPO closing on CLOSE_DAY."""
    user = User(email="me@example.com")
    session.add(user)
    await session.flush()

    session.add(
        NotificationChannel(
            user_id=user.id,
            channel=Channel.EMAIL,
            destination="me@example.com",
            verified_at=datetime(2026, 1, 1, tzinfo=IST),
        )
    )

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

    defaults = dict(
        user_id=user.id,
        ipo_id=None,
        rule_type=RuleType.LAST_DAY,
        channels=["EMAIL"],
        fire_hours_ist=[10, 15],
        active=True,
        watchlist_only=False,
    )
    defaults.update(rule_kwargs)
    rule = AlertRule(**defaults)
    session.add(rule)
    await session.flush()
    return user, ipo, rule


async def _count(session):
    from sqlalchemy import func, select

    return await session.scalar(select(func.count()).select_from(Notification))


def at(hour: int, minute: int = 0, day: date = CLOSE_DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


# --------------------------------------------------------------------------- #
# Dedupe
# --------------------------------------------------------------------------- #


async def test_repeated_polls_send_exactly_one_alert_per_slot(session):
    """The headline guarantee: a 15-minute cadence must not spam."""
    await _setup(session)

    # Simulate the poller running every 15 minutes from 10:00 to 12:45 - all
    # inside the 10:00 slot's grace window.
    for minute in range(0, 165, 15):
        moment = at(10) + timedelta(minutes=minute)
        await evaluate_rules(session, now=moment)

    assert await _count(session) == 1


async def test_each_configured_slot_fires_once(session):
    await _setup(session)
    for hour, minute in [(10, 0), (10, 30), (11, 0), (15, 0), (15, 45), (16, 30)]:
        await evaluate_rules(session, now=at(hour, minute))

    # Two configured slots -> exactly two alerts.
    assert await _count(session) == 2


async def test_alert_queued_per_selected_channel(session):
    user, _, rule = await _setup(session, channels=["EMAIL", "TELEGRAM"])
    session.add(
        NotificationChannel(
            user_id=user.id,
            channel=Channel.TELEGRAM,
            destination="12345",
            verified_at=datetime(2026, 1, 1, tzinfo=IST),
        )
    )
    await session.flush()

    await evaluate_rules(session, now=at(10))
    await evaluate_rules(session, now=at(10, 30))  # re-poll must not duplicate

    from sqlalchemy import select

    channels = sorted(
        c.value for c in (await session.execute(select(Notification.channel))).scalars()
    )
    assert channels == ["EMAIL", "TELEGRAM"]


# --------------------------------------------------------------------------- #
# Firing windows
# --------------------------------------------------------------------------- #


async def test_does_not_fire_before_the_slot(session):
    await _setup(session)
    await evaluate_rules(session, now=at(9, 45))
    assert await _count(session) == 0


async def test_late_rule_creation_does_not_backfill_earlier_slots(session):
    """Created at 15:30, the 10:00 slot is long gone and must stay silent."""
    await _setup(session)
    await evaluate_rules(session, now=at(15, 30))
    assert await _count(session) == 1  # only the 15:00 slot


async def test_never_fires_after_the_application_cutoff(session):
    """Applications close ~17:00 IST; an alert after that is useless noise."""
    await _setup(session, fire_hours_ist=[17, 18])
    await evaluate_rules(session, now=at(17, 30))
    await evaluate_rules(session, now=at(18, 15))
    assert await _count(session) == 0


async def test_only_fires_on_the_close_date(session):
    await _setup(session)
    await evaluate_rules(session, now=at(10, 0, day=date(2026, 8, 13)))  # day before
    await evaluate_rules(session, now=at(10, 0, day=date(2026, 8, 15)))  # day after
    assert await _count(session) == 0


async def test_inactive_rule_never_fires(session):
    await _setup(session, active=False)
    await evaluate_rules(session, now=at(10))
    assert await _count(session) == 0


async def test_no_verified_channel_means_nothing_queued(session):
    """An unverified destination must not silently queue undeliverable alerts."""
    user, _, _ = await _setup(session)
    from sqlalchemy import update

    await session.execute(
        update(NotificationChannel)
        .where(NotificationChannel.user_id == user.id)
        .values(verified_at=None)
    )
    await evaluate_rules(session, now=at(10))
    assert await _count(session) == 0


# --------------------------------------------------------------------------- #
# Targeting
# --------------------------------------------------------------------------- #


async def test_board_filter_excludes_other_boards(session):
    await _setup(session, board_filter=Board.SME)
    await evaluate_rules(session, now=at(10))
    assert await _count(session) == 0  # the fixture IPO is mainboard


async def test_watchlist_only_requires_the_ipo_to_be_watchlisted(session):
    user, ipo, _ = await _setup(session, watchlist_only=True)
    await evaluate_rules(session, now=at(10))
    assert await _count(session) == 0

    session.add(WatchlistItem(user_id=user.id, ipo_id=ipo.id))
    await session.flush()
    await evaluate_rules(session, now=at(10, 15))
    assert await _count(session) == 1


# --------------------------------------------------------------------------- #
# Threshold rules
# --------------------------------------------------------------------------- #


async def test_subscription_threshold_fires_once_per_day(session):
    _, ipo, _ = await _setup(
        session, rule_type=RuleType.SUBSCRIPTION_ABOVE, threshold=10.0
    )
    session.add(
        SubscriptionSnapshot(
            ipo_id=ipo.id,
            captured_at=at(11),
            category=SubCategory.TOTAL,
            times_subscribed=12.5,
        )
    )
    await session.flush()

    for minute in (0, 15, 30, 45):
        await evaluate_rules(session, now=at(12, minute))
    assert await _count(session) == 1


async def test_subscription_threshold_silent_below_threshold(session):
    _, ipo, _ = await _setup(
        session, rule_type=RuleType.SUBSCRIPTION_ABOVE, threshold=10.0
    )
    session.add(
        SubscriptionSnapshot(
            ipo_id=ipo.id,
            captured_at=at(11),
            category=SubCategory.TOTAL,
            times_subscribed=4.0,
        )
    )
    await session.flush()
    await evaluate_rules(session, now=at(12))
    assert await _count(session) == 0


async def test_threshold_uses_latest_snapshot(session):
    """Subscription falls back below threshold - the newest reading wins."""
    _, ipo, _ = await _setup(
        session, rule_type=RuleType.SUBSCRIPTION_ABOVE, threshold=10.0
    )
    session.add_all(
        [
            SubscriptionSnapshot(
                ipo_id=ipo.id,
                captured_at=at(11),
                category=SubCategory.TOTAL,
                times_subscribed=12.0,
            ),
            SubscriptionSnapshot(
                ipo_id=ipo.id,
                captured_at=at(13),
                category=SubCategory.TOTAL,
                times_subscribed=2.0,
            ),
        ]
    )
    await session.flush()
    await evaluate_rules(session, now=at(14))
    assert await _count(session) == 0


# --------------------------------------------------------------------------- #
# Message content
# --------------------------------------------------------------------------- #


async def test_alert_body_carries_what_you_need_to_act(session):
    await _setup(session)
    await evaluate_rules(session, now=at(10))

    from sqlalchemy import select

    note = (await session.execute(select(Notification))).scalars().one()
    assert "LAST DAY" in note.title
    assert "Shiprocket" in note.title
    assert "154" in note.body  # lot size
    assert "14,938" in note.body  # 154 shares x Rs.97 cap = one lot
    assert "not investment advice" in note.body
    # Hash-routed: a plain /ipo/... path 404s on a static host with no rewrite
    # rule, which would make every alert link dead.
    assert note.url.endswith("/#/ipo/SHIPROCKET")


@pytest.mark.parametrize(
    ("rule_type", "field", "phrase"),
    [
        (RuleType.OPEN_DAY, "open_date", "opens for subscription"),
        (RuleType.ALLOTMENT_DAY, "allotment_date", "Allotment"),
        (RuleType.LISTING_DAY, "listing_date", "lists today"),
    ],
)
async def test_other_date_rules(session, rule_type, field, phrase):
    _, ipo, _ = await _setup(session, rule_type=rule_type, fire_hours_ist=[10])
    setattr(ipo, field, CLOSE_DAY)
    await session.flush()

    await evaluate_rules(session, now=at(10))
    from sqlalchemy import select

    note = (await session.execute(select(Notification))).scalars().one()
    assert phrase in note.title
