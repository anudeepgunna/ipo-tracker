"""Small operational CLI.

    python -m app.cli vapid-keys        generate a VAPID keypair for web push
    python -m app.cli poll              run one ingest/evaluate/dispatch cycle
    python -m app.cli seed-alerts EMAIL create a default last-day rule for a user
    python -m app.cli test-notify EMAIL send a test through every active channel
"""

from __future__ import annotations

import asyncio
import base64
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    AlertRule,
    Channel,
    NotificationChannel,
    RuleType,
    User,
)
from app.services.notifications.base import Message
from app.services.notifications.channels import get_notifier


def vapid_keys() -> None:
    """Print a VAPID keypair in the base64url form pywebpush and the browser expect."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())

    der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    print(f"VAPID_PRIVATE_KEY={b64(der)}")
    print(f"VAPID_PUBLIC_KEY={b64(raw_public)}")
    print("\nPaste both into backend/.env (and your Render env vars).")


async def _poll() -> None:
    from app.tasks.poll import run_cycle

    async with SessionLocal() as session:
        print(await run_cycle(session))


async def _seed_alerts(email: str) -> None:
    """Give a user the default setup: in-app + email, last-day at 10:00 and 15:00."""
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            user = User(email=email.lower())
            session.add(user)
            await session.flush()

        from datetime import UTC, datetime

        for channel, destination in ((Channel.INAPP, ""), (Channel.EMAIL, user.email)):
            exists = await session.scalar(
                select(NotificationChannel).where(
                    NotificationChannel.user_id == user.id,
                    NotificationChannel.channel == channel,
                )
            )
            if exists is None:
                session.add(
                    NotificationChannel(
                        user_id=user.id,
                        channel=channel,
                        destination=destination,
                        verified_at=datetime.now(UTC),
                    )
                )

        session.add(
            AlertRule(
                user_id=user.id,
                ipo_id=None,
                rule_type=RuleType.LAST_DAY,
                channels=[Channel.INAPP.value, Channel.EMAIL.value],
                fire_hours_ist=[10, 15],
                active=True,
            )
        )
        await session.commit()
        print(f"Seeded last-day alerts for {user.email} (in-app + email, 10:00 & 15:00 IST).")


async def _test_notify(email: str) -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            print(f"No user with email {email}")
            return

        rows = (
            (
                await session.execute(
                    select(NotificationChannel).where(NotificationChannel.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            print("No channels registered for this user.")
            return

        for row in rows:
            notifier = get_notifier(row.channel.value)
            label = row.channel.value
            if notifier is None or not notifier.configured:
                print(f"  {label:<9} SKIP  (not configured on the server)")
                continue
            if not row.is_active:
                print(f"  {label:<9} SKIP  (not verified)")
                continue
            try:
                await notifier.send(
                    row.destination,
                    Message(
                        title="IPO Tracker test alert",
                        body="If you can read this, this channel is working.",
                    ),
                )
            except Exception as exc:
                print(f"  {label:<9} FAIL  {exc}")
            else:
                print(f"  {label:<9} OK")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]
    if command == "vapid-keys":
        vapid_keys()
    elif command == "poll":
        asyncio.run(_poll())
    elif command == "seed-alerts" and len(sys.argv) > 2:
        asyncio.run(_seed_alerts(sys.argv[2]))
    elif command == "test-notify" and len(sys.argv) > 2:
        asyncio.run(_test_notify(sys.argv[2]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
