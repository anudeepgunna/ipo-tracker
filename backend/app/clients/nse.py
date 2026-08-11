"""NSE India client.

NSE has no documented public API. The JSON endpoints the website itself calls are
open, but they reject any request that doesn't look like it came from a browser
session - so every call must ride on a cookie jar primed by first fetching an HTML
page with a browser User-Agent. That priming step is the single most common reason
NSE integrations break, which is why it lives here behind one client rather than
being repeated at each call site.

Endpoints used (all verified live):
  GET /api/all-upcoming-issues?category=ipo   - the IPO list
  GET /api/ipo-active-category?symbol=&series= - category-wise subscription
  GET /api/ipo-detail?symbol=&series=          - lot size, face value, registrar
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import IST
from app.models import Board, IpoStatus, SubCategory

log = logging.getLogger(__name__)

BASE = "https://www.nseindia.com"
PRIME_URL = f"{BASE}/market-data/all-upcoming-issues-ipo"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# NSE's status vocabulary -> ours.
_STATUS_MAP = {
    "active": IpoStatus.OPEN,
    "forthcoming": IpoStatus.UPCOMING,
    "closed": IpoStatus.CLOSED,
    "listed": IpoStatus.LISTED,
}

# Top-level bidding categories carry a bare integer srNo ("1", "2"). Anything like
# "1(a)" or "2.1" is a breakdown row and must not be stored as a category total,
# or the numbers double-count.
_TOP_LEVEL_SR = re.compile(r"^\d+$")


def _to_float(value: str | float | None) -> float | None:
    """Parse NSE numerics.

    Handles the empty strings used on breakdown rows and the scientific notation
    ("8.1798244E7") that appears on Total rows.
    """
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"-", "na", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_date(value: str | None) -> date | None:
    """Parse NSE's '14-Aug-2026' day format."""
    if not value:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    log.warning("nse: unparseable date %r", value)
    return None


def _parse_price_band(text: str | None) -> tuple[float | None, float | None]:
    """'Rs.92 to Rs.97' or 'Rs. 133 to Rs. 140 per Equity Share' -> (92.0, 97.0).

    A fixed-price issue quotes a single number, in which case both ends match.
    """
    if not text:
        return None, None
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]
    if not nums:
        return None, None
    if len(nums) == 1:
        return nums[0], nums[0]
    return min(nums[0], nums[1]), max(nums[0], nums[1])


def _parse_update_time(text: str | None) -> datetime | None:
    """'Updated as on 11-Aug-2026 17:00:00' -> aware IST datetime.

    We use NSE's own stamp as the snapshot time rather than wall-clock now(). NSE
    republishes the same figures between refreshes, so keying on their timestamp
    means a 15-minute poll only writes a row when the data genuinely changed.
    """
    if not text:
        return None
    m = re.search(r"(\d{1,2}-\w{3}-\d{4})\s+(\d{1,2}:\d{2}:\d{2})", text)
    if not m:
        return None
    try:
        naive = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=IST)


def _map_category(name: str) -> SubCategory:
    n = name.lower()
    if "total" in n:
        return SubCategory.TOTAL
    if "qualified institutional" in n or n.startswith("qib"):
        return SubCategory.QIB
    if "non institutional" in n or "non-institutional" in n:
        return SubCategory.NII
    if "retail" in n or "riis" in n:
        return SubCategory.RETAIL
    if "employee" in n:
        return SubCategory.EMPLOYEE
    return SubCategory.OTHER


# --------------------------------------------------------------------------- #
# Parsed value objects
# --------------------------------------------------------------------------- #


@dataclass
class IpoListing:
    symbol: str
    company_name: str
    series: str
    board: Board
    status: IpoStatus
    open_date: date | None
    close_date: date | None
    price_band_min: float | None
    price_band_max: float | None
    issue_size: float | None
    raw: dict = field(default_factory=dict)


@dataclass
class CategoryBid:
    category: SubCategory
    label: str
    shares_offered: float | None
    shares_bid: float | None
    times_subscribed: float | None


@dataclass
class SubscriptionReport:
    captured_at: datetime | None
    categories: list[CategoryBid]


@dataclass
class IpoDetail:
    lot_size: int | None = None
    face_value: float | None = None
    registrar: str | None = None
    price_band_min: float | None = None
    price_band_max: float | None = None


class NseClient:
    """Cookie-primed async client for NSE's IPO endpoints."""

    def __init__(self, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": BROWSER_UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": PRIME_URL,
            },
        )
        self._primed = False

    async def __aenter__(self) -> NseClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _prime(self) -> None:
        """Fetch the HTML page once to obtain the cookies the JSON API demands."""
        if self._primed:
            return
        await self._client.get(PRIME_URL)
        self._primed = True

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    async def _get_json(self, path: str, params: dict | None = None):
        await self._prime()
        resp = await self._client.get(path, params=params)
        if resp.status_code in (401, 403):
            # Cookies expired mid-run: drop them, re-prime, and let tenacity retry.
            self._primed = False
            self._client.cookies.clear()
            resp.raise_for_status()
        resp.raise_for_status()
        return resp.json()

    # ----------------------------------------------------------------- #

    async def fetch_ipo_list(self) -> list[IpoListing]:
        data = await self._get_json("/api/all-upcoming-issues", {"category": "ipo"})
        return [parse_listing(row) for row in data or []]

    async def fetch_subscription(self, symbol: str, series: str = "EQ") -> SubscriptionReport:
        data = await self._get_json(
            "/api/ipo-active-category", {"symbol": symbol, "series": series}
        )
        return parse_subscription(data)

    async def fetch_detail(self, symbol: str, series: str = "EQ") -> IpoDetail:
        data = await self._get_json("/api/ipo-detail", {"symbol": symbol, "series": series})
        return parse_detail(data)


# --------------------------------------------------------------------------- #
# Pure parsers - kept module-level so tests can exercise them on fixtures with
# no network involved.
# --------------------------------------------------------------------------- #


def parse_listing(row: dict) -> IpoListing:
    series = (row.get("series") or "EQ").strip().upper()
    lo, hi = _parse_price_band(row.get("issuePrice"))
    return IpoListing(
        symbol=(row.get("symbol") or "").strip().upper(),
        company_name=(row.get("companyName") or "").strip(),
        series=series,
        # NSE exposes no board flag; the series code is the discriminator.
        board=Board.SME if series == "SME" else Board.MAINBOARD,
        status=_STATUS_MAP.get((row.get("status") or "").strip().lower(), IpoStatus.UPCOMING),
        open_date=_to_date(row.get("issueStartDate")),
        close_date=_to_date(row.get("issueEndDate")),
        price_band_min=lo,
        price_band_max=hi,
        issue_size=_to_float(row.get("issueSize")),
        raw=row,
    )


def parse_subscription(payload: dict) -> SubscriptionReport:
    """Extract top-level category subscription from /api/ipo-active-category.

    The payload's first row is a header echo (srNo == 'Sr.No.'), breakdown rows use
    compound srNo values ('1(a)', '2.1'), and the Total row has a null srNo. Only
    bare-integer rows and Total are real category totals.
    """
    rows = (payload or {}).get("dataList") or []
    out: list[CategoryBid] = []

    for row in rows:
        sr = row.get("srNo")
        label = (row.get("category") or "").strip()
        if not label or label == "Category" or sr == "Sr.No.":
            continue  # header echo

        is_total = label.lower() == "total"
        if not is_total and not (sr is not None and _TOP_LEVEL_SR.match(str(sr).strip())):
            continue  # breakdown row - would double-count

        out.append(
            CategoryBid(
                category=_map_category(label),
                label=label,
                shares_offered=_to_float(row.get("noOfShareOffered")),
                shares_bid=_to_float(row.get("noOfSharesBid")),
                times_subscribed=_to_float(row.get("noOfTotalMeant")),
            )
        )

    return SubscriptionReport(
        captured_at=_parse_update_time((payload or {}).get("updateTime")),
        categories=out,
    )


def parse_detail(payload: dict) -> IpoDetail:
    """Pull the fields the list endpoint omits out of the title/value pairs."""
    detail = IpoDetail()
    for item in ((payload or {}).get("issueInfo") or {}).get("dataList") or []:
        title = (item.get("title") or "").strip().lower()
        value = (item.get("value") or "").strip()
        if not title or not value:
            continue
        if "bid lot" in title or "minimum order quantity" in title:
            if detail.lot_size is None and (n := re.search(r"\d[\d,]*", value)):
                detail.lot_size = int(n.group(0).replace(",", ""))
        elif "face value" in title:
            if n := re.search(r"\d+(?:\.\d+)?", value):
                detail.face_value = _to_float(n.group(0))
        elif "name of the registrar" in title:
            # Must be the name specifically - "Address of the Registrar" also
            # matches a looser test and would clobber it.
            detail.registrar = value.strip('"')
        elif "price range" in title or "price band" in title:
            detail.price_band_min, detail.price_band_max = _parse_price_band(value)
    return detail
