"""Assembles the enriched IPO payloads the dashboard renders.

Latest-snapshot lookups are done in two set-based queries for the whole page
rather than per IPO, so adding IPOs doesn't add round trips.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GmpSnapshot, Ipo, SubCategory, SubscriptionSnapshot, WatchlistItem
from app.services.scoring import compute_score, estimate_listing


async def latest_subscriptions(
    session: AsyncSession, ipo_ids: list[int]
) -> dict[int, dict[str, float | None]]:
    """{ipo_id: {"TOTAL": 4.2, "QIB": 8.1, ...}} using each IPO's newest capture."""
    if not ipo_ids:
        return {}

    newest = (
        select(
            SubscriptionSnapshot.ipo_id.label("ipo_id"),
            func.max(SubscriptionSnapshot.captured_at).label("captured_at"),
        )
        .where(SubscriptionSnapshot.ipo_id.in_(ipo_ids))
        .group_by(SubscriptionSnapshot.ipo_id)
        .subquery()
    )

    rows = await session.execute(
        select(SubscriptionSnapshot).join(
            newest,
            (SubscriptionSnapshot.ipo_id == newest.c.ipo_id)
            & (SubscriptionSnapshot.captured_at == newest.c.captured_at),
        )
    )

    out: dict[int, dict[str, float | None]] = {}
    for snapshot in rows.scalars():
        out.setdefault(snapshot.ipo_id, {})[snapshot.category.value] = snapshot.times_subscribed
    return out


async def latest_gmps(session: AsyncSession, ipo_ids: list[int]) -> dict[int, GmpSnapshot]:
    if not ipo_ids:
        return {}

    newest = (
        select(
            GmpSnapshot.ipo_id.label("ipo_id"),
            func.max(GmpSnapshot.captured_at).label("captured_at"),
        )
        .where(GmpSnapshot.ipo_id.in_(ipo_ids))
        .group_by(GmpSnapshot.ipo_id)
        .subquery()
    )

    rows = await session.execute(
        select(GmpSnapshot).join(
            newest,
            (GmpSnapshot.ipo_id == newest.c.ipo_id)
            & (GmpSnapshot.captured_at == newest.c.captured_at),
        )
    )
    return {s.ipo_id: s for s in rows.scalars()}


async def previous_gmp_pct(session: AsyncSession, ipo_id: int) -> float | None:
    """The reading before the newest, used for the GMP momentum component."""
    readings = (
        (
            await session.execute(
                select(GmpSnapshot.gmp_pct)
                .where(GmpSnapshot.ipo_id == ipo_id, GmpSnapshot.gmp_pct.is_not(None))
                .order_by(GmpSnapshot.captured_at.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    return readings[1] if len(readings) > 1 else None


async def watchlisted_ids(session: AsyncSession, user_id: int | None) -> set[int]:
    if user_id is None:
        return set()
    rows = await session.execute(
        select(WatchlistItem.ipo_id).where(WatchlistItem.user_id == user_id)
    )
    return set(rows.scalars().all())


def enrich(
    ipo: Ipo,
    *,
    subscription: dict[str, float | None],
    gmp: GmpSnapshot | None,
    gmp_pct_previous: float | None,
    watchlisted: bool,
    today: date,
) -> dict:
    """Combine an IPO row with its latest snapshots into the API payload."""
    days_to_close = (ipo.close_date - today).days if ipo.close_date else None

    estimate = estimate_listing(ipo.cap_price, gmp.gmp_value if gmp else None)
    score = compute_score(
        gmp_pct=gmp.gmp_pct if gmp else None,
        gmp_pct_previous=gmp_pct_previous,
        qib_times=subscription.get(SubCategory.QIB.value),
        nii_times=subscription.get(SubCategory.NII.value),
        retail_times=subscription.get(SubCategory.RETAIL.value),
        total_times=subscription.get(SubCategory.TOTAL.value),
    )

    return {
        "days_to_close": days_to_close,
        # The flag the whole app exists for.
        "is_last_day": days_to_close == 0,
        "min_investment": (
            round(ipo.lot_size * ipo.cap_price, 2) if ipo.lot_size and ipo.cap_price else None
        ),
        "subscription": subscription,
        "gmp": gmp,
        "estimated_listing_price": estimate["estimated_listing_price"],
        "expected_gain_pct": estimate["expected_gain_pct"],
        "score": score.to_dict(),
        "watchlisted": watchlisted,
    }
