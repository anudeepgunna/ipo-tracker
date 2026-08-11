"""The scheduled cycle: ingest -> evaluate rules -> dispatch.

Run directly (`python -m app.tasks.poll`) or via POST /internal/tasks/poll, which
is what the GitHub Actions cron calls.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.services.alerts import evaluate_rules
from app.services.ingest import ingest
from app.services.notifications.dispatch import dispatch_pending

log = logging.getLogger(__name__)


async def run_cycle(session: AsyncSession) -> dict:
    """One full cycle. Each stage is isolated so a failure can't cascade.

    Order matters: ingest first so rules evaluate against fresh data, and dispatch
    last so anything queued this cycle goes out immediately rather than waiting
    another 15 minutes.
    """
    result: dict = {}

    try:
        result["ingest"] = await ingest(session)
    except Exception as exc:
        log.exception("poll: ingest failed")
        result["ingest"] = {"error": str(exc)}
        await session.rollback()

    try:
        result["queued"] = await evaluate_rules(session)
    except Exception as exc:
        log.exception("poll: rule evaluation failed")
        result["queued"] = {"error": str(exc)}
        await session.rollback()

    try:
        result["dispatch"] = await dispatch_pending(session)
    except Exception as exc:
        log.exception("poll: dispatch failed")
        result["dispatch"] = {"error": str(exc)}
        await session.rollback()

    return result


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    async with SessionLocal() as session:
        summary = await run_cycle(session)
    log.info("poll cycle finished: %s", summary)


if __name__ == "__main__":
    asyncio.run(main())
