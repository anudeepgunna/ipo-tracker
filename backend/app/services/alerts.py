"""Alert rule evaluation.

Evaluation only ever *inserts* rows into `notifications`; delivery is a separate
pass (`dispatch.py`). Keeping those apart means a Telegram outage or an expired
Resend key can never lose an alert - the row survives and the next cycle retries it.

Firing model: a date-based rule (LAST_DAY, OPEN_DAY, ...) declares the IST hours it
should fire at, e.g. [10, 15]. A slot fires when the current IST time falls inside
`[hour, hour + GRACE_HOURS)`. The grace window matters in two directions:

  * with a 15-minute poll cadence, every slot is caught reliably;
  * a rule created late in the day fires only the slot it is currently inside,
    instead of dumping every earlier slot at once as catch-up spam.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import IST, settings
from app.models import (
    AlertRule,
    GmpSnapshot,
    Ipo,
    IpoStatus,
    Notification,
    NotificationChannel,
    RuleType,
    SubCategory,
    SubscriptionSnapshot,
    WatchlistItem,
)

log = logging.getLogger(__name__)

# How long after a scheduled hour a slot may still fire.
GRACE_HOURS = 3

# Retail UPI mandate approval closes around 17:00 IST on the final day; an alert
# that lands after this is useless, so last-day slots are never fired past it.
APPLICATION_CUTOFF_HOUR = 17

_DATE_RULES: dict[RuleType, str] = {
    RuleType.LAST_DAY: "close_date",
    RuleType.OPEN_DAY: "open_date",
    RuleType.ALLOTMENT_DAY: "allotment_date",
    RuleType.LISTING_DAY: "listing_date",
}


# --------------------------------------------------------------------------- #
# Latest-value helpers
# --------------------------------------------------------------------------- #


async def latest_total_subscription(session: AsyncSession, ipo_id: int) -> float | None:
    return await session.scalar(
        select(SubscriptionSnapshot.times_subscribed)
        .where(
            SubscriptionSnapshot.ipo_id == ipo_id,
            SubscriptionSnapshot.category == SubCategory.TOTAL,
        )
        .order_by(SubscriptionSnapshot.captured_at.desc())
        .limit(1)
    )


async def latest_gmp(session: AsyncSession, ipo_id: int) -> GmpSnapshot | None:
    return await session.scalar(
        select(GmpSnapshot)
        .where(GmpSnapshot.ipo_id == ipo_id)
        .order_by(GmpSnapshot.captured_at.desc())
        .limit(1)
    )


# --------------------------------------------------------------------------- #
# Message building
# --------------------------------------------------------------------------- #


def _money(value: float | None) -> str:
    return f"Rs.{value:,.0f}" if value is not None else "-"


async def build_body(session: AsyncSession, ipo: Ipo, headline: str) -> str:
    """Compose an alert body with everything needed to decide, in one glance."""
    lines = [headline, ""]

    if ipo.price_band_min and ipo.price_band_max:
        band = (
            _money(ipo.price_band_min)
            if ipo.price_band_min == ipo.price_band_max
            else f"{_money(ipo.price_band_min)} - {_money(ipo.price_band_max)}"
        )
        lines.append(f"Price band: {band}")

    if ipo.lot_size:
        lines.append(f"Lot size: {ipo.lot_size} shares")
        if ipo.cap_price:
            # What one lot at the cap actually costs - the number you need at hand.
            lines.append(f"Amount for 1 lot (at cap): {_money(ipo.lot_size * ipo.cap_price)}")

    total = await latest_total_subscription(session, ipo.id)
    if total is not None:
        lines.append(f"Subscribed: {total:.2f}x overall")

    gmp = await latest_gmp(session, ipo.id)
    if gmp and gmp.gmp_value is not None:
        est = (
            f", implies ~{_money(gmp.estimated_listing_price)}"
            if gmp.estimated_listing_price
            else ""
        )
        pct = f" ({gmp.gmp_pct:+.1f}%)" if gmp.gmp_pct is not None else ""
        lines.append(f"GMP: {_money(gmp.gmp_value)}{pct}{est}")

    if ipo.close_date:
        lines.append(f"Closes: {ipo.close_date:%d %b %Y}")

    lines.append("")
    lines.append("Informational only, not investment advice.")
    return "\n".join(lines)


def _headline(rule_type: RuleType, ipo: Ipo) -> str:
    name = ipo.company_name or ipo.symbol
    return {
        RuleType.LAST_DAY: f"Today is the LAST DAY to apply for {name}.",
        RuleType.OPEN_DAY: f"{name} opens for subscription today.",
        RuleType.ALLOTMENT_DAY: f"Allotment for {name} is expected today.",
        RuleType.LISTING_DAY: f"{name} lists today.",
        RuleType.GMP_ABOVE: f"GMP alert for {name}.",
        RuleType.SUBSCRIPTION_ABOVE: f"Subscription alert for {name}.",
    }[rule_type]


# --------------------------------------------------------------------------- #
# Queueing
# --------------------------------------------------------------------------- #


async def _active_channels(session: AsyncSession, user_id: int) -> list[NotificationChannel]:
    rows = (
        (
            await session.execute(
                select(NotificationChannel).where(NotificationChannel.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    return [c for c in rows if c.is_active]


async def _queue(
    session: AsyncSession,
    *,
    rule: AlertRule,
    ipo: Ipo,
    dedupe_suffix: str,
    title: str,
    body: str,
) -> int:
    """Insert one pending notification per selected channel, ignoring duplicates.

    The insert is `ON CONFLICT DO NOTHING` against the unique `dedupe_key`, which
    makes this safe to call on every poll - and safe against two pollers racing.
    """
    wanted = {c.upper() for c in (rule.channels or [])}
    channels = [
        c for c in await _active_channels(session, rule.user_id) if c.channel.value in wanted
    ]
    if not channels:
        return 0

    url = settings.app_url(f"/ipo/{ipo.symbol}")
    queued = 0

    for channel in channels:
        dedupe_key = (
            f"{rule.id}:{ipo.id}:{rule.rule_type.value}:"
            f"{dedupe_suffix}:{channel.channel.value}"
        )
        values = {
            "user_id": rule.user_id,
            "ipo_id": ipo.id,
            "rule_id": rule.id,
            "channel": channel.channel,
            "dedupe_key": dedupe_key,
            "title": title,
            "body": body,
            "url": url,
        }

        dialect = session.bind.dialect.name if session.bind else ""
        if dialect == "postgresql":
            stmt = pg_insert(Notification).values(**values).on_conflict_do_nothing(
                index_elements=["dedupe_key"]
            )
            result = await session.execute(stmt)
            queued += result.rowcount or 0
        else:
            # SQLite (local dev): emulate with a pre-check.
            exists = await session.scalar(
                select(Notification.id).where(Notification.dedupe_key == dedupe_key)
            )
            if exists is None:
                session.add(Notification(**values))
                queued += 1

    return queued


def _slot_is_live(now_ist: datetime, hour: int, *, cutoff: int | None = None) -> bool:
    """True when `now` sits inside this slot's firing window."""
    if cutoff is not None and now_ist.hour >= cutoff:
        return False
    start = now_ist.replace(hour=hour, minute=0, second=0, microsecond=0)
    return start <= now_ist < start + timedelta(hours=GRACE_HOURS)


async def _candidate_ipos(session: AsyncSession, rule: AlertRule) -> list[Ipo]:
    """Resolve which IPOs a rule applies to."""
    stmt = select(Ipo)
    if rule.ipo_id is not None:
        stmt = stmt.where(Ipo.id == rule.ipo_id)
    else:
        if rule.board_filter is not None:
            stmt = stmt.where(Ipo.board == rule.board_filter)
        if rule.watchlist_only:
            stmt = stmt.join(
                WatchlistItem,
                (WatchlistItem.ipo_id == Ipo.id) & (WatchlistItem.user_id == rule.user_id),
            )
    return list((await session.execute(stmt)).scalars().all())


async def evaluate_rules(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Evaluate every active rule and queue notifications. Returns rows queued."""
    now_ist = (now or datetime.now(IST)).astimezone(IST)
    today: date = now_ist.date()

    rules = (
        (await session.execute(select(AlertRule).where(AlertRule.active.is_(True))))
        .scalars()
        .all()
    )

    queued = 0
    for rule in rules:
        try:
            queued += await _evaluate_one(session, rule, now_ist, today)
        except Exception:
            # One malformed rule must not stop the rest from firing.
            log.exception("alerts: rule %s failed to evaluate", rule.id)

    if queued:
        await session.commit()
    return queued


async def _evaluate_one(
    session: AsyncSession, rule: AlertRule, now_ist: datetime, today: date
) -> int:
    queued = 0
    ipos = await _candidate_ipos(session, rule)

    # ---- Date-anchored rules ----
    if rule.rule_type in _DATE_RULES:
        field = _DATE_RULES[rule.rule_type]
        cutoff = APPLICATION_CUTOFF_HOUR if rule.rule_type is RuleType.LAST_DAY else None
        hours = [int(h) for h in (rule.fire_hours_ist or [10])]

        for ipo in ipos:
            if getattr(ipo, field) != today:
                continue
            for hour in hours:
                if not _slot_is_live(now_ist, hour, cutoff=cutoff):
                    continue
                title = _headline(rule.rule_type, ipo)
                body = await build_body(session, ipo, title)
                queued += await _queue(
                    session,
                    rule=rule,
                    ipo=ipo,
                    dedupe_suffix=f"{today.isoformat()}:{hour}",
                    title=title,
                    body=body,
                )
        return queued

    # ---- Threshold rules: at most one alert per IPO per day ----
    threshold = rule.threshold
    if threshold is None:
        return 0

    for ipo in ipos:
        # A threshold crossing only matters while you can still act on it.
        if ipo.status not in (IpoStatus.OPEN, IpoStatus.CLOSED):
            continue

        if rule.rule_type is RuleType.SUBSCRIPTION_ABOVE:
            value = await latest_total_subscription(session, ipo.id)
            if value is None or value < threshold:
                continue
            title = f"{ipo.company_name or ipo.symbol} crossed {threshold:g}x subscription"
        else:  # GMP_ABOVE
            snapshot = await latest_gmp(session, ipo.id)
            value = snapshot.gmp_pct if snapshot else None
            if value is None or value < threshold:
                continue
            title = f"{ipo.company_name or ipo.symbol} GMP crossed {threshold:g}%"

        body = await build_body(session, ipo, title)
        queued += await _queue(
            session,
            rule=rule,
            ipo=ipo,
            dedupe_suffix=today.isoformat(),
            title=title,
            body=body,
        )

    return queued
