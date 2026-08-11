"""ORM models.

Design note: subscription and GMP are stored as *append-only snapshots* rather than
mutable columns on `ipos`. A single "currently 4.2x subscribed" number is far less
useful than the curve that got there - momentum on the final day is the signal most
worth acting on, and it only exists if we keep history.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Board(str, enum.Enum):
    MAINBOARD = "MAINBOARD"
    SME = "SME"


class IpoStatus(str, enum.Enum):
    UPCOMING = "UPCOMING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LISTED = "LISTED"


class SubCategory(str, enum.Enum):
    QIB = "QIB"
    NII = "NII"
    RETAIL = "RETAIL"
    EMPLOYEE = "EMPLOYEE"
    OTHER = "OTHER"
    TOTAL = "TOTAL"


class Channel(str, enum.Enum):
    EMAIL = "EMAIL"
    TELEGRAM = "TELEGRAM"
    WEBPUSH = "WEBPUSH"
    INAPP = "INAPP"


class RuleType(str, enum.Enum):
    LAST_DAY = "LAST_DAY"
    OPEN_DAY = "OPEN_DAY"
    ALLOTMENT_DAY = "ALLOTMENT_DAY"
    LISTING_DAY = "LISTING_DAY"
    GMP_ABOVE = "GMP_ABOVE"
    SUBSCRIPTION_ABOVE = "SUBSCRIPTION_ABOVE"


class NotificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #


class Ipo(Base):
    __tablename__ = "ipos"
    __table_args__ = (UniqueConstraint("symbol", "exchange", name="uq_ipo_symbol_exchange"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(8), default="NSE")
    company_name: Mapped[str] = mapped_column(String(255))
    board: Mapped[Board] = mapped_column(Enum(Board), default=Board.MAINBOARD)
    status: Mapped[IpoStatus] = mapped_column(
        Enum(IpoStatus), default=IpoStatus.UPCOMING, index=True
    )
    series: Mapped[str | None] = mapped_column(String(8), default="EQ")

    open_date: Mapped[date | None] = mapped_column(Date, index=True)
    close_date: Mapped[date | None] = mapped_column(Date, index=True)
    allotment_date: Mapped[date | None] = mapped_column(Date)
    listing_date: Mapped[date | None] = mapped_column(Date)

    price_band_min: Mapped[float | None] = mapped_column(Float)
    price_band_max: Mapped[float | None] = mapped_column(Float)
    issue_price: Mapped[float | None] = mapped_column(Float)
    face_value: Mapped[float | None] = mapped_column(Float)
    lot_size: Mapped[int | None] = mapped_column(Integer)
    issue_size: Mapped[float | None] = mapped_column(Float)
    registrar: Mapped[str | None] = mapped_column(String(255))

    # Raw upstream payload, kept for debugging when NSE changes shape on us.
    raw: Mapped[dict | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    subscriptions: Mapped[list[SubscriptionSnapshot]] = relationship(
        back_populates="ipo", cascade="all, delete-orphan"
    )
    gmps: Mapped[list[GmpSnapshot]] = relationship(
        back_populates="ipo", cascade="all, delete-orphan"
    )

    @property
    def cap_price(self) -> float | None:
        """Best available "what you pay" price: final issue price, else band cap."""
        return self.issue_price or self.price_band_max


class SubscriptionSnapshot(Base):
    __tablename__ = "subscription_snapshots"
    __table_args__ = (
        Index("ix_sub_ipo_captured", "ipo_id", "captured_at"),
        UniqueConstraint("ipo_id", "category", "captured_at", name="uq_sub_point"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipos.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[SubCategory] = mapped_column(Enum(SubCategory))
    shares_offered: Mapped[float | None] = mapped_column(Float)
    shares_bid: Mapped[float | None] = mapped_column(Float)
    times_subscribed: Mapped[float | None] = mapped_column(Float)

    ipo: Mapped[Ipo] = relationship(back_populates="subscriptions")


class GmpSnapshot(Base):
    __tablename__ = "gmp_snapshots"
    __table_args__ = (Index("ix_gmp_ipo_captured", "ipo_id", "captured_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipos.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    gmp_value: Mapped[float | None] = mapped_column(Float)
    gmp_pct: Mapped[float | None] = mapped_column(Float)
    estimated_listing_price: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))

    ipo: Mapped[Ipo] = relationship(back_populates="gmps")


# --------------------------------------------------------------------------- #
# Users, watchlists, alerting
# --------------------------------------------------------------------------- #


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    channels: Mapped[list[NotificationChannel]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    rules: Mapped[list[AlertRule]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("user_id", "ipo_id", name="uq_watch_user_ipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipos.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationChannel(Base):
    """A verified destination for one channel, for one user."""

    __tablename__ = "notification_channels"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", "destination", name="uq_channel_dest"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[Channel] = mapped_column(Enum(Channel))
    # EMAIL -> address; TELEGRAM -> chat id; WEBPUSH -> JSON subscription; INAPP -> ""
    destination: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="channels")

    @property
    def is_active(self) -> bool:
        return self.channel is Channel.INAPP or self.verified_at is not None


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # NULL means "apply to every IPO" - the common case for LAST_DAY.
    ipo_id: Mapped[int | None] = mapped_column(ForeignKey("ipos.id", ondelete="CASCADE"))
    rule_type: Mapped[RuleType] = mapped_column(Enum(RuleType))
    threshold: Mapped[float | None] = mapped_column(Float)
    # Which channels this rule fires on, e.g. ["EMAIL", "TELEGRAM"].
    channels: Mapped[list] = mapped_column(JSON, default=list)
    # Local-time hours on the event date at which to fire, e.g. [10, 15].
    fire_hours_ist: Mapped[list] = mapped_column(JSON, default=lambda: [10, 15])
    board_filter: Mapped[Board | None] = mapped_column(Enum(Board))
    # Only meaningful when ipo_id is NULL: restrict a blanket rule to watchlisted IPOs.
    watchlist_only: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="rules")


class Notification(Base):
    """One outbound message.

    `dedupe_key` is the load-bearing column. The poller runs every 15 minutes, so
    without a uniqueness constraint a single last-day rule would emit dozens of
    duplicate alerts per day. Rule evaluation only ever *inserts* here; delivery is
    a separate pass, which means a channel outage retries instead of losing the alert.
    """

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_notification_dedupe"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ipo_id: Mapped[int | None] = mapped_column(ForeignKey("ipos.id", ondelete="CASCADE"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"))
    channel: Mapped[Channel] = mapped_column(Enum(Channel))
    dedupe_key: Mapped[str] = mapped_column(String(255))

    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)

    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus), default=NotificationStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MagicLinkToken(Base):
    __tablename__ = "magic_link_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
