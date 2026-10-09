"""Internal ledger mappings only; no settlement or cancellation behavior.

One price_change entry and one cancellation_reconciliation entry per change.
The latter points to the original adjustment, preserving its amount/history.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base
from app.models.reservation_change_event import _CurrentTimestamp, utc_now


class ReservationChangeAdjustment(Base):
    __tablename__ = "reservation_change_adjustments"
    __table_args__ = (
        UniqueConstraint("change_id", "entry_role", name="uq_adjustment_change_role"),
        UniqueConstraint("reconciles_adjustment_id", name="uq_adjustment_reconciliation"),
        # Composite parent key also prevents linking a different change's ledger.
        UniqueConstraint("adjustment_id", "change_id", name="uq_adjustment_id_change"),
        Index("ix_adjustment_reconciles", "reconciles_adjustment_id", "change_id"),
        ForeignKeyConstraint(
            ["reconciles_adjustment_id", "change_id"],
            ["reservation_change_adjustments.adjustment_id", "reservation_change_adjustments.change_id"],
            name="fk_adjustment_reconciles", ondelete="RESTRICT", onupdate="RESTRICT",
        ),
        {"mysql_engine": "InnoDB"},
    )

    adjustment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("reservation_change_events.change_id", name="fk_adjustment_change", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False,
    )
    entry_role: Mapped[str] = mapped_column(
        Enum("price_change", "cancellation_reconciliation", name="adjustment_entry_role", validate_strings=True, create_constraint=True),
        default="price_change", server_default="price_change", nullable=False,
    )
    reconciles_adjustment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(
        Enum("charge", "credit", name="adjustment_kind", validate_strings=True, create_constraint=True), nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("pending", "paid", "failed", "recorded", "voided", name="adjustment_status", validate_strings=True, create_constraint=True), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), default=utc_now, server_default=_CurrentTimestamp(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), default=utc_now, server_default=_CurrentTimestamp(), nullable=False,
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
