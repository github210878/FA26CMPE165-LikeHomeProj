"""Internal charge acknowledgements and numeric financial read models.

Authenticated customer routes expose these contracts. Credits describe
reservation-specific ledger entries, never refunds, reward points or balances.
"""

from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.schemas.booking_schema import PaymentResponse


class AdjustmentSettlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_amount: Decimal = Field(gt=0, le=Decimal("99999999.99"), allow_inf_nan=False)
    reservation_revision: int = Field(strict=True, ge=0, le=4294967295)
    accept_payment: bool = Field(strict=True)

    @field_validator("accepted_amount", mode="before")
    @classmethod
    def numeric_acknowledgement(cls, value):
        if isinstance(value, bool):
            raise ValueError("Accepted amount must be numeric")
        return value

    @field_validator("accept_payment")
    @classmethod
    def explicit_acceptance(cls, value):
        if not value:
            raise ValueError("Internal payment must be explicitly accepted")
        return value


class AdjustmentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjustment_id: int
    change_id: int
    reservation_id: int
    currency: Literal["USD"] = "USD"
    entry_role: Literal["price_change", "cancellation_reconciliation"]
    reconciles_adjustment_id: int | None = None
    kind: Literal["charge", "credit"]
    amount: float = Field(gt=0, allow_inf_nan=False)
    status: Literal["pending", "paid", "failed", "recorded", "voided"]
    settled_at: AwareDatetime | None


class AdjustmentSettlementResponse(AdjustmentDetailResponse):
    entry_role: Literal["price_change"] = "price_change"
    kind: Literal["charge"] = "charge"
    status: Literal["paid"] = "paid"
    settled_at: AwareDatetime


class ReservationFinancialSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: int
    reservation_revision: int
    reservation_status: Literal["confirmed", "cancelled", "completed"]
    currency: Literal["USD"] = "USD"
    latest_change_id: int | None
    current_reservation_total: float = Field(gt=0, allow_inf_nan=False)
    current_booking_obligation: float = Field(
        gt=0, allow_inf_nan=False,
        description="Latest committed tax-inclusive stay obligation, not a cancellation or net cash balance.",
    )
    original_booking_payment: PaymentResponse = Field(
        description="Original booking Payment record; its pending amount can have been revised in place.",
    )
    paid_additional_charges: float = Field(ge=0, allow_inf_nan=False)
    pending_additional_charges: float = Field(ge=0, allow_inf_nan=False)
    failed_additional_charges: float = Field(ge=0, allow_inf_nan=False)
    recorded_internal_credits: float = Field(ge=0, allow_inf_nan=False)
    outstanding_additional_amount: float = Field(
        ge=0, allow_inf_nan=False,
        description="Pending plus failed primary charges; credits are not deducted.",
    )
    adjustments: list[AdjustmentDetailResponse]
    voided_additional_charges: float = Field(default=0, ge=0, allow_inf_nan=False)
    cancellation_reconciliations: list[AdjustmentDetailResponse] = Field(default_factory=list)
    reconciliation_credits: float = Field(default=0, ge=0, allow_inf_nan=False)
    reconciliation_debits: float = Field(default=0, ge=0, allow_inf_nan=False)
    cancellation_payment: PaymentResponse | None = None
    outstanding_cancellation_amount: float = Field(default=0, ge=0, allow_inf_nan=False)
    outstanding_booking_amount: float = Field(default=0, ge=0, allow_inf_nan=False)
