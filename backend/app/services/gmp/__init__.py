"""GMP provider selection."""

import logging

from app.config import settings
from app.services.gmp.base import GmpProvider, GmpQuote, NullGmpProvider

log = logging.getLogger(__name__)

__all__ = ["GmpProvider", "GmpQuote", "NullGmpProvider", "get_gmp_provider"]


def get_gmp_provider() -> GmpProvider:
    """Build the configured provider, falling back to the null one.

    A misconfigured or unreachable GMP source must never take the poller down -
    subscription data from NSE is the more important payload and arrives on the
    same cycle.
    """
    choice = (settings.gmp_provider or "none").strip().lower()

    if choice == "ipoguru":
        if not settings.ipoguru_api_key:
            log.warning("gmp: provider 'ipoguru' selected but IPOGURU_API_KEY is empty; disabling")
            return NullGmpProvider()
        from app.services.gmp.ipoguru import IpoGuruProvider

        return IpoGuruProvider(settings.ipoguru_api_key)

    if choice not in {"none", ""}:
        log.warning("gmp: unknown provider %r; disabling", choice)
    return NullGmpProvider()
