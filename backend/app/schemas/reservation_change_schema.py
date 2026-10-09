"""Contracts for reviewing date-only reservation changes.

Clients reconfirm destination/occupancy but cannot choose owner/property identity
or authoritative pricing. Quote acknowledgements must be compared with a verified
review and fresh revalidation; they never authorize a payment adjustment themselves.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import booking_schema
from app.schemas.hotel_schema import HotelRevalidationResponse

MAX_CHANGE_QUOTE_LENGTH = 16384


class ReservationChangeQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_in_date: date
    check_out_date: date

    @field_validator("check_in_date", "check_out_date", mode="before")
    @classmethod
    def calendar_date(cls, value: object) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() == value:
                    return parsed
            except ValueError as exc:
                raise ValueError("Date must be a valid date in YYYY-MM-DD format") from exc
        raise ValueError("Date must be a valid date in YYYY-MM-DD format")

    @model_validator(mode="after")
    def valid_stay(self) -> "ReservationChangeQuoteRequest":
        # Share booking validation's calendar, including its fixed test clock.
        if self.check_in_date < booking_schema.date.today():
            raise ValueError("check_in_date cannot be in the past")
        if self.check_out_date <= self.check_in_date:
            raise ValueError("check_out_date must be after check_in_date")
        return self


class ReservationChangeConfirmRequest(ReservationChangeQuoteRequest):
    quote_id: str = Field(min_length=1, max_length=MAX_CHANGE_QUOTE_LENGTH)
    accept_quote: bool = Field(strict=True)
    price_per_night: float = Field(
        gt=0, le=99999999.99, allow_inf_nan=False,
        description="Accepted base nightly quote; compared with provider, never authoritative.",
    )
    accepted_payment_amount: float = Field(
        gt=0, le=99999999.99, allow_inf_nan=False,
        description="Accepted full LikeHome quote; not a client-selected payment adjustment.",
    )

    @field_validator("quote_id")
    @classmethod
    def nonblank_quote_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A reviewed quote is required")
        return value

    @field_validator("accept_quote")
    @classmethod
    def explicit_acceptance(cls, value: bool) -> bool:
        if not value:
            raise ValueError("The revised quote must be explicitly accepted")
        return value


class ReservationChangeReceiptRequest(ReservationChangeConfirmRequest):
    """Read-only historical retry input; never use this to authorize a new change."""

    @model_validator(mode="after")
    def valid_stay(self) -> "ReservationChangeReceiptRequest":
        if self.check_out_date <= self.check_in_date:
            raise ValueError("Check-out must follow check-in")
        return self


class ReservationChangeQuoteResponse(BaseModel):
    """A signed ten-minute review; it does not finalize a reservation change."""

    model_config = ConfigDict(extra="forbid")

    reservation_id: int = Field(strict=True, gt=0)
    quote_id: str = Field(min_length=1, max_length=MAX_CHANGE_QUOTE_LENGTH)
    expires_at: AwareDatetime
    quote: HotelRevalidationResponse


class ReservationChangeRevalidationContext(BaseModel):
    """Server-established context, from storage or an approved reconfirmation flow.

    Neither occupancy field has a default: existing reservations do not store
    these values. Provider capacity and room labels cannot establish occupancy.
    Currency/locale match the existing booking contract's supported values.
    """

    model_config = ConfigDict(extra="forbid")

    q: str = Field(min_length=1, max_length=255)
    adults: int = Field(strict=True, ge=1, le=20)
    children: int = Field(strict=True, ge=0, le=20)
    currency: Literal["USD"] = "USD"
    gl: Literal["us"] = "us"
    hl: Literal["en"] = "en"

    @field_validator("q")
    @classmethod
    def nonblank_destination(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A destination is required")
        return value


class ReservationChangeReviewRequest(
    ReservationChangeQuoteRequest, ReservationChangeRevalidationContext,
):
    """Customer-reconfirmed context for the public quote-only endpoint.

    These occupancy values are not verified historical occupancy. Property
    identity still comes exclusively from the authenticated owner's reservation.
    """
