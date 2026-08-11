"""Public IPO read endpoints."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import optional_user
from app.config import IST
from app.db import get_session
from app.models import GmpSnapshot, Ipo, IpoStatus, SubscriptionSnapshot, User
from app.schemas import IpoDetail, IpoSummary
from app.services import views

router = APIRouter(prefix="/api/ipos", tags=["ipos"])

# Open issues first, then what's coming, then history - the order you actually
# care about when the point is "what can I still apply to".
_STATUS_ORDER = {
    IpoStatus.OPEN: 0,
    IpoStatus.UPCOMING: 1,
    IpoStatus.CLOSED: 2,
    IpoStatus.LISTED: 3,
}


@router.get("", response_model=list[IpoSummary])
async def list_ipos(
    status: IpoStatus | None = None,
    board: str | None = None,
    watchlist: bool = Query(False, description="Restrict to the signed-in user's watchlist"),
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(optional_user),
):
    stmt = select(Ipo)
    if status is not None:
        stmt = stmt.where(Ipo.status == status)
    if board:
        stmt = stmt.where(Ipo.board == board.upper())

    ipos = list((await session.execute(stmt)).scalars().all())

    watched = await views.watchlisted_ids(session, user.id if user else None)
    if watchlist:
        if user is None:
            raise HTTPException(401, "Sign in to use the watchlist filter")
        ipos = [i for i in ipos if i.id in watched]

    ids = [i.id for i in ipos]
    subs = await views.latest_subscriptions(session, ids)
    gmps = await views.latest_gmps(session, ids)
    today = datetime.now(IST).date()

    payload = []
    for ipo in ipos:
        summary = IpoSummary.model_validate(ipo)
        extra = views.enrich(
            ipo,
            subscription=subs.get(ipo.id, {}),
            gmp=gmps.get(ipo.id),
            gmp_pct_previous=None,  # trend is computed on the detail view only
            watchlisted=ipo.id in watched,
            today=today,
        )
        payload.append(summary.model_copy(update=extra))

    payload.sort(
        key=lambda i: (
            _STATUS_ORDER.get(i.status, 9),
            i.close_date or date.max,
            i.company_name,
        )
    )
    return payload


@router.get("/{symbol}", response_model=IpoDetail)
async def get_ipo(
    symbol: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(optional_user),
):
    ipo = await session.scalar(select(Ipo).where(Ipo.symbol == symbol.upper()))
    if ipo is None:
        raise HTTPException(404, f"No IPO found with symbol {symbol!r}")

    subs = await views.latest_subscriptions(session, [ipo.id])
    gmps = await views.latest_gmps(session, [ipo.id])
    watched = await views.watchlisted_ids(session, user.id if user else None)

    detail = IpoDetail.model_validate(ipo)
    extra = views.enrich(
        ipo,
        subscription=subs.get(ipo.id, {}),
        gmp=gmps.get(ipo.id),
        gmp_pct_previous=await views.previous_gmp_pct(session, ipo.id),
        watchlisted=ipo.id in watched,
        today=datetime.now(IST).date(),
    )

    history = (
        (
            await session.execute(
                select(SubscriptionSnapshot)
                .where(SubscriptionSnapshot.ipo_id == ipo.id)
                .order_by(SubscriptionSnapshot.captured_at)
            )
        )
        .scalars()
        .all()
    )
    gmp_history = (
        (
            await session.execute(
                select(GmpSnapshot)
                .where(GmpSnapshot.ipo_id == ipo.id)
                .order_by(GmpSnapshot.captured_at)
            )
        )
        .scalars()
        .all()
    )

    extra["subscription_history"] = list(history)
    extra["gmp_history"] = list(gmp_history)
    return detail.model_copy(update=extra)
