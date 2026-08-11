"""The four delivery channels.

Each notifier is independently optional: if its credentials are absent it reports
`configured = False` and the dispatcher skips it rather than erroring. That means
you can run with only Telegram set up, add email later, and nothing else changes.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import settings
from app.services.notifications.base import Message, NotifierError

log = logging.getLogger(__name__)


class InAppNotifier:
    """No-op sender.

    In-app delivery is already complete once the row exists in `notifications` -
    the dashboard reads it from there. Modelling it as a notifier keeps the
    dispatcher uniform instead of special-casing one channel.
    """

    name = "INAPP"

    @property
    def configured(self) -> bool:
        return True

    async def send(self, destination: str, message: Message) -> None:
        return None


class EmailNotifier:
    """Email via the Resend HTTP API."""

    name = "EMAIL"

    @property
    def configured(self) -> bool:
        return bool(settings.resend_api_key)

    async def send(self, destination: str, message: Message) -> None:
        if not self.configured:
            raise NotifierError("RESEND_API_KEY is not set")

        link = (
            f'<p><a href="{message.url}" style="display:inline-block;padding:10px 18px;'
            f'background:#2563eb;color:#fff;border-radius:6px;text-decoration:none">'
            f"Open dashboard</a></p>"
            if message.url
            else ""
        )
        html = (
            f'<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;'
            f'max-width:560px;line-height:1.55">'
            f"<h2 style=\"margin:0 0 12px\">{message.title}</h2>"
            f'<div style="white-space:pre-wrap;color:#334155">{message.body}</div>'
            f"{link}"
            f'<hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">'
            f'<p style="font-size:12px;color:#64748b">Informational only, not investment '
            f"advice. Grey market premium is unofficial and unregulated.</p></div>"
        )

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.email_from,
                    "to": [destination],
                    "subject": message.title,
                    "html": html,
                },
            )
        if resp.status_code >= 400:
            raise NotifierError(f"resend {resp.status_code}: {resp.text[:300]}")


class TelegramNotifier:
    """Telegram via the Bot API. `destination` is the chat id."""

    name = "TELEGRAM"

    @property
    def configured(self) -> bool:
        return bool(settings.telegram_bot_token)

    async def send(self, destination: str, message: Message) -> None:
        if not self.configured:
            raise NotifierError("TELEGRAM_BOT_TOKEN is not set")

        text = f"*{_md_escape(message.title)}*\n\n{_md_escape(message.body)}"
        if message.url:
            text += f"\n\n[Open dashboard]({message.url})"

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": destination,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
            )
        if resp.status_code >= 400:
            raise NotifierError(f"telegram {resp.status_code}: {resp.text[:300]}")


def _md_escape(text: str) -> str:
    """Escape Telegram MarkdownV2 reserved characters.

    Unescaped '.', '-' or '(' in a company name or a price band is enough for
    Telegram to reject the whole message with a 400.
    """
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


class WebPushNotifier:
    """Browser push via VAPID. `destination` is the JSON PushSubscription."""

    name = "WEBPUSH"

    @property
    def configured(self) -> bool:
        return bool(settings.vapid_private_key and settings.vapid_public_key)

    async def send(self, destination: str, message: Message) -> None:
        if not self.configured:
            raise NotifierError("VAPID keys are not set")

        try:
            from pywebpush import WebPushException, webpush
        except ImportError as exc:  # pragma: no cover
            raise NotifierError(f"pywebpush unavailable: {exc}") from exc

        try:
            subscription = json.loads(destination)
        except json.JSONDecodeError as exc:
            raise NotifierError(f"invalid push subscription JSON: {exc}") from exc

        payload = json.dumps(
            {"title": message.title, "body": message.body, "url": message.url or "/"}
        )
        try:
            # pywebpush is synchronous; these payloads are tiny and the dispatcher
            # runs in a background task, so the blocking call is acceptable here.
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
            )
        except WebPushException as exc:
            raise NotifierError(f"webpush: {exc}") from exc


REGISTRY: dict[str, object] = {
    n.name: n
    for n in (InAppNotifier(), EmailNotifier(), TelegramNotifier(), WebPushNotifier())
}


def get_notifier(channel: str):
    return REGISTRY.get(channel)
