"""Ingestion: pull from NSE + the GMP provider and persist snapshots."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.nse import IpoListing, NseClient
from app.models import GmpSnapshot, Ipo, IpoStatus, SubscriptionSnapshot
from app.services.gmp import GmpQuote, get_gmp_provider
from app.services.scoring import estimate_listing

log = logging.getLogger(__name__)

# Statuses worth spending extra HTTP calls on. A forthcoming IPO has no bids yet
# and a long-listed one will never change again.
_LIVE_STATUSES = {IpoStatus.OPEN, IpoStatus.CLOSED}


async def upsert_ipo(session: AsyncSession, listing: IpoListing) -> Ipo:
    """Insert or update one IPO, keyed on (symbol, exchange)."""
    existing = await session.scalar(
        select(Ipo).where(Ipo.symbol == listing.symbol, Ipo.exchange == "NSE")
    )
    if existing is None:
        existing = Ipo(symbol=listing.symbol, exchange="NSE")
        session.add(existing)

    existing.company_name = listing.company_name or existing.company_name
    existing.board = listing.board
    existing.status = listing.status
    existing.series = listing.series
    existing.open_date = listing.open_date or existing.open_date
    existing.close_date = listing.close_date or existing.close_date
    existing.price_band_min = listing.price_band_min or existing.price_band_min
    existing.price_band_max = listing.price_band_max or existing.price_band_max
    existing.issue_size = listing.issue_size or existing.issue_size
    existing.raw = listing.raw
    return existing


async def record_subscription(session: AsyncSession, ipo: Ipo, client: NseClient) -> int:
    """Fetch and append category-wise subscription for one IPO.

    Returns the number of new snapshot rows written. NSE stamps its own
    `updateTime`, and we key snapshots on it, so repeated polls between NSE
    refreshes are no-ops rather than duplicate rows.
    """
    try:
        report = await client.fetch_subscription(ipo.symbol, ipo.series or "EQ")
    except Exception:
        log.exception("ingest: subscription fetch failed for %s", ipo.symbol)
        return 0

    if not report.categories:
        return 0

    # No stamp means bidding hasn't opened; nothing meaningful to store.
    captured_at = report.captured_at
    if captured_at is None:
        return 0

    existing = set(
        (
            await session.execute(
                select(SubscriptionSnapshot.category).where(
                    SubscriptionSnapshot.ipo_id == ipo.id,
                    SubscriptionSnapshot.captured_at == captured_at,
                )
            )
        )
        .scalars()
        .all()
    )

    written = 0
    for bid in report.categories:
        if bid.category in existing:
            continue
        session.add(
            SubscriptionSnapshot(
                ipo_id=ipo.id,
                captured_at=captured_at,
                category=bid.category,
                shares_offered=bid.shares_offered,
                shares_bid=bid.shares_bid,
                times_subscribed=bid.times_subscribed,
            )
        )
        written += 1
    return written


async def enrich_detail(session: AsyncSession, ipo: Ipo, client: NseClient) -> None:
    """Backfill lot size / face value / registrar, which the list endpoint omits."""
    if ipo.lot_size and ipo.registrar and ipo.face_value:
        return  # already known and these never change mid-issue
    try:
        detail = await client.fetch_detail(ipo.symbol, ipo.series or "EQ")
    except Exception:
        log.exception("ingest: detail fetch failed for %s", ipo.symbol)
        return

    ipo.lot_size = detail.lot_size or ipo.lot_size
    ipo.face_value = detail.face_value if detail.face_value is not None else ipo.face_value
    ipo.registrar = detail.registrar or ipo.registrar
    ipo.price_band_min = detail.price_band_min or ipo.price_band_min
    ipo.price_band_max = detail.price_band_max or ipo.price_band_max


def _match_quote(ipo: Ipo, quotes: list[GmpQuote]) -> GmpQuote | None:
    """Match a provider quote to an IPO by symbol, then by company name.

    Providers key on company names that rarely match NSE's exactly, so symbol is
    tried first and the name comparison is normalised and prefix-based.
    """
    for q in quotes:
        if q.symbol and q.symbol == ipo.symbol:
            return q

    def norm(text: str) -> str:
        out = text.lower()
        for suffix in (" limited", " ltd.", " ltd", " private", " pvt"):
            out = out.replace(suffix, "")
        return "".join(ch for ch in out if ch.isalnum())

    target = norm(ipo.company_name or "")
    if not target:
        return None
    for q in quotes:
        if not q.company_name:
            continue
        candidate = norm(q.company_name)
        if candidate and (candidate == target or candidate.startswith(target[:12])):
            return q
    return None


async def record_gmp(session: AsyncSession, ipos: list[Ipo], quotes: list[GmpQuote]) -> int:
    """Append a GMP snapshot per IPO we can match, and backfill provider-only dates."""
    if not quotes:
        return 0

    now = datetime.now(UTC)
    written = 0
    for ipo in ipos:
        quote = _match_quote(ipo, quotes)
        if quote is None or quote.gmp_value is None:
            continue

        # Providers carry allotment/listing dates that NSE's IPO feed omits.
        ipo.allotment_date = quote.allotment_date or ipo.allotment_date
        ipo.listing_date = quote.listing_date or ipo.listing_date

        estimate = estimate_listing(ipo.cap_price, quote.gmp_value)
        session.add(
            GmpSnapshot(
                ipo_id=ipo.id,
                captured_at=now,
                gmp_value=quote.gmp_value,
                gmp_pct=quote.gmp_pct
                if quote.gmp_pct is not None
                else estimate["expected_gain_pct"],
                estimated_listing_price=quote.estimated_listing_price
                or estimate["estimated_listing_price"],
                source=quote.source,
            )
        )
        written += 1
    return written


async def ingest(session: AsyncSession) -> dict:
    """One full ingestion cycle. Returns a summary for logging/observability."""
    summary = {"ipos": 0, "subscription_rows": 0, "gmp_rows": 0, "errors": []}

    async with NseClient() as client:
        try:
            listings = await client.fetch_ipo_list()
        except Exception as exc:
            log.exception("ingest: NSE list fetch failed")
            summary["errors"].append(f"nse_list: {exc}")
            return summary

        ipos: list[Ipo] = []
        for listing in listings:
            if not listing.symbol:
                continue
            ipos.append(await upsert_ipo(session, listing))
        # Flush so newly inserted rows have ids before we attach snapshots.
        await session.flush()
        summary["ipos"] = len(ipos)

        for ipo in ipos:
            if ipo.status not in _LIVE_STATUSES:
                continue
            summary["subscription_rows"] += await record_subscription(session, ipo, client)
            await enrich_detail(session, ipo, client)

    provider = get_gmp_provider()
    try:
        quotes = await provider.fetch_all()
        summary["gmp_rows"] = await record_gmp(session, ipos, quotes)
    except Exception as exc:
        # GMP is strictly optional - never let it fail the whole cycle.
        log.warning("ingest: GMP provider %s failed: %s", provider.name, exc)
        summary["errors"].append(f"gmp: {exc}")
    finally:
        await provider.aclose()

    await session.commit()
    log.info("ingest complete: %s", summary)
    return summary
