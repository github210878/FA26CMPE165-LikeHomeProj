"""Append-only committed change receipts, inserted by atomic confirmation.

DATETIME values represent UTC without an offset in MySQL. Future callers must
normalize quote timestamps to UTC before removing tzinfo. JSON money snapshots
must use canonical decimal strings (or integer cents), never raw Decimal values.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import CHAR, JSON, Date, DateTime, Enum, ForeignKey, Index, Integer, LargeBinary, Numeric, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.functions import FunctionElement

from app.config.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _CurrentTimestamp(FunctionElement):
    """Matching server defaults for MySQL microseconds and isolated SQLite tests."""
    inherit_cache = True


@compiles(_CurrentTimestamp)
def _timestamp_default(element, compiler, **kw):
    return "CURRENT_TIMESTAMP"


@compiles(_CurrentTimestamp, "mysql")
def _mysql_timestamp_default(element, compiler, **kw):
    return "CURRENT_TIMESTAMP(6)"


class ReservationChangeEvent(Base):
    __tablename__ = "reservation_change_events"
    __table_args__ = (
        UniqueConstraint("quote_jti", name="uq_change_quote_jti"),
        UniqueConstraint("reservation_id", "revision_after", name="uq_change_reservation_revision"),
        Index("ix_change_user", "user_id", "change_id"),
        Index("ix_change_payment", "booking_payment_id"),
        Index("ix_change_old_room", "old_room_type_id"),
        Index("ix_change_new_room", "new_room_type_id"),
        {"mysql_engine": "InnoDB"},
    )

    change_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservations.reservation_id", name="fk_change_reservation", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id", name="fk_change_user", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False,
    )
    booking_payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.payment_id", name="fk_change_payment", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False,
    )
    quote_jti: Mapped[str] = mapped_column(
        CHAR(36).with_variant(mysql.CHAR(36, charset="ascii", collation="ascii_bin"), "mysql"), nullable=False,
    )
    quote_sha256: Mapped[bytes] = mapped_column(LargeBinary(32).with_variant(mysql.BINARY(32), "mysql"), nullable=False)
    request_sha256: Mapped[bytes] = mapped_column(LargeBinary(32).with_variant(mysql.BINARY(32), "mysql"), nullable=False)
    original_state_sha256: Mapped[bytes] = mapped_column(LargeBinary(32).with_variant(mysql.BINARY(32), "mysql"), nullable=False)
    revision_before: Mapped[int] = mapped_column(Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"), nullable=False)
    revision_after: Mapped[int] = mapped_column(Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"), nullable=False)
    old_room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_types.room_type_id", name="fk_change_old_room", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False,
    )
    new_room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_types.room_type_id", name="fk_change_new_room", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False,
    )
    old_check_in_date: Mapped[date] = mapped_column(Date, nullable=False)
    old_check_out_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_check_in_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_check_out_date: Mapped[date] = mapped_column(Date, nullable=False)
    old_reservation_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    new_reservation_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    old_payment_obligation: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    new_payment_obligation: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    booking_payment_status_before: Mapped[str] = mapped_column(
        Enum("pending", "paid", name="change_booking_payment_status", validate_strings=True, create_constraint=True), nullable=False,
    )
    currency: Mapped[str] = mapped_column(CHAR(3), default="USD", server_default="USD", nullable=False)
    context_json: Mapped[dict] = mapped_column(JSON(none_as_null=True), nullable=False)
    fresh_quote_json: Mapped[dict] = mapped_column(JSON(none_as_null=True), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSON(none_as_null=True), nullable=False)
    quote_issued_at: Mapped[datetime] = mapped_column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False)
    quote_expires_at: Mapped[datetime] = mapped_column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), default=utc_now, server_default=_CurrentTimestamp(), nullable=False,
    )
