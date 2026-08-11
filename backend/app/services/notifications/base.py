"""Notifier interface and the message envelope shared by every channel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Message:
    title: str
    body: str
    url: str | None = None


class NotifierError(RuntimeError):
    """Delivery failed. Raised so the dispatcher can record it and retry later."""


@runtime_checkable
class Notifier(Protocol):
    name: str

    @property
    def configured(self) -> bool:
        """False when required credentials are missing, so we skip instead of failing."""
        ...

    async def send(self, destination: str, message: Message) -> None: ...
