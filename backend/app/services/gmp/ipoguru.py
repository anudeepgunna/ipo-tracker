"""IPO Guru GMP adapter.

Free tier: 300 requests/day, 15/minute, key obtained by email. Because a single
`fetch_all()` returns every IPO at once, one call per poll is enough - at a
15-minute cadence that is ~96 calls/day, comfortably inside the daily cap.

Docs: https://www.ipoguru.in/ipo-gmp-details-developer-api
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.services.gmp.base import GmpQuote

log = logging.getLogger(__name__)

BASE_URL = "https://www.ipoguru.in/api/v1"


def _num(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("₹", "").replace("%", "")
    if not text or text in {"-", "NA", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _day(value) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


class IpoGuruProvider:
    name = "ipoguru"

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=BASE_URL, timeout=timeout, headers={"X-API-KEY": api_key}
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None) -> dict:
        resp = await self._client.get(path, params=params)
        if resp.status_code == 429:
            # Rate limited. Surfacing this as an error lets tenacity back off; if
            # we exhaust retries the caller degrades to "no GMP this cycle".
            log.warning("ipoguru: rate limited (429)")
            resp.raise_for_status()
        resp.raise_for_status()
        return resp.json()

    async def fetch_all(self) -> list[GmpQuote]:
        payload = await self._get("/ipos")
        if not payload.get("success"):
            log.warning("ipoguru: unsuccessful payload %s", payload)
            return []

        quotes: list[GmpQuote] = []
        for row in payload.get("data") or []:
            gmp = row.get("gmp") or {}
            gmp_value = _num(gmp.get("price"))
            issue_price = _num(row.get("issue_price"))
            est = None
            if gmp_value is not None and issue_price:
                est = issue_price + gmp_value

            quotes.append(
                GmpQuote(
                    symbol=(row.get("symbol") or "").strip().upper() or None,
                    company_name=(row.get("name") or "").strip() or None,
                    gmp_value=gmp_value,
                    gmp_pct=_num(gmp.get("percentage")),
                    estimated_listing_price=est,
                    allotment_date=_day(row.get("allotment_date")),
                    listing_date=_day(row.get("listing_date")),
                    source=self.name,
                )
            )
        return quotes

    async def aclose(self) -> None:
        await self._client.aclose()
