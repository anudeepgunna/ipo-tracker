"""Endpoints for the scheduler, guarded by a shared secret."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.tasks.poll import run_cycle

router = APIRouter(prefix="/internal", tags=["internal"])


async def verify_token(x_internal_token: str = Header(default="")) -> None:
    # Constant-time compare so the token can't be recovered by timing the endpoint.
    if not secrets.compare_digest(x_internal_token, settings.internal_task_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid internal token")


@router.post("/tasks/poll", dependencies=[Depends(verify_token)])
async def trigger_poll(session: AsyncSession = Depends(get_session)):
    """Run one ingest -> evaluate -> dispatch cycle.

    Called by the GitHub Actions cron. Returns the cycle summary so a failing
    stage is visible in the workflow log rather than silently swallowed.
    """
    return await run_cycle(session)
