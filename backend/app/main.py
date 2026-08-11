"""FastAPI application entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, internal, ipos, me, telegram

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(
    title="IPO Tracker",
    version="0.1.0",
    description=(
        "Indian IPO dashboard: live subscription from NSE, grey market premium, "
        "listing estimates and last-day alerts.\n\n"
        "Informational only. Not investment advice."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # required for the session cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ipos.router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(telegram.router)
app.include_router(internal.router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


@app.get("/api/config", tags=["meta"])
async def public_config():
    """What the frontend needs to know about server capabilities.

    Lets the UI hide channels that cannot possibly work rather than offering a
    Telegram button that fails once clicked.
    """
    return {
        "channels": {
            "EMAIL": bool(settings.resend_api_key),
            "TELEGRAM": bool(settings.telegram_bot_token),
            "WEBPUSH": bool(settings.vapid_public_key and settings.vapid_private_key),
            "INAPP": True,
        },
        "vapid_public_key": settings.vapid_public_key or None,
        "gmp_provider": settings.gmp_provider,
    }
