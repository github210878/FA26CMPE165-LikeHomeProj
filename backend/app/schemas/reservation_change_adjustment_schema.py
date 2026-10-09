"""Persistence input guard, deliberately unused by public endpoints for now.

MySQL 5.7 does not enforce CHECK expressions. Future write services must use
this guard and validate the referenced original entry under reservation locks:
same change, primary entry, opposite kind, and approved reconciliation amount.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReservationChangeAdjustmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: int = Field(strict=True, gt=0)
    entry_role: Literal["price_change", "cancellation_reconciliation"] = "price_change"
    reconciles_adjustment_id: int | None = Field(default=None, strict=True, gt=0)
    kind: Literal["charge", "credit"]
    amount: Decimal = Field(gt=0, le=Decimal("99999999.99"), max_digits=10, decimal_places=2, allow_inf_nan=False)
    status: Literal["pending", "paid", "failed", "recorded", "voided"]

    @model_validator(mode="after")
    def valid_entry(self) -> "ReservationChangeAdjustmentRecord":
        if self.entry_role == "cancellation_reconciliation":
            if self.reconciles_adjustment_id is None or self.status != "recorded":
                raise ValueError("Reconciliation requires an original adjustment and recorded status")
        elif self.reconciles_adjustment_id is not None:
            raise ValueError("A primary price adjustment cannot reconcile another entry")
        elif self.kind == "credit" and self.status != "recorded":
            raise ValueError("An internal price credit must be recorded")
        elif self.kind == "charge" and self.status == "recorded":
            raise ValueError("A primary charge requires a charge lifecycle status")
        return self
