"""Parser tests against payloads captured live from NSE.

These fixtures are real responses, so they encode the shapes that actually break
naive parsers: header echo rows, compound srNo breakdown rows, empty-string
numerics, and scientific notation on the Total row.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from app.clients.nse import (
    _parse_price_band,
    _parse_update_time,
    _to_float,
    parse_detail,
    parse_listing,
    parse_subscription,
)
from app.models import Board, IpoStatus, SubCategory

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


# --------------------------------------------------------------------------- #
# Scalars
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8.1798244E7", 81798244.0),  # Total rows use scientific notation
        ("23323308", 23323308.0),
        ("", None),  # breakdown rows leave these blank
        ("  ", None),
        ("-", None),
        ("1,23,456", 123456.0),
        (None, None),
        ("garbage", None),
    ],
)
def test_to_float(raw, expected):
    assert _to_float(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rs.92 to Rs.97", (92.0, 97.0)),
        ("Rs. 133 to Rs. 140 per Equity Share", (133.0, 140.0)),
        ("Rs.271 to Rs.285", (271.0, 285.0)),
        ("Rs. 100", (100.0, 100.0)),  # fixed-price issue
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_price_band(raw, expected):
    assert _parse_price_band(raw) == expected


def test_parse_update_time_is_ist():
    got = _parse_update_time("Updated as on 11-Aug-2026 17:00:00")
    assert got is not None
    assert (got.year, got.month, got.day, got.hour) == (2026, 8, 11, 17)
    assert got.utcoffset().total_seconds() == 5.5 * 3600


def test_parse_update_time_handles_null_stamp():
    assert _parse_update_time("Updated as on null") is None
    assert _parse_update_time("-") is None


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


def test_parse_listing_mainboard():
    ipo = parse_listing(load("all_upcoming_issues.json")[0])
    assert ipo.symbol == "SHIPROCKET"
    assert ipo.company_name == "Shiprocket Limited"
    assert ipo.board is Board.MAINBOARD
    assert ipo.status is IpoStatus.OPEN  # NSE says "Active"
    assert ipo.open_date == date(2026, 8, 12)
    assert ipo.close_date == date(2026, 8, 14)
    assert (ipo.price_band_min, ipo.price_band_max) == (92.0, 97.0)


def test_series_sme_maps_to_sme_board():
    """The only signal NSE gives for SME issues is the series code."""
    rows = load("all_upcoming_issues.json")
    sme = [parse_listing(r) for r in rows if r["series"] == "SME"]
    assert sme, "fixture should contain at least one SME issue"
    assert all(i.board is Board.SME for i in sme)
    assert all(
        parse_listing(r).board is Board.MAINBOARD for r in rows if r["series"] == "EQ"
    )


def test_status_vocabulary_fully_mapped():
    statuses = {parse_listing(r).status for r in load("all_upcoming_issues.json")}
    assert statuses <= {IpoStatus.OPEN, IpoStatus.UPCOMING, IpoStatus.CLOSED, IpoStatus.LISTED}
    assert IpoStatus.UPCOMING in statuses  # "Forthcoming"
    assert IpoStatus.CLOSED in statuses


# --------------------------------------------------------------------------- #
# Subscription - the highest-risk parser
# --------------------------------------------------------------------------- #


def test_parse_subscription_returns_only_top_level_categories():
    report = parse_subscription(load("ipo_active_category.json"))
    labels = [c.label for c in report.categories]

    # Breakdown rows ("1(a)" FIIs, "2.1" sNII, "3(a)" Cut Off) must be excluded or
    # the category figures double-count against the total.
    assert not any("FII" in lbl for lbl in labels)
    assert not any("Cut Off" in lbl for lbl in labels)
    assert not any(lbl.startswith("Corporates") for lbl in labels)

    cats = {c.category for c in report.categories}
    assert cats == {
        SubCategory.QIB,
        SubCategory.NII,
        SubCategory.RETAIL,
        SubCategory.EMPLOYEE,
        SubCategory.TOTAL,
    }


def test_parse_subscription_values():
    report = parse_subscription(load("ipo_active_category.json"))
    by_cat = {c.category: c for c in report.categories}

    qib = by_cat[SubCategory.QIB]
    assert qib.shares_offered == 23323308.0
    assert qib.shares_bid == 9184773.0
    assert qib.times_subscribed == pytest.approx(0.3938023285547659)

    # Total is published in scientific notation.
    total = by_cat[SubCategory.TOTAL]
    assert total.shares_offered == pytest.approx(81798244.0)
    assert total.times_subscribed == pytest.approx(0.791620, rel=1e-4)

    # Employees oversubscribed while the book overall is not - a real case that
    # a naive "use the total" reading would hide.
    assert by_cat[SubCategory.EMPLOYEE].times_subscribed > 1
    assert total.times_subscribed < 1


def test_parse_subscription_uses_nse_timestamp_not_now():
    report = parse_subscription(load("ipo_active_category.json"))
    assert report.captured_at is not None
    assert (report.captured_at.day, report.captured_at.hour) == (11, 17)


def test_parse_subscription_handles_pre_open_empty_shape():
    """Before bidding opens NSE returns a Total row of literal '0.0' and no stamp."""
    payload = {
        "dataList": [
            {
                "category": "Category",
                "noOfShareOffered": "No.of shares offered/reserved",
                "noOfSharesBid": "No. of shares bid for",
                "noOfTotalMeant": "No. of times of total meant for the category",
                "srNo": "Sr.No.",
            },
            {
                "category": "Total",
                "noOfShareOffered": "0.0",
                "noOfSharesBid": "0.0",
                "noOfTotalMeant": "0.00",
                "srNo": None,
            },
        ],
        "updateTime": "Updated as on null",
    }
    report = parse_subscription(payload)
    assert report.captured_at is None
    assert len(report.categories) == 1
    assert report.categories[0].category is SubCategory.TOTAL
    assert report.categories[0].times_subscribed == 0.0


def test_parse_subscription_tolerates_empty_payload():
    assert parse_subscription({}).categories == []
    assert parse_subscription({"dataList": None}).categories == []


# --------------------------------------------------------------------------- #
# Detail
# --------------------------------------------------------------------------- #


def test_parse_detail():
    d = parse_detail(load("ipo_detail.json"))
    assert d.lot_size == 107  # "107 Equity Shares and in multiples thereof"
    assert d.face_value == 2.0  # "Rs. 2 per Equity Share"
    assert d.registrar == "KFin Technologies Limited"
    assert (d.price_band_min, d.price_band_max) == (133.0, 140.0)


def test_parse_detail_tolerates_empty_payload():
    d = parse_detail({})
    assert d.lot_size is None and d.registrar is None
