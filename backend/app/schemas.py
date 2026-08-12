"""Pydantic response/request models."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Board, Channel, IpoStatus, RuleType, SubCategory


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# IPOs
# --------------------------------------------------------------------------- #


class SubscriptionPoint(ORMModel):
    captured_at: datetime
    category: SubCategory
    shares_offered: float | None = None
    shares_bid: float | None = None
    times_subscribed: float | None = None


class GmpPoint(ORMModel):
    captured_at: datetime
    gmp_value: float | None = None
    gmp_pct: float | None = None
    estimated_listing_price: float | None = None
    source: str


class IpoSummary(ORMModel):
    id: int
    symbol: str
    company_name: str
    board: Board
    status: IpoStatus
    exchange: str
    open_date: date | None = None
    close_date: date | None = None
    allotment_date: date | None = None
    listing_date: date | None = None
    price_band_min: float | None = None
    price_band_max: float | None = None
    lot_size: int | None = None
    issue_size: float | None = None
    registrar: str | None = None

    # Derived, attached by the router.
    days_to_close: int | None = None
    is_last_day: bool = False
    min_investment: float | None = None
    subscription: dict[str, float | None] = Field(default_factory=dict)
    gmp: GmpPoint | None = None
    estimated_listing_price: float | None = None
    expected_gain_pct: float | None = None
    score: dict | None = None
    watchlisted: bool = False


class IpoDetail(IpoSummary):
    subscription_history: list[SubscriptionPoint] = Field(default_factory=list)
    gmp_history: list[GmpPoint] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


class MagicLinkRequest(BaseModel):
    email: EmailStr


class UserOut(ORMModel):
    id: int
    email: str
    timezone: str
    display_name: str | None = None
    avatar_url: str | None = None


# --------------------------------------------------------------------------- #
# Channels & rules
# --------------------------------------------------------------------------- #


class ChannelIn(BaseModel):
    channel: Channel
    destination: str = ""


class ChannelOut(ORMModel):
    id: int
    channel: Channel
    destination: str
    verified_at: datetime | None = None
    is_active: bool = False


class AlertRuleIn(BaseModel):
    rule_type: RuleType = RuleType.LAST_DAY
    ipo_id: int | None = None
    threshold: float | None = None
    channels: list[Channel] = Field(default_factory=lambda: [Channel.INAPP])
    fire_hours_ist: list[int] = Field(default_factory=lambda: [10, 15])
    board_filter: Board | None = None
    watchlist_only: bool = False
    active: bool = True


class AlertRuleOut(ORMModel):
    id: int
    rule_type: RuleType
    ipo_id: int | None = None
    threshold: float | None = None
    channels: list[str]
    fire_hours_ist: list[int]
    board_filter: Board | None = None
    watchlist_only: bool
    active: bool


class NotificationOut(ORMModel):
    id: int
    ipo_id: int | None = None
    channel: Channel
    title: str
    body: str
    url: str | None = None
    status: str
    read_at: datetime | None = None
    created_at: datetime
