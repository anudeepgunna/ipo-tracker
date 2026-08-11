"""GMP provider interface.

Grey Market Premium is the one number in this app that no exchange publishes -
the grey market is unofficial and off-exchange by definition. That makes it the
only field with a hard third-party dependency, so it sits behind a Protocol with
a null implementation. Everything else in the app must keep working when no GMP
provider is configured, and the UI is expected to render "GMP unavailable" rather
than break.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass
class GmpQuote:
    """A GMP reading for one IPO, keyed by symbol and/or company name.

    Providers vary in what they can match on, so both are optional and the
    ingestion layer resolves loosely.
    """

    symbol: str | None
    company_name: str | None
    gmp_value: float | None
    gmp_pct: float | None = None
    estimated_listing_price: float | None = None
    # Providers often carry dates NSE omits; we opportunistically backfill these.
    allotment_date: date | None = None
    listing_date: date | None = None
    source: str = "unknown"


@runtime_checkable
class GmpProvider(Protocol):
    name: str

    async def fetch_all(self) -> list[GmpQuote]:
        """Return current GMP readings for every IPO the provider knows about."""
        ...

    async def aclose(self) -> None: ...


class NullGmpProvider:
    """Used when no provider is configured. Returns nothing, never raises."""

    name = "none"

    async def fetch_all(self) -> list[GmpQuote]:
        return []

    async def aclose(self) -> None:
        return None
