"""Internal charge acknowledgements and numeric financial read models.

These dormant schemas register no routes or financial operations. Credits describe
reservation-specific ledger entries, never refunds, reward points or balances.
"""

from decimal import Decimal
from math import isfinite
from typing import Literal

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, field_serializer,
    field_validator, model_validator,
)

from app.schemas.booking_schema import PaymentResponse


class AdjustmentSettlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_amount: Decimal = Field(gt=0, le=Decimal("99999999.99"), allow_inf_nan=False)
    reservation_revision: int = Field(strict=True, ge=0, le=4294967295)
    accept_payment: bool = Field(strict=True)

    @field_validator("accepted_amount", mode="before")
    @classmethod
    def numeric_acknowledgement(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError("Accepted amount must be numeric")
        return value

    @field_serializer("accepted_amount", when_used="json")
    def numeric_json_amount(self, value: Decimal) -> float:
        # The wire acknowledgement uses a JSON number. Do not quantize it:
        # cent-equivalent request comparison belongs to the future service.
        return float(value)

    @field_validator("accept_payment")
    @classmethod
    def explicit_acceptance(cls, value):
        if not value:
            raise ValueError("Internal payment must be explicitly accepted")
        return value


class AdjustmentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjustment_id: int = Field(strict=True, gt=0, le=9007199254740991)
    change_id: int = Field(strict=True, gt=0, le=9007199254740991)
    reservation_id: int = Field(strict=True, gt=0, le=9007199254740991)
    currency: Literal["USD"] = "USD"
    entry_role: Literal["price_change", "cancellation_reconciliation"]
    reconciles_adjustment_id: int | None = Field(default=None, strict=True, gt=0, le=9007199254740991)
    kind: Literal["charge", "credit"]
    amount: float = Field(strict=True, gt=0, allow_inf_nan=False)
    status: Literal["pending", "paid", "failed", "recorded", "voided"]
    settled_at: AwareDatetime | None

    @model_validator(mode="after")
    def valid_detail(self) -> "AdjustmentDetailResponse":
        if self.entry_role == "cancellation_reconciliation":
            if (self.reconciles_adjustment_id is None
                    or self.reconciles_adjustment_id == self.adjustment_id
                    or self.status != "recorded" or self.settled_at is not None):
                raise ValueError("Reconciliation requires a distinct parent and recorded internal entry")
        elif self.reconciles_adjustment_id is not None:
            raise ValueError("A primary adjustment cannot reconcile another entry")
        elif self.kind == "credit":
            if self.status != "recorded" or self.settled_at is not None:
                raise ValueError("Internal credits are recorded without external settlement")
        elif self.status == "recorded" or ((self.status == "paid") != (self.settled_at is not None)):
            raise ValueError("Only a paid primary charge has a settlement timestamp")
        return self


class AdjustmentSettlementResponse(AdjustmentDetailResponse):
    entry_role: Literal["price_change"] = "price_change"
    kind: Literal["charge"] = "charge"
    status: Literal["paid"] = "paid"
    settled_at: AwareDatetime


class ReservationFinancialSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: int = Field(strict=True, gt=0, le=9007199254740991)
    reservation_revision: int = Field(strict=True, ge=0, le=4294967295)
    reservation_status: Literal["confirmed", "cancelled", "completed"]
    currency: Literal["USD"] = "USD"
    latest_change_id: int | None = Field(strict=True, gt=0, le=9007199254740991)
    current_reservation_total: float = Field(strict=True, gt=0, allow_inf_nan=False)
    current_booking_obligation: float = Field(
        strict=True, gt=0, allow_inf_nan=False,
        description="Latest committed tax-inclusive stay obligation, not a cancellation or net cash balance.",
    )
    original_booking_payment: PaymentResponse = Field(
        description="Original booking Payment record; its pending amount can have been revised in place.",
    )
    paid_additional_charges: float = Field(strict=True, ge=0, allow_inf_nan=False)
    pending_additional_charges: float = Field(strict=True, ge=0, allow_inf_nan=False)
    failed_additional_charges: float = Field(strict=True, ge=0, allow_inf_nan=False)
    recorded_internal_credits: float = Field(strict=True, ge=0, allow_inf_nan=False)
    outstanding_additional_amount: float = Field(
        strict=True, ge=0, allow_inf_nan=False,
        description="Pending plus failed primary charges; credits are not deducted.",
    )
    adjustments: list[AdjustmentDetailResponse]
    voided_additional_charges: float = Field(default=0, strict=True, ge=0, allow_inf_nan=False)
    cancellation_reconciliations: list[AdjustmentDetailResponse] = Field(default_factory=list)
    reconciliation_credits: float = Field(default=0, strict=True, ge=0, allow_inf_nan=False)
    reconciliation_debits: float = Field(default=0, strict=True, ge=0, allow_inf_nan=False)
    cancellation_payment: PaymentResponse | None = None
    outstanding_cancellation_amount: float = Field(default=0, strict=True, ge=0, allow_inf_nan=False)
    outstanding_booking_amount: float = Field(default=0, strict=True, ge=0, allow_inf_nan=False)

    @field_validator("original_booking_payment", "cancellation_payment", mode="before")
    @classmethod
    def strict_payment_fields(cls, value):
        if isinstance(value, dict):
            return PaymentResponse.model_validate(value, strict=True)
        return value

    @model_validator(mode="after")
    def consistent_references(self) -> "ReservationFinancialSummary":
        # Match the frontend's declared references and lifecycle shapes. Do not
        # recompute obligations, net credits, or determine refunds/reward policy.
        original = self.original_booking_payment
        for payment, kind in ((original, "booking"), (self.cancellation_payment, "cancellation")):
            if payment is None:
                continue
            if (not 0 < payment.payment_id <= 9007199254740991
                    or payment.reservation_id != self.reservation_id
                    or payment.payment_type != kind or not isfinite(payment.amount)
                    or payment.amount < 0 or (kind == "booking" and payment.amount == 0)):
                raise ValueError("Financial payment must identify this reservation and payment kind")
        entries = self.adjustments + self.cancellation_reconciliations
        if (len({entry.adjustment_id for entry in entries}) != len(entries)
                or (entries and self.latest_change_id is None)):
            raise ValueError("Adjustment history requires unique identities and a latest change")
        for group, role in ((self.adjustments, "price_change"),
                            (self.cancellation_reconciliations, "cancellation_reconciliation")):
            if any(entry.reservation_id != self.reservation_id or entry.entry_role != role for entry in group):
                raise ValueError("Adjustment reservation and role must match their summary bucket")
        parents = {entry.adjustment_id: entry for entry in self.adjustments}
        reconciled = set()
        for entry in self.cancellation_reconciliations:
            parent = parents.get(entry.reconciles_adjustment_id)
            if (parent is None or parent.adjustment_id in reconciled
                    or parent.change_id != entry.change_id or parent.kind == entry.kind
                    or parent.amount != entry.amount
                    or (parent.kind == "charge" and parent.status != "paid")):
                raise ValueError("Reconciliation must reference one matching opposite internal entry")
            reconciled.add(parent.adjustment_id)
        if self.reservation_status == "cancelled":
            if (self.cancellation_payment is None
                    or self.cancellation_payment.payment_id == original.payment_id
                    or original.payment_status not in ("pending", "refunded")):
                raise ValueError("Cancelled summaries require a separate cancellation payment")
        elif self.cancellation_payment is not None or self.cancellation_reconciliations:
            raise ValueError("Only cancelled summaries contain cancellation accounting")
        return self
